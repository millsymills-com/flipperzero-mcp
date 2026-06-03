# WiFi Dev Board (ESP32‑S2): Protobuf RPC over WiFi

This guide is an end-to-end reference for using the official Flipper WiFi Dev Board (ESP32‑S2) with this MCP server. It covers architecture, firmware ("flirmware") setup, transport configuration, framing, and troubleshooting.

## Table of Contents

1. [Overview](#overview)
2. [Hardware Requirements](#hardware-requirements)
3. [Architecture](#architecture)
4. [Firmware Setup (ESP32‑S2 Bridge)](#firmware-setup-esp32-s2-bridge)
5. [Server Configuration (WiFi Transport)](#server-configuration-wifi-transport)
6. [Communication Flow](#communication-flow)
7. [Protobuf RPC Framing](#protobuf-rpc-framing)
8. [Sanity Check: `check_wifi_bridge.py`](#sanity-check-check_wifi_bridgepy)
9. [Troubleshooting](#troubleshooting)
10. [References](#references)

---

## Overview

The WiFi Dev Board runs a small firmware that bridges a **TCP socket** to the Flipper's **UART Expansion** link. The MCP server uses `WiFiTransport` to open a TCP connection to the Dev Board and then speaks **nanopb-delimited Protobuf RPC** directly.

High level:

```
Claude Desktop / MCP client
          │  (stdio MCP / JSON-RPC)
          ▼
   flipperzero-mcp (Python)
          │  (TCP, raw bytes)
          ▼
 WiFi Dev Board (ESP32-S2)
          │  (UART Expansion)
          ▼
      Flipper Zero
```

What's important:

- The bridge is **transparent**: it forwards bytes bidirectionally.
- Protobuf RPC framing is **preserved** end-to-end.
- Unlike USB CDC, WiFi does **not** require CLI → RPC session switching.

---

## Hardware Requirements

- **Flipper Zero**
- **Official Flipper WiFi Dev Board (ESP32‑S2)**
- **USB cable** (for flashing the Dev Board)
- A **WiFi network** (or use the Dev Board captive portal for first-time setup)

### Pin Configuration (ESP32‑S2 to Flipper Zero)

The bridge firmware in this repo defaults to the ESP32‑S2 pins used by the WiFi Dev Board:

| ESP32‑S2 | Flipper Zero | Function |
|----------|--------------|----------|
| GPIO 43 (TX) | Pin 14 (RX) | Data to Flipper |
| GPIO 44 (RX) | Pin 13 (TX) | Data from Flipper |
| GND | Pin 8/11/18 | Ground |
| 3.3V | Pin 9 | Power |

If you need to change these, see the bridge firmware config (`idf.py menuconfig`) in `firmware/tcp_uart_bridge/README.md`.

---

## Architecture

### Component overview

```
╔════════════════════════════════════════════════════════════════╗
║                 WiFi Dev Board (ESP32‑S2)                      ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║  ┌──────────────────────────────────────────────────────────┐  ║
║  │                Captive Portal + WiFi Manager              │  ║
║  │  - AP for first-time setup (SSID: FlipperBridge)          │  ║
║  │  - Stores credentials in NVS                              │  ║
║  └──────────────────────────┬───────────────────────────────┘  ║
║                             │                                  ║
║  ┌──────────────────────────▼───────────────────────────────┐  ║
║  │                     TCP Server (default 8080)            │  ║
║  │  - Accepts one client connection                          │  ║
║  │  - RX task: TCP → UART                                    │  ║
║  │  - TX task: UART → TCP                                    │  ║
║  └──────────────────────────┬───────────────────────────────┘  ║
║                             │                                  ║
║  ┌──────────────────────────▼───────────────────────────────┐  ║
║  │                   UART Expansion Bridge                   │  ║
║  │  - Negotiates expansion / target baud rate                │  ║
║  │  - Forwards raw bytes (no varint parsing)                 │  ║
║  └──────────────────────────────────────────────────────────┘  ║
╚════════════════════════════════════════════════════════════════╝
                              │ UART
                              ▼
                       ┌──────────────┐
                       │  Flipper Zero│
                       └──────────────┘
```

### Where the code lives in this repo

- **Firmware ("flirmware")**: `firmware/tcp_uart_bridge/`
- **Python transport**: `src/flipperzero_mcp/transport/wifi.py`
- **Auto selection policy**: `src/flipperzero_mcp/transport/auto.py`
- **Protobuf RPC framing**: `src/flipperzero_mcp/rpc/protobuf_rpc.py`

---

## Firmware Setup (ESP32‑S2 Bridge)

The WiFi Dev Board firmware is part of this repo:

- `firmware/tcp_uart_bridge/README.md`

That README is the authoritative guide for:

- ESP‑IDF prerequisites
- Build/flash commands (`idf.py set-target esp32s2`, `idf.py build`, `idf.py flash`, `idf.py monitor`)
- Captive portal setup (SSID `FlipperBridge`, AP password set at build time)
- Build-time config options (TCP port, UART pins, negotiated baud rate, etc.)

---

## Server Configuration (WiFi Transport)

The server reads environment variables (via `src/flipperzero_mcp/config.py`) and builds the transport config in `src/flipperzero_mcp/server.py`.

### WiFi only

```bash
export FLIPPER_TRANSPORT=wifi
export FLIPPER_WIFI_HOST=<DEVBOARD_IP>
export FLIPPER_WIFI_PORT=8080
flipperzero-mcp
```

### Recommended: auto (USB-first) with WiFi fallback

If `FLIPPER_TRANSPORT` is unset, the server defaults to `auto`:

- Try **USB** first
- Fall back to **WiFi** only when `FLIPPER_WIFI_HOST` is set

```bash
export FLIPPER_WIFI_HOST=<DEVBOARD_IP>
export FLIPPER_WIFI_PORT=8080
flipperzero-mcp
```

---

## Communication Flow

### Connection and request/response lifecycle

```
MCP Client            MCP Server                 WiFi Dev Board           Flipper Zero
(Claude, etc.)        (flipperzero-mcp)          (ESP32-S2)               (RPC)
     │                      │                          │                     │
     │ tools/call JSON-RPC   │                          │                     │
     ├──────────stdio────────►                          │                     │
     │                      │ open TCP(host,port)       │                     │
     │                      ├────────────TCP────────────►                     │
     │                      │                          │ UART bytes           │
     │                      │  [varint][pb bytes]       ├─────────UART────────►
     │                      │                          │                     │
     │                      │                          │  [varint][pb bytes]  │
     │                      │  [varint][pb bytes]       ◄─────────UART────────┤
     │                      ◄────────────TCP────────────┤                     │
     │ result JSON-RPC       │                          │                     │
     ◄──────────stdio────────┤                          │                     │
```

Key point: the ESP32‑S2 bridge does **not** interpret framing; it forwards bytes.

---

## Protobuf RPC Framing

Flipper Protobuf RPC uses **nanopb-delimited framing**:

```
┌───────────────────┬──────────────────────────────┐
│ Varint length (N) │ N bytes of protobuf payload  │
└───────────────────┴──────────────────────────────┘
```

This is implemented in:

- `src/flipperzero_mcp/rpc/protobuf_rpc.py` (varint encode/decode, `receive_exact`, etc.)

Important transport-specific behavior:

- **USB**: may start in CLI mode; the server may need to switch to RPC session.
- **WiFi**: treated as already "RPC clean" (no CLI switching; no `start_rpc_session` bytes sent).

---

## Sanity Check: `check_wifi_bridge.py`

This repo includes a helper that verifies TCP reachability + an RPC ping round-trip:

```bash
export FLIPPER_WIFI_HOST=<DEVBOARD_IP>
export FLIPPER_WIFI_PORT=8080
python3 firmware/tcp_uart_bridge/check_wifi_bridge.py
```

Expected output includes:

- `rpc_responsive=True`

---

## Troubleshooting

### Auto mode doesn't fall back to WiFi

- Auto mode only considers WiFi "configured" when `FLIPPER_WIFI_HOST` is set.

### TCP connects but RPC isn't responsive

- Verify the Dev Board firmware is running and has completed its Expansion negotiation.
- Verify the Dev Board is attached to the Flipper and the Flipper is powered on.
- If you changed firmware defaults, ensure UART pins / TCP port match the config (`idf.py menuconfig`).

### "Connection refused" / can't reach the TCP port

- Confirm the Dev Board's IP address from the captive portal or your router DHCP leases.
- Ensure the TCP port matches `BRIDGE_TCP_PORT` in firmware config (default 8080).

---

## References

- Firmware (this repo): `firmware/tcp_uart_bridge/README.md`
- Protobuf RPC framing: `docs/protobuf_rpc.md`
- Flipper protobuf schemas (upstream): `https://github.com/flipperdevices/flipperzero-protobuf`
