/*
 * XIAO ESP32S3 Sense - SIMPLE SYNC VERSION
 *
 * TFT_eSPI: Edit Arduino/libraries/TFT_eSPI/User_Setup.h:
 */
#define BLE_ENABLED 1
// BLE stays on; stop advertising during HTTP sync, restart when app sends /sync-complete.

/*
 *   - #define GC9A01_DRIVER
 *   - Pins for Round Display: TFT_CS D1, TFT_DC D3, etc (see Seeed Round Display wiki)
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
 * - Files saved with date/time via Round Display RTC (manual calibration)
 * - See: https://wiki.seeedstudio.com/seeedstudio_round_display_usage/#off-line-manual-calibration-of-the-rtc
 */

#include <Arduino.h>
SET_LOOP_TASK_STACK_SIZE(16 * 1024);  // QR scanner (quirc) needs larger stack
#include <TFT_eSPI.h>
#include <SPI.h>
#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <Wire.h>
#include "esp_system.h"
#if BLE_ENABLED
#include "NimBLEDevice.h"
#endif
#include "I2C_BM8563.h"
#include "esp_camera.h"
#include "FS.h"
#include "SD.h"
#include "driver/i2s.h"

#define CAMERA_MODEL_XIAO_ESP32S3
#define SD_CS_PIN D2
// Round Display: D4=SDA, D5=SCL (I2C for RTC/touch). XIAO ESP32S3: D4=GPIO5, D5=GPIO6
#define RTC_SDA 5
#define RTC_SCL 6
// TFT backlight: Round Display D6. Set 0 to disable. If backlight stays off, adjust as needed
#define TFT_BL  0

#include "camera_pins.h"
// Touch input trigger (replaces the external GPIO button)
#include "touch44_debounced_trigger_for_take_picture.h"
// QR code scanner (from QR_reader_touch)
#include "qr_scanner.h"

// ================= WIFI CONFIGURATION =================
const char* AP_SSID = "ESP32_CAM";
const char* AP_PASS = "12345678";

// ================= RTC (Round Display - I2C_BM8563) =================
// Install: Arduino Library Manager -> search "I2C_BM8563" (by TANAKA Masayuki)
// Manual calibration: https://wiki.seeedstudio.com/seeedstudio_round_display_usage/#off-line-manual-calibration-of-the-rtc
// Set to 1 ONLY when you need to set the RTC time (run once, then set back to 0)
#define SET_RTC_ON_BOOT 0

#if SET_RTC_ON_BOOT
  #define RTC_YEAR   2026
  #define RTC_MONTH  4
  #define RTC_DAY    13
  #define RTC_WEEKDAY 1 // 0=Sun, 1=Mon, ... 6=Sat
  #define RTC_HOUR   14
  #define RTC_MINUTE 28
  #define RTC_SECOND 0
#endif

I2C_BM8563 rtc(I2C_BM8563_DEFAULT_ADDRESS, Wire);
bool rtcReady = false;  // True when RTC initialized; enables date/time in filenames

WebServer server(80);
static DNSServer dnsServer;
static uint32_t lastApHealMs = 0;
static uint32_t lastStaSeenMs = 0;
static uint32_t lastHttpTransferMs = 0; // must be declared before ensureApHealthy()

static void printResetReason() {
  const esp_reset_reason_t r = esp_reset_reason();
  Serial.print("Reset reason: ");
  Serial.println((int)r);
}

static void ensureApHealthy() {
  const uint32_t now = millis();
  if (now - lastApHealMs < 3000) return;
  lastApHealMs = now;

  const IPAddress ip = WiFi.softAPIP();
  const bool ipBad = (ip[0] == 0);
  const uint8_t sta = WiFi.softAPgetStationNum();
  if (sta > 0) lastStaSeenMs = now;

  // Log station count periodically for debugging
  static uint32_t lastLogMs = 0;
  if (now - lastLogMs > 10000) {
    lastLogMs = now;
    Serial.printf("AP: sta=%u ip=%s lastXfer=%lus ago\n",
      sta, ip.toString().c_str(), (unsigned long)((now - lastHttpTransferMs) / 1000));
  }

  // IMPORTANT:
  // sta==0 is NORMAL whenever the phone is disconnected / screen off / user leaves Wi-Fi settings.
  // Restarting SoftAP in that case *causes* disconnect loops (exactly what you're seeing).
  //
  // So we ONLY heal when the AP IP becomes invalid (true Wi-Fi stack fault).
  if (ipBad) {
    Serial.println("AP heal: softAPIP invalid -> restarting SoftAP");
    dnsServer.stop();
    WiFi.softAPdisconnect(true);
    delay(200);
    WiFi.mode(WIFI_AP);
    WiFi.setSleep(false);
    WiFi.softAP(AP_SSID, AP_PASS, 1, 0);
    delay(200);
    dnsServer.start(53, "*", WiFi.softAPIP());
    Serial.print("AP healed, new IP: ");
    Serial.println(WiFi.softAPIP());
  }
}

// ================= FILE MANAGEMENT =================
int currentIndex = 1;
int cachedFileCount = 0;  // Cache file count to avoid slow SD scans
const char* INDEX_FILE = "/index.txt";

// ================= BLE INDEX BROADCAST (NimBLE - allows restart without reboot) =================
#if BLE_ENABLED
#define BLE_DEVICE_NAME "Memorable"
#define BLE_SERVICE_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define BLE_INDEX_CHAR_UUID "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

NimBLEServer* pBleServer = nullptr;
NimBLECharacteristic* pIndexCharacteristic = nullptr;
NimBLEAdvertising* pBleAdvertising = nullptr;
bool deviceConnected = false;
volatile bool httpTransferInProgress = false;
bool bleAdvertisingStopped = false;

void stopBleAdvertising() {
  if (!bleAdvertisingStopped && pBleAdvertising) {
    pBleAdvertising->stop();
    bleAdvertisingStopped = true;
    Serial.println("BLE advertising stopped for WiFi sync");
  }
}

void resumeBleAdvertising() {
  if (bleAdvertisingStopped && pBleAdvertising) {
    pBleAdvertising->start();
    bleAdvertisingStopped = false;
    Serial.println("BLE advertising resumed (sync-complete)");
  }
}

#endif

// ================= BLE FILE TRANSFER =================
// Protocol:
//   Phone → ESP32 via CMD char (WRITE_NO_RESPONSE):
//     "LIST"       → ESP32 pushes L-chunks then X
//     "GET:<path>" → ESP32 opens file, auto-sends first D-chunk
//     "NEXT"       → ESP32 sends next D-chunk (used after 1st chunk)
//     "ABORT"      → cancel current transfer
//   ESP32 → Phone via DATA char (NOTIFY), first byte = type:
//     'L' + bytes  → list JSON fragment
//     'D' + bytes  → file data chunk
//     'X'          → end of transfer (list or file)
//     'E' + msg    → error string
#if BLE_ENABLED

#define BLE_XFER_SERVICE_UUID   "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define BLE_XFER_CMD_CHAR_UUID  "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define BLE_XFER_DATA_CHAR_UUID "beb5483f-36e1-4688-b7f5-ea07361b26a8"

#define BXFER_TYPE_LIST   'L'
#define BXFER_TYPE_DATA   'D'
#define BXFER_TYPE_END    'X'
#define BXFER_TYPE_ERROR  'E'
// Warmup packet: throwaway notification sent at the start of each LIST/GET to
// absorb the first-notification byte-drop seen on some Android BT stacks.
#define BXFER_TYPE_WARMUP 'W'
// Chunk payload bytes (1 type byte + BXFER_CHUNK_BYTES data = total notify size).
// Kept SMALL (240 → 241-byte notification) because when DLE isn't explicitly
// negotiated, the link-layer PDU defaults to 27 bytes. A 513-byte notification
// would fragment into 20 LL packets — fragile and several drops cause the
// whole notification to be lost. 241 bytes fragments into ~9 LL packets which
// is far more reliable. Trade: more chunks per file (~2× fewer bytes each)
// but significantly higher success rate.
#define BXFER_CHUNK_BYTES 240
// Burst window: ESP32 streams this many chunks, then pauses until phone sends NEXT.
// Tuned for reliability over speed — smaller burst means less chance of overrunning
// NimBLE's TX mbuf pool and silently dropping chunks. 4 + per-chunk pacing gives a
// good balance: each GET cycle produces ~2 KB of data then waits for NEXT, enough
// to saturate one connection event but not overflow the queue.
#define BXFER_BURST_SIZE 4

enum BleXferState { BXFER_IDLE, BXFER_LIST, BXFER_FILE };

