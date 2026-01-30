#include <LovyanGFX.hpp>
#include "esp_camera.h"

// ================= LCD =================
class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7789 _panel;
  lgfx::Bus_SPI _bus;

public:
  LGFX() {
    { // SPI
      auto cfg = _bus.config();
      cfg.spi_host   = SPI2_HOST;
      cfg.spi_mode   = 0;
      cfg.freq_write = 80000000;   // 🔥 Push SPI hard
      cfg.spi_3wire  = true;

      cfg.pin_sclk = 7;
      cfg.pin_mosi = 8;
      cfg.pin_miso = -1;
      cfg.pin_dc   = 3;

      _bus.config(cfg);
      _panel.setBus(&_bus);
    }

    { // Panel
      auto cfg = _panel.config();
      cfg.pin_cs  = 4;
      cfg.pin_rst = 2;

      cfg.memory_width  = 240;
      cfg.memory_height = 280;
      cfg.panel_width   = 240;
      cfg.panel_height  = 280;

      cfg.invert = true;  // NV3030B often needs this
      _panel.config(cfg);
    }

    setPanel(&_panel);
  }
};

LGFX lcd;

// ================= CAMERA =================
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39

#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15

#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

// Small fast line buffer
static uint16_t lineBuffer[240];

void setup() {
  Serial.begin(115200);
  delay(500);

  // ---- LCD ----
  lcd.init();
  lcd.setRotation(1);
  lcd.setColorDepth(16);
  lcd.setSwapBytes(false);
  lcd.writecommand(0x20);  // normal color
  lcd.fillScreen(TFT_BLACK);

  // ---- CAMERA ----
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href  = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 24000000;
  config.pixel_format = PIXFORMAT_RGB565;
  config.frame_size   = FRAMESIZE_QVGA;  // 320x240
  config.fb_count     = 2;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera failed");
    while (1);
  }

  // ---- SENSOR TUNING ----
  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);

  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  s->set_aec2(s, 1);

  s->set_brightness(s, 1);
  s->set_contrast(s, 1);
  s->set_saturation(s, 1);

  Serial.println("Ultra FPS Fullscreen Streaming Started");
}

void loop() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return;

  uint16_t *src = (uint16_t*)fb->buf;
  static uint16_t lineBuffer[240];

  for (int y = 0; y < 280; y++) {
    int sy = y * 240 / 280;
    uint16_t *srcLine = &src[sy * 320];

    for (int x = 0; x < 240; x++) {
      int sx = x * 320 / 240;
      lineBuffer[x] = srcLine[sx];
    }

    lcd.pushImage(0, y, 240,1, lineBuffer);
    
  }

  esp_camera_fb_return(fb);
}
