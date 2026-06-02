# flipperzero-mcp

An MCP server for the Flipper Zero. It speaks protobuf RPC to a Flipper over USB
or over WiFi (via an ESP32 WiFi Dev Board) and exposes connection and system
tools to MCP clients such as Claude Desktop.

## Features

- stdio MCP server (FastMCP).
- Two transports for the Flipper protobuf RPC link:
  - **USB** — serial CDC, with CLI → RPC session switching.
  - **WiFi** — TCP to an ESP32 dev board running the TCP↔UART bridge firmware.
- `auto` transport selection: USB first, WiFi fallback only when a WiFi host is set.
- Tools: `flipper_connection_health`, `flipper_connection_reconnect`, `systeminfo_get`.

## Install

```bash
uv sync
# or
pip install -e .
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "flipper-zero": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/flipperzero-mcp", "flipperzero-mcp"],
      "env": { "FLIPPER_TRANSPORT": "auto" }
    }
  }
}
```

## Configuration

The server reads `FLIPPER_*` environment variables (or a local `.env`). See
`src/flipperzero_mcp/config.py` for the authoritative definitions.

| Variable | Default | Description |
|---|---|---|
| `FLIPPER_TRANSPORT` | `auto` | Transport selection: `auto`, `usb`, or `wifi`. |
| `FLIPPER_USB_PORT` | (auto-detect) | Serial device path (e.g. `/dev/ttyACM0`). Unset = auto-detect. |
| `FLIPPER_USB_BAUDRATE` | `115200` | USB serial baud rate. |
| `FLIPPER_WIFI_HOST` | (unset) | Dev board IP/hostname. Required for WiFi. |
| `FLIPPER_WIFI_PORT` | `8080` | Dev board TCP port. |
| `FLIPPER_DEBUG` | `false` | Enable verbose debug logging. |

With `FLIPPER_TRANSPORT=auto` (the default), the server tries USB first and only
falls back to WiFi when `FLIPPER_WIFI_HOST` is set.

## Available tools

| Tool | Description |
|---|---|
| `flipper_connection_health` | Report connection health (connected, transport, RPC responsiveness, last error). Optionally pings RPC. |
| `flipper_connection_reconnect` | Disconnect and reconnect, then report updated health. |
| `systeminfo_get` | Return device info (name, hardware, firmware), transport, and SD-card availability. |
| `flipper_fs_list` | List a device directory; returns typed entries (name, type, size, optional md5). |
| `flipper_fs_mkdir` | Create a directory on the device storage. |
| `flipper_fs_push` | Upload a local file to the device and verify integrity against the device MD5. |
| `flipper_fs_pull` | Download a device file to the host and verify integrity against the device MD5. |

## Firmware

WiFi transport requires an ESP32 WiFi Dev Board running the TCP↔UART bridge
firmware shipped in `firmware/tcp_uart_bridge/`. See that directory's `README.md`
for ESP-IDF build/flash instructions and `docs/wifi_dev_board.md` for the
end-to-end setup guide. The firmware is harvested as-is and is not built in CI.

## Attribution

Portions of this project (transport layer, protobuf RPC implementation, and the
ESP32 WiFi-bridge firmware) are harvested from
[busse/flipperzero-mcp](https://github.com/busse/flipperzero-mcp) under the MIT
License. See `NOTICE` for details.

## License

MIT. See `LICENSE`.
