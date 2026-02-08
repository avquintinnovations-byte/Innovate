/*
 * XIAO ESP32S3 Sense
 * Live Camera Preview + Press&Hold Audio (WAV) + Photo Capture
 * Button press  -> start audio
 * Button release-> stop audio + take picture
 *
 * ADDED:
 * - File index resumes after restart
 * - Battery percentage display
 * - WiFi hotspot + SD sync server
 */

#include <Arduino.h>
#include <TFT_eSPI.h>
#include <SPI.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "FS.h"
#include "SD.h"
#include "driver/i2s.h"

#define CAMERA_MODEL_XIAO_ESP32S3
#define CAPTURE_BTN 43
#define SD_CS_PIN D2

#include "camera_pins.h"

int currentIndex = 1;      // index used for current capture
int idx=0;
const char* INDEX_FILE = "/index.txt";
// ================= WIFI =================
const char* AP_SSID = "ESP32_CAM";
const char* AP_PASS = "12345678";
WebServer server(80);

// ================= DISPLAY =================
TFT_eSPI tft = TFT_eSPI();
const int camera_width  = 240;
const int camera_height = 240;

// ================= AUDIO =================
#define SAMPLE_RATE       16000
#define BITS_PER_SAMPLE   16
#define NUM_CHANNELS      1
#define WAV_HEADER_SIZE   44
#define MIC_GAIN          2

File audioFile;
volatile bool isRecording = false;
volatile bool shouldStopRecording = false;
uint32_t audioBytes = 0;

TaskHandle_t audioTaskHandle = NULL;
SemaphoreHandle_t audioFileMutex = NULL;

// ================= SYSTEM =================
bool camera_sign = false;
bool sd_sign = false;
int imageCount = 1;

// ================= BATTERY =================
#define BATTERY_ADC_PIN 1
#define ADC_MAX         4095.0
#define ADC_REF_VOLT    3.3
#define BATTERY_MAX_V   4.2
#define BATTERY_MIN_V   3.0




int readLastIndexFromFile() {
  if (!SD.exists(INDEX_FILE)) {
    return 0;   // no file yet
  }

  File f = SD.open(INDEX_FILE, FILE_READ);
  if (!f) return 0;

  int idx = f.parseInt();
  f.close();
  return idx;
}

void writeLastIndexToFile(int idx) {
  File f = SD.open(INDEX_FILE, FILE_WRITE);
  if (!f) return;

  f.seek(0);
  f.print(idx);
  f.flush();     // IMPORTANT: force write to SD
  f.close();
}


// ================= FILE INDEX RESUME =================
int getLastFileIndex() {
  int maxIndex = 0;
  File root = SD.open("/");

  File file = root.openNextFile();
  while (file) {
    if (!file.isDirectory()) {
      String name = file.name();

      // imageX.jpg
      if (name.startsWith("/image") && name.endsWith(".jpg")) {
        int idx = name.substring(6, name.length() - 4).toInt();
        if (idx > maxIndex) maxIndex = idx;
      }

      // audioX.wav (ignore empty / broken files)
      if (name.startsWith("/audio") && name.endsWith(".wav") && file.size() > 44) {
        int idx = name.substring(6, name.length() - 4).toInt();
        if (idx > maxIndex) maxIndex = idx;
      }
    }
    file = root.openNextFile();
  }

  root.close();
  return maxIndex;
}


// ================= BATTERY % =================


// ================= SD WRITE =================
void writeFile(fs::FS &fs, const char *path, uint8_t *data, size_t len) {
  File file = fs.open(path, FILE_WRITE);
  if (!file) return;
  file.write(data, len);
  file.close();
}

// ================= WAV HEADER =================
void writeWavHeader(File file,
                    uint32_t sampleRate,
                    uint16_t bitsPerSample,
                    uint16_t channels,
                    uint32_t dataSize) {

  uint32_t byteRate   = sampleRate * channels * bitsPerSample / 8;
  uint16_t blockAlign = channels * bitsPerSample / 8;
  uint32_t chunkSize  = 36 + dataSize;

  file.seek(0);
  file.write((const uint8_t*)"RIFF", 4);
  file.write((uint8_t*)&chunkSize, 4);
  file.write((const uint8_t*)"WAVE", 4);
  file.write((const uint8_t*)"fmt ", 4);

  uint32_t subChunk1Size = 16;
  uint16_t audioFormat = 1;

  file.write((uint8_t*)&subChunk1Size, 4);
  file.write((uint8_t*)&audioFormat, 2);
  file.write((uint8_t*)&channels, 2);
  file.write((uint8_t*)&sampleRate, 4);
  file.write((uint8_t*)&byteRate, 4);
  file.write((uint8_t*)&blockAlign, 2);
  file.write((uint8_t*)&bitsPerSample, 2);
  file.write((const uint8_t*)"data", 4);
  file.write((uint8_t*)&dataSize, 4);
}

