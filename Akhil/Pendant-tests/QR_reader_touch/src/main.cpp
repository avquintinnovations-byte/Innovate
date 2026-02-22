/*
 * Live Camera + QR Reader - XIAO ESP32-S3 Sense + Round Display
 * Continuous live view; on valid QR detected, show info for 5 sec then resume live
 */
#include <Arduino.h>

// Prevent stack overflow: quirc uses deep recursion (~12KB+ stack)
SET_LOOP_TASK_STACK_SIZE(16 * 1024);
#include <TFT_eSPI.h>
#include "esp_camera.h"
#include "camera_pins.h"

// quirc from ESP32QRCodeReader (add -I to platformio.ini if needed)
extern "C" {
#include "quirc/quirc.h"
}

#define DISP_W 240
#define DISP_H 240
#define PADDING 8

// Display orientation: 0=0°, 1=90°CW, 2=180°, 3=90°CCW
#define DISP_ROTATION 1

// Set to 1 to see QR detection status in Serial Monitor (helps debug)
#define DEBUG_QR 0

// Touch screen - GPIO 44 is touch INT (LOW when touching)
#define TOUCH_PIN 44
#define LONG_PRESS_MS 300
#define DEBOUNCE_COUNT 2
#define QR_CHECK_INTERVAL 5   // Only try QR decode every N frames when no result yet

TFT_eSPI tft = TFT_eSPI();
struct quirc* qr = nullptr;
uint16_t* displayBuf = nullptr;  // PSRAM: 240*240 RGB565
uint8_t* grayQrBuf = nullptr;    // PSRAM: grayscale+contrast for QR decode
bool showingQrResult = false;
char lastQrPayload[512] = "";
uint32_t frameCount = 0;
unsigned long lastDebugPrint = 0;

// Touch state
bool lastTouchState = false;
uint32_t touchStartTime = 0;
bool inLongPress = false;
uint8_t debounceCount = 0;

// Convert RGB565 to grayscale with increased contrast for QR decode
// Apply byte swap so R,G,B extraction is correct (camera may use different endianness)
void rgb565ToGrayscaleContrast(uint16_t* rgb565, uint8_t* grayOut, int w, int h) {
  const int contrastNum = 3;   // contrast 1.5x
  const int contrastDen = 2;
  for (int i = 0; i < w * h; i++) {
    uint16_t rgb = rgb565[i];
    rgb = (rgb >> 8) | (rgb << 8);  // Byte swap for correct R,G,B
    int r = (rgb >> 11) & 0x1F;
    int g = (rgb >> 5) & 0x3F;
    int b = rgb & 0x1F;
    int r8 = (r << 3) | (r >> 2);
    int g8 = (g << 2) | (g >> 4);
    int b8 = (b << 3) | (b >> 2);
    int gray = (77 * r8 + 150 * g8 + 29 * b8) >> 8;
    // Increase contrast: ((gray - 128) * 1.5) + 128
    int c = ((gray - 128) * contrastNum / contrastDen) + 128;
    grayOut[i] = (c < 0) ? 0 : (c > 255) ? 255 : (uint8_t)c;
  }
}

// Fix pixel for display - correct camera format for GC9A01 round display
static inline uint16_t fixPixelForDisplay(uint16_t p) {
  p = (p >> 8) | (p << 8);  // Byte swap (camera endianness)
 // return ((p & 0x001F) << 11) | (p & 0x07E0) | ((p & 0xF800) >> 11);  // R-B swap (GC9A01 BGR)
 return p;
}

// Display RGB565 frame (color) - correct byte order and color order for round display
void displayFrame(uint16_t* rgb565, int w, int h) {
  if (!displayBuf) return;
  int srcSize = (w < h) ? w : h;
  int offX = (w - srcSize) / 2;
  int offY = (h - srcSize) / 2;
  for (int dy = 0; dy < DISP_H; dy++) {
    int sy = offY + (dy * srcSize / DISP_H);
    uint16_t* row = rgb565 + sy * w;
    for (int dx = 0; dx < DISP_W; dx++) {
      int sx = offX + (dx * srcSize / DISP_W);
      displayBuf[dy * DISP_W + dx] = fixPixelForDisplay(row[sx]);
    }
  }
  tft.startWrite();
  tft.setAddrWindow(0, 0, DISP_W, DISP_H);
  tft.pushColors(displayBuf, DISP_W * DISP_H);
  tft.endWrite();
}

bool tryDecodeQr(uint8_t* gray, int w, int h, char* outPayload, int maxLen) {
  if (!qr) return false;
  if (quirc_resize(qr, w, h) < 0) return false;

  int qw, qh;
  uint8_t* buf = quirc_begin(qr, &qw, &qh);
  if (!buf) return false;
  memcpy(buf, gray, w * h);
  quirc_end(qr);

  int count = quirc_count(qr);
  if (count == 0) return false;

  struct quirc_code code;
  struct quirc_data data;
  quirc_extract(qr, 0, &code);
  quirc_decode_error_t err = quirc_decode(&code, &data);

  if (err != QUIRC_SUCCESS) {
#if DEBUG_QR
    Serial.printf("QR seen but decode failed: %s\n", quirc_strerror(err));
#endif
    return false;  // Only accept valid decodes
  }

  int len = data.payload_len;
  if (len >= maxLen) len = maxLen - 1;
  memcpy(outPayload, data.payload, len);
  outPayload[len] = '\0';
  return true;
}

