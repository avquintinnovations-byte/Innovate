#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_AHRS.h>

Adafruit_MPU6050 mpu;
Adafruit_Madgwick filter;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);   // ESP32 I2C pins

  if (!mpu.begin()) {
    Serial.println("MPU6050 not found");
    while (1);
  }

  // Configure MPU6050 ranges
  mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  mpu.setGyroRange(MPU6050_RANGE_250_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  // Start sensor fusion at 50 Hz
  filter.begin(50);

  // Wait for connection
  delay(2000);
  
  Serial.println("IMU Mouse Controller Ready");
  Serial.println("Roll,Pitch");
}

void loop() {
  sensors_event_t acc, gyro, temp;
  mpu.getEvent(&acc, &gyro, &temp);

  // Convert gyro from rad/s to deg/s
  float gx = gyro.gyro.x * 180.0 / PI;
  float gy = gyro.gyro.y * 180.0 / PI;
  float gz = gyro.gyro.z * 180.0 / PI;

  // Update sensor fusion
  filter.updateIMU(gx, gy, gz,
                   acc.acceleration.x,
                   acc.acceleration.y,
                   acc.acceleration.z);

  // Get orientation angles
  float roll  = filter.getRoll();
  float pitch = filter.getPitch();
  float yaw   = filter.getYaw();

  // Send yaw and pitch to Python (comma-separated)
  Serial.print(yaw);
  Serial.print(",");
  Serial.println(pitch);
  
  delay(20);  // 50Hz update rate (matches filter rate)
}