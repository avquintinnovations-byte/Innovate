from machine import Pin, PWM
import time

s1 = PWM(Pin(26), freq=50)
s2 = PWM(Pin(27), freq=50)

def move(a):
    pulse = 500 + (2400 - 500) * a // 180
    duty = int(pulse * 65535 / 20000)
    s1.duty_u16(duty)
    s2.duty_u16(duty)

while True:
    for a in range(0, 181, 1):
        move(a)
        time.sleep(0.02)

    for a in range(180, -1, -2):
        move(a)
        time.sleep(0.02)
