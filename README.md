<p align="center"><img src="assets/logo.svg" alt="flipperzero-mcp" width="200"></p>

# flipperzero-mcp

An MCP server for the Flipper Zero. It speaks protobuf RPC to a Flipper over USB
or over WiFi (via an ESP32 WiFi Dev Board) and exposes connection and system
tools to MCP clients such as Claude Desktop.

## Status

**Stage: S2** (wrapped). The server runs over stdio with read tools (connection
health, reconnect, system info/power/datetime/protobuf-version, and storage reads
`fs_info`, `fs_stat`, `fs_timestamp`, `fs_list`, `fs_pull`) and write tools
(`fs_mkdir`, `fs_delete`, `fs_rename`, `fs_push`, `app_start`, `cli_exec`).
Device-mutating storage/app operations are gated behind
`FLIPPER_ENABLE_WRITE_TOOLS` and transmit/destructive CLI commands behind
`FLIPPER_ENABLE_TX_TOOLS`, both default-off. CI runs lint and tests on the
committed lockfile. The `/flipper-install` flagship and live integration suite
are the S3 climb tracked in the public-launch issues (#37 umbrella).

## Features

- stdio MCP server (FastMCP).
- Two transports for the Flipper protobuf RPC link:
  - **USB**: serial CDC, with CLI to RPC session switching.
  - **WiFi**: TCP to an ESP32 dev board running the TCP-to-UART bridge firmware.
- `auto` transport selection: USB first, WiFi fallback only when a WiFi host is set.
- Tools: connection health/reconnect, system info/power/datetime/protobuf-version, storage info/stat/timestamp/list/push/pull/mkdir/delete/rename, app start, and USB CLI exec.

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
| `FLIPPER_ENABLE_WRITE_TOOLS` | `false` | Server-side gate for device-mutating storage writes (`fs_push`, `fs_mkdir`). Off blocks them. |
| `FLIPPER_ENABLE_TX_TOOLS` | `false` | Server-side gate for transmit/destructive CLI commands. Off blocks them regardless of the per-call flag. |
| `FLIPPER_ENABLE_FIRMWARE_FLASH` | `false` | Server-side gate for `flipperzero_firmware_install`. Requires `FLIPPER_ENABLE_WRITE_TOOLS=true` as well. |
| `FLIPPER_DEBUG` | `false` | Enable verbose debug logging. |
| `FLIPPER_FORCE_START_RPC_SESSION` | `false` | Advanced/debug: force `start_rpc_session` even when probing suggests RPC mode is already active. |

With `FLIPPER_TRANSPORT=auto` (the default), the server tries USB first and only
falls back to WiFi when `FLIPPER_WIFI_HOST` is set.

## Available tools

| Tool | Description |
|---|---|
| `flipperzero_connection_health` | Report connection health (connected, transport, RPC responsiveness, last error). Optionally pings RPC. |
| `flipperzero_connection_reconnect` | Disconnect and reconnect, then report updated health. |
| `flipperzero_system_info` | Return device info (name, hardware, firmware), transport, and SD-card availability. |
| `flipperzero_system_power_info` | Return firmware-reported power/battery key-value pairs. |
| `flipperzero_system_protobuf_version` | Return the device protobuf RPC major/minor version. |
| `flipperzero_system_datetime` | Return the device date/time fields. |
| `flipperzero_fs_info` | Return storage capacity information for a path such as `/ext`. |
| `flipperzero_fs_stat` | Return metadata for a device file or directory. |
| `flipperzero_fs_timestamp` | Return the device timestamp for a file or directory. |
| `flipperzero_fs_list` | List a device directory; returns typed entries (name, type, size, optional md5). |
| `flipperzero_fs_mkdir` | Create a directory on the device storage. |
| `flipperzero_fs_delete` | Delete a file or directory on the device storage. |
| `flipperzero_fs_rename` | Rename or move a device file/directory. |
| `flipperzero_fs_push` | Upload a local file to the device and verify integrity against the device MD5. |
| `flipperzero_fs_pull` | Download a device file to the host and verify integrity against the device MD5. |
| `flipperzero_app_start` | Start a Flipper application via RPC; gated behind `FLIPPER_ENABLE_WRITE_TOOLS`. |
| `flipperzero_cli_exec` | Run one Flipper CLI command and return its output, completion flag, and risk classification. |
| `flipperzero_firmware_install` | Flash a firmware bundle to the device via USB. Destructive; gated by `FLIPPER_ENABLE_FIRMWARE_FLASH=true` + `FLIPPER_ENABLE_WRITE_TOOLS=true` + a `confirm` token matching the device name. |

CLI exec is USB-only; transmit/destructive commands require both
`FLIPPER_ENABLE_TX_TOOLS=true` on the server and `i_accept_responsibility=true`
on the call.

## Scope & limitations

- **CLI is USB-only.** `flipperzero_cli_exec` needs the Flipper text CLI shell,
  which only the USB CDC link carries. Over the WiFi bridge (protobuf-only) it
  returns a clear "CLI text mode unavailable over WiFi bridge" error.
- **No streaming/interactive commands.** Commands that never return to the `>:`
  prompt (e.g. `subghz rx`, `ir rx`, `log`) time out with `completed=false` and
  partial output. Commands that expect interactive input are unsupported.
- **Transmit/destructive commands are double-gated.** Both `FLIPPER_ENABLE_TX_TOOLS=true`
  (operator, server-side) and `i_accept_responsibility=true` (per call) are
  required; either missing refuses the command. The risk classifier is an
  advisory ordered-prefix list that fails open — the env flag is the real
  boundary. Radio transmission is subject to local regulations; you are
  responsible for legal use.
- **Device writes are gated.** Storage/app mutations need `FLIPPER_ENABLE_WRITE_TOOLS=true`,
  default-off.
- **Distribution is git-clone + `uv`.** No PyPI package at this stage.
- **WiFi needs the ESP32 bridge** running the harvested TCP↔UART firmware; that
  firmware is not built in CI.

## Resources & prompts

Bundled MCP resources:

- `flipper://reference/cli`
- `flipper://reference/connection`
- `flipper://reference/filesystem`
- `flipper://reference/system`
- `flipper://workflow/install-app`
- `flipper://workflow/transfer-files`
- `flipper://workflow/flash-esp32`
- `flipper://workflow/capture-replay`

Prompts:

- `manage_flipper`
- `troubleshoot_connection`

## Development

```bash
uv sync --extra dev              # install runtime + dev deps into .venv
uv run pytest -m "not integration"   # default suite (no hardware required)
uv run ruff check && uv run ruff format --check
uv run ty check
```

Integration tests (`-m integration`) need a real Flipper over USB or WiFi and are
local-only. See `CLAUDE.md` for project conventions and `CONTRIBUTING.md`.

## Firmware

**Supported firmware.** The server supports both **Official** firmware (channels
`release`, `release-candidate`, `development`; tested on 1.4.x) and **Momentum**
(`mntm-012`). The protobuf RPC layer is firmware-agnostic. The golden test
fixtures (`tests/golden/`) were captured on Momentum `mntm-012` (protobuf RPC
0.25, build 2025-12-31). CLI text output and command availability can differ
between firmware flavors — re-validate and re-record fixtures
(`make record-fixtures`) after a firmware change.

The protobuf runtime is pinned to `protobuf==6.33.5` (see `CLAUDE.md`).
`flipperzero_system_info` returns a `firmware` block: `{flavor, version,
origin_fork, origin_git, target}`.

**Flashing firmware (`flipperzero_firmware_install`).** The tool pushes a
firmware bundle to `/ext/update/<pkg>/` on the device and reboots into the
on-device updater. The source is either a local `.tgz` path or `{flavor,
channel, version}` for auto-download (downloads Official from
`update.flipperzero.one` or Momentum from GitHub releases).

- **Integrity.** Bundles are verified by sha256 before transfer — Official via
  the per-file `sha256` in `directory.json`; Momentum via the GitHub release
  asset digest. This is integrity verification over HTTPS, not GPG-signed
  provenance.
- **USB-only.** Flashing requires USB. The device reboots into the on-device
  updater; the WiFi bridge cannot survive that reboot.
- **Gating.** Requires `FLIPPER_ENABLE_WRITE_TOOLS=true` AND
  `FLIPPER_ENABLE_FIRMWARE_FLASH=true` (both default-off), plus a `confirm`
  argument that must equal the connected device's name.
- **Recovery.** If flashing fails, the device enters DFU mode. Use
  [qFlipper](https://flipperzero.one/update) to recover. Momentum has no
  automatic OTA fallback.

**ESP32 WiFi bridge.** WiFi transport requires an ESP32 WiFi Dev Board running
the TCP↔UART bridge firmware shipped in `firmware/tcp_uart_bridge/`. See that
directory's `README.md` for ESP-IDF build/flash instructions and
`docs/wifi_dev_board.md` for the end-to-end setup guide. The firmware is
harvested as-is and is not built in CI.

## Attribution

Portions of this project (transport layer, protobuf RPC implementation, and the
ESP32 WiFi-bridge firmware) are harvested from
[busse/flipperzero-mcp](https://github.com/busse/flipperzero-mcp) under the MIT
License. See `NOTICE` for details.

## License

MIT. See `LICENSE`.
