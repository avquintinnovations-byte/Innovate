/**
 * QR Code Reader - XIAO ESP32S3 Sense
 * Set USE_DISPLAY 1 for live view + display (crashes on some units - TFT init)
 * Set USE_DISPLAY 0 for Serial only - STABLE, no reboots
 */
#define USE_DISPLAY 0  // 0 = Serial only (stable), 1 = Round Display

#include <Arduino.h>
#include <ESP32QRCodeReader.h>
#include <SPI.h>
#include <SD.h>
#if USE_DISPLAY
#include <esp_camera.h>
#include <TFT_eSPI.h>
#endif

static const CameraPins XIAO_ESP32S3_SENSE_PINS = {
  .PWDN_GPIO_NUM = -1, .RESET_GPIO_NUM = -1,
  .XCLK_GPIO_NUM = 10, .SIOD_GPIO_NUM = 40, .SIOC_GPIO_NUM = 39,
  .Y9_GPIO_NUM = 48, .Y8_GPIO_NUM = 11, .Y7_GPIO_NUM = 12, .Y6_GPIO_NUM = 14,
  .Y5_GPIO_NUM = 16, .Y4_GPIO_NUM = 18, .Y3_GPIO_NUM = 17, .Y2_GPIO_NUM = 15,
  .VSYNC_GPIO_NUM = 38, .HREF_GPIO_NUM = 47, .PCLK_GPIO_NUM = 13,
};

#define SD_CS_PIN 3

ESP32QRCodeReader reader(XIAO_ESP32S3_SENSE_PINS, FRAMESIZE_QVGA);
bool sdReady = false;

#if USE_DISPLAY
#define DISP_W 240
#define DISP_H 240
TFT_eSPI tft = TFT_eSPI();
volatile bool qrValid = false;
volatile char qrPayload[128] = {0};
volatile unsigned long qrShowUntil = 0;
#endif

void onQrCodeTask(void *pvParameters) {
  struct QRCodeData qrCodeData;
  while (true) {
    if (reader.receiveQrCode(&qrCodeData, 50)) {
      const char *p = (const char *)qrCodeData.payload;
      Serial.println("========== QR Code ==========");
      Serial.println(qrCodeData.valid ? p : (String("Invalid: ") + p));

#if USE_DISPLAY
      strncpy((char *)qrPayload, p, sizeof(qrPayload) - 1);
      qrPayload[sizeof(qrPayload) - 1] = '\0';
      qrValid = qrCodeData.valid;
      qrShowUntil = millis() + 3000;
#endif

      if (qrCodeData.valid && sdReady) {
        File f = SD.open("/qr_log.txt", FILE_APPEND);
        if (f) { f.print(millis()); f.print(",VALID,"); f.println(p); f.close(); }
      }
      Serial.println("============================");
    }
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // LED on = running
  Serial.begin(115200);
  delay(3000);  // USB CDC: wait for host to connect
  Serial.println();
  Serial.println("=== XIAO ESP32S3 QR Reader ===");
  Serial.println("Starting...");
  Serial.flush();

#if USE_DISPLAY
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("Init...", 120, 120, 2);
  delay(300);
#endif

  Serial.println("Init SD card...");
  Serial.flush();
  sdReady = SD.begin(SD_CS_PIN);
  if (sdReady) Serial.println("SD OK");
  else Serial.println("SD not found");

  Serial.println("Init camera...");
  Serial.flush();
  if (reader.setup() != SETUP_OK) {
    Serial.println("Camera FAILED!");
#if USE_DISPLAY
    tft.fillScreen(TFT_RED);
    tft.drawString("CAM ERROR", 120, 120, 4);
#endif
    while (1) delay(1000);
  }
  Serial.println("Camera OK");

  reader.beginOnCore(1);
  xTaskCreate(onQrCodeTask, "qr", 12 * 1024, NULL, 4, NULL);

#if USE_DISPLAY
  tft.fillScreen(TFT_BLACK);
  tft.drawString("Scanning...", 120, 120, 2);
#endif

  Serial.println("QR scanning is started - point camera at QR code");
  Serial.flush();
}

void loop() {
#if USE_DISPLAY
  if (millis() < qrShowUntil) {
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(qrValid ? TFT_GREEN : TFT_ORANGE, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.drawString(qrValid ? "QR OK!" : "Invalid", 120, 60, 4);
    String s = (const char *)qrPayload;
    if (s.length() > 28) s = s.substring(0, 25) + "...";
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawString(s, 120, 120, 2);
    delay(80);
    return;
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb && fb->format == PIXFORMAT_GRAYSCALE) {
    uint8_t *src = fb->buf;
    static uint16_t row[240];
    tft.startWrite();
    for (int y = 0; y < fb->height && y < DISP_H; y++) {
      for (int x = 0; x < fb->width && x < DISP_W; x++) {
        uint8_t g = src[y * fb->width + x];
        row[x] = ((g >> 3) << 11) | ((g >> 2) << 5) | (g >> 3);
      }
      tft.setAddrWindow(0, y, DISP_W, 1);
      tft.pushPixels(row, DISP_W);
    }
    tft.endWrite();
    esp_camera_fb_return(fb);
  }
#else
  static uint32_t last = 0;
  if (millis() - last > 500) {
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));  // Blink = alive
    last = millis();
  }
#endif
  delay(10);
}
