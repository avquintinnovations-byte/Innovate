#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

// ===== ESP32-C3 PIN DEFINITIONS =====
#define TFT_CS   10
#define TFT_DC    9
#define TFT_RST   8
#define TFT_BL    3

#define TFT_SCLK  6
#define TFT_MOSI  7

// ST7789 1.83" resolution
#define TFT_WIDTH  240
#define TFT_HEIGHT 284

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

void setup() {
  // Backlight
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  // SPI begin
  SPI.begin(TFT_SCLK, -1, TFT_MOSI, TFT_CS);

  // Initialize LCD
  tft.init(TFT_WIDTH, TFT_HEIGHT);
  tft.setRotation(0);
  tft.fillScreen(ST77XX_WHITE);

  // Draw text
  tft.setTextColor(ST77XX_RED);
  tft.setTextSize(2);
  tft.setCursor(20, 20);
  tft.println("ESP32-C3 LCD");

  tft.setTextColor(ST77XX_BLUE);
  tft.setCursor(20, 50);
  tft.println("ST7789P");

  // Shapes
  tft.drawRect(20, 90, 200, 60, ST77XX_GREEN);
  tft.fillCircle(60, 180, 20, ST77XX_RED);
  tft.fillCircle(120, 180, 20, ST77XX_BLUE);
  tft.fillCircle(180, 180, 20, ST77XX_GREEN);
}

void loop() {
  // nothing here
}
