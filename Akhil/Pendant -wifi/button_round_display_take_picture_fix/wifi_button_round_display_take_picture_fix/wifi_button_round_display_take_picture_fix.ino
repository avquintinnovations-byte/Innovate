


/*
 * XIAO ESP32S3 Sense - SIMPLE SYNC VERSION
 * 
 * Architecture: ESP32 as File Server Only
 * - Runs WiFi AP (ESP32_CAM)
 * - Computer connects to AP
 * - Computer pulls files via HTTP
 * - Computer handles all upload/processing
 * 
 * Features:
 * - Live camera preview on TFT
 * - Press & hold button to record
 * - Release to capture photo
 * - Display shows: file count, recording status
 * - Simple HTTP file server
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

// ================= WIFI CONFIGURATION =================
const char* AP_SSID = "ESP32_CAM";
const char* AP_PASS = "12345678";

WebServer server(80);

// ================= FILE MANAGEMENT =================
int currentIndex = 1;
int cachedFileCount = 0;  // Cache file count to avoid slow SD scans
const char* INDEX_FILE = "/index.txt";

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
unsigned long lastDisplayUpdate = 0;

// ================= BATTERY =================
#define NUM_ADC_SAMPLE 20           // Sampling frequency for accuracy
#define BATTERY_DEFICIT_VOL 1850    // Battery voltage at empty (mV)
#define BATTERY_FULL_VOL 2450       // Battery voltage at full (mV)

int getBatteryPercentage() {
  // Average multiple samples for accuracy (official XIAO method)
  int32_t mvolts = 0;
  for(int8_t i = 0; i < NUM_ADC_SAMPLE; i++) {
    mvolts += analogReadMilliVolts(D0);  // D0 is battery sense pin on XIAO
  }
  mvolts /= NUM_ADC_SAMPLE;
  
  // Calculate percentage
  int32_t level = (mvolts - BATTERY_DEFICIT_VOL) * 100 / (BATTERY_FULL_VOL - BATTERY_DEFICIT_VOL);
  
  // Constrain between 0-100
  if (level < 0) level = 0;
  if (level > 100) level = 100;
  
  return (int)level;
}

// ================= FILE INDEX =================
int readLastIndexFromFile() {
  if (!SD.exists(INDEX_FILE)) return 0;
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
  f.flush();
  f.close();
}

// ================= FILE COUNTING =================
int countFilePairs() {
  int count = 0;
  File root = SD.open("/");
  
  File file = root.openNextFile();
  while (file) {
    if (!file.isDirectory()) {
      String name = file.name();
      if (name.startsWith("/image") && name.endsWith(".jpg")) {
        String index = name.substring(6, name.length() - 4);
        String audioName = "/audio" + index + ".wav";
        if (SD.exists(audioName)) {
          count++;
        }
      }
    }
    file = root.openNextFile();
  }
  root.close();
  return count;
}

// ================= SD WRITE =================
void writeFile(fs::FS &fs, const char *path, uint8_t *data, size_t len) {
  File file = fs.open(path, FILE_WRITE);
  if (!file) return;
  file.write(data, len);
  file.close();
}

// ================= WAV HEADER =================
void writeWavHeader(File file, uint32_t sampleRate, uint16_t bitsPerSample,
                    uint16_t channels, uint32_t dataSize) {
  uint32_t byteRate = sampleRate * channels * bitsPerSample / 8;
  uint16_t blockAlign = channels * bitsPerSample / 8;
  uint32_t chunkSize = 36 + dataSize;

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
  sprintf(f, "/audio%d.wav", currentIndex);

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY)) {
    audioFile = SD.open(f, FILE_WRITE);
    for (int i = 0; i < WAV_HEADER_SIZE; i++) audioFile.write((uint8_t)0);
    audioBytes = 0;
    shouldStopRecording = false;
    isRecording = true;
    xSemaphoreGive(audioFileMutex);
  }
  
  // Show recording indicator
  tft.fillRect(0, 220, 240, 20, TFT_RED);
  tft.setTextColor(TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("REC", 120, 230, 4);
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

// ================= HTTP HANDLERS =================
void handleRoot() {
  String html = "<html><head><title>ESP32 Camera</title></head><body>";
  html += "<h1>ESP32 Camera - File Server</h1>";
  html += "<p>Files: " + String(cachedFileCount) + " pairs</p>";
  html += "<p><a href='/list'>List Files</a></p>";
  html += "<p><a href='/status'>Status</a></p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

void handleListFiles() {
  File root = SD.open("/");
  String json = "[";

  File f = root.openNextFile();
  while (f) {
    if (!f.isDirectory()) {
      String name = f.name();
      // Remove leading slash for JSON
      if (name.startsWith("/")) name = name.substring(1);
      json += "\"" + name + "\",";
    }
    f = root.openNextFile();
  }

  if (json.endsWith(",")) json.remove(json.length() - 1);
  json += "]";
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

void handleDownload() {
  if (!server.hasArg("file")) {
    server.send(400, "text/plain", "Missing file parameter");
    return;
  }

  String filename = server.arg("file");
  if (!filename.startsWith("/")) filename = "/" + filename;
  
  File f = SD.open(filename);
  if (!f) {
    server.send(404, "text/plain", "File not found");
    return;
  }

  server.streamFile(f, "application/octet-stream");
  f.close();
}

void handleStatus() {
  String json = "{";
  json += "\"file_pairs\":" + String(cachedFileCount) + ",";
  json += "\"current_index\":" + String(currentIndex) + ",";
  json += "\"recording\":" + String(isRecording ? "true" : "false") + ",";
  json += "\"sd_card\":" + String(sd_sign ? "true" : "false") + ",";
  json += "\"camera\":" + String(camera_sign ? "true" : "false");
  json += "}";
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// ================= DISPLAY UPDATE =================
void updateDisplay() {
  // Update status every second
  if (millis() - lastDisplayUpdate < 1000) return;
  lastDisplayUpdate = millis();
  
  // Draw battery indicator (top-right corner)
  int batteryPercent = getBatteryPercentage();
  
  // Battery display area
  int battX = 145;
  int battY = 4;
  int battW = 32;
  int battH = 14;
  
  // Clear background for battery area (semi-transparent effect)
  tft.fillRect(battX - 25, battY - 1, 65, 18, TFT_BLACK);
  
  // Choose color based on battery level
  uint16_t battColor;
  if (batteryPercent > 50) {
    battColor = TFT_GREEN;
  } else if (batteryPercent > 20) {
    battColor = TFT_ORANGE;
  } else {
    battColor = TFT_RED;
  }
  
  // Draw percentage text first
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(TR_DATUM);
  tft.drawString(String(batteryPercent) + "%", battX - 3, battY + 3, 2);
  
  // Draw battery outline
  tft.drawRect(battX, battY, battW, battH, TFT_WHITE);
  tft.fillRect(battX + battW, battY + 4, 3, 6, TFT_WHITE); // Battery tip
  
  // Clear inside of battery
  tft.fillRect(battX + 2, battY + 2, battW - 4, battH - 4, TFT_BLACK);
  
  // Fill battery based on percentage
  int fillWidth = (battW - 4) * batteryPercent / 100;
  if (fillWidth > 0) {
    tft.fillRect(battX + 2, battY + 2, fillWidth, battH - 4, battColor);
  }
  
  if (!isRecording) {
    // Show file count at bottom (using cached count - fast!)
    tft.fillRect(0, 220, 240, 20, TFT_DARKGREEN);
    tft.setTextColor(TFT_WHITE);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("Files: " + String(cachedFileCount), 120, 230, 2);
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  pinMode(CAPTURE_BTN, INPUT_PULLUP);
  
  // Configure ADC for battery reading (XIAO official method)
  analogReadResolution(12);  // 12-bit ADC resolution

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
  
  // DISPLAY
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);
  
  // Show startup message
  tft.setTextColor(TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("ESP32 CAM", 120, 100, 4);
  tft.drawString("Starting...", 120, 140, 2);

  // SD CARD
  sd_sign = SD.begin(SD_CS_PIN);

  if (sd_sign) {
    int last = readLastIndexFromFile();
    currentIndex = last + 1;
    Serial.printf("Resuming from index: %d\n", currentIndex);
    
    // Count existing files once at startup (slow but only happens once!)
    cachedFileCount = countFilePairs();
    Serial.printf("Found %d existing file pairs\n", cachedFileCount);
    
    tft.drawString("SD Card: OK", 120, 170, 2);
  } else {
    tft.setTextColor(TFT_RED);
    tft.drawString("SD Card: FAILED", 120, 170, 2);
    cachedFileCount = 0;
  }

  delay(1000);

  // AUDIO
  setupI2S();
  xTaskCreatePinnedToCore(audioRecordingTask, "AudioTask", 4096, NULL, 2, &audioTaskHandle, 1);

  // WIFI AP
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  
  Serial.println("\n=================================");
  Serial.println("ESP32 Camera File Server Ready!");
  Serial.println("=================================");
  Serial.print("AP SSID: ");
  Serial.println(AP_SSID);
  Serial.print("AP Password: ");
  Serial.println(AP_PASS);
  Serial.print("AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("=================================");
  Serial.println("Connect computer to ESP32_CAM WiFi");
  Serial.println("Then run: python esp32_auto_sync_client.py");
  Serial.println("=================================\n");

  // HTTP Server
  server.on("/", handleRoot);
  server.on("/list", handleListFiles);
  server.on("/download", handleDownload);
  server.on("/status", handleStatus);
  server.begin();
  
  tft.fillScreen(TFT_BLACK);
}

// ================= LOOP =================
void loop() {
  server.handleClient();

  if (!camera_sign || !sd_sign) return;

  // Update display
  updateDisplay();

  // Get camera frame
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return;

  // Button handling
  static bool lastButton = HIGH;
  bool nowButton = digitalRead(CAPTURE_BTN);

  // Button pressed - start recording
  if (lastButton == HIGH && nowButton == LOW) {
    char imgPath[32];
    sprintf(imgPath, "/image%d.jpg", currentIndex);

    // Capture image
    uint8_t *jpg;
    size_t len;
    frame2jpg(fb, 100, &jpg, &len);
    writeFile(SD, imgPath, jpg, len);
    free(jpg);

    Serial.printf("Captured image%d.jpg\n", currentIndex);

    // Start audio recording
    startRecording();
    Serial.printf("Started recording audio%d.wav\n", currentIndex);
  }

  // Button released - stop recording
  if (lastButton == LOW && nowButton == HIGH) {
    stopRecording();
    Serial.printf("Saved audio%d.wav\n", currentIndex);
    
    // Flash green to indicate save
    tft.fillRect(0, 220, 240, 20, TFT_GREEN);
    tft.setTextColor(TFT_WHITE);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("SAVED #" + String(currentIndex), 120, 230, 2);
    
    // Increment counters
    currentIndex++;
    cachedFileCount++;  // Update cached count (fast!)
    writeLastIndexToFile(currentIndex - 1);
    
    delay(500);
  }

  lastButton = nowButton;

  // Display camera preview (only when not recording)
  if (!isRecording) {
    tft.startWrite();
    tft.setAddrWindow(0, 0, camera_width, camera_height);
    tft.pushImage(0, 0, camera_width, camera_height, (uint16_t*)fb->buf);
    tft.endWrite();
  }

  esp_camera_fb_return(fb);
  delay(10);
}