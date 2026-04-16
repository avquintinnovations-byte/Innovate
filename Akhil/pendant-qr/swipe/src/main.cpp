#include <Arduino.h>
#include <Wire.h>

#define USE_TFT_ESPI_LIBRARY
#include "lv_xiao_round_screen.h"

// ================= I2C =================
static constexpr int I2C_SDA = 5;
static constexpr int I2C_SCL = 6;

// ================= GESTURE SETTINGS =================
#define TAP_MAX_MS        200
#define LONG_PRESS_MS     800
#define MOVE_TOLERANCE    10

#define SWIPE_MIN_PIXELS  40
#define SWIPE_MAX_OFFAXIS 50
#define SWIPE_MAX_MS      700

#define RESULT_SHOW_MS       800   // tap / generic result
#define SWIPE_RESULT_SHOW_MS 900   // swipe result feedback (non-overlay)
#define RELEASE_DEBOUNCE_MS  60
#define HOLD_STATUS_POLL_MS 25

// Overlay animation
#define OVERLAY_ANIM_MS 180
#define OVERLAY_TEXT_EDGE_PAD 10

// ================= TOUCH STATE =================
struct TouchState {
  bool active = false;
  bool longPressTriggered = false;
  bool swipeTriggered = false;
  bool ignoreUntilRelease = false;
  bool overlayActive = false;
  bool overlayCommitted = false;

  int16_t startX = 0, startY = 0;
  int16_t lastX = 0, lastY = 0;

  uint32_t startTime = 0;
  uint32_t lastPressedTime = 0;
};

static TouchState touch;
static uint32_t resultUntilMs = 0;
static uint32_t lastHoldPollMs = 0;

// ================= DISPLAY =================
static TFT_eSprite gFrame = TFT_eSprite(&tft);

static inline int screenW() { return 240; }
static inline int screenH() { return 240; }

// Forward declarations (avoid ordering issues)
static void drawModeBase();
static void drawOverlay();

static void beginFrame() {
  gFrame.fillSprite(TFT_BLACK);
  gFrame.setTextFont(1);
}

static void endFrame() {
  gFrame.pushSprite(0, 0);
}

static void renderFrame(bool withOverlay) {
  beginFrame();
  drawModeBase();
  if (withOverlay) drawOverlay();
  endFrame();
}

static void drawCentered(const char* l1, const char* l2) {
  const int cx = screenW() / 2;
  const int cy = screenH() / 2;

  beginFrame();
  gFrame.setTextDatum(MC_DATUM);
  gFrame.setTextColor(TFT_GREEN, TFT_BLACK);
  gFrame.setTextSize(1);

  gFrame.drawString(l1, cx, cy - 20);
  gFrame.drawString(l2, cx, cy + 20);
  endFrame();
}

static void showHome() {
  drawCentered("Gesture Test", "Tap / Hold / Swipe");
}

static void showTap() {
  Serial.println("TOUCH DETECTED");
  drawCentered("Detected", "TOUCH");
  resultUntilMs = millis() + RESULT_SHOW_MS;
}

// ================= MODES =================
static constexpr const char* kModes[] = {"Capture", "QR"};
static constexpr int kModeCount = (int)(sizeof(kModes) / sizeof(kModes[0]));
static int gModeIndex = 0;

static void drawModeBase() {
  const int cx = screenW() / 2;
  const int cy = screenH() / 2;

  gFrame.setTextDatum(MC_DATUM);
  gFrame.setTextColor(TFT_WHITE, TFT_BLACK);
  gFrame.setTextSize(2);
  gFrame.drawString(kModes[gModeIndex], cx, cy - 20);

  gFrame.setTextColor(TFT_GREEN, TFT_BLACK);
  gFrame.setTextSize(1);
  gFrame.drawString("Swipe: change mode", cx, cy + 25);
}

static void renderModeScreen() {
  renderFrame(false);
}

// ================= OVERLAY =================
enum class OverlaySide : uint8_t { FromLeft, FromRight };
static OverlaySide gOverlaySide = OverlaySide::FromLeft;
static int gOverlayW = 0;        // current overlay width [0..screenW]
static int gOverlayWTarget = 0;  // animation target width
static uint32_t gOverlayAnimStartMs = 0;
static int gOverlayWStart = 0;
static int gOverlayTargetMode = 0;

static uint16_t overlayBgColor() {
  // Different color per target mode for clarity
  return (gOverlayTargetMode % 2 == 0) ? TFT_DARKGREY : TFT_NAVY;
}

