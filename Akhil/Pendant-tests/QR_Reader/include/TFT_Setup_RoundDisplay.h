/**
 * TFT_eSPI config for Seeed Round Display for XIAO
 * Based on Setup66_Seeed_XIAO_Round.h
 * Compatible with XIAO ESP32S3 Sense (display uses different pins than camera)
 */
#define USER_SETUP_LOADED 1
#define USER_SETUP_ID 66

#define GC9A01_DRIVER
#define TFT_RGB_ORDER TFT_BGR  /* BGR often needed for round displays */
#define TFT_WIDTH 240
#define TFT_HEIGHT 240

/* XIAO ESP32S3 pinout - Round Display (no conflict with camera pins) */
#define TFT_SCLK 7   /* D8 - SPI SCK */
#define TFT_MISO 8   /* D9 - SPI MISO */
#define TFT_MOSI 9   /* D10 - SPI MOSI */
#define TFT_CS   2   /* D1 - Chip select */
#define TFT_DC   4   /* D3 - Data/Command */
#define TFT_BL   -1  /* D6=GPIO43 is USB-UART TX - avoid conflict; backlight likely always on */
#define TFT_RST  -1  /* Reset, -1 if shared with MCU */
#define TOUCH_CS -1   /* Touch not used - suppress TFT_eSPI warning */

/* Fonts */
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

#define SPI_FREQUENCY 20000000   /* 20MHz - 40MHz can cause instability on some wiring */
#define SPI_READ_FREQUENCY 16000000
