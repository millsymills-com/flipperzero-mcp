# Hardware proof — `/flipper-install` flagship (Gate C)

Date: 2026-06-10. Captured on a real Flipper Zero over USB, driving the actual
MCP tools (`Client(create_server(...))`), not mocks.

## Target

- App: [`besya/flipperzero-tuning-fork`](https://github.com/besya/flipperzero-tuning-fork)
  (`fap_version` 2.1, `fap_category` Media) — a standalone FAP, no extra hardware.

## Device

- Name `Lun10n`, Flipper Zero `f7`.
- Firmware: Momentum `mntm-012` (Next-Flip/Momentum-Firmware), API 87.1.
- SD card present.

## Pipeline run (clone → build → push → verify → launch)

1. **Clone** — `git clone https://github.com/besya/flipperzero-tuning-fork`;
   located `application.fam` at the repo root.
2. **SDK match** — `firmware.flavor` read as `momentum` from
   `flipperzero_system_info`, so ufbt was pointed at the Momentum SDK index:
   `ufbt update --index-url https://up.momentum-fw.dev/firmware/directory.json`
   → resolved `mntm-012`, the exact device version.
3. **Build** — `ufbt` produced `dist/tuning_fork.fap`. `APPCHK` reported
   `Target: 7, API: 87.1`, matching the device — no channel/firmware mismatch.
4. **Push (md5-verified)** — `flipperzero_fs_push` wrote 24712 bytes to
   `/ext/apps/Media/tuning_fork.fap`; the device MD5
   `de43b1370d3a30b095d485b6cbd529f2` matched the local file (`verified: true`).
5. **Confirm** — `flipperzero_fs_list /ext/apps/Media` showed
   `tuning_fork.fap` (FILE, 24712 bytes).
6. **Launch** — `flipperzero_app_start` started the app (`started: true`).

The captured tool output is in
[`2026-06-10-flipper-install-tuning-fork.json`](2026-06-10-flipper-install-tuning-fork.json).

## Reproduce

```bash
uv tool install ufbt
git clone https://github.com/besya/flipperzero-tuning-fork /tmp/tf
cd /tmp/tf
ufbt update --index-url https://up.momentum-fw.dev/firmware/directory.json  # Momentum; omit for Official
ufbt                                                                        # -> dist/tuning_fork.fap
# then, with FLIPPER_ENABLE_WRITE_TOOLS=true, run the /flipper-install runbook
# (flipperzero_fs_push -> md5 verify -> flipperzero_app_start).
```
