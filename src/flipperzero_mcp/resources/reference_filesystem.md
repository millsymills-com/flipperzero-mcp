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
