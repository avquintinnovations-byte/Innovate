#ifndef ESP32_CAMERA_PINS_H_
#define ESP32_CAMERA_PINS_H_

/*
 * Custom camera pins for XIAO ESP32S3 Sense.
 * This file overrides the library's pins to add XIAO ESP32S3 Sense support.
 * Pin mapping from Seeed Studio wiki: wiki.seeedstudio.com/xiao_esp32s3_camera_usage
 */

struct CameraPins
{
  int PWDN_GPIO_NUM;
  int RESET_GPIO_NUM;
  int XCLK_GPIO_NUM;
  int SIOD_GPIO_NUM;
  int SIOC_GPIO_NUM;
  int Y9_GPIO_NUM;
  int Y8_GPIO_NUM;
  int Y7_GPIO_NUM;
  int Y6_GPIO_NUM;
  int Y5_GPIO_NUM;
  int Y4_GPIO_NUM;
  int Y3_GPIO_NUM;
  int Y2_GPIO_NUM;
  int VSYNC_GPIO_NUM;
  int HREF_GPIO_NUM;
  int PCLK_GPIO_NUM;
};

#if defined(CAMERA_MODEL_XIAO_ESP32S3)
/* XIAO ESP32S3 Sense - OV2640/OV3660 camera on expansion board */
/* Pin mapping from Seeed Studio wiki */
#define CAMERA_MODEL_XIAO_ESP32S3 \
  {                               \
    .PWDN_GPIO_NUM = -1,          \
    .RESET_GPIO_NUM = -1,         \
    .XCLK_GPIO_NUM = 10,          \
    .SIOD_GPIO_NUM = 40,          \
    .SIOC_GPIO_NUM = 39,          \
    .Y9_GPIO_NUM = 48,            \
    .Y8_GPIO_NUM = 11,            \
    .Y7_GPIO_NUM = 12,            \
    .Y6_GPIO_NUM = 14,            \
    .Y5_GPIO_NUM = 16,            \
    .Y4_GPIO_NUM = 18,            \
    .Y3_GPIO_NUM = 17,            \
    .Y2_GPIO_NUM = 15,            \
    .VSYNC_GPIO_NUM = 38,         \
    .HREF_GPIO_NUM = 47,          \
    .PCLK_GPIO_NUM = 13,          \
  }
#endif

#endif