NimBLECharacteristic* pXferCmdChar  = nullptr;
NimBLECharacteristic* pXferDataChar = nullptr;

BleXferState bleXferState     = BXFER_IDLE;
File         bleXferFile;
bool         bleXferInProgress = false;
// Set true by CMD callback so the main loop (not the BLE task) does the SD read + notify
volatile bool bleXferSendChunk = false;
// Chunks sent in current burst window; reset to 0 on GET and NEXT.
int           bleXferBurstCount = 0;

// For LIST: full JSON held in RAM, sent piece by piece
static String bleXferListJson  = "";
static int    bleXferListOffset = 0;

// ---- Request flags set by the BLE callback, consumed by the BLE xfer task ----
// The BLE host task MUST NOT touch SD (not thread-safe). All SD operations run
// on a DEDICATED task (bleXferTask), not on loop(), so that slow/blocking SD
// operations on corrupted files don't freeze the main UI loop (camera preview,
// display updates stay responsive; phone just sees the affected transfer time
// out and retries/skips, instead of watching the whole pendant hang).
volatile bool bleXferReqAbort = false;
volatile bool bleXferReqList  = false;
volatile bool bleXferReqGet   = false;
volatile bool bleXferReqNext  = false;
char          bleXferReqPath[64] = {0};
// Safety cap: refuse to transfer absurdly large files over BLE (typical JPEGs
// are <200 KB, WAVs <2 MB). Protects against FAT32 reading a bogus size from
// a corrupted directory entry.
#define BLE_XFER_MAX_FILE_BYTES (5UL * 1024UL * 1024UL)

// END marker. If totalBytes >= 0 we append a little-endian 4-byte size so the
// phone can validate the received byte count and retry on truncation. LIST
// calls this with totalBytes = -1 (size isn't meaningful for a JSON list).
static void bleXferSendEnd(int32_t totalBytes = -1) {
  if (!pXferDataChar || !deviceConnected) return;
  if (totalBytes < 0) {
    uint8_t pkt[1] = { BXFER_TYPE_END };
    pXferDataChar->setValue(pkt, 1);
  } else {
    uint8_t pkt[5];
    pkt[0] = BXFER_TYPE_END;
    pkt[1] = (uint8_t)(totalBytes        & 0xFF);
    pkt[2] = (uint8_t)((totalBytes >> 8)  & 0xFF);
    pkt[3] = (uint8_t)((totalBytes >> 16) & 0xFF);
    pkt[4] = (uint8_t)((totalBytes >> 24) & 0xFF);
    pXferDataChar->setValue(pkt, 5);
  }
  pXferDataChar->notify();
}

// Small throwaway notification sent before real payload. Absorbs any
// first-notification byte-drop; phone ignores 'W' packets.
static void bleXferSendWarmup() {
  if (!pXferDataChar || !deviceConnected) return;
  uint8_t pkt[32];
  pkt[0] = BXFER_TYPE_WARMUP;
  for (int i = 1; i < 32; i++) pkt[i] = 0;
  pXferDataChar->setValue(pkt, 32);
  pXferDataChar->notify();
  // Brief pause so the warmup actually transmits on a connection event BEFORE
  // we queue the first real data chunk. With back-to-back notify() calls at
  // small LL PDU sizes the queue can back up and chunks get dropped.
  delay(30);
}

static void bleXferSendError(const char* msg) {
  if (pXferDataChar && deviceConnected) {
    String s = String((char)BXFER_TYPE_ERROR) + msg;
    pXferDataChar->setValue((uint8_t*)s.c_str(), s.length());
    pXferDataChar->notify();
  }
  if (bleXferFile) bleXferFile.close();
  bleXferState      = BXFER_IDLE;
  bleXferInProgress = false;
  bleXferSendChunk  = false;
}

static void bleXferAbort() {
  if (bleXferFile) bleXferFile.close();
  bleXferState      = BXFER_IDLE;
  bleXferInProgress = false;
  bleXferSendChunk  = false;
  bleXferListJson   = "";
  bleXferListOffset = 0;
  bleXferBurstCount = 0;
}

// Called from loop() — all SD I/O (LIST, GET, chunk read) happens here so it
// never races with the BLE host task. onWrite just sets request flags.
void processBleXfer() {
  // ---- Command dispatch (must run BEFORE the chunk-send logic below) ----
  if (bleXferReqAbort) {
    bleXferReqAbort = false;
    bleXferAbort();
    delay(20);  // let the SD library settle after close
  }
  if (bleXferReqNext) {
    bleXferReqNext = false;
    if (bleXferState == BXFER_FILE || bleXferState == BXFER_LIST) {
      bleXferBurstCount = 0;
      bleXferSendChunk  = true;
    }
  }
  if (bleXferReqList) {
    bleXferReqList = false;
    String json = "[";
    File root = SD.open("/");
    if (root) {
      File f = root.openNextFile();
      while (f) {
        if (!f.isDirectory()) {
          String name = f.name();
          if (name.startsWith("/")) name = name.substring(1);
          json += "\"" + name + "\",";
        }
        f.close();
        f = root.openNextFile();
      }
      root.close();
    }
    if (json.endsWith(",")) json.remove(json.length() - 1);
    json += "]";
    bleXferListJson   = json;
    bleXferListOffset = 0;
    bleXferState      = BXFER_LIST;
    bleXferBurstCount = 0;
    bleXferInProgress = true;
    bleXferSendWarmup();  // absorb first-notification byte-drop
    bleXferSendChunk  = true;
    Serial.printf("BLE LIST built: %d bytes\n", (int)json.length());
  }
  if (bleXferReqGet) {
    bleXferReqGet = false;
    String path = String(bleXferReqPath);
    if (!path.startsWith("/")) path = "/" + path;
    // Go straight to SD.open() — avoid a second SD lookup via SD.exists which
    // can itself block on corrupted directory entries. SD.open() returns an
    // empty File for missing or unreadable paths, which we handle below.
    bleXferFile = SD.open(path);
    if (!bleXferFile) {
      Serial.printf("BLE GET open failed: %s\n", path.c_str());
      bleXferSendError("Not found");
      return;
    }
    // Reject absurdly large files — a corrupted FAT32 entry can claim GB-scale
    // sizes, which would make the phone wait forever. Also reject zero-size
    // files (nothing to send).
    uint32_t fileSize = bleXferFile.size();
    if (fileSize == 0) {
      Serial.printf("BLE GET: empty file %s\n", path.c_str());
      bleXferFile.close();
      bleXferSendError("Empty file");
      return;
    }
    if (fileSize > BLE_XFER_MAX_FILE_BYTES) {
      Serial.printf("BLE GET: file too large (%u bytes) for BLE: %s\n",
                    (unsigned)fileSize, path.c_str());
      bleXferFile.close();
      bleXferSendError("File too large");
      return;
    }
    bleXferState      = BXFER_FILE;
    bleXferBurstCount = 0;
    bleXferInProgress = true;
    bleXferSendWarmup();  // absorb first-notification byte-drop
    bleXferSendChunk  = true;
    Serial.printf("BLE GET opened: %s (%u bytes)\n", path.c_str(), (unsigned)bleXferFile.size());
  }

  if (!bleXferSendChunk || !pXferDataChar || !deviceConnected) {
    bleXferSendChunk = false;
    return;
  }
  bleXferSendChunk = false;

  if (bleXferState == BXFER_LIST) {
    // Use the same burst window as FILE: push up to BXFER_BURST_SIZE chunks
    // then stop until the phone acks with NEXT. Without this, a large file-list
    // JSON overflows NimBLE's TX mbuf pool and packets get silently dropped,
    // producing truncated JSON on the phone → JSONArray parse fails → empty list →
    // "no new files" even when the pendant has new captures.
    if (bleXferBurstCount >= BXFER_BURST_SIZE) {
      return;  // wait for phone's NEXT to reopen the window
    }
    int remaining = (int)bleXferListJson.length() - bleXferListOffset;
    if (remaining <= 0) {
      // All list chunks sent — send END
      bleXferSendEnd();
      bleXferState      = BXFER_IDLE;
      bleXferInProgress = false;
      bleXferBurstCount = 0;
      bleXferListJson   = "";
      bleXferListOffset = 0;
      return;
    }
    int chunkLen = min(remaining, BXFER_CHUNK_BYTES);
    uint8_t buf[BXFER_CHUNK_BYTES + 1];
    buf[0] = BXFER_TYPE_LIST;
    memcpy(buf + 1, bleXferListJson.c_str() + bleXferListOffset, chunkLen);
    pXferDataChar->setValue(buf, chunkLen + 1);
    pXferDataChar->notify();
    bleXferListOffset += chunkLen;
    bleXferBurstCount++;
    delay(8);                 // pace LIST chunks same as FILE
    bleXferSendChunk = true;  // next tick sends the next chunk (or pauses at burst limit)

  } else if (bleXferState == BXFER_FILE) {
    if (!bleXferFile) { bleXferSendError("File not open"); return; }
    // One chunk per tick + 8 ms delay → roughly one chunk per connection event.
    // This is slower than batch-within-tick but far more reliable: NimBLE's TX
    // mbuf pool cannot overrun because each chunk has fully transmitted (or at
    // least entered the LL queue) before the next one is queued.
    if (bleXferBurstCount >= BXFER_BURST_SIZE) {
      return;  // burst exhausted — wait for phone's NEXT
    }
    uint8_t buf[BXFER_CHUNK_BYTES + 1];
    int n = bleXferFile.read(buf + 1, BXFER_CHUNK_BYTES);
    if (n <= 0) {
      // EOF — send END with total file size so phone can verify no truncation.
      uint32_t totalSize = bleXferFile.size();
      bleXferFile.close();
      bleXferSendEnd((int32_t)totalSize);
      bleXferState      = BXFER_IDLE;
      bleXferInProgress = false;
      bleXferBurstCount = 0;
      Serial.printf("BLE GET done: %u bytes sent\n", (unsigned)totalSize);
      return;
    }
    buf[0] = BXFER_TYPE_DATA;
    pXferDataChar->setValue(buf, n + 1);
    pXferDataChar->notify();
    bleXferBurstCount++;
    // Diagnostic: print every 10 chunks so we can see progress on serial
    static uint32_t totalChunksSent = 0;
    totalChunksSent++;
    if (totalChunksSent % 10 == 0) {
      Serial.printf("[xfer] chunks sent so far: %u (burst=%d)\n",
                    (unsigned)totalChunksSent, bleXferBurstCount);
    }
    delay(8);                   // let NimBLE actually transmit this one
    bleXferSendChunk = true;    // continue next tick (up to burst limit)
  }
}

