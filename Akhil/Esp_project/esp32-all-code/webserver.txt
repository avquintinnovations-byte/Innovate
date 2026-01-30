#include <WiFi.h>
#include <HTTPClient.h>

#define BUTTON 4

const char* ssid = "All About Empire";
const char* password = "Plutonium3";
const char* server = "http://192.168.1.61:8080";

bool lastButtonState = HIGH;
void setup() {
  Serial.begin(115200);
  pinMode(BUTTON, INPUT_PULLUP);

  WiFi.begin(ssid, password);
  Serial.println("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.println("..");
  }
  Serial.println("Wifi connected");
}

void loop() {
  bool currentState = digitalRead(BUTTON);
  
  if (lastButtonState == HIGH && currentState == LOW) {
    HTTPClient http;
    http.begin(server);
    http.GET();
    http.end();

    Serial.println("Button pressed");
    delay(1000);
  }
    lastButtonState = currentState;
    delay(50);
}
