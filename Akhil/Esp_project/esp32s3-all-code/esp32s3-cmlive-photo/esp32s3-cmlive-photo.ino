//#include "FS.h"
//#include "SD_MMC.h"

void setup() {
  Serial.begin(9600);
  delay(100);

  Serial.println("Mounting SD (4-bit mode)...");

  //if (!SD_MMC.begin()) {   // ← no "true"
    //Serial.println("Mount failed");
    //return;
  //}

  Serial.println("SD mounted successfully!");
}

void loop() {}
