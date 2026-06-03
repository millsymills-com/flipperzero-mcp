# Workflow: Flash the ESP32 dev board

This is a future typed capability (`esp32_detect` / `esp32_flash`). For now, flash manually with esptool on the host:

1. Identify the ESP32 serial port (NOT the Flipper port).
2. Download the firmware release and verify its SHA-256.
3. Run `esptool --port <port> write_flash <addr> <firmware.bin>`.

Caution: if you connect to the Flipper over WiFi, the bridge ESP32 may be the very board you are flashing — flashing it tears down the WiFi link. Use a USB Flipper connection while flashing the bridge board.