// Draw QR text overlay - no background, text over camera feed
void drawQrOverlay(const char* payload) {
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(1);
  tft.setTextDatum(TL_DATUM);
  tft.setTextWrap(true);
  const int x0 = PADDING;
  const int y0 = DISP_H - 80;
  tft.setCursor(x0, y0);
  const int maxChars = 400;
  for (int i = 0; payload[i] && i < maxChars; i++) {
    tft.print(payload[i]);
  }
  if (strlen(payload) > maxChars) tft.print("...");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  tft.init();
  tft.setRotation(DISP_ROTATION);
  tft.fillScreen(TFT_BLACK);

  // Display + QR grayscale buffers in PSRAM
  displayBuf = (uint16_t*)ps_malloc(DISP_W * DISP_H * 2);
  grayQrBuf = (uint8_t*)ps_malloc(DISP_W * DISP_H);
  if (!displayBuf || !grayQrBuf) {
    tft.print("No PSRAM!");
    return;
  }

  // Camera config - GRAYSCALE for quirc, higher res helps ECC
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM;
  cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM;
  cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM;
  cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM;
  cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk = XCLK_GPIO_NUM;
  cfg.pin_pclk = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM;
  cfg.pin_href = HREF_GPIO_NUM;
  cfg.pin_sscb_sda = SIOD_GPIO_NUM;
  cfg.pin_sscb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn = PWDN_GPIO_NUM;
  cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 10000000;
  cfg.frame_size = FRAMESIZE_240X240;  // Match 240x240 display - no stretch
  cfg.pixel_format = PIXFORMAT_RGB565;  // Color for display
  cfg.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  cfg.fb_location = CAMERA_FB_IN_PSRAM;
  cfg.fb_count = 2;

  if (esp_camera_init(&cfg) != ESP_OK) {
    tft.print("Camera fail!");
    return;
  }

  // Fix camera orientation (flip/mirror - adjust if image is wrong way up)
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_vflip(s, 1);   // Vertical flip
    s->set_hmirror(s, 0); // 0=normal, 1=mirror (was causing horizontal flip)
  }

  qr = quirc_new();
  if (!qr) {
    tft.print("Quirc fail!");
    return;
  }

  pinMode(TOUCH_PIN, INPUT_PULLUP);

#ifdef TFT_BL
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);
#endif

  Serial.println("Live cam + QR ready (long-press screen to scan)");
}

void loop() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) return;

  int w = fb->width;
  int h = fb->height;

  if (fb->format != PIXFORMAT_RGB565) {
    esp_camera_fb_return(fb);
    return;
  } 

  uint16_t* rgb565 = (uint16_t*)fb->buf;
  frameCount++;

  // Touch detection (long press = scan QR)
  bool touched = (digitalRead(TOUCH_PIN) == LOW);
  if (touched) {
    if (!lastTouchState) {
      debounceCount++;
      if (debounceCount >= DEBOUNCE_COUNT) {
        lastTouchState = true;
        touchStartTime = millis();
        inLongPress = false;
        debounceCount = 0;
      }
    } else {
      debounceCount = 0;
      if (!inLongPress && (millis() - touchStartTime) >= LONG_PRESS_MS) {
        inLongPress = true;
      }
    }
  } else {
    if (lastTouchState) {
      debounceCount++;
      if (debounceCount >= DEBOUNCE_COUNT) {
        lastTouchState = false;
        inLongPress = false;
        debounceCount = 0;
      }
    } else {
      debounceCount = 0;
    }
  }

  // Always show live camera
  displayFrame(rgb565, w, h);

  if (inLongPress) {
    if (showingQrResult) {
      drawQrOverlay(lastQrPayload);
    } else if (grayQrBuf && (frameCount % QR_CHECK_INTERVAL == 0)) {
      rgb565ToGrayscaleContrast(rgb565, grayQrBuf, w, h);
      if (tryDecodeQr(grayQrBuf, w, h, lastQrPayload, sizeof(lastQrPayload))) {
        showingQrResult = true;
#if DEBUG_QR
        Serial.print("QR: ");
        Serial.println(lastQrPayload);
#endif
      }
    }
  } else {
    showingQrResult = false;
  }

#if DEBUG_QR
  // Heartbeat every 3 sec so you know it's running
  if (millis() - lastDebugPrint >= 3000) {
    lastDebugPrint = millis();
    Serial.printf("Running... frames=%lu\n", frameCount);
  }
#endif

  esp_camera_fb_return(fb);
}
