#pragma once
// Touch + hold logic extracted from `main.cpp` (TOUCH_PIN=44).
// Provides debounced touch down/up edges and a long-press activation edge.

#include <Arduino.h>

#ifndef TOUCH44_TRIGGER_PIN
#define TOUCH44_TRIGGER_PIN 44
#endif

#ifndef TOUCH44_LONG_PRESS_MS
#define TOUCH44_LONG_PRESS_MS 300
#endif

#ifndef TOUCH44_DEBOUNCE_COUNT
#define TOUCH44_DEBOUNCE_COUNT 2
#endif

struct Touch44TriggerEvent {
  // True exactly once when the debounced touch becomes active (finger down).
  bool touchJustActivated = false;
  // True exactly once when the debounced long-press becomes active.
  bool longPressJustActivated = false;
  // True exactly once when the debounced touch ends (finger lifted), after debounce.
  bool touchJustReleased = false;

  // Useful for UI/debug.
  bool debouncedTouchDown = false;
  bool longPressActive = false;
  uint32_t heldMs = 0;
};

// Keep state across loop iterations.
static bool touch44_lastTouchState = false;
static uint32_t touch44_touchStartTime = 0;
static bool touch44_inLongPress = false;
static uint8_t touch44_debounceCount = 0;

static inline void touch44_trigger_init() {
  pinMode(TOUCH44_TRIGGER_PIN, INPUT_PULLUP);
}

static inline Touch44TriggerEvent touch44_trigger_update() {
  Touch44TriggerEvent evt;

  const bool touched = (digitalRead(TOUCH44_TRIGGER_PIN) == LOW);
  const bool prevDebouncedTouchDown = touch44_lastTouchState;
  const bool prevLongPressActive = touch44_inLongPress;

  if (touched) {
    if (!touch44_lastTouchState) {
      touch44_debounceCount++;
      if (touch44_debounceCount >= TOUCH44_DEBOUNCE_COUNT) {
        touch44_lastTouchState = true;
        touch44_touchStartTime = millis();
        touch44_inLongPress = false;
        touch44_debounceCount = 0;
      }
    } else {
      touch44_debounceCount = 0;
      if (!touch44_inLongPress && (millis() - touch44_touchStartTime) >= TOUCH44_LONG_PRESS_MS) {
        touch44_inLongPress = true;
      }
    }
  } else {
    if (touch44_lastTouchState) {
      touch44_debounceCount++;
      if (touch44_debounceCount >= TOUCH44_DEBOUNCE_COUNT) {
        touch44_lastTouchState = false;
        touch44_inLongPress = false;
        touch44_debounceCount = 0;
      }
    } else {
      touch44_debounceCount = 0;
    }
  }

  evt.debouncedTouchDown = touch44_lastTouchState;
  evt.longPressActive = touch44_inLongPress;
  evt.heldMs = touch44_lastTouchState ? (millis() - touch44_touchStartTime) : 0;

  evt.touchJustActivated = (!prevDebouncedTouchDown && touch44_lastTouchState);
  evt.longPressJustActivated = (!prevLongPressActive && touch44_inLongPress);
  evt.touchJustReleased = (prevDebouncedTouchDown && !touch44_lastTouchState);
  return evt;
}

