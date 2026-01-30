#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

// Pin definitions
#define TFT_CS   4    // D3 = GPIO4
#define TFT_DC   3    // D2 = GPIO3
#define TFT_RST  2    // D1 = GPIO2

#define TFT_SCLK 8    // D8 = GPIO8
#define TFT_MOSI 10   // D10 = GPIO10

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

void setup() {
  SPI.begin(TFT_SCLK, -1, TFT_MOSI);   // SCLK, MISO unused, MOSI

  tft.init(240, 284);   // try 240,240 firstj
  tft.setRotation(1);

  tft.fillScreen(ST77XX_BLACK);
  tft.setTextColor(ST77XX_GREEN);
  tft.setTextSize(2);

  tft.setCursor(20, 40);
  tft.println("XIAO ESP32-S3");

  tft.setCursor(20, 80);
  tft.println("Camera + LCD OK!");
}

void loop() {
}
