# ESP32 WiFi Dev Board: TCP-UART Bridge

Firmware for the Flipper Zero WiFi Dev Board (ESP32-S2) that bridges TCP socket connections to UART, enabling Protobuf RPC communication over WiFi.

```
MCP Client <--TCP--> ESP32 <--UART--> Flipper Zero
```

## Features

- **Captive Portal**: Web-based WiFi configuration (no hardcoded credentials)
- **Persistent Storage**: WiFi credentials stored in NVS (survives reboots)
- **Bidirectional Bridge**: Transparent TCP↔UART forwarding
- **LED Status**: Visual connection state indication
- **Auto-reconnect**: Handles WiFi disconnections gracefully

## Hardware Requirements

- Flipper Zero with WiFi Dev Board (ESP32-S2)
- USB cable for flashing

### Pin Configuration (ESP32-S2 to Flipper Zero)

| ESP32-S2 | Flipper Zero | Function |
|----------|--------------|----------|
| GPIO 43 (TX) | Pin 14 (RX) | Data to Flipper |
| GPIO 44 (RX) | Pin 13 (TX) | Data from Flipper |
| GND | Pin 8/11/18 | Ground |
| 3.3V | Pin 9 | Power |

## Building

### Prerequisites

1. Install [ESP-IDF v5.1+](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s2/get-started/)

```bash
# Clone ESP-IDF
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
git checkout v5.1
./install.sh esp32s2
source export.sh
```

### Build & Flash

```bash
cd firmware/tcp_uart_bridge

# Set target to ESP32-S2
idf.py set-target esp32s2

# Build
idf.py build

# Flash (connect WiFi dev board via USB)
idf.py -p /dev/ttyACM0 flash

# Monitor serial output
idf.py -p /dev/ttyACM0 monitor
```

## First-Time Setup

1. **Flash the firmware** to your WiFi Dev Board
2. **Power on** the Flipper Zero with Dev Board attached
3. **Connect to WiFi** network `FlipperBridge` (using the AP password you set at build time)
4. **Open browser** to `http://192.168.4.1/`
5. **Select your WiFi network** and enter password
6. **Note the IP address** shown after connection

## Usage

Once configured and connected to your WiFi:

```bash
export FLIPPER_TRANSPORT=wifi
export FLIPPER_WIFI_HOST=<DEVBOARD_IP>
export FLIPPER_WIFI_PORT=8080
python3 check_wifi_bridge.py
```

If `rpc_responsive=True`, you're ready to use MCP over WiFi!

## Configuration Options

Build-time options in `Kconfig.projbuild`:

| Option | Default | Description |
|--------|---------|-------------|
| `BRIDGE_TCP_PORT` | 8080 | TCP server port |
| `BRIDGE_UART_BAUD_RATE` | 230400 | Target baud rate after Expansion negotiation |
| `BRIDGE_UART_TX_PIN` | 43 | ESP32 TX GPIO |
| `BRIDGE_UART_RX_PIN` | 44 | ESP32 RX GPIO |
| `BRIDGE_AP_SSID` | FlipperBridge | Captive portal AP name |
| `BRIDGE_AP_PASSWORD` | (unset) | Captive portal password (set before flashing, min 8 chars) |

To change settings:

```bash
idf.py menuconfig
# Navigate to: TCP-UART Bridge Configuration
```

## LED Status Indicators

| Pattern | Meaning |
|---------|---------|
| Fast blink | Not connected to WiFi (captive portal active) |
| Medium blink | WiFi connected, connecting to Flipper (Expansion Protocol) |
| Slow blink | Flipper connected, waiting for TCP client |
| Solid on | WiFi + Flipper + TCP client connected (bridging active) |

## Troubleshooting

### Can't connect to captive portal
- Ensure the dev board is powered
- Look for `FlipperBridge` WiFi network
- Try resetting the dev board

### WiFi connects but no RPC response
- Check UART wiring between ESP32 and Flipper
- Verify Flipper is on and not in another app
- Ensure the bridge firmware is running and has completed Expansion negotiation (UART speed may change after connect; see `BRIDGE_UART_BAUD_RATE`)

### Reset WiFi credentials
Clear stored credentials via code (call `wifi_manager_reset_credentials()`), or erase NVS by reflashing/erasing flash as part of your ESP-IDF workflow.

## Technical Details

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ESP32-S2 Firmware                                          │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │ WiFi Manager│   │ TCP Server  │   │ UART Bridge │       │
│  │             │   │             │   │             │       │
│  │ • STA mode  │   │ • Port 8080 │   │ • 115200    │       │
│  │ • AP mode   │   │ • 1 client  │   │ • 8N1       │       │
│  │ • Captive   │   │ • RX task   │   │ • RX task   │       │
│  │   portal    │   │             │   │             │       │
│  └─────────────┘   └──────┬──────┘   └──────┬──────┘       │
│                           │                  │              │
│                    ┌──────┴──────────────────┴──────┐       │
│                    │      Bidirectional Bridge      │       │
│                    │   TCP RX → UART TX            │       │
│                    │   UART RX → TCP TX            │       │
│                    └────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Memory Usage

- Flash: ~1MB (including NVS partition)
- RAM: ~50KB dynamic allocation
- Stack: 4KB per task

### Dependencies

- ESP-IDF v5.1+
- FreeRTOS (included in ESP-IDF)
- lwIP (included in ESP-IDF)

## License

MIT License - see repository root LICENSE file.
