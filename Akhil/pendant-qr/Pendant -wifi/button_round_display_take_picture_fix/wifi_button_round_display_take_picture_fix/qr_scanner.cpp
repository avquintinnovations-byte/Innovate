/*
 * QR scanner implementation - from QR_reader_touch
 */
#include "qr_scanner.h"

static struct quirc* qr = nullptr;
static uint8_t* grayBuf = nullptr;  // PSRAM: 240*240 for grayscale conversion

bool qr_scanner_init(void) {
  qr = quirc_new();
  if (!qr) return false;
  grayBuf = (uint8_t*)ps_malloc(240 * 240);
  if (!grayBuf) {
    quirc_destroy(qr);
    qr = nullptr;
    return false;
  }
  return true;
}

void qr_scanner_end(void) {
  if (grayBuf) {
    free(grayBuf);
    grayBuf = nullptr;
  }
  if (qr) {
    quirc_destroy(qr);
    qr = nullptr;
  }
}

static void rgb565_to_grayscale(uint16_t* rgb565, uint8_t* grayOut, int w, int h) {
  const int contrastNum = 3;
  const int contrastDen = 2;
  for (int i = 0; i < w * h; i++) {
    uint16_t rgb = rgb565[i];
    rgb = (rgb >> 8) | (rgb << 8);
    int r = (rgb >> 11) & 0x1F;
    int g = (rgb >> 5) & 0x3F;
    int b = rgb & 0x1F;
    int r8 = (r << 3) | (r >> 2);
    int g8 = (g << 2) | (g >> 4);
    int b8 = (b << 3) | (b >> 2);
    int gray = (77 * r8 + 150 * g8 + 29 * b8) >> 8;
    int c = ((gray - 128) * contrastNum / contrastDen) + 128;
    grayOut[i] = (c < 0) ? 0 : (c > 255) ? 255 : (uint8_t)c;
  }
}

bool qr_scanner_try_decode(uint16_t* rgb565, int w, int h, char* outBuf, int maxLen) {
  if (!qr || !grayBuf || !outBuf || maxLen <= 0 || w * h > 240 * 240) return false;

  rgb565_to_grayscale(rgb565, grayBuf, w, h);

  if (quirc_resize(qr, w, h) < 0) return false;

  int qw, qh;
  uint8_t* buf = quirc_begin(qr, &qw, &qh);
  if (!buf) return false;
  memcpy(buf, grayBuf, (size_t)(w * h));
  quirc_end(qr);

  int count = quirc_count(qr);
  if (count == 0) return false;

  struct quirc_code code;
  struct quirc_data data;

  // Try all detected regions; region 0 may fail while another succeeds.
  for (int i = 0; i < count; i++) {
    quirc_extract(qr, i, &code);
    quirc_decode_error_t err = quirc_decode(&code, &data);
    if (err != QUIRC_SUCCESS) continue;

    int len = data.payload_len;
    if (len >= maxLen) len = maxLen - 1;
    memcpy(outBuf, data.payload, len);
    outBuf[len] = '\0';
    return true;
  }

  return false;
}
