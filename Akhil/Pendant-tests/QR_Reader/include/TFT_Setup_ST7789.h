/**
 * Alternative: ST7789 - use if GC9A01 shows blank
 * In platformio.ini change: -include $PROJECT_DIR/include/TFT_Setup_ST7789.h
 */
#define USER_SETUP_LOADED 1
#define ST7789_2_DRIVER
#define TFT_RGB_ORDER TFT_BGR
#define TFT_WIDTH 240
#define TFT_HEIGHT 240

#define TFT_SCLK 7
#define TFT_MISO 8
#define TFT_MOSI 9
#define TFT_CS   2
#define TFT_DC   4
#define TFT_BL   -1
#define TFT_RST  -1
#define TOUCH_CS -1

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF

#define SPI_FREQUENCY 20000000
#define SPI_READ_FREQUENCY 16000000