// ================= I2S =================
void setupI2S() {
  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 16,
    .dma_buf_len = 512,
    .use_apll = true
  };

  i2s_pin_config_t pin = {
    .bck_io_num = -1,
    .ws_io_num = 42,
    .data_out_num = -1,
    .data_in_num = 41
  };

  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin);
  i2s_zero_dma_buffer(I2S_NUM_0);
}

// ================= AUDIO TASK =================
void audioRecordingTask(void *parameter) {
  int16_t samples[512];
  int32_t dc = 0;

  while (true) {
    if (isRecording && !shouldStopRecording) {
      size_t bytesRead;
      i2s_read(I2S_NUM_0, samples, sizeof(samples), &bytesRead, portMAX_DELAY);

      for (int i = 0; i < bytesRead / 2; i++) {
        dc = (dc * 995 + samples[i]) / 996;
        int32_t s = (samples[i] - dc) * MIC_GAIN;
        samples[i] = constrain(s, -32768, 32767);
      }

      if (xSemaphoreTake(audioFileMutex, portMAX_DELAY)) {
        audioFile.write((uint8_t*)samples, bytesRead);
        audioBytes += bytesRead;
        xSemaphoreGive(audioFileMutex);
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(10));
      dc = 0;
    }
  }
}

// ================= AUDIO CONTROL =================
void startRecording() {
  char f[32];
  sprintf(f, "/audio%d.wav", idx);

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY)) {
    audioFile = SD.open(f, FILE_WRITE);
    for (int i = 0; i < WAV_HEADER_SIZE; i++) audioFile.write((uint8_t)0);
    audioBytes = 0;
    shouldStopRecording = false;
    isRecording = true;
    xSemaphoreGive(audioFileMutex);
  }
}

void stopRecording() {
  shouldStopRecording = true;
  vTaskDelay(pdMS_TO_TICKS(50));

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY)) {
    writeWavHeader(audioFile, SAMPLE_RATE, BITS_PER_SAMPLE, NUM_CHANNELS, audioBytes);
    audioFile.close();
    isRecording = false;
    xSemaphoreGive(audioFileMutex);
  }
}

// ================= WIFI SERVER =================
void handleListFiles() {
  File root = SD.open("/");
  String json = "[";

  File f = root.openNextFile();
  while (f) {
    if (!f.isDirectory()) json += "\"" + String(f.name()) + "\",";
    f = root.openNextFile();
  }

  if (json.endsWith(",")) json.remove(json.length() - 1);
  json += "]";
  server.send(200, "application/json", json);
}

void handleDownload() {
  if (!server.hasArg("file")) {
    server.send(400, "text/plain", "Missing file");
    return;
  }

  File f = SD.open("/" + server.arg("file"));
  if (!f) {
    server.send(404, "text/plain", "Not found");
    return;
  }

  server.streamFile(f, "application/octet-stream");
  f.close();
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  pinMode(CAPTURE_BTN, INPUT_PULLUP);
  analogReadResolution(12);

  audioFileMutex = xSemaphoreCreateMutex();

  // CAMERA
  camera_config_t c;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;
  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;
  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;
  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sscb_sda = SIOD_GPIO_NUM;
  c.pin_sscb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.frame_size = FRAMESIZE_240X240;
  c.pixel_format = PIXFORMAT_RGB565;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.fb_count = 1;

   if (esp_camera_init(&c) != ESP_OK) {
    Serial.println("Camera init failed");
    return;
  }
  camera_sign = true;

  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 0);
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);

  sd_sign = SD.begin(SD_CS_PIN);

   if (sd_sign) {
    int last = readLastIndexFromFile();
    currentIndex = last + 1;
    Serial.printf("Resuming index: %d\n", currentIndex);
  }

  setupI2S();
  xTaskCreatePinnedToCore(audioRecordingTask, "AudioTask", 4096, NULL, 2, &audioTaskHandle, 1);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("ESP32 AP IP: ");
  Serial.println(WiFi.softAPIP());

  server.on("/list", handleListFiles);
  server.on("/download", handleDownload);
  server.begin();
}

// ================= LOOP =================
void loop() {
  server.handleClient();

  if (!camera_sign || !sd_sign) return;

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return;

  static bool last = HIGH;
  bool now = digitalRead(CAPTURE_BTN);

  if (last == HIGH && now == LOW) {
    char img[32];
    idx = currentIndex;          // reserve index
currentIndex++;                 // move to next
writeLastIndexToFile(idx);      // SAVE IMMEDIATELY

sprintf(img, "/image%d.jpg", idx);

    uint8_t *jpg;
    size_t len;
    frame2jpg(fb, 100, &jpg, &len);
    writeFile(SD, img, jpg, len);
    free(jpg);

    startRecording();
  }

  if (last == LOW && now == HIGH) {
    stopRecording();
    
  }

  last = now;

  if (!isRecording) {
    tft.startWrite();
    tft.setAddrWindow(0, 0, camera_width, camera_height);
    tft.pushImage(0, 0, camera_width, camera_height, (uint16_t*)fb->buf);
    tft.endWrite();
  }

  

  esp_camera_fb_return(fb);
  delay(10);
}
