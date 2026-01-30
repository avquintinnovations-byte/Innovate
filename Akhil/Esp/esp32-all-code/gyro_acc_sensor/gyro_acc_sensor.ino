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

  // Start sensor fusion at 50 Hz
  filter.begin(50);

  // Print header for Serial Plotter labels
  Serial.println("LinX LinY LinZ GyroX GyroY GyroZ q0 q1 q2 q3");


  delay(1000);
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

  // Orientation angles
  float roll  = filter.getRoll();
  float pitch = filter.getPitch();
  float yaw   = filter.getYaw();


   // Get quaternion
  float q0, q1, q2, q3;
  filter.getQuaternion(&q0, &q1, &q2, &q3);

  // Gravity from quaternion
  float gravX = 2 * (q1*q3 - q0*q2);
  float gravY = 2 * (q0*q1 + q2*q3);
  float gravZ = q0*q0 - q1*q1 - q2*q2 + q3*q3;

  // Linear acceleration (gravity removed)
  float linX = acc.acceleration.x - gravX * 9.81;
  float linY = acc.acceleration.y - gravY * 9.81;
  float linZ = acc.acceleration.z - gravZ * 9.81;





  // ---- Send data to Serial Plotter (only numbers) ----
unsigned long t = millis();

Serial.print(t); Serial.print(" ");

 // ACC (unchanged)
Serial.print(linX); Serial.print(" ");
Serial.print(linY); Serial.print(" ");
Serial.print(linZ); Serial.print(" ");

// GYRO (unchanged)
Serial.print(gx); Serial.print(" ");
Serial.print(gy); Serial.print(" ");
Serial.print(gz); Serial.print(" ");

// QUATERNION (for visualization)
Serial.print(q0); Serial.print(" ");
Serial.print(q1); Serial.print(" ");
Serial.print(q2); Serial.print(" ");
Serial.println(q3);

delay(10); 

}
