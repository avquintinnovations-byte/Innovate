# QR Code Reader - XIAO ESP32S3 Sense + Round Display

PlatformIO project for reading QR codes using the [ESP32QRCodeReader](https://github.com/alvarowolfx/ESP32QRCodeReader) library on Seeed Studio XIAO ESP32S3 Sense with the Round Display for XIAO.

## Hardware

- **Seeed XIAO ESP32S3 Sense** - ESP32-S3 with OV2640/OV3660 camera
- **Round Display for XIAO** - 1.28" 240×240 round display (GC9A01)
- **microSD card** - Use the SD slot on the Round Display

## SD Card Note

When using both XIAO ESP32S3 Sense and Round Display together, use the **SD card slot on the Round Display** (not the Sense board). The Sense expansion has pull-up resistors that can conflict. Format the SD card as FAT32.

## Build & Upload

```bash
# Build
pio run

# Upload to board
pio run --target upload

# Monitor Serial output
pio device monitor
```

Or use PlatformIO IDE in VS Code: open the project and click Upload/Monitor.

## Features

- Continuous QR code scanning via camera
- Display scanned content on the Round Display
- Serial output at 115200 baud
- Optional: Log scans to `qr_log.txt` on SD card

## Project Structure

```
qr reader/
├── platformio.ini      # PlatformIO config (board, libs, build flags)
├── src/
│   └── main.cpp        # Main application
├── include/
│   ├── ESP32CameraPins.h           # Camera pins reference
│   └── TFT_Setup_RoundDisplay.h    # Display configuration
└── README.md
```

## Nothing in Serial Monitor?

1. **LED check:** After upload, the LED should turn ON. It blinks every 0.5 sec when running.
   - No LED = board not running or upload failed.
   - Steady/blinking LED = code is running; Serial may be the issue.

2. **Correct order:**
   - Upload: `pio run -t upload`
   - Open Serial Monitor: `pio device monitor -b 115200`
   - **Press RESET** on the board
   - Wait 3–5 seconds (USB CDC needs time)

3. **COM port:** In Device Manager, check for "USB Serial Device" or "USB JTAG". Use that port.

4. **Try UART mode** (needs external USB-Serial on TX/RX):
   ```bash
   pio run -e seeed_xiao_esp32s3_uart -t upload
   ```

5. **Baud rate:** Must be **115200**.

## Display blank?

- **Blue border at startup?** If you see a blue border → display works; camera may not be providing frames.
- **Try rotation:** In `main.cpp` change `tft.setRotation(0)` to `1`, `2`, or `3`.
- **Try ST7789:** If using GC9A01 and screen is blank, in `platformio.ini` change the include to:
  `-include $PROJECT_DIR/include/TFT_Setup_ST7789.h`
- **Serial Monitor:** Open at 115200 to see "Camera OK", "Waiting cam...", etc.

## References

- [ESP32QRCodeReader - GitHub](https://github.com/alvarowolfx/ESP32QRCodeReader)
- [XIAO ESP32S3 Sense Camera Usage - Seeed Wiki](https://wiki.seeedstudio.com/xiao_esp32s3_camera_usage)
- [Round Display for XIAO - Seeed Wiki](https://wiki.seeedstudio.com/get_start_round_display/)
