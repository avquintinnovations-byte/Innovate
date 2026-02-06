/*
 * XIAO ESP32S3 Sense
 * Live Camera Preview + Press&Hold Audio (WAV) + Photo Capture
 * Button press  -> start audio
 * Button release-> stop audio + take picture
 * 
 * FIXED VERSION: Uses dedicated FreeRTOS task for audio recording
 * This prevents frame drops and audio glitches
 */

#include <Arduino.h>
#include <TFT_eSPI.h>
#include <SPI.h>
#include "esp_camera.h"
#include "FS.h"
#include "SD.h"
#include "driver/i2s.h"

#define CAMERA_MODEL_XIAO_ESP32S3
#define CAPTURE_BTN 43
#define SD_CS_PIN D2

#include "camera_pins.h"

// ================= DISPLAY =================
TFT_eSPI tft = TFT_eSPI();
const int camera_width  = 240;
const int camera_height = 240;

// ================= AUDIO =================
#define SAMPLE_RATE       16000
#define BITS_PER_SAMPLE   16
#define NUM_CHANNELS      1
#define WAV_HEADER_SIZE   44
#define MIC_GAIN          2    // Reduced for cleaner audio

File audioFile;
volatile bool isRecording = false;
volatile bool shouldStopRecording = false;
uint32_t audioBytes = 0;

// FreeRTOS task handle
TaskHandle_t audioTaskHandle = NULL;
SemaphoreHandle_t audioFileMutex = NULL;

// DC offset filter state (per task)
static int32_t dc_offset = 0;

// ================= SYSTEM =================
bool camera_sign = false;
bool sd_sign = false;
int imageCount = 1;

// ================= SD FILE WRITE =================
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

// ================= AUDIO (PDM MIC) =================
void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 16,              // Increased buffer count
    .dma_buf_len = 512,                // Optimal size for 16kHz
    .use_apll = true,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = -1,
    .ws_io_num = 42,      // PDM CLK
    .data_out_num = -1,
    .data_in_num = 41     // PDM DATA
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);

  // Stabilize PDM clock
  i2s_set_clk(I2S_NUM_0, SAMPLE_RATE,
              I2S_BITS_PER_SAMPLE_16BIT,
              I2S_CHANNEL_MONO);

  i2s_zero_dma_buffer(I2S_NUM_0);

  Serial.println("PDM microphone stable");
}

// ================= AUDIO RECORDING TASK =================
void audioRecordingTask(void *parameter) {
  int16_t samples[512];
  int32_t local_dc_offset = 0;
  
  while (true) {
    if (isRecording && !shouldStopRecording) {
      size_t bytesRead = 0;

      // Read from I2S with timeout
      esp_err_t result = i2s_read(I2S_NUM_0, samples,
                                   sizeof(samples),
                                   &bytesRead,
                                   pdMS_TO_TICKS(100));

      if (result == ESP_OK && bytesRead > 0) {
        int sampleCount = bytesRead / 2;

        // Process audio samples
        for (int i = 0; i < sampleCount; i++) {
          // DC offset removal (1st order HPF)
          local_dc_offset = (local_dc_offset * 995 + samples[i]) / 996;
          int32_t s = samples[i] - local_dc_offset;

          // Apply gain AFTER DC removal
          s *= MIC_GAIN;

          // Clipping protection
          if (s > 32767)  s = 32767;
          if (s < -32768) s = -32768;

          samples[i] = (int16_t)s;
        }

        // Write to SD card (thread-safe)
        if (xSemaphoreTake(audioFileMutex, portMAX_DELAY) == pdTRUE) {
          if (audioFile) {
            audioFile.write((uint8_t*)samples, bytesRead);
            audioBytes += bytesRead;
          }
          xSemaphoreGive(audioFileMutex);
        }
      }
    } else {
      // Not recording, yield CPU
      vTaskDelay(pdMS_TO_TICKS(10));
      local_dc_offset = 0;  // Reset DC offset when not recording
    }
  }
}

// ================= AUDIO CONTROL =================
void startRecording() {
  if (isRecording) return;
  
  char filename[32];
  sprintf(filename, "/audio%d.wav", imageCount);

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY) == pdTRUE) {
    audioFile = SD.open(filename, FILE_WRITE);
    if (!audioFile) {
      xSemaphoreGive(audioFileMutex);
      Serial.println("Failed to open audio file!");
      return;
    }

    // Write dummy WAV header
    for (int i = 0; i < WAV_HEADER_SIZE; i++) {
      audioFile.write((uint8_t)0);
    }

    audioBytes = 0;
    dc_offset = 0;
    shouldStopRecording = false;
    isRecording = true;

    xSemaphoreGive(audioFileMutex);

    Serial.println("Audio recording started");
  }
}

