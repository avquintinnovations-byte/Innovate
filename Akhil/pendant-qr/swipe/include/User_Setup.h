// User setup for Seeed Studio Round Display for XIAO
// Target: XIAO ESP32S3 Sense (GC9A01 240x240, SPI via D8/D10/D1/D3)

#pragma once

#define GC9A01_DRIVER
#define TFT_WIDTH 240
#define TFT_HEIGHT 240

#define TFT_MOSI D10
#define TFT_SCLK D8
#define TFT_CS D1
#define TFT_DC D3

#define TFT_RST -1

#define TFT_BL D6

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7

#define USE_HSPI_PORT

#define SPI_FREQUENCY 40000000
#define SPI_READ_FREQUENCY 20000000
#define SPI_TOUCH_FREQUENCY 2500000

