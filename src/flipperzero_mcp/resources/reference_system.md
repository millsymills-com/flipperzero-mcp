# Flipper Zero System/API Surface

Read-only system RPC tools:

- `flipperzero_system_info()` — connection health plus normalized device info and SD-card availability.
- `flipperzero_system_power_info()` — firmware-reported power/battery key-value pairs.
- `flipperzero_system_protobuf_version()` — protobuf RPC protocol major/minor version.
- `flipperzero_system_datetime()` — device date/time fields (`year`, `month`, `day`, `hour`, `minute`, `second`, `weekday`).

Application RPC tools:

- `flipperzero_app_start(name, args="")` — starts an app by firmware-recognized name/path. This changes device UI state and some apps can disrupt USB mode, so it requires `FLIPPER_ENABLE_WRITE_TOOLS=true`.

Prefer native RPC tools for structured state. Use `flipperzero_cli_exec` only when the protobuf API lacks an equivalent operation or when following a CLI-oriented runbook.
