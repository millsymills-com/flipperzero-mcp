# Workflow: Install an app

1. Confirm USB connection: call `flipperzero_system_info` (or `flipperzero_connection_health`).
2. Ensure the SD card is present (`flipperzero_system_info` -> `sd_card_available`).
3. Place the `.fap` on the SD card under `/ext/apps/<Category>/`. Push with `flipperzero_fs_push` when write tools are enabled, or use qFlipper.
4. Verify: call `flipperzero_fs_list` for `/ext/apps/<Category>`.
5. Launch: `flipperzero_cli_exec "loader open <AppName>"`; stop with `flipperzero_cli_exec "loader close"`.

Note: a `.fap` must match the device firmware API. Building with ufbt against the matching SDK channel is a future capability.
