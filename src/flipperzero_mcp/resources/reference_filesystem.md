# Flipper Zero Filesystem

- `/int` — internal flash (small; settings, a few files).
- `/ext` — microSD card (where apps, dumps, and databases live).

Common locations on `/ext`:
- `/ext/apps/<Category>/` — installed `.fap` applications
- `/ext/subghz/` — saved SubGHz captures (`.sub`)
- `/ext/nfc/` — saved NFC cards (`.nfc`)
- `/ext/lfrfid/` — saved 125 kHz RFID cards (`.rfid`)
- `/ext/infrared/` — saved IR remotes (`.ir`)
- `/ext/ibutton/` — saved iButton keys

Paths must start with `/int` or `/ext`. Hex values are lowercase. Use `storage md5 <path>` (or the RPC md5sum op) to verify transfers.

MCP storage tools:
- `flipperzero_fs_info(path="/ext")` — capacity/free-space for a storage root.
- `flipperzero_fs_stat(path)` — metadata for one file or directory.
- `flipperzero_fs_timestamp(path)` — firmware timestamp for one file or directory.
- `flipperzero_fs_list(path)` — directory entries.
- `flipperzero_fs_pull(src_path, local_path)` — download and verify MD5.
- `flipperzero_fs_mkdir(path)` — create a directory; requires `FLIPPER_ENABLE_WRITE_TOOLS=true`.
- `flipperzero_fs_delete(path, recursive=false)` — delete; requires `FLIPPER_ENABLE_WRITE_TOOLS=true`.
- `flipperzero_fs_rename(old_path, new_path)` — move/rename; requires `FLIPPER_ENABLE_WRITE_TOOLS=true`.
- `flipperzero_fs_push(local_path, dest_path)` — upload and verify MD5; requires `FLIPPER_ENABLE_WRITE_TOOLS=true`.
