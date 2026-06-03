# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Native storage RPC tools: `flipperzero_fs_list`, `flipperzero_fs_mkdir`,
  `flipperzero_fs_push`, and `flipperzero_fs_pull`. Push and pull verify integrity by
  comparing the local MD5 to the device's `storage_md5sum` and fail loud on
  mismatch. Adds a `storage_md5sum` method to the protobuf RPC layer.
- Dual-mode link manager on `FlipperClient`: `enter_cli()`, `enter_rpc()`, and
  `mode()` (a `LinkMode` enum) track and switch the shared link between the text
  CLI and nanopb RPC. A single client-level `_io_lock` now serializes every CLI
  and RPC round-trip so frames cannot interleave on one link.

## [0.1.0]

### Added
- `flipperzero_connection_health` and `flipperzero_connection_reconnect` tools (callable
  even when disconnected).
- `flipperzero_system_info` tool returning device info, transport, and SD-card status.
- USB and WiFi transports plus an `auto` selector (USB first, WiFi fallback when
  `FLIPPER_WIFI_HOST` is set).
- Protobuf RPC implementation with nanopb-delimited framing and vendored
  protobuf bindings under `src/flipperzero_mcp/rpc/protobuf_gen/`.
- ESP32 TCP↔UART bridge firmware under `firmware/tcp_uart_bridge/` for WiFi.
- Configuration via `FLIPPER_*` environment variables.
- Stderr-bound JSON logging (stdout is reserved for the JSON-RPC channel).

[Unreleased]: https://github.com/millsymills-com/flipperzero-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/millsymills-com/flipperzero-mcp/releases/tag/v0.1.0