void stopRecording() {
  if (!isRecording) return;

  shouldStopRecording = true;
  vTaskDelay(pdMS_TO_TICKS(50));  // Let task finish current write

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY) == pdTRUE) {
    if (audioFile) {
      // Update WAV header with actual data size
      writeWavHeader(audioFile, SAMPLE_RATE,
                     BITS_PER_SAMPLE, NUM_CHANNELS,
                     audioBytes);

      audioFile.close();
    }

    isRecording = false;
    xSemaphoreGive(audioFileMutex);

    Serial.printf("Audio recording stopped. Bytes: %d (%.2f sec)\n", 
                  audioBytes, 
                  (float)audioBytes / (SAMPLE_RATE * 2));
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  pinMode(CAPTURE_BTN, INPUT_PULLUP);

  // Create mutex for thread-safe file access
  audioFileMutex = xSemaphoreCreateMutex();

  // ---- CAMERA ----
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size  = FRAMESIZE_240X240;
  config.pixel_format = PIXFORMAT_RGB565;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.fb_count    = 1;
  config.grab_mode   = CAMERA_GRAB_LATEST;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera init failed");
    return;
  }
  camera_sign = true;

  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 0);

  // ---- DISPLAY ----
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);

  // ---- SD ----
  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("SD init failed");
    sd_sign = false;
  } else {
    sd_sign = true;
    Serial.println("SD card initialized");
  }

  // ---- AUDIO ----
  setupI2S();

  // Create high-priority audio task on Core 1
  xTaskCreatePinnedToCore(
    audioRecordingTask,     // Task function
    "AudioRecorder",        // Task name
    4096,                   // Stack size (bytes)
    NULL,                   // Parameters
    2,                      // Priority (higher than loop)
    &audioTaskHandle,       // Task handle
    1                       // Core 1 (Core 0 runs Arduino loop)
  );

  Serial.println("System ready");
}

// ================= LOOP =================
void loop() {
  if (!camera_sign || !sd_sign) {
    delay(100);
    return;
  }

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    delay(100);
    return;
  }

  static bool lastBtnState = HIGH;
  static unsigned long lastDebounceTime = 0;
  const unsigned long debounceDelay = 50;
  
  bool btnState = digitalRead(CAPTURE_BTN);

  // Debounce without blocking delay
  if (btnState != lastBtnState) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    static bool lastStableState = HIGH;

    // ---- BUTTON PRESS (HIGH -> LOW) ----
  // ---- BUTTON PRESS (HIGH -> LOW) ----
if (lastStableState == HIGH && btnState == LOW) {

  // 📸 TAKE PHOTO IMMEDIATELY
  char filename[32];
  sprintf(filename, "/image%d.jpg", imageCount);

  uint8_t *jpg_buf = NULL;
  size_t jpg_len = 0;

  if (frame2jpg(fb, 100, &jpg_buf, &jpg_len)) {
    writeFile(SD, filename, jpg_buf, jpg_len);
    free(jpg_buf);
    Serial.printf("Image saved: %s\n", filename);
  } else {
    Serial.println("JPEG encoding failed");
  }

  // 🎙️ START AUDIO RECORDING
  startRecording();
}

// ---- BUTTON RELEASE (LOW -> HIGH) ----
if (lastStableState == LOW && btnState == HIGH) {
  stopRecording();
  imageCount++;   // increment AFTER full press-release cycle
}


    lastStableState = btnState;
  }

  lastBtnState = btnState;

  // ---- UPDATE DISPLAY (only when NOT recording) ----
  if (!isRecording) {
    tft.startWrite();
    tft.setAddrWindow(0, 0, camera_width, camera_height);
    tft.pushImage(0, 0,
                  camera_width, camera_height,
                  (uint16_t*)fb->buf);
    tft.endWrite();
  } else {
    // Show recording indicator
    static unsigned long lastBlinkTime = 0;
    static bool blinkState = false;
    
    if (millis() - lastBlinkTime > 500) {
      lastBlinkTime = millis();
      blinkState = !blinkState;
      
      // Draw red circle in corner
      if (blinkState) {
        tft.fillCircle(220, 20, 10, TFT_RED);
      } else {
        tft.fillCircle(220, 20, 10, TFT_BLACK);
      }
    }
  }

  esp_camera_fb_return(fb);

  // Small delay to prevent watchdog issues
  delay(10);
}