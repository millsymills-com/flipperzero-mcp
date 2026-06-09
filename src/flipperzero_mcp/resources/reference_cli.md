# Flipper Zero CLI Reference

Baseline firmware: official 1.x. The CLI surface can change across firmware releases — re-validate after firmware updates.

Connect over USB; the MCP `flipperzero_cli_exec` tool runs one command at a time in CLI text mode and returns output up to the `>:` prompt. Streaming commands (`subghz rx`, `ir rx`, `log`, `input dump`, `subghz chat`) never return to the prompt and will time out with partial output — they are not usable via `flipperzero_cli_exec` in this release.

## Core
- `help` / `?` — list commands
- `device info` / `!` — device information
- `date` — get/set date and time
- `uptime` — time since boot
- `free` — heap allocator info
- `power off` | `power reboot` | `power reboot2dfu` (destructive)
- `factory reset` (destructive)

## Storage (also available as typed RPC)
- `storage info /ext` | `/int`
- `storage list <path>` / `storage tree <path>`
- `storage read <path>` / `storage read chunks <path> <size>`
- `storage write <path> <text>` / `storage write chunk <path> <size>`
- `storage copy <src> <dst>` / `storage rename <path> <newpath>`
- `storage mkdir <path>` / `storage remove <path>`
- `storage md5 <path>` / `storage stat <path>` / `storage timestamp <path>`
- `storage extract <archive> <dir>`
- `storage format /ext` (destructive)

## Loader (apps)
- `loader list` — enumerate apps
- `loader open <app>` / `loader close`
- `loader signal <number> <arg>`

## GPIO
- `gpio mode <pin> <0|1>` / `gpio set <pin> <0|1>` / `gpio read <pin>`
- Pins: PA7 PA6 PA4 PB3 PB2 PC3 PC1 PC0
- `power 5v <0|1>` / `power 3v3 <0|1>` (debug)

## Sub-GHz (RF — transmit is regulated)
- `subghz rx <freq> [device]` (streaming)
- `subghz rx raw <freq>` (streaming)
- `subghz tx <key> <freq> <te> <repeat> [device]` (TRANSMIT — gated)
- `subghz tx from file <path> <repeat> [device]` (TRANSMIT — gated)
- `subghz decode raw <path>`
- `subghz chat <freq> <device>` (streaming)
- Bands: 299.9–348, 387–464, 779–928 MHz. device 0 = internal, 1 = external.
- Region default: US (FCC ISM, 902–928 MHz). Examples assume this band; the server enforces no region. Confirm local regulations before transmitting.

## NFC / RFID / iButton / IR
- `nfc scanner` / `nfc field` / `nfc emulate f <path>` / `nfc apdu d <data>`
- `rfid read` / `rfid emulate <type> <data>` / `rfid write <type> <data>` (TRANSMIT — gated)
- `ikey read` / `ikey emulate <type> <data>` / `ikey write dallas <data>` (gated)
- `ir rx` / `ir rx raw` (streaming) / `ir tx <protocol> <address> <command>` (TRANSMIT — gated)
- `ir decode` / `ir universal`

## Misc
- `led r|g|b <0-255>` / `led bl <0-255>`
- `vibro <0|1>` / `buzzer freq <hz> <dur>` / `buzzer note <note> <dur>`
- `input dump` (streaming) / `input send <key> <type>`
- `log [error|warn|info|debug|trace]` (streaming) / `i2c` / `crypto ...`
- `update install <path>` (destructive)
