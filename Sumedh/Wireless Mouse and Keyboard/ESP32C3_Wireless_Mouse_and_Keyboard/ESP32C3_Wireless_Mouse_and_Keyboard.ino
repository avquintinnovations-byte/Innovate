#define USE_NIMBLE // Use this if you have NimBLE-Arduino installed
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_AHRS.h>
#include <BleMouse.h>

// --- CONFIGURATION ---
#define SCREEN_WIDTH 1920  
#define SCREEN_HEIGHT 1080  
#define ANGLE_RANGE 40.0    
#define SMOOTHING 0.5       

#define I2C_SDA 6
#define I2C_SCL 7
#define BUTTON_PIN 2        // Left click button on GPIO 2

Adafruit_MPU6050 mpu;
Adafruit_Madgwick filter;
BleMouse bleMouse("C3-Air-Mouse", "Espressif", 100);

float ref_yaw = 0, ref_pitch = 0;
float smooth_yaw = 0, smooth_pitch = 0;
float smooth_x = SCREEN_WIDTH / 2;
float smooth_y = SCREEN_HEIGHT / 2;
int virtual_x = SCREEN_WIDTH / 2;
int virtual_y = SCREEN_HEIGHT / 2;

bool mpu_ready = false;
bool calibrated = false;
bool last_button_state = HIGH;  // Track previous button state

void setup() {
  Serial.begin(115200);
  delay(1000); // Give serial time
  
  Serial.println("--- Booting ESP32-C3 ---");

  // Initialize button pin
  pinMode(BUTTON_PIN, INPUT_PULLUP);  // Internal pullup, LOW when pressed
  
  // 1. START BLUETOOTH FIRST
  bleMouse.begin();
  Serial.println("Bluetooth Advertising Started...");

  // 2. START I2C & MPU
  Wire.begin(I2C_SDA, I2C_SCL);
  if (mpu.begin()) {
    mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
    mpu.setGyroRange(MPU6050_RANGE_250_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    filter.begin(50);
    mpu_ready = true;
    Serial.println("MPU6050 Initialized Successfully.");
  } else {
    Serial.println("CRITICAL: MPU6050 not found! Check GPIO 6/7.");
  }
}

int mapAngleToPos(float angle, int screen_dimension) {
  angle = constrain(angle, -ANGLE_RANGE, ANGLE_RANGE);
  float normalized = (angle + ANGLE_RANGE) / (2.0 * ANGLE_RANGE);
  return (int)(normalized * screen_dimension);
}

void loop() {
  // Check connection status for debugging
  static bool last_conn = false;
  bool curr_conn = bleMouse.isConnected();
  if (curr_conn != last_conn) {
    Serial.println(curr_conn ? ">> Bluetooth Connected!" : ">> Bluetooth Disconnected!");
    last_conn = curr_conn;
    if (!curr_conn) calibrated = false; // Reset calibration on disconnect
  }

  if (!curr_conn || !mpu_ready) return;

  // Handle button (left click)
  bool button_state = digitalRead(BUTTON_PIN);
  if (button_state == LOW && last_button_state == HIGH) {
    // Button pressed (rising edge from HIGH to LOW due to pullup)
    bleMouse.click(MOUSE_LEFT);
    Serial.println("Left click!");
  }
  last_button_state = button_state;

  sensors_event_t acc, gyro, temp;
  mpu.getEvent(&acc, &gyro, &temp);

  // Convert rad/s to deg/s for the filter
  filter.updateIMU(gyro.gyro.x * 57.2958, gyro.gyro.y * 57.2958, gyro.gyro.z * 57.2958, 
                     acc.acceleration.x, acc.acceleration.y, acc.acceleration.z);

  // Calibration Logic (Wait for 50 steady samples)
  if (!calibrated) {
    static int samples = 0;
    static float sum_y = 0, sum_p = 0;
    if (samples < 50) {
      sum_y += filter.getYaw();
      sum_p += filter.getPitch();
      samples++;
      if (samples % 10 == 0) Serial.print(".");
    } else {
      ref_yaw = sum_y / 50.0;
      ref_pitch = sum_p / 50.0;
      calibrated = true;
      Serial.println("\nCalibration Done!");
    }
    delay(20);
    return;
  }

  // --- MAPPING LOGIC ---
  float rel_yaw = filter.getYaw() - ref_yaw;
  if (rel_yaw > 180) rel_yaw -= 360;
  else if (rel_yaw < -180) rel_yaw += 360;
  
  float rel_pitch = filter.getPitch() - ref_pitch;

  smooth_yaw = (smooth_yaw * SMOOTHING) + (rel_yaw * (1.0 - SMOOTHING));
  smooth_pitch = (smooth_pitch * SMOOTHING) + (rel_pitch * (1.0 - SMOOTHING));

  int target_x = mapAngleToPos(-smooth_yaw, SCREEN_WIDTH);
  int target_y = mapAngleToPos(smooth_pitch, SCREEN_HEIGHT);

  smooth_x = (smooth_x * 0.3) + (target_x * 0.7);
  smooth_y = (smooth_y * 0.3) + (target_y * 0.7);

  int move_x = (int)smooth_x - virtual_x;
  int move_y = (int)smooth_y - virtual_y;

  if (move_x != 0 || move_y != 0) {
    bleMouse.move(move_x, move_y);
    virtual_x += move_x;
    virtual_y += move_y;
  }

  delay(20); 
}