// No dedicated task — processBleXfer is called directly from loop(). Simpler
// and reliable; if a bad SD file blocks the loop, at worst the display stops
// updating briefly, but the BLE transfer state remains consistent.

class BleXferCmdCallback : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pChar) override {
    if (!deviceConnected) return;
    String cmd = pChar->getValue().c_str();
    cmd.trim();
    Serial.printf("BLE XFER CMD: '%s'\n", cmd.c_str());

    // CRITICAL: onWrite runs on the NimBLE host task; SD operations here race
    // with the main loop's SD I/O and corrupt the file handle. Only set flags.
    if (cmd == "LIST") {
      bleXferReqAbort = true;
      bleXferReqList  = true;
    } else if (cmd.startsWith("GET:")) {
      String path = cmd.substring(4);
      strncpy(bleXferReqPath, path.c_str(), sizeof(bleXferReqPath) - 1);
      bleXferReqPath[sizeof(bleXferReqPath) - 1] = '\0';
      bleXferReqAbort = true;
      bleXferReqGet   = true;
    } else if (cmd == "NEXT") {
      bleXferReqNext = true;
    } else if (cmd == "ABORT") {
      bleXferReqAbort = true;
    }
    // Wake up the main loop so processBleXfer() actually runs.
    bleXferSendChunk = true;
  }
};

#endif  // BLE_ENABLED (file transfer)

void notifyBleIndex(int idx) {
#if BLE_ENABLED
  if (httpTransferInProgress) return;
  if (pIndexCharacteristic && deviceConnected) {
    char buf[16];
    int len = snprintf(buf, sizeof(buf), "%d", idx);
    pIndexCharacteristic->setValue(buf);
    pIndexCharacteristic->notify((uint8_t*)buf, len);  // Explicit value for reliable delivery
  }
#endif
}

#if BLE_ENABLED
class BleServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* pServer, ble_gap_conn_desc* desc) override {
    deviceConnected = true;

    // ==== BLE link settings — tuned for RELIABILITY over speed ====
    // (1) 1M PHY (not 2M). 1M has ~5 dB better sensitivity, so fewer bit errors
    //     and fewer LL retransmissions. 2M was faster but some Android stacks
    //     drop chunks on 2M; 1M is the universally-supported, reliable default.
    ble_gap_set_prefered_le_phy(
      desc->conn_handle,
      BLE_GAP_LE_PHY_1M_MASK, BLE_GAP_LE_PHY_1M_MASK, BLE_GAP_LE_PHY_CODED_ANY);
    // (2) 15-30 ms connection interval (not the aggressive 7.5 ms).
    //     Gives the stack breathing room; Android is more likely to honor this
    //     range and stay synchronized under load.
    ble_gap_upd_params p = {};
    p.itvl_min = 12;   // 15 ms
    p.itvl_max = 24;   // 30 ms
    p.latency  = 0;
    p.supervision_timeout = 400;   // 4 s — roomier to tolerate brief stalls
    p.min_ce_len = 0; p.max_ce_len = 0;
    ble_gap_update_params(desc->conn_handle, &p);
    // Note: NimBLE negotiates DLE automatically when setMTU(517) is called, so
    // we no longer call ble_gap_set_data_len() explicitly — that symbol isn't
    // exposed in all NimBLE-Arduino releases and was causing linker errors.
  }
  void onDisconnect(NimBLEServer* pServer, ble_gap_conn_desc* desc) override {
    deviceConnected = false;
    if (!bleAdvertisingStopped) pBleAdvertising->start();  // Restart only if not in sync
  }
};

void setupBle() {
  NimBLEDevice::init(BLE_DEVICE_NAME);
  // Request maximum MTU so we can push 500-byte data chunks efficiently
  NimBLEDevice::setMTU(517);
  pBleServer = NimBLEDevice::createServer();
  pBleServer->setCallbacks(new BleServerCallbacks());

  // --- Index broadcast service (existing) ---
  NimBLEService* pService = pBleServer->createService(BLE_SERVICE_UUID);
  pIndexCharacteristic = pService->createCharacteristic(
    BLE_INDEX_CHAR_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY
  );
  char buf[16];
  snprintf(buf, sizeof(buf), "%d", readLastIndexFromFile());
  pIndexCharacteristic->setValue(buf);
  pService->start();

  // --- File transfer service (new) ---
  NimBLEService* pXferService = pBleServer->createService(BLE_XFER_SERVICE_UUID);
  // CMD: phone writes commands (WRITE + WRITE_NR so Android can use no-response writes)
  pXferCmdChar = pXferService->createCharacteristic(
    BLE_XFER_CMD_CHAR_UUID,
    NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
  );
  pXferCmdChar->setCallbacks(new BleXferCmdCallback());
  // DATA: ESP32 notifies phone with file chunks
  pXferDataChar = pXferService->createCharacteristic(
    BLE_XFER_DATA_CHAR_UUID,
    NIMBLE_PROPERTY::NOTIFY
  );
  pXferService->start();

  pBleAdvertising = NimBLEDevice::getAdvertising();
  pBleAdvertising->setName(BLE_DEVICE_NAME);
  pBleAdvertising->addServiceUUID(BLE_SERVICE_UUID);
  pBleAdvertising->addServiceUUID(BLE_XFER_SERVICE_UUID);
  pBleAdvertising->setScanResponse(true);
  pBleAdvertising->start();
  Serial.println("BLE advertising started - index + file-transfer services");
}
#endif

// ================= DISPLAY =================
TFT_eSPI tft = TFT_eSPI();
const int camera_width  = 240;
const int camera_height = 240;

// MAIN UI double-buffer (fixes overlay flicker/tearing like swipe demo)
static TFT_eSprite mainFrame = TFT_eSprite(&tft);
static bool mainFrameReady = false;
static uint32_t mainHomeLastDrawMs = 0;
static const uint32_t MAIN_HOME_REFRESH_MS = 1000;

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

// ================= QR SCANNER (from QR_reader_touch) =================
char lastQrPayload[QR_SCANNER_PAYLOAD_MAX] = "";
unsigned long qrOverlayUntil = 0;  // millis() when overlay hides
#define QR_OVERLAY_MS 5000

void drawQrOverlay(const char* payload) {
  tft.setTextColor(TFT_RED, TFT_BLACK);  // red text with black backing for readability
  tft.setTextSize(2);  // slightly larger
  tft.setTextDatum(TL_DATUM);
  tft.setTextWrap(true);
  const int x0 = 8;
  const int y0 = 80;
  tft.setCursor(x0, y0);
  const int maxChars = 300;
  for (int i = 0; payload[i] && i < maxChars; i++) {
    tft.print(payload[i]);
  }
  if (strlen(payload) > maxChars) tft.print("...");
}