static void drawOverlayEdgeLabel(const char* text) {
  const int w = screenW();
  const int h = screenH();
  const int cx = w / 2;
  const int cy = h / 2;

  gFrame.setTextDatum(MC_DATUM);
  gFrame.setTextColor(TFT_YELLOW, overlayBgColor());
  gFrame.setTextSize(2);

  if (gOverlayW >= (w - 2)) {
    // Full cover: center text
    gFrame.drawString(text, cx, cy);
    return;
  }

  // Partial overlay: label near the overlay edge
  if (gOverlaySide == OverlaySide::FromLeft) {
    const int edgeX = gOverlayW - OVERLAY_TEXT_EDGE_PAD;
    gFrame.setTextDatum(MR_DATUM);
    gFrame.drawString(text, edgeX, cy);
  } else {
    const int edgeX = (w - gOverlayW) + OVERLAY_TEXT_EDGE_PAD;
    gFrame.setTextDatum(ML_DATUM);
    gFrame.drawString(text, edgeX, cy);
  }
}

static void drawOverlay() {
  const int w = screenW();
  const int h = screenH();

  if (gOverlayW <= 0) return;

  gFrame.setTextDatum(TL_DATUM);
  if (gOverlaySide == OverlaySide::FromLeft) {
    gFrame.fillRect(0, 0, gOverlayW, h, overlayBgColor());
  } else {
    gFrame.fillRect(w - gOverlayW, 0, gOverlayW, h, overlayBgColor());
  }

  drawOverlayEdgeLabel(kModes[gOverlayTargetMode]);
}

static void setOverlayWidthImmediate(int w) {
  const int sw = tft.width();
  if (w < 0) w = 0;
  if (w > sw) w = sw;
  gOverlayW = w;
}

static void startOverlayAnimTo(int targetW) {
  const int sw = tft.width();
  if (targetW < 0) targetW = 0;
  if (targetW > sw) targetW = sw;
  gOverlayWStart = gOverlayW;
  gOverlayWTarget = targetW;
  gOverlayAnimStartMs = millis();
}

static void tickOverlayAnim() {
  if (gOverlayAnimStartMs == 0) return;

  const uint32_t now = millis();
  const uint32_t dt = now - gOverlayAnimStartMs;
  if (dt >= OVERLAY_ANIM_MS) {
    gOverlayAnimStartMs = 0;
    gOverlayW = gOverlayWTarget;
    return;
  }

  const float t = (float)dt / (float)OVERLAY_ANIM_MS;
  gOverlayW = (int)(gOverlayWStart + (gOverlayWTarget - gOverlayWStart) * t);
}

static void beginOverlay(OverlaySide side, int targetMode) {
  gOverlaySide = side;
  gOverlayTargetMode = targetMode;
  touch.overlayActive = true;
  touch.overlayCommitted = false;
  gOverlayAnimStartMs = 0;
  setOverlayWidthImmediate(0);
}

static void cancelOverlayAnim() {
  startOverlayAnimTo(0);
  touch.overlayCommitted = false;
}

static void commitOverlayAnim() {
  startOverlayAnimTo(screenW());
  touch.overlayCommitted = true;
}

// ================= TOUCH =================
static bool readTouch(int16_t& x, int16_t& y) {
  // Gate I2C reads with the interrupt pin to avoid hammering I2C when no touch.
  // TOUCH_INT is active-low when a touch event is present.
  if (digitalRead(TOUCH_INT) != LOW) return false;

  uint8_t temp[CHSC6X_READ_POINT_LEN] = {0};
  const uint8_t read_len = Wire.requestFrom(CHSC6X_I2C_ID, CHSC6X_READ_POINT_LEN);
  if (read_len != CHSC6X_READ_POINT_LEN) return false;

  Wire.readBytes(temp, read_len);
  if (temp[0] != 0x01) return false; // 0x01 means one touch point present

  // Convert coordinates based on screen rotation (matches Seeed helper logic).
  chsc6x_convert_xy(&temp[2], &temp[4]);
  x = (int16_t)temp[2];
  y = (int16_t)temp[4];
  return true;
}

static bool isTouchStillDown() {
  // Fast path: INT pin low => definitely a touch pending
  if (digitalRead(TOUCH_INT) == LOW) return true;

  // INT can go high even if finger remains down, so occasionally poll status via I2C.
  const uint32_t now = millis();
  if ((now - lastHoldPollMs) < HOLD_STATUS_POLL_MS) return true; // assume still down
  lastHoldPollMs = now;

  uint8_t temp[CHSC6X_READ_POINT_LEN] = {0};
  const uint8_t read_len = Wire.requestFrom(CHSC6X_I2C_ID, CHSC6X_READ_POINT_LEN);
  if (read_len != CHSC6X_READ_POINT_LEN) return true; // on error, assume still down
  Wire.readBytes(temp, read_len);
  return temp[0] == 0x01;
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(200);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  pinMode(TOUCH_INT, INPUT_PULLUP);

  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);

  gFrame.setColorDepth(16);
  gFrame.createSprite(screenW(), screenH());

  renderModeScreen();
}

