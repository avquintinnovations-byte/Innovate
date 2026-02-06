// ESP32-C3 Potentiometer Test - Robust Version
// Change GPIO number to match your wiring
const int potPin = 2;  // ADC-capable GPIO (0-5 on most C3 boards)

int potValue = 0;
int lastStableValue = 0;
unsigned long lastPrint = 0;

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  // Configure ADC for stability
  analogReadResolution(12);      // 12-bit (0-4095)
  analogSetAttenuation(ADC_11db); // Full 0-3.3V range
  
  Serial.println("=== ESP32-C3 Potentiometer Test ===");
  Serial.println("Turn knob slowly - values should change smoothly");
  Serial.println("Raw: 0-4095  |  Voltage: 0.00-3.30V");
  Serial.println("=====================================");
}

void loop() {
  // Read multiple times and average for stability
  int sum = 0;
  for(int i = 0; i < 5; i++) {
    sum += analogRead(potPin);
    delay(5);
  }
  potValue = sum / 5;
  
  // Only print if value changed significantly (reduces noise)
  if(abs(potValue - lastStableValue) > 10 || millis() - lastPrint > 1000) {
    float voltage = (potValue / 4095.0) * 3.3;
    
    Serial.print("Raw: ");
    Serial.print(potValue);
    Serial.print("  |  Voltage: ");
    Serial.print(voltage, 2);
    Serial.print("V  |  %: ");
    Serial.println((potValue / 4095.0) * 100, 1);
    
    lastStableValue = potValue;
    lastPrint = millis();
  }
  
  delay(50);  // Small delay for stability
}