// ================= CHSC6x Touch (I2C) =================
// Round Display touch controller is CHSC6x (capacitive).
// We read register 0..4 (5 bytes). When data[0] != 0 a touch exists:
//  - x = data[2]
//  - y = data[4]
//
// Default I2C address is 0x2E (per ESPP docs).
#define CHSC6X_ADDR 0x2E
#define CHSC6X_REG_START 0x00

// Our display is rotated with `tft.setRotation(1)` (90 degrees). The CHSC6x raw
// coordinates are typically reported for rotation=0, so we remap them here.
#define CHSC6X_TOUCH_ROTATE 1
// If needed, set these to 1 to correct mirroring.
#define CHSC6X_TOUCH_INVERT_X 0
#define CHSC6X_TOUCH_INVERT_Y 0

static bool chsc6x_read_touch_point(uint16_t* outX, uint16_t* outY) {
  if (!outX || !outY) return false;

  uint8_t data[5] = {0};
  const uint8_t want = (uint8_t)sizeof(data);

  // Robust read: retries reduce Wire error spam under load/noise.
  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    // Point to register 0, then read 5 bytes.
    Wire.beginTransmission(CHSC6X_ADDR);
    Wire.write(CHSC6X_REG_START);
    const uint8_t tx = (uint8_t)Wire.endTransmission(true); // STOP to release bus
    if (tx != 0) {
      delay(2);
      continue;
    }

    // Request 5 bytes and read them out. Use explicit uint8_t types to avoid
    // ambiguous Wire.requestFrom overloads.
    const uint8_t got = Wire.requestFrom((uint8_t)CHSC6X_ADDR, (uint8_t)want, (uint8_t)true);
    if (got != want) {
      delay(2);
      continue;
    }

    for (uint8_t i = 0; i < want; i++) data[i] = (uint8_t)Wire.read();
    break;
  }

  if (data[0] == 0) return false;

  uint16_t x = data[2];
  uint16_t y = data[4];

  // Optional invert
  if (CHSC6X_TOUCH_INVERT_X) x = 239 - x;
  if (CHSC6X_TOUCH_INVERT_Y) y = 239 - y;

  // Remap based on TFT rotation
  if (CHSC6X_TOUCH_ROTATE == 1) {
    // 90 degrees CW: (x,y) -> (y, 239-x)
    uint16_t rx = x;
    uint16_t ry = y;
    x = ry;
    y = 239 - rx;
  } else if (CHSC6X_TOUCH_ROTATE == 2) {
    x = 239 - x;
    y = 239 - y;
  } else if (CHSC6X_TOUCH_ROTATE == 3) {
    // 270 CW: (x,y) -> (239-y, x)
    uint16_t rx = x;
    uint16_t ry = y;
    x = 239 - ry;
    y = rx;
  }

  *outX = x;
  *outY = y;
  return true;
}

// ================= UI STATE =================
// We want true "click CAPTURE" vs "click QR" based on which on-screen button
// rectangle was touched. The Round Display uses a CHSC6x capacitive touch
// controller (read over I2C) with an interrupt on GPIO44.
//
// So: we use `touch44_trigger_update()` for press/hold timing, and read
// x/y from CHSC6x when touch is activated.
enum UiMode { UI_MAIN = 0, UI_CAPTURE = 1, UI_QR = 2 };
UiMode uiMode = UI_MAIN;

static bool waitingForBack = false;
static bool backIgnoreOnce = false;  // prevents immediate BACK on the same release that saved

static bool haveTouchCoords = false;
static uint16_t lastTouchX = 0;
static uint16_t lastTouchY = 0;
static UiMode mainPendingMode = UI_MAIN;
static bool backPressedThisTouch = false;

// Swipe-to-select mode on MAIN screen (based on swipe/src/main.cpp)
static const uint32_t MAIN_SWIPE_MAX_MS = 700;
static const uint32_t MAIN_SWIPE_POLL_MS = 25;
static const int MAIN_SWIPE_MIN_PIXELS = 40;
static const int MAIN_SWIPE_MAX_OFFAXIS = 50;
static const int MAIN_MOVE_TOLERANCE = 10;
static bool mainSwipeTriggered = false;
static uint32_t mainTouchStartMs = 0;
static uint16_t mainTouchStartX = 0;
static uint16_t mainTouchStartY = 0;
static uint32_t mainLastPollMs = 0;

// Sliding overlay animation (ported from swipe/src/main.cpp)
// NOTE: use uint8_t in function signatures to avoid Arduino auto-prototype issues.
static const uint8_t MAIN_OVERLAY_FROM_LEFT = 0;
static const uint8_t MAIN_OVERLAY_FROM_RIGHT = 1;
static uint8_t mainOverlaySide = MAIN_OVERLAY_FROM_LEFT;
static int mainOverlayW = 0;
static int mainOverlayWTarget = 0;
static int mainOverlayWStart = 0;
static uint32_t mainOverlayAnimStartMs = 0;
static bool mainOverlayActive = false;
static bool mainOverlayCommitted = false;
static uint8_t mainOverlayTargetMode = 1; // UiMode value: UI_CAPTURE=1, UI_QR=2
static bool mainIgnoreGesturesUntilRelease = false;
static const uint32_t MAIN_OVERLAY_ANIM_MS = 180;

static inline uint16_t mainOverlayBgColor() {
  return (mainOverlayTargetMode == 1) ? TFT_DARKGREY : TFT_NAVY;
}

static void mainOverlaySetWidthImmediate(int w) {
  if (w < 0) w = 0;
  if (w > 240) w = 240;
  mainOverlayW = w;
}

static void mainOverlayStartAnimTo(int targetW) {
  if (targetW < 0) targetW = 0;
  if (targetW > 240) targetW = 240;
  mainOverlayWStart = mainOverlayW;
  mainOverlayWTarget = targetW;
  mainOverlayAnimStartMs = millis();
}

static void mainOverlayTickAnim() {
  if (mainOverlayAnimStartMs == 0) return;
  const uint32_t now = millis();
  const uint32_t dt = now - mainOverlayAnimStartMs;
  if (dt >= MAIN_OVERLAY_ANIM_MS) {
    mainOverlayAnimStartMs = 0;
    mainOverlayW = mainOverlayWTarget;
    return;
  }
  const float t = (float)dt / (float)MAIN_OVERLAY_ANIM_MS;
  mainOverlayW = (int)(mainOverlayWStart + (mainOverlayWTarget - mainOverlayWStart) * t);
}

static void drawMainOverlay() {
  if (mainOverlayW <= 0) return;
  const int w = 240;
  const int h = 240;
  const int cx = w / 2;
  const int cy = h / 2;

  if (mainOverlaySide == MAIN_OVERLAY_FROM_LEFT) {
    mainFrame.fillRect(0, 0, mainOverlayW, h, mainOverlayBgColor());
  } else {
    mainFrame.fillRect(w - mainOverlayW, 0, mainOverlayW, h, mainOverlayBgColor());
  }

  const char* label = (mainOverlayTargetMode == 2) ? "QR" : "Capture";
  mainFrame.setTextColor(TFT_YELLOW, mainOverlayBgColor());
  mainFrame.setTextSize(2);

  if (mainOverlayW >= (w - 2)) {
    mainFrame.setTextDatum(MC_DATUM);
    mainFrame.drawString(label, cx, cy, 4);
    return;
  }

  const int edgePad = 10;
  if (mainOverlaySide == MAIN_OVERLAY_FROM_LEFT) {
    const int edgeX = mainOverlayW - edgePad;
    mainFrame.setTextDatum(MR_DATUM);
    mainFrame.drawString(label, edgeX, cy, 4);
  } else {
    const int edgeX = (w - mainOverlayW) + edgePad;
    mainFrame.setTextDatum(ML_DATUM);
    mainFrame.drawString(label, edgeX, cy, 4);
  }
}

static void mainOverlayBegin(uint8_t side, uint8_t targetMode) {
  mainOverlaySide = side;
  mainOverlayTargetMode = targetMode;
  mainOverlayActive = true;
  mainOverlayCommitted = false;
  mainOverlayAnimStartMs = 0;
  mainOverlaySetWidthImmediate(0);
}

static void mainOverlayCancelAnim() {
  mainOverlayStartAnimTo(0);
  mainOverlayCommitted = false;
}

