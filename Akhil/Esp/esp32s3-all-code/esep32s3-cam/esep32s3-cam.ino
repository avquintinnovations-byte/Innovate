#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

// GPIO numbers (XIAO ESP32-S3 Sense)
#define TFT_CS   4   // D3 = GPIO4
#define TFT_DC   3   // D2 = GPIO3
#define TFT_RST  2   // D1 = GPIO2
#define TFT_SCLK 7   // D6 = GPIO7
#define TFT_MOSI 8   // D7 = GPIO8

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

void setup() {
  Serial.begin(115200);
  while (!Serial);   // Wait for Serial Monitor to open
  Serial.println("USB Serial Ready");
  SPI.begin(TFT_SCLK, -1, TFT_MOSI);

  // Initialize display (240x280 panel)
  tft.init(240, 284);

  // Use landscape
  tft.setRotation(0);

  // ✅ Correct offset for rotation(1) on Waveshare 1.83"
  tft.setAddrWindow(0, 20, 240, 284);

  // Test colors
  tft.fillScreen(ST77XX_RED);
  delay(800);
  tft.fillScreen(ST77XX_GREEN);
  delay(800);
  tft.fillScreen(ST77XX_BLUE);
  delay(800);

  // Final screen
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextColor(ST77XX_WHITE);
  tft.setTextSize(2);

  tft.setCursor(10, 30);
  tft.println("Waveshare");

  tft.setCursor(10, 60);
  tft.println("LCD OK!");
}

void loop() {}