// ================= LOOP =================
void loop() {
  // Tick overlay animation and redraw scene when active/animating.
  tickOverlayAnim();

  int16_t x = 0, y = 0;
  bool pressed = readTouch(x, y);
  const uint32_t now = millis();

  // If we triggered a gesture, wait until finger is released before starting a new one.
  if (touch.ignoreUntilRelease) {
    // Use robust release detection (INT can be unreliable while held)
    if (!isTouchStillDown()) {
      touch.ignoreUntilRelease = false;
      renderModeScreen();
    }
    // Still render overlay if it is animating out/in (e.g. after commit/cancel)
    if (touch.overlayActive || gOverlayAnimStartMs != 0) {
      renderFrame(true);
    }
    delay(5);
    return;
  }

  // ===== TOUCH START =====
  if (pressed && !touch.active) {
    touch.active = true;
    touch.longPressTriggered = false;
    touch.swipeTriggered = false;
    touch.ignoreUntilRelease = false;
    touch.overlayActive = false;
    touch.overlayCommitted = false;

    touch.startX = x;
    touch.startY = y;
    touch.lastX = x;
    touch.lastY = y;
    touch.startTime = now;
    touch.lastPressedTime = now;
  }

  // ===== TOUCH MOVE =====
  if (pressed && touch.active) {
    touch.lastX = x;
    touch.lastY = y;
    touch.lastPressedTime = now;

    uint32_t dt = now - touch.startTime;
    int dx = x - touch.startX;
    int dy = y - touch.startY;

    // -------- SWIPE OVERLAY (interactive, fast) --------
    // Start overlay as soon as movement exceeds tolerance.
    if (!touch.overlayActive && !touch.longPressTriggered) {
      if (abs(dx) > MOVE_TOLERANCE || abs(dy) > MOVE_TOLERANCE) {
        if (dx > 0) {
          // Swipe RIGHT -> bring overlay from LEFT, target previous mode
          const int target = (gModeIndex - 1 + kModeCount) % kModeCount;
          beginOverlay(OverlaySide::FromLeft, target);
        } else if (dx < 0) {
          // Swipe LEFT -> bring overlay from RIGHT, target next mode
          const int target = (gModeIndex + 1) % kModeCount;
          beginOverlay(OverlaySide::FromRight, target);
        }
      }
    }

    if (touch.overlayActive && !touch.overlayCommitted) {
      // 2x displacement, use horizontal for overlay width; off-axis still allowed but limited
      const int sw = tft.width();
      int wDisp = abs(dx) * 2;
      if (wDisp > sw) wDisp = sw;
      setOverlayWidthImmediate(wDisp);

      // Redraw base + overlay (single push)
      renderFrame(true);
    }

    // -------- LONG PRESS --------
    if (!touch.longPressTriggered &&
        !touch.overlayActive &&
        dt > LONG_PRESS_MS &&
        abs(dx) < MOVE_TOLERANCE &&
        abs(dy) < MOVE_TOLERANCE) {

      touch.longPressTriggered = true;

      Serial.println("PRESS & HOLD");
      drawCentered("Detected", "PRESS & HOLD");
      // Stay on this screen until the user releases.
      resultUntilMs = 0;
      touch.active = false;
      touch.ignoreUntilRelease = true;
    }
  }

  // ===== TOUCH RELEASE =====
  if (!pressed && touch.active && (now - touch.lastPressedTime) >= RELEASE_DEBOUNCE_MS) {
    uint32_t dt = now - touch.startTime;
    int dx = touch.lastX - touch.startX;
    int dy = touch.lastY - touch.startY;

    touch.active = false;

    // -------- OVERLAY RELEASE DECISION --------
    if (touch.overlayActive && !touch.overlayCommitted) {
      const int sw = tft.width();
      const bool passedHalf = gOverlayW >= (sw / 2);
      if (passedHalf) {
        commitOverlayAnim();
      } else {
        cancelOverlayAnim();
      }
      // While animating, don't start a new gesture.
      touch.ignoreUntilRelease = true;
    }

    // -------- TAP --------
    else if (dt < TAP_MAX_MS &&
             abs(dx) < MOVE_TOLERANCE &&
             abs(dy) < MOVE_TOLERANCE &&
             !touch.longPressTriggered) {
      showTap();
      // Return to mode screen after feedback timer
      resultUntilMs = now + RESULT_SHOW_MS;
    }

    // -------- RELEASE AFTER HOLD --------
    else if (touch.longPressTriggered) {
      // When releasing after hold/swipe → just go back (or wait for result timer)
    }
  }

  // Overlay animation follow-up: when anim finishes
  if (touch.overlayActive && gOverlayAnimStartMs == 0) {
    // If committed and fully open, switch mode, then animate away to reveal new mode.
    if (touch.overlayCommitted && gOverlayW >= (tft.width() - 2)) {
      gModeIndex = gOverlayTargetMode;
      renderFrame(true);
      // Keep overlay full for one frame, then close it quickly
      startOverlayAnimTo(0);
      touch.overlayCommitted = false;
    } else if (gOverlayW == 0) {
      touch.overlayActive = false;
      renderModeScreen();
    }
  }

  // If we showed tap feedback, return to mode screen when timer ends
  if (resultUntilMs != 0 && (int32_t)(millis() - resultUntilMs) >= 0) {
    resultUntilMs = 0;
    renderModeScreen();
  }

  delay(5);
}