static void mainOverlayCommitAnim() {
  mainOverlayStartAnimTo(240);
  mainOverlayCommitted = true;
}

static const char* weekdayName(int w) {
  // BM8563 weekDay: 0=Sun..6=Sat (per project constants)
  static const char* k[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
  if (w < 0 || w > 6) return "";
  return k[w];
}

static const char* monthName(int m) {
  static const char* k[] = {"", "January", "February", "March", "April", "May", "June",
                            "July", "August", "September", "October", "November", "December"};
  if (m < 1 || m > 12) return "";
  return k[m];
}

static const char* ordinalSuffix(int d) {
  if (d % 100 >= 11 && d % 100 <= 13) return "th";
  switch (d % 10) {
    case 1: return "st";
    case 2: return "nd";
    case 3: return "rd";
    default: return "th";
  }
}

static void drawHomeIcons(TFT_eSprite& s) {
  const uint16_t iconBg = tft.color565(0, 70, 140); // neon darker blue

  // Left "camera" icon
  const int cxL = 24;  // closer to edge (corner-ish) with small gap
  const int cy = 122;
  s.fillRoundRect(cxL - 14, cy - 10, 28, 20, 4, iconBg);
  s.fillRoundRect(cxL - 8, cy - 14, 16, 6, 2, iconBg);
  s.drawCircle(cxL, cy, 6, TFT_WHITE);
  s.fillCircle(cxL, cy, 2, TFT_WHITE);

  // Right "grid/apps" icon (2x2 squares)
  const int cxR = 216; // closer to edge (corner-ish) with small gap
  const int g = 6;
  const int gap = 4;
  for (int r = 0; r < 2; r++) {
    for (int c = 0; c < 2; c++) {
      int x = cxR - (g * 2 + gap) / 2 + c * (g + gap);
      int y = cy - (g * 2 + gap) / 2 + r * (g + gap);
      s.fillRoundRect(x, y, g, g, 2, iconBg);
    }
  }
}

static void drawBatteryBadge(TFT_eSprite& s, int pct) {
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;

 // const uint16_t ringColor = TFT_WHITE; // requested: white boundary
  const int cx = 120;
  const int cy = 18;
  // Slightly larger badge so text fits inside cleanly
  const int rOuter = 16;
  const int rInner = 14;

  // White ring boundary
//  for (int i = 0; i < 4; i++) s.drawCircle(cx, cy, rOuter - i, ringColor);
  s.fillCircle(cx, cy, rInner,  tft.color565(0, 70, 140));

  // Percent text
  s.setTextDatum(MC_DATUM);
  s.setTextColor(TFT_WHITE,  tft.color565(0, 70, 140));
  s.setTextSize(1);
  // Keep inside badge: clamp 100->99 for width
  const int shown = (pct >= 100) ? 99 : pct;
  s.drawString(String(shown) + "%", cx, cy + 1, 2);
}

// QR scanning cadence while in UI_QR (avoid decoding every loop).
static uint32_t lastQrScanAttemptMs = 0;
static const uint32_t QR_SCAN_INTERVAL_MS = 400;

// BaseName used for the current capture, so we can display it consistently.
static char currentCaptureBaseName[24] = "";

// Main screen buttons
// Main screen is swipe-based (no on-screen CAPTURE/QR buttons)
static UiMode mainSelectedMode = UI_CAPTURE;

// Back button (shown after capture/qr completes)
static const int BACK_BTN_X = 52;
static const int BACK_BTN_Y = 196;
static const int BACK_BTN_W = 136;
static const int BACK_BTN_H = 30;
static const int BACK_BTN_R = 12;

// Recording indicator (avoid overlapping BACK button)
// Top-right inside visible circle for Round Display
static const int REC_DOT_X = 180;
static const int REC_DOT_Y = 34;
static const int REC_DOT_R = 9;

static inline bool pointInRect(uint16_t x, uint16_t y, int rx, int ry, int rw, int rh) {
  return (x >= (uint16_t)rx && x < (uint16_t)(rx + rw) && y >= (uint16_t)ry && y < (uint16_t)(ry + rh));
}

static void drawMainBase() {
  mainFrame.fillSprite(TFT_BLACK);

  // Purple outer ring (anti-aliased "bezel" to avoid black speckle/jaggies)
  // Using smooth filled circles gives a dense, smartwatch-like boundary.
  const int cx = 120;
  const int cy = 120;
  const int rOuter = 112;
  const int ringW = 16;
  const int rInner = rOuter - ringW;

  // Clean AA ring: draw outer, then punch inner with correct AA background.
  // This avoids "pepper" artifacts caused by multiple blended shells.
  // Outermost bezel: neon blue (requested)
  const uint16_t ringOuterCol = tft.color565(0, 210, 255);
  mainFrame.fillSmoothCircle(cx, cy, rOuter, ringOuterCol, TFT_BLACK);
  mainFrame.fillSmoothCircle(cx, cy, rInner, TFT_BLACK, ringOuterCol);

  // Subtle inner lip (gives depth, still clean)
  const uint16_t lipCol = tft.color565(0, 140, 220);
  mainFrame.drawSmoothCircle(cx, cy, rInner + 1, lipCol, TFT_BLACK);

  // Dial background (light cream + subtle gloss)
  const uint16_t cream = tft.color565(245, 236, 220);
  const uint16_t creamShade = tft.color565(225, 214, 196);
  mainFrame.fillCircle(120, 120, 98, cream);
  mainFrame.drawCircle(120, 120, 98, creamShade);
  mainFrame.fillSmoothRoundRect(30, 38, 180, 84, 42, creamShade, cream);
  mainFrame.fillSmoothRoundRect(30, 44, 180, 74, 37, cream, creamShade);

  // Battery badge (top, round style like ring)
  drawBatteryBadge(mainFrame, getBatteryPercentage());

  // Hint text
  mainFrame.setTextDatum(MC_DATUM);
  mainFrame.setTextColor(tft.color565(70, 70, 80), cream);
  mainFrame.setTextSize(1);
  mainFrame.drawString("< swipe to enter mode >", 120, 80, 2);

  // Time + Date from RTC (fallback to placeholders)
  char timeBuf[6] = "09:30";
  char dateBuf[40] = "Tue, 31st March";
  if (rtcReady) {
    I2C_BM8563_DateTypeDef d;
    I2C_BM8563_TimeTypeDef t;
    rtc.getDate(&d);
    rtc.getTime(&t);
    snprintf(timeBuf, sizeof(timeBuf), "%02d:%02d", t.hours, t.minutes);
    snprintf(dateBuf, sizeof(dateBuf), "%s, %d%s %s",
             weekdayName(d.weekDay), (int)d.date, ordinalSuffix(d.date), monthName(d.month));
  }

  mainFrame.setTextColor(tft.color565(25, 25, 35), cream);
  mainFrame.setTextDatum(MC_DATUM);
  mainFrame.setTextSize(2); // requested
  mainFrame.drawString(timeBuf, 120, 130, 4);

  mainFrame.setTextSize(1);
  mainFrame.drawString(dateBuf, 120, 164, 2);

  // Side icons
  drawHomeIcons(mainFrame);
}

void drawMainInterface() {
  uiMode = UI_MAIN;
  waitingForBack = false;
  backIgnoreOnce = false;
  haveTouchCoords = false;
  backPressedThisTouch = false;
  currentCaptureBaseName[0] = '\0';
  lastQrPayload[0] = '\0';
  qrOverlayUntil = 0;
  if (mainFrameReady) {
    drawMainBase();
    mainFrame.pushSprite(0, 0);
  } else {
    // Fallback (should not happen): direct draw
    tft.fillScreen(TFT_BLACK);
    // Purple ring
  for (int i = 0; i < 10; i++) tft.drawCircle(120, 120, 112 - i, TFT_PURPLE);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.setTextSize(1);
    tft.setTextColor(0xBDF7, TFT_BLACK);
  tft.drawString("< swipe to enter mode >", 120, 80, 2);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("09:30", 120, 132, 4);
    tft.setTextSize(1);
    tft.drawString("Tue, 31st March", 120, 166, 2);
  }
}

void drawBackButton() {
  tft.fillRoundRect(BACK_BTN_X, BACK_BTN_Y, BACK_BTN_W, BACK_BTN_H, BACK_BTN_R, TFT_DARKGREY);
  tft.drawRoundRect(BACK_BTN_X, BACK_BTN_Y, BACK_BTN_W, BACK_BTN_H, BACK_BTN_R, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(1);
  tft.drawString("BACK", BACK_BTN_X + BACK_BTN_W / 2, BACK_BTN_Y + BACK_BTN_H / 2 + 1, 4);
}

void drawMainButtonPressed(uint8_t which) {
  // No-op: main UI no longer uses button rectangles.
  (void)which;
}

void drawBackButtonPressed() {
  tft.fillRoundRect(BACK_BTN_X, BACK_BTN_Y, BACK_BTN_W, BACK_BTN_H, BACK_BTN_R, TFT_RED);
  tft.drawRoundRect(BACK_BTN_X, BACK_BTN_Y, BACK_BTN_W, BACK_BTN_H, BACK_BTN_R, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, TFT_RED);
  tft.setTextDatum(MC_DATUM);
  // Keep font size identical to normal (no "big BACK" on press)
  tft.setTextSize(1);
  tft.drawString("BACK", BACK_BTN_X + BACK_BTN_W / 2, BACK_BTN_Y + BACK_BTN_H / 2 + 1, 4);
}

// ================= BATTERY =================
#define NUM_ADC_SAMPLE 20           // Sampling frequency for accuracy
#define BATTERY_DEFICIT_VOL 1850 // Battery voltage at empty (mV)
#define BATTERY_FULL_VOL 2450    // Battery voltage at full (mV)

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

// ================= DATE/TIME FOR FILENAMES (RTC) =================
// Based on Seeed Round Display manual RTC calibration:
// https://wiki.seeedstudio.com/seeedstudio_round_display_usage/#off-line-manual-calibration-of-the-rtc
// Returns "YYYYMMDD_HHMMSS" for use in filenames, or empty string if RTC not ready
void getTimestampForFilename(char* buf, size_t bufSize) {
  if (!rtcReady) { buf[0] = '\0'; return; }
  I2C_BM8563_DateTypeDef dateStruct;
  I2C_BM8563_TimeTypeDef timeStruct;
  rtc.getDate(&dateStruct);
  rtc.getTime(&timeStruct);
  snprintf(buf, bufSize, "%04d%02d%02d_%02d%02d%02d",
           dateStruct.year, dateStruct.month, dateStruct.date,
           timeStruct.hours, timeStruct.minutes, timeStruct.seconds);
}

// (QR filenames must match image/audio baseName; we save QR on release.)

// Init RTC - manual calibration when SET_RTC_ON_BOOT is 1
bool initRTC() {
  // XIAO ESP32S3: D4=GPIO5 (SDA), D5=GPIO6 (SCL) - Round Display RTC/touch I2C
  Wire.begin(RTC_SDA, RTC_SCL);
  Wire.setClock(100000); // CHSC6x + RTC are more stable at 100k under load
  rtc.begin();
  delay(20);  // Allow RTC to stabilize before write
#if SET_RTC_ON_BOOT
  I2C_BM8563_DateTypeDef dateStruct;
  dateStruct.weekDay = RTC_WEEKDAY;
  dateStruct.month = RTC_MONTH;
  dateStruct.date = RTC_DAY;
  dateStruct.year = RTC_YEAR;
  rtc.setDate(&dateStruct);
  I2C_BM8563_TimeTypeDef timeStruct;
  timeStruct.hours = RTC_HOUR;
  timeStruct.minutes = RTC_MINUTE;
  timeStruct.seconds = RTC_SECOND;
  rtc.setTime(&timeStruct);
  Serial.println("RTC time calibration complete!");
  // Verify: read back and print
  I2C_BM8563_DateTypeDef d;
  I2C_BM8563_TimeTypeDef t;
  rtc.getDate(&d);
  rtc.getTime(&t);
  Serial.printf("RTC readback: %04d-%02d-%02d %02d:%02d:%02d\n",
                d.year, d.month, d.date, t.hours, t.minutes, t.seconds);
#endif
  rtcReady = true;
  return true;
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
      // Legacy: /image1.jpg + /audio1.wav
      if (name.startsWith("/image") && name.endsWith(".jpg")) {
        String index = name.substring(6, name.length() - 4);
        String audioName = "/audio" + index + ".wav";
        if (SD.exists(audioName)) count++;
      }
      // Date/time: /image_20250216_143022.jpg + /audio_20250216_143022.wav
      else if (name.startsWith("/image_") && name.endsWith(".jpg")) {
        String stamp = name.substring(7, name.length() - 4);
        String audioName = "/audio_" + stamp + ".wav";
        if (SD.exists(audioName)) count++;
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

// Write QR payload as plain text (for pairing with image/audio by filename base).
void writeTextFile(fs::FS &fs, const char *path, const char *text) {
  if (!text || text[0] == '\0') return;
  File file = fs.open(path, FILE_WRITE);
  if (!file) return;
  file.print(text);
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

// Save QR payload to a .txt file with QR prefix.
// QR_<baseName>.txt (RTC mode) or QR<idx>.txt (index fallback).
void saveQrPayloadTxt(const char* baseName, int index, const char* payload) {
  if (!payload || payload[0] == '\0') return;

  char txtPath[64];
  if (baseName && baseName[0] != '\0') {
    snprintf(txtPath, sizeof(txtPath), "/QR_%s.txt", baseName);
  } else {
    snprintf(txtPath, sizeof(txtPath), "/QR%d.txt", index);
  }

  writeTextFile(SD, txtPath, payload);
  Serial.printf("Saved QR payload %s\n", txtPath);
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
// baseName: e.g. "20250216_143022" or "1" - shared between image and audio for this capture
void startRecording(const char* baseName) {
  char f[48];
  if (rtcReady && baseName[0] != '\0') {
    snprintf(f, sizeof(f), "/audio_%s.wav", baseName);
  } else {
    sprintf(f, "/audio%d.wav", currentIndex);
  }

  if (xSemaphoreTake(audioFileMutex, portMAX_DELAY)) {
    audioFile = SD.open(f, FILE_WRITE);
    for (int i = 0; i < WAV_HEADER_SIZE; i++) audioFile.write((uint8_t)0);
    audioBytes = 0;
    shouldStopRecording = false;
    isRecording = true;
    xSemaphoreGive(audioFileMutex);
  }
  
  // Show recording indicator (red dot only, no text)
  tft.fillCircle(REC_DOT_X, REC_DOT_Y, REC_DOT_R, TFT_RED);
  tft.drawCircle(REC_DOT_X, REC_DOT_Y, REC_DOT_R + 1, TFT_WHITE);
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

  // Clear recording indicator dot
  tft.fillCircle(REC_DOT_X, REC_DOT_Y, REC_DOT_R + 2, TFT_BLACK);
}

// ================= HTTP HANDLERS =================
void handleRoot() {
#if BLE_ENABLED
  stopBleAdvertising();
#endif
  String html = "<html><head><title>ESP32 Camera</title></head><body>";
  html += "<h1>ESP32 Camera - File Server</h1>";
  html += "<p>Files: " + String(cachedFileCount) + " pairs</p>";
  html += "<p><a href='/list'>List Files</a></p>";
  html += "<p><a href='/status'>Status</a></p>";
  html += "</body></html>";
  server.sendHeader("Connection", "close");
  server.send(200, "text/html", html);
}

void handleListFiles() {
  // Do NOT stop BLE here — /list is lightweight and called by keep-alive frequently.
  // BLE is only paused during actual binary file downloads (handleDownload).
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
  server.sendHeader("Connection", "close");
  server.send(200, "application/json", json);
}

void handleDownload() {
#if BLE_ENABLED
  stopBleAdvertising();
#endif
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

  httpTransferInProgress = true;
  lastHttpTransferMs = millis();

  // Stream manually in chunks with yields (prevents stalls/freezes on long transfers)
  WiFiClient client = server.client();
  server.setContentLength((int)f.size());
  server.sendHeader("Connection", "close");
  server.send(200, "application/octet-stream", "");

  uint8_t buf[1024];
  uint32_t startMs = millis();
  uint32_t lastProgressMs = millis();
  while (client.connected()) {
    // Hard timeout + progress timeout to avoid "device freeze" if client drops mid-download
    const uint32_t now = millis();
    if (now - startMs > 60000) break;         // 60s max per file
    if (now - lastProgressMs > 5000) break;   // 5s without progress

    int n = f.read(buf, sizeof(buf));
    if (n <= 0) break;
    size_t w = client.write(buf, (size_t)n);
    if (w == 0) break;
    lastHttpTransferMs = millis();
    lastProgressMs = lastHttpTransferMs;
    delay(1);
  }

  f.close();
  // Make sure the TCP socket is closed so we don't exhaust file descriptors.
  client.stop();
  httpTransferInProgress = false;
  lastHttpTransferMs = millis();
}

void handleSyncComplete() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Connection", "close");
  server.send(200, "application/json", "{\"ok\":true}");
#if BLE_ENABLED
  resumeBleAdvertising();
#endif
}

void handleStatus() {
  // Do NOT stop BLE here — /status is the keep-alive endpoint pinged every 5s by the app.
  // Stopping BLE advertising on every ping toggles the shared radio and drops the AP connection.
  String json = "{";
  json += "\"file_pairs\":" + String(cachedFileCount) + ",";
  json += "\"current_index\":" + String(currentIndex) + ",";
  json += "\"recording\":" + String(isRecording ? "true" : "false") + ",";
  json += "\"syncing\":" + String(httpTransferInProgress ? "true" : "false") + ",";
  json += "\"sd_card\":" + String(sd_sign ? "true" : "false") + ",";
  json += "\"camera\":" + String(camera_sign ? "true" : "false");
  json += "}";
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Connection", "close");
  server.send(200, "application/json", json);
}

// Connectivity check helpers: make Android/iOS/Windows believe this AP has internet.
//
// CRITICAL: NEVER return HTTP 200 with an HTML body here.
// Android's ConnectivityService probes a URL and classifies the response:
//   - HTTP 204 (no body)  → "has internet"  → stays connected ✓
//   - HTTP 200 + HTML     → "captive portal" → shows "Sign in to network",
//                           then disconnects after ~60 s and REFUSES to reconnect ✗
//
// We return 204 for every connectivity probe path so Android always sees "internet OK".
static void handleGenerate204() {
  server.sendHeader("Connection", "close");
  server.send(204);
}
static void handleConnectivityCheck() {
  // Return 204 for all connectivity check / unknown paths.
  // This prevents Android from treating the AP as a captive portal.
  server.sendHeader("Connection", "close");
  server.send(204);
}

// ================= DISPLAY UPDATE =================
void updateDisplay() {
  // MAIN screen battery is drawn in the watchface. In CAPTURE/QR we don't draw battery.
  (void)0;
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(50);
  printResetReason();
  touch44_trigger_init();
  
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
  // Use DRAM for fb: pushImage can struggle with PSRAM on some TFT SPI setups
  c.fb_location = CAMERA_FB_IN_DRAM;
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
#if TFT_BL > 0
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);  // Turn on backlight
#endif
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(tft.color565(0, 210, 255));

  // MAIN UI sprite (double buffer) to prevent overlay flicker
  mainFrame.setColorDepth(16);
  mainFrameReady = mainFrame.createSprite(240, 240);
  
  // Show startup message
  tft.setTextColor(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("MEMORABLE", 120, 100, 4);
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

  // RTC INIT (Round Display - manual calibration, see SET_RTC_ON_BOOT)
  if (initRTC()) {
    tft.drawString("RTC: OK", 120, 195, 2);
  } else {
    tft.drawString("RTC: Index mode", 120, 195, 2);
  }
  delay(500);

  // AUDIO
  setupI2S();
  xTaskCreatePinnedToCore(audioRecordingTask, "AudioTask", 4096, NULL, 2, &audioTaskHandle, 1);

  // QR SCANNER (from QR_reader_touch - requires PSRAM)
  if (qr_scanner_init()) {
    Serial.println("QR scanner ready (short tap to scan)");
  } else {
    Serial.println("QR scanner init failed (no PSRAM?)");
  }

  // WIFI AP
  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);                 // critical: prevent AP drops under load
  WiFi.softAP(AP_SSID, AP_PASS, 1, 0);  // fixed channel=1, visible SSID
  WiFi.setTxPower(WIFI_POWER_15dBm);    // reduce brownout spikes during sync
  dnsServer.start(53, "*", WiFi.softAPIP());
  
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
  server.on("/sync-complete", handleSyncComplete);
  // Connectivity check endpoints — all return 204 so Android never sees a captive portal.
  server.on("/generate_204", handleGenerate204);        // Android (AOSP)
  server.on("/gen_204", handleGenerate204);             // Android (alt)
  server.on("/hotspot-detect.html", handleConnectivityCheck); // Apple CNA
  server.on("/connecttest.txt", handleConnectivityCheck);     // Windows NCSI
  server.on("/ncsi.txt", handleConnectivityCheck);            // Windows NCSI (alt)
  server.onNotFound(handleConnectivityCheck); // any OEM variant → always 204
  server.begin();

#if BLE_ENABLED
  setupBle();
  if (sd_sign) notifyBleIndex(readLastIndexFromFile());
#endif
  
  drawMainInterface();
}

// ================= LOOP =================
void loop() {
  // Avoid UDP send errors when no station is connected.
  // (These were showing up as WiFiUdp endPacket(): could not send data.)
  if (WiFi.softAPgetStationNum() > 0) {
    dnsServer.processNextRequest();
  }
  server.handleClient();
#if BLE_ENABLED
  // Process pending BLE file-transfer work. Called directly from loop() — all
  // SD operations live here (never in the BLE callback) so the callback stays
  // thread-safe and fast.
  if ((bleXferSendChunk || bleXferReqAbort || bleXferReqList || bleXferReqGet || bleXferReqNext)
      && !httpTransferInProgress) {
    processBleXfer();
  }
#endif
  ensureApHealthy();

  if (!camera_sign || !sd_sign) return;

  // During HTTP or BLE sync, pause heavy camera/UI work.
  if (httpTransferInProgress || bleXferInProgress || (millis() - lastHttpTransferMs) < 200) {
    delay(2);
    return;
  }

  updateDisplay();

  const Touch44TriggerEvent touchEvt = touch44_trigger_update();
  static bool touchArmed = false;

  // MAIN overlay animation tick (runs even when no touch)
  if (uiMode == UI_MAIN) {
    // Periodic redraw for clock/battery when idle on MAIN
    if (!mainOverlayActive && mainOverlayAnimStartMs == 0) {
      const uint32_t now = millis();
      if (now - mainHomeLastDrawMs >= MAIN_HOME_REFRESH_MS) {
        mainHomeLastDrawMs = now;
        if (mainFrameReady) {
          drawMainBase();
          mainFrame.pushSprite(0, 0);
        }
      }
    }

    mainOverlayTickAnim();
    if (mainOverlayActive || mainOverlayAnimStartMs != 0) {
      if (mainFrameReady) {
        drawMainBase();
        drawMainOverlay();
        mainFrame.pushSprite(0, 0);
      } else {
        drawMainBase();
        // (no overlay in fallback)
      }
    }
  }

  // Arm on touch down
  if (touchEvt.touchJustActivated) {
    touchArmed = true;

    // MAIN: swipe-based selection (no buttons)
    if (uiMode == UI_MAIN) {
      haveTouchCoords = chsc6x_read_touch_point(&lastTouchX, &lastTouchY);
      mainTouchStartMs = millis();
      mainSwipeTriggered = false;
      mainLastPollMs = mainTouchStartMs;
      mainIgnoreGesturesUntilRelease = false;
      mainOverlayActive = false;
      mainOverlayCommitted = false;
      mainOverlayAnimStartMs = 0;
      mainOverlaySetWidthImmediate(0);
      if (haveTouchCoords) {
        mainTouchStartX = lastTouchX;
        mainTouchStartY = lastTouchY;
      }
      mainPendingMode = mainSelectedMode; // start from current selection
      drawMainInterface();
    } else {
      // In CAPTURE/QR, BACK should be available anytime.
      haveTouchCoords = chsc6x_read_touch_point(&lastTouchX, &lastTouchY);
      backPressedThisTouch = (haveTouchCoords &&
                               pointInRect(lastTouchX, lastTouchY, BACK_BTN_X, BACK_BTN_Y, BACK_BTN_W, BACK_BTN_H));
      if (backPressedThisTouch) {
        drawBackButtonPressed();
        touchArmed = false;  // don't start recording when touching BACK
      } else {
        backPressedThisTouch = false;
      }
    }
  }

  // Decide if we need a camera frame this iteration
  const bool needCameraFrame = (uiMode != UI_MAIN) && !waitingForBack;
  camera_fb_t *fb = nullptr;
  if (needCameraFrame) {
    fb = esp_camera_fb_get();
    if (!fb) {
      delay(10);
      return;
    }
  }

  // ===== UI: MAIN =====
  if (uiMode == UI_MAIN) {
    // If we already committed/cancelled an overlay, ignore gestures until finger is released.
    if (mainIgnoreGesturesUntilRelease) {
      if (touchEvt.touchJustReleased) {
        mainIgnoreGesturesUntilRelease = false;
        drawMainInterface();
      }
    } else {
      // While finger is down on MAIN: show interactive overlay and allow swipe commit/cancel.
      if (touchEvt.debouncedTouchDown && touchArmed) {
        const uint32_t now = millis();
        if ((now - mainTouchStartMs) <= MAIN_SWIPE_MAX_MS && (now - mainLastPollMs) >= MAIN_SWIPE_POLL_MS) {
          mainLastPollMs = now;
          uint16_t x, y;
          if (chsc6x_read_touch_point(&x, &y)) {
            lastTouchX = x;
            lastTouchY = y;
            int dx = (int)x - (int)mainTouchStartX;
            int dy = (int)y - (int)mainTouchStartY;

            // Start overlay as soon as movement exceeds tolerance.
            if (!mainOverlayActive) {
              if (abs(dx) > MAIN_MOVE_TOLERANCE || abs(dy) > MAIN_MOVE_TOLERANCE) {
                if (dx > 0) {
                  // Swipe RIGHT -> go to QR
                  mainOverlayBegin(MAIN_OVERLAY_FROM_LEFT, 2);
                } else if (dx < 0) {
                  // Swipe LEFT -> go to CAPTURE
                  mainOverlayBegin(MAIN_OVERLAY_FROM_RIGHT, 1);
                }
              }
            }

            if (mainOverlayActive && !mainOverlayCommitted) {
              // 2x displacement like demo
              int wDisp = abs(dx) * 2;
              if (wDisp > 240) wDisp = 240;
              mainOverlaySetWidthImmediate(wDisp);
            }
          }
        }
      }

      // Touch release handling in MAIN:
      if (touchEvt.touchJustReleased) {
        touchArmed = false;

        // If overlay is active (swipe), commit/cancel. On commit we'll enter that mode automatically.
        if (mainOverlayActive && !mainOverlayCommitted) {
          const bool passedHalf = mainOverlayW >= (240 / 2);
          if (passedHalf) mainOverlayCommitAnim();
          else mainOverlayCancelAnim();
          mainIgnoreGesturesUntilRelease = true;
        } else if (!mainOverlayActive) {
          // No swipe: do nothing (user requested swipe-to-open)
        }
      }
    }

    // Overlay animation follow-up: when commit finishes, enter that mode.
    if (mainOverlayActive && mainOverlayAnimStartMs == 0) {
      if (mainOverlayCommitted && mainOverlayW >= (240 - 2)) {
        mainSelectedMode = (mainOverlayTargetMode == 2) ? UI_QR : UI_CAPTURE;
        // Enter the selected mode immediately after commit reaches full cover.
        uiMode = (mainSelectedMode == UI_QR) ? UI_QR : UI_CAPTURE;
        waitingForBack = false;
        lastQrPayload[0] = '\0';
        qrOverlayUntil = 0;
        currentCaptureBaseName[0] = '\0';
        mainOverlayCommitted = false;
        mainOverlayActive = false;
        mainIgnoreGesturesUntilRelease = false;
        mainOverlayW = 0;
        tft.fillScreen(TFT_BLACK);
      } else if (mainOverlayW == 0) {
        mainOverlayActive = false;
        drawMainInterface();
      }
    }
  }

  // BACK handling is done after the CAPTURE/QR logic, using the same touch gesture.

  // ===== UI: CAPTURE or QR =====
  if (uiMode != UI_MAIN && needCameraFrame && fb) {
    // Long press -> capture image + start audio (both CAPTURE and QR modes).
    if (touchEvt.longPressJustActivated && touchArmed && !isRecording) {
      getTimestampForFilename(currentCaptureBaseName, sizeof(currentCaptureBaseName));

      char imgPath[48];
      if (rtcReady && currentCaptureBaseName[0] != '\0') {
        snprintf(imgPath, sizeof(imgPath), "/image_%s.jpg", currentCaptureBaseName);
      } else {
        sprintf(imgPath, "/image%d.jpg", currentIndex);
      }

      // Capture image
      uint8_t *jpg;
      size_t len;
      frame2jpg(fb, 100, &jpg, &len);
      writeFile(SD, imgPath, jpg, len);
      free(jpg);
      Serial.printf("Captured %s\n", imgPath);

      // In QR mode, decode immediately from the same RGB565 frame.
      if (uiMode == UI_QR) {
        // Don't clear lastQrPayload here; if immediate decode fails, we still want to
        // save the most recent live-detected payload on release.
        if (fb->format == PIXFORMAT_RGB565 && fb->width > 0 && fb->height > 0) {
          if (qr_scanner_try_decode((uint16_t*)fb->buf, fb->width, fb->height,
                                     lastQrPayload, sizeof(lastQrPayload))) {
            qrOverlayUntil = millis() + QR_OVERLAY_MS;
            drawQrOverlay(lastQrPayload);  // show right away
            Serial.print("QR: ");
            Serial.println(lastQrPayload);
          }
        }
      }

      // Start audio recording (same baseName for pairing)
      startRecording(currentCaptureBaseName);
    }

    // Touch release: stop audio (if we were recording) + show BACK screen
    if (touchEvt.touchJustReleased) {
      touchArmed = false;

      const bool wasRecording = isRecording;
      if (wasRecording) stopRecording();

      if (wasRecording) {
        // In QR mode: save QR payload on release with same baseName as image/audio.
        if (uiMode == UI_QR && lastQrPayload[0] != '\0') {
          saveQrPayloadTxt(currentCaptureBaseName, currentIndex, lastQrPayload);
        }

        // Flash green to indicate save
        tft.fillRect(0, 220, 240, 20, TFT_GREEN);
        tft.setTextColor(TFT_WHITE);
        tft.setTextDatum(MC_DATUM);

        // Show the exact same timestamp used in the filenames (captured at long-press start)
        if (rtcReady && currentCaptureBaseName[0] != '\0') {
          tft.drawString(String("SAVED ") + currentCaptureBaseName, 120, 230, 2);
          Serial.printf("Saved image_%s.jpg + audio_%s.wav\n", currentCaptureBaseName, currentCaptureBaseName);
        } else {
          tft.drawString("SAVED #" + String(currentIndex), 120, 230, 2);
          Serial.printf("Saved image%d.jpg + audio%d.wav\n", currentIndex, currentIndex);
        }

        // Increment counters
        currentIndex++;
        cachedFileCount++;
        writeLastIndexToFile(currentIndex - 1);

#if BLE_ENABLED
        notifyBleIndex(currentIndex - 1);
#endif

        // Show BACK option
        waitingForBack = true;
        backIgnoreOnce = true;  // ignore BACK on the same release that finished saving
        delay(200);

        // If QR mode, show QR text on the BACK screen too
        if (uiMode == UI_QR && lastQrPayload[0] != '\0') {
          // Keep the camera area clear
          tft.fillRect(0, 80, 240, 130, TFT_BLACK);
          drawQrOverlay(lastQrPayload);
        }
        drawBackButton();
        delay(300);
      }
    }

    // Camera preview (only when not recording and not in BACK screen)
    if (!waitingForBack && !isRecording) {
      if (fb->format == PIXFORMAT_RGB565) {
        tft.startWrite();
        tft.setAddrWindow(0, 0, camera_width, camera_height);
        tft.pushImage(0, 0, camera_width, camera_height, (uint16_t*)fb->buf);
        tft.endWrite();

          // BACK button should be available all the time on CAPTURE/QR screens.
          if (backPressedThisTouch) drawBackButtonPressed();
          else drawBackButton();

        // While in QR screen: keep scanning periodically and update overlay on success.
        if (uiMode == UI_QR && lastQrPayload[0] != '\0') {
          // Keep showing latest payload until timeout.
          if (millis() < qrOverlayUntil) {
            drawQrOverlay(lastQrPayload);
          }
        }

        if (uiMode == UI_QR && millis() >= qrOverlayUntil && millis() - lastQrScanAttemptMs >= QR_SCAN_INTERVAL_MS) {
          lastQrScanAttemptMs = millis();
          if (qr_scanner_try_decode((uint16_t*)fb->buf, fb->width, fb->height, lastQrPayload, sizeof(lastQrPayload))) {
            qrOverlayUntil = millis() + QR_OVERLAY_MS;
            drawQrOverlay(lastQrPayload);
            Serial.print("QR (live): ");
            Serial.println(lastQrPayload);
          }
        }
      }
    }
  }

  // BACK button: works anytime in CAPTURE/QR.
  if (uiMode != UI_MAIN && backPressedThisTouch && touchEvt.touchJustReleased && !isRecording) {
    backPressedThisTouch = false;
    drawMainInterface();  // returns to UI_MAIN
  }

  if (fb) esp_camera_fb_return(fb);
  delay(10);
}