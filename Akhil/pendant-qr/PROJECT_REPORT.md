# Project Report — Memorable Pendant + GemmaApp

## Overview
This project contains:
- **Pendant device firmware** (ESP32-S3 + Seeed Round Display + Camera + SD + Mic + RTC): captures **images**, records **audio**, scans **QR codes**, and exposes SD-card files over **Wi‑Fi HTTP**. It also broadcasts a “latest index” over **BLE** so the phone app can show whether there are new captures to sync.
- **Android app** (**Memorable** / `GemmaApp`): stores “memories” (image + optional audio + text context) in a local database, supports **sync-from-pendant over Wi‑Fi**, supports **BLE new-memory indicator**, supports **voice transcription**, and provides **LLM + embedding based recall** over stored memories.

---

## Device (Pendant) — Features (implemented in firmware)

### Hardware and peripherals used
- **MCU**: Seeed Studio **XIAO ESP32‑S3 Sense** (Arduino framework via PlatformIO).
- **Display**: Seeed Studio **Round Display** (GC9A01 240×240 TFT) using `TFT_eSPI`.
- **Touch**: Capacitive touch controller **CHSC6x** over **I2C** (custom I2C read logic for coordinates).
- **Camera**: ESP32 camera (`esp_camera`) configured for **240×240 RGB565** preview and conversion to **JPEG** for saving.
- **Microphone / Audio**: I2S audio capture (`driver/i2s.h`) saved as **WAV**.
- **Storage**: **SD card** (`FS`, `SD`) for saving image/audio/text files.
- **RTC**: **BM8563** (`I2C_BM8563`) for date/time filenames (with validity checking).

### On-device UI / user interaction
- **Main screen with two on‑screen buttons**:
  - **CAPTURE** button: opens the live camera capture interface.
  - **QR** button: opens the live camera QR scanning interface.
- **Pressed-state visual feedback**:
  - Buttons show a “pressed/highlight” state when touched for confirmation.
- **Back navigation always available**:
  - A **BACK** button is drawn and remains available on both CAPTURE and QR screens (before/after press/release).
- **State machine navigation**:
  - UI is implemented as a mode/state machine (`UI_MAIN`, `UI_CAPTURE`, `UI_QR`) with rectangle hit‑testing using CHSC6x touch coordinates.

### Capture mode (CAPTURE)
- **Live camera preview** displayed on the round screen.
- **Long-press capture workflow**:
  - **Press and hold** begins **audio recording**.
  - Recording continues **until touch is released**.
  - On release, the capture flow completes and files are saved to SD.
- **On-screen status updates**:
  - Shows recording / saved indications and file counters (main screen shows file count).

### QR mode (QR)
- **Live camera preview** displayed on the round screen.
- **Continuous QR scanning** while in QR mode (throttled interval-based scanning).
- **QR payload overlay**:
  - Decoded QR payload is shown **in red** with a **larger font** for readability.
  - Overlay is time-limited (auto-hides after a set duration).
- **Long-press record workflow in QR mode**:
  - Same “hold to record audio / release to finish” behavior as capture.
  - Additionally attempts to persist the **QR payload** captured during the session.

### QR decoding engine (device)
- Uses **ESP32QRCodeReader** (and `quirc`) integrated via a helper module:
  - Converts RGB565 frame → grayscale buffer (PSRAM).
  - Runs `quirc` decode; tries all detected regions to increase decode success.
- Includes increased loop task stack size to support `quirc` decode workload.

### File creation and naming on SD card
- Saves to SD card:
  - **JPEG image** file for captures.
  - **WAV audio** file for recordings.
  - **QR text file** containing the decoded payload when available.
- **Datetime-based filenames** when RTC is valid.
- **Fallback index-based filenames** when RTC is invalid (prevents broken timestamps).
- **QR text file naming**:
  - QR payload is saved as **`QR_<baseName>.txt`** (aligned with the capture baseName).

### Wi‑Fi + HTTP file server (device)
- Device runs as a **Wi‑Fi Access Point**:
  - SSID: **`ESP32_CAM`**
  - Password: **`12345678`**
- Exposes SD-card files via HTTP endpoints used by the app:
  - **`/list`**: returns a list of files on the SD card.
  - **`/download?file=...`**: downloads a requested file.
  - **`/sync-complete`**: app notifies device that sync is done.

### BLE (device → app indicator)
- BLE device name: **`Memorable`**
- BLE service UUID: **`6e400001-b5a3-f393-e0a9-e50e24dcca9e`**
- BLE characteristic UUID (index): **`6e400003-b5a3-f393-e0a9-e50e24dcca9e`**
- The pendant advertises an **index** representing the latest saved capture count/index.
- BLE behavior during Wi‑Fi sync:
  - Advertising can be **stopped during HTTP transfer** and **resumed** when the app calls **`/sync-complete`**.

---

## Android App (`GemmaApp`) — Features (implemented)

### App identity
- App label (launcher): **“Memorable”**.
- Application class: `GemmaApp`.

### Local database + storage
- Uses **ObjectBox** as the local database (`BoxStore`) to store `Knowledge` records.
- Stores media files in app private storage:
  - `knowledge_images/` for synced or user-added images.
  - `knowledge_audio/` for synced audio.
- Includes automatic recovery path if ObjectBox store init fails (delete store files and recreate).

### Memories (Knowledge) management UI
Main screen (`MainActivity`) includes:
- **Memories grid** (3-column grid of images).
- **Memory count** display.
- **“+” Add Memory** flow (opens `AddKnowledgeActivity`).
- **Clear**: deletes all records and deletes associated files from storage.
- **Memory detail overlay** on tap:
  - Shows image (or audio placeholder when image missing).
  - Shows metadata datetime (when available).
  - Shows similarity score when a record is highlighted by search.
  - Supports audio playback and transcription display.

### Add Memory (manual entry)
`AddKnowledgeActivity` supports:
- Add a memory with required **text context**.
- Attach an image via:
  - **Camera capture**, or
  - **Gallery pick**.
- Generates and stores a **text embedding vector** for the context using `TextEmbedder`.

### Sync from pendant over Wi‑Fi (app → device)
Sync button (“Sync”) triggers `Esp32SyncHelper.sync()`:
- Assumes the phone is connected to the pendant AP and uses base URL:
  - **`http://192.168.4.1`**
- Fetches pendant SD file list from **`/list`**.
- Downloads files via **`/download?file=...`**.
- Imports content into ObjectBox:
  - **Images** are saved locally and inserted as `Knowledge` records.
  - If `index.txt` is present, it maps filename → text context; that context is embedded and stored.
  - **Audio** files are downloaded, associated with the matching image record by shared index, and can be auto-transcribed (WAV supported).
  - Metadata is stored as JSON including `"source":"esp32"`, `"filename"`, `"audioFilename"` (when present), and `"datetime"` when it can be parsed from filenames.
- Notifies the pendant that sync is done via **`/sync-complete`** (with retries).
- Pauses BLE during sync and resumes BLE after sync (to reduce radio contention / simplify user experience).

### BLE “new memories” indicator (app)
- Connects to BLE device named **`Memorable`** and subscribes to the index characteristic.
- Persists the last received pendant index in shared preferences (`gemma_prefs`).
- Shows indicator text on main screen:
  - **“X new memories”** when pendant index > synced count from database,
  - otherwise **“Up to date”**.

### AI / Recall features (RAG-style memory retrieval)
Main screen provides a “Recall a memory” prompt and “Send”:
- **LLM** via MediaPipe `LlmInference`:
  - Loads a Gemma model from device path: `/data/local/tmp/llm/gemma3-1b-it-int4.task`.
  - Used for answering questions using retrieved memory context.
- **Text embeddings** via MediaPipe `TextEmbedder`:
  - Uses `universal_sentence_encoder.tflite` asset.
  - L2-normalized vectors; cosine similarity used for retrieval.
- **Time filtering**:
  - Attempts to classify natural language time filters (today/yesterday/last week/etc.) using the LLM.
  - Has a fallback parser if the LLM step fails.
- **Retrieval behavior**:
  - Computes similarity and selects the most relevant memory (subject to a relevance threshold).
  - Highlights the most relevant memory card in the grid and scrolls to it.
  - Builds a prompt that instructs the LLM to answer **only using provided memories** (no invention).

### Audio transcription + playback (app)
- Transcribes audio using `AudioTranscriber` (includes an embedded Vosk model directory in assets).
- Plays audio with `MediaPlayer`.
- Supports **word-timing synchronized transcript display** during playback (when timings are available).

---

## Device ↔ App integration (end-to-end behavior)

### “Capture on pendant → recall in app” pipeline
- Pendant creates media on SD:
  - Image (`.jpg`) + audio (`.wav`) + optional QR payload text (`QR_*.txt`).
- Phone connects to pendant Wi‑Fi AP (**`ESP32_CAM`**) and taps **Sync**.
- App downloads new files via HTTP and stores them locally.
- App indexes memory text (from `index.txt` mapping and/or audio transcription) using embeddings.
- User can query memories using natural language; app retrieves relevant memory and uses the on-device LLM to respond.

### “New memories” notification to the app
- Pendant advertises BLE index updates.
- App subscribes and displays **“new memories”** count, helping the user know when to sync.

---

## Project structure (top-level)
- `Pendant -wifi/…`: ESP32 firmware (PlatformIO project).
- `GemmaApp/`: Android application (“Memorable”).
- `QR_reader_touch/`: Source reference used to integrate QR scanning functionality.

