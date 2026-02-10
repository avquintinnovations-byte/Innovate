#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

Adafruit_MPU6050 mpu;

float gyroZ_offset = 0;
float yaw = 0;
unsigned long last_time = 0;

#define LED_PIN 2           // The blue LED pin on most ESP32s
#define HARD_DEADZONE 0.50  
float filter_strength = 0.2; 
float smoothed_gz = 0;

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT); // Set the blue LED as an output

  if (!mpu.begin()) {
    Serial.println("Failed to find MPU6050 chip");
    while (1) { delay(10); }
  }

  mpu.setFilterBandwidth(MPU6050_BAND_5_HZ);
  mpu.setGyroRange(MPU6050_RANGE_250_DEG);

  // --- CALIBRATION WITH BLINKING LED ---
  //Serial.println("STEP 1: Calibrating. DO NOT MOVE SENSOR...");
  float z_sum = 0;
  
  for (int i = 0; i < 3000; i++) {
    sensors_event_t a, g, t;
    mpu.getEvent(&a, &g, &t);
    z_sum += g.gyro.z;

    // Blink logic: Toggle LED every 100 samples (approx every 100ms)
    if (i % 100 == 0) {
      digitalWrite(LED_PIN, !digitalRead(LED_PIN)); 
    }

    delay(1);
    //if(i % 500 == 0) Serial.print("."); 
  }
  
  gyroZ_offset = z_sum / 3000;
  digitalWrite(LED_PIN, LOW); // Turn LED off when calibration is finished
  //Serial.println("\nCalibration Done.");
  
  last_time = micros();
}

void loop() {
  sensors_event_t acc, gyro, temp;
  mpu.getEvent(&acc, &gyro, &temp);

  unsigned long current_time = micros();
  float dt = (current_time - last_time) / 1000000.0;
  last_time = current_time;

  float raw_gz_deg = (gyro.gyro.z - gyroZ_offset) * (180.0 / PI);
  smoothed_gz = (smoothed_gz * (1.0 - filter_strength)) + (raw_gz_deg * filter_strength);

  float final_gz = smoothed_gz;
  if (abs(final_gz) < HARD_DEADZONE) {
    final_gz = 0; 
  }

  yaw += final_gz * dt;

  static float last_printed_yaw = 0;
  if (abs(yaw - last_printed_yaw) > 0.01) {
    Serial.println(yaw, 2); 
    last_printed_yaw = yaw;
  }

  delay(10);
}