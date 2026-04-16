#pragma once
/*
 * QR code scanner - integrated from QR_reader_touch.
 * Uses quirc from ESP32QRCodeReader for decoding.
 * Call qr_scanner_init() once, then qr_scanner_try_decode() with RGB565 frame.
 */

#include <Arduino.h>

extern "C" {
#include "quirc/quirc.h"
}

#define QR_SCANNER_PAYLOAD_MAX 512

// Initialize QR scanner (allocates PSRAM). Call once in setup.
bool qr_scanner_init(void);

// Free QR scanner resources.
void qr_scanner_end(void);

// Try to decode QR from RGB565 camera frame. Returns true if decoded, payload in outBuf.
bool qr_scanner_try_decode(uint16_t* rgb565, int w, int h, char* outBuf, int maxLen);
