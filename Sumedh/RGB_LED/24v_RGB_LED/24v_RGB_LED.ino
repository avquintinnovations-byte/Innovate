const int redPin = 18;
const int greenPin = 19;
const int bluePin = 21;

const int freq = 5000;
const int resolution = 8;

// In older versions, we must manually assign channels (0-15)
const int redChannel = 0;
const int greenChannel = 1;
const int blueChannel = 2;

void setup() {
  Serial.begin(115200);

  // Configure PWM functionalites
  ledcSetup(redChannel, freq, resolution);
  ledcSetup(greenChannel, freq, resolution);
  ledcSetup(blueChannel, freq, resolution);

  // Attach the channel to the GPIO to be controlled
  ledcAttachPin(redPin, redChannel);
  ledcAttachPin(greenPin, greenChannel);
  ledcAttachPin(bluePin, blueChannel);

  Serial.println("System Ready. Enter RGB (e.g., 255,0,0):");
}

void loop() {
  if (Serial.available() > 0) {
    // Parse the input (looks for integers and skips commas/spaces)
    int r = Serial.parseInt();
    int g = Serial.parseInt();
    int b = Serial.parseInt();

    // Check for the newline character to confirm end of input
    if (Serial.read() == '\n' || Serial.read() == '\r') {
      setColor(r, g, b);

      Serial.print("Set -> R:");
      Serial.print(r);
      Serial.print(" G:");
      Serial.print(g);
      Serial.print(" B:");
      Serial.println(b);
    }
  }
}

void setColor(int r, int g, int b) {
  ledcWrite(redChannel, r);
  ledcWrite(greenChannel, g);
  ledcWrite(blueChannel, b);
}