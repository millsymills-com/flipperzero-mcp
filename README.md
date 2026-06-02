# flipperzero-mcp

An MCP server for the Flipper Zero. It speaks protobuf RPC to a Flipper over USB
or over WiFi (via an ESP32 WiFi Dev Board) and exposes connection and system
tools to MCP clients such as Claude Desktop.

## Status

Stage: S1 (walking skeleton) — the server runs over stdio and exposes
read-only tools (`flipper_connection_health`, `flipper_connection_reconnect`,
`flipper_system_info`) backed by unit tests. Write tools (`flipper_cli_exec`,
the `flipper_fs_*` storage slice) are the S2/S3 launch work tracked in #37.

This repo officially adopts the `flipper_` tool namespace — a documented
deviation from the literal PROTO-002 rule (which would be `flipperzero_`),
chosen for ergonomics and applied uniformly across the surface.

## Features

- stdio MCP server (FastMCP).
- Two transports for the Flipper protobuf RPC link:
  - **USB** — serial CDC, with CLI → RPC session switching.
  - **WiFi** — TCP to an ESP32 dev board running the TCP↔UART bridge firmware.
- `auto` transport selection: USB first, WiFi fallback only when a WiFi host is set.
- Tools: `flipper_connection_health`, `flipper_connection_reconnect`, `flipper_system_info`.

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
| `flipper_system_info` | Return device info (name, hardware, firmware), transport, and SD-card availability. |

## Firmware

WiFi transport requires an ESP32 WiFi Dev Board running the TCP↔UART bridge
firmware shipped in `firmware/tcp_uart_bridge/`. See that directory's `README.md`
for ESP-IDF build/flash instructions and `docs/wifi_dev_board.md` for the
end-to-end setup guide. The firmware is harvested as-is and is not built in CI.

## Development

```bash
uv sync --extra dev          # install with dev dependencies
uv run pytest -m "not integration"   # default unit/property suite
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run ty check src/flipperzero_mcp/ # type-check
```

Integration tests (marked `integration`, plus `usb`/`wifi`) require a real
Flipper and are local-only. See `CLAUDE.md` for project conventions.

## Attribution

Portions of this project (transport layer, protobuf RPC implementation, and the
ESP32 WiFi-bridge firmware) are harvested from
[busse/flipperzero-mcp](https://github.com/busse/flipperzero-mcp) under the MIT
License. See `NOTICE` for details.

## License

MIT. See `LICENSE`.
