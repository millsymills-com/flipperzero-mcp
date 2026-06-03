# Connecting to the Flipper Zero

## Transports
- **USB** — serial CDC ACM. Supports both CLI text mode and protobuf RPC. This is the only transport that supports `flipperzero_cli_exec`.
- **WiFi** — TCP to an ESP32 dev board running the TCP↔UART bridge. Speaks protobuf RPC only; CLI text mode is NOT available. `flipperzero_cli_exec` errors on this transport.

## Baud rate
USB CDC ACM ignores the baud rate — the device does not honor it, so the `FLIPPER_USB_BAUDRATE` config value (default 115200) has no effect over USB. The harvested ESP32 WiFi bridge sets its UART to 115200 (`CONFIG_BRIDGE_UART_BAUD_RATE` in `firmware/tcp_uart_bridge/sdkconfig.defaults`), negotiating up from a 9600 start; no 230400 path exists in this repo.

## Modes (USB)
The same USB port starts in CLI text mode (prompt `>:`). Sending the CLI command `start_rpc_session` switches it into nanopb-delimited protobuf RPC mode. Returning to CLI mode requires the RPC `StopSession` message. The MCP arbitrates this automatically; CLI commands and RPC probes are serialized by a shared lock so they never interleave on the wire.

## Ports
- macOS: `/dev/cu.usbmodemflip_*`
- Linux: `/dev/ttyACM*`

Set `FLIPPER_USB_PORT` to override auto-detection.
