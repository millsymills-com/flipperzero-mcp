# Tool ↔ schema coverage matrix

Canonical, checked-in inventory of every MCP tool this server registers and the
exact input schema + behavioral annotations each exposes.
`tests/unit/test_schema_matrix_drift.py` parses the two tables below and asserts
them against the live `FastMCP` server, so any added/removed tool, renamed or
retyped parameter, changed default, or flipped annotation hint fails CI until this
file is regenerated in the same change.

Do not hand-edit. Regenerate after intentional tool changes, then review the diff:

```bash
uv run python tests/tools/gen_schema_matrix.py
uv run pytest tests/unit/test_schema_matrix_drift.py
```


**28 tools** across 9 groups: apps, cli, cli_typed, connection, device, diagnostics, firmware, storage, systeminfo.

## Annotations

`Gate` is the env/argument interlock enforced at call time (informational; the
drift test asserts the four hint columns, not `Gate`). `WRITE` =
`FLIPPER_ENABLE_WRITE_TOOLS`, `FIRMWARE_FLASH` = `FLIPPER_ENABLE_FIRMWARE_FLASH`,
`TX` = `FLIPPER_ENABLE_TX_TOOLS`.

| Tool | Group | readOnly | destructive | idempotent | openWorld | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `flipperzero_app_get_error` | device | true | — | true | true | none |
| `flipperzero_app_lock_status` | device | true | — | true | true | none |
| `flipperzero_app_start` | apps | false | false | false | true | WRITE |
| `flipperzero_cli_exec` | cli | false | true | false | true | TX + i_accept_responsibility |
| `flipperzero_connection_health` | connection | true | — | true | true | none |
| `flipperzero_connection_reconnect` | connection | false | false | false | true | none |
| `flipperzero_core_status` | cli_typed | true | — | true | true | none |
| `flipperzero_desktop_is_locked` | device | true | — | true | true | none |
| `flipperzero_firmware_install` | firmware | false | true | false | true | WRITE + FIRMWARE_FLASH |
| `flipperzero_fs_delete` | storage | false | true | false | true | WRITE |
| `flipperzero_fs_info` | storage | true | — | true | true | none |
| `flipperzero_fs_list` | storage | true | — | true | true | none |
| `flipperzero_fs_mkdir` | storage | false | false | false | true | WRITE |
| `flipperzero_fs_pull` | storage | false | true | true | true | none |
| `flipperzero_fs_push` | storage | false | true | true | true | WRITE |
| `flipperzero_fs_rename` | storage | false | true | false | true | WRITE |
| `flipperzero_fs_stat` | storage | true | — | true | true | none |
| `flipperzero_fs_timestamp` | storage | true | — | true | true | none |
| `flipperzero_fs_tree` | cli_typed | true | — | true | true | none |
| `flipperzero_gpio_read` | device | true | — | true | true | none |
| `flipperzero_i2c_scan` | cli_typed | true | — | true | true | none |
| `flipperzero_loader_list` | cli_typed | true | — | true | true | none |
| `flipperzero_system_datetime` | systeminfo | true | — | true | true | none |
| `flipperzero_system_info` | systeminfo | true | — | true | true | none |
| `flipperzero_system_ping` | diagnostics | true | — | true | true | none |
| `flipperzero_system_power_info` | systeminfo | true | — | true | true | none |
| `flipperzero_system_property_get` | diagnostics | true | — | true | true | none |
| `flipperzero_system_protobuf_version` | systeminfo | true | — | true | true | none |

## Parameters

One row per parameter (`ctx` is injected by FastMCP and omitted). Tools with no
caller-supplied parameters show a single `—` row. `Default` is `—` for required
parameters.

| Tool | Parameter | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `flipperzero_app_get_error` | — | — | — | — |
| `flipperzero_app_lock_status` | — | — | — | — |
| `flipperzero_app_start` | `name` | string | required | — |
| `flipperzero_app_start` | `args` | string | optional | `""` |
| `flipperzero_cli_exec` | `command` | string | required | — |
| `flipperzero_cli_exec` | `timeout_s` | number | optional | `10.0` |
| `flipperzero_cli_exec` | `i_accept_responsibility` | boolean | optional | `false` |
| `flipperzero_connection_health` | `probe_rpc` | boolean | optional | `true` |
| `flipperzero_connection_reconnect` | `probe_rpc` | boolean | optional | `true` |
| `flipperzero_core_status` | — | — | — | — |
| `flipperzero_desktop_is_locked` | — | — | — | — |
| `flipperzero_firmware_install` | `source` | object | required | — |
| `flipperzero_firmware_install` | `confirm` | string | required | — |
| `flipperzero_fs_delete` | `path` | string | required | — |
| `flipperzero_fs_delete` | `recursive` | boolean | optional | `false` |
| `flipperzero_fs_info` | `path` | string | optional | `/ext` |
| `flipperzero_fs_list` | `path` | string | required | — |
| `flipperzero_fs_mkdir` | `path` | string | required | — |
| `flipperzero_fs_pull` | `src_path` | string | required | — |
| `flipperzero_fs_pull` | `local_path` | string | required | — |
| `flipperzero_fs_push` | `local_path` | string | required | — |
| `flipperzero_fs_push` | `dest_path` | string | required | — |
| `flipperzero_fs_rename` | `old_path` | string | required | — |
| `flipperzero_fs_rename` | `new_path` | string | required | — |
| `flipperzero_fs_stat` | `path` | string | required | — |
| `flipperzero_fs_timestamp` | `path` | string | required | — |
| `flipperzero_fs_tree` | `path` | string | required | — |
| `flipperzero_gpio_read` | `pin` | integer | required | — |
| `flipperzero_i2c_scan` | — | — | — | — |
| `flipperzero_loader_list` | — | — | — | — |
| `flipperzero_system_datetime` | — | — | — | — |
| `flipperzero_system_info` | — | — | — | — |
| `flipperzero_system_ping` | — | — | — | — |
| `flipperzero_system_power_info` | — | — | — | — |
| `flipperzero_system_property_get` | `key` | string | required | — |
| `flipperzero_system_protobuf_version` | — | — | — | — |
