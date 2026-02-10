from machine import Pin
import time

led = Pin(2, Pin.OUT)   # change to 23 if needed

print("ESP32 MicroPython LED control ready")
print("Commands:")
print("  1 -> LED ON")
print("  0 -> LED OFF")
print("  b   -> blink once")
print("  s   -> status")

led_state = False

while True:
    cmd = input().strip().lower()

    if cmd == "1":
        led.on()
        led_state = True
        print("LED ON")

    elif cmd == "0":
        led.off()
        led_state = False
        print("LED OFF")

    elif cmd == "b":
        print("Blink")
        led.on()
        time.sleep(0.2)
        led.off()

    elif cmd == "s":
        print("LED is", "ON" if led_state else "OFF")

    else:
        print("Unknown command")
