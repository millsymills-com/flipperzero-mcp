# Multi-firmware support + firmware-flash tooling — design

**Date:** 2026-06-09
**Status:** Approved design; pending implementation plan
**Branch:** `multi-firmware-support`

## Problem

The server is validated only against Momentum `mntm-012`: the golden fixtures
(`tests/golden/`) and the README firmware-baseline statement both assume
Momentum. The RPC/protobuf layer itself is firmware-agnostic (the vendored
protos come from official `flipperdevices/flipperzero-protobuf`, and no code in
`src/` branches on firmware), but three things make the server effectively
Momentum-only in practice:

1. Golden fixtures and CLI reference captured on Momentum.
2. No way to tell the agent *which* firmware is connected, so prompts can't
   adapt (e.g. ufbt SDK selection in `/flipper-install`).
3. No way to put a device onto a known firmware for validation.

We want first-class support for **official** Flipper firmware (channels
`release`, `release-candidate`, `development`) alongside **Momentum**, including
the ability to flash firmware over USB so the server can validate itself on real
hardware.

## Goals

- Detect and report the connected firmware flavor + version.
- Flash a chosen firmware (official or Momentum) onto a USB-connected Flipper,
  with strong safety gating, integrity verification, and honest recovery docs.
- Validate the server end to end on real official firmware, capturing official
  golden fixtures alongside the Momentum ones.
- Update prompts and docs so both firmwares are first-class.

## Non-goals

- WiFi-transport flashing. The flash flow is **USB-only** — the device reboots
  through the updater (multiple restarts, FUS radio-stack reinstall) and the
  WiFi bridge cannot survive that. Stated as a limitation.
- Cryptographic *provenance* (GPG signatures). Upstream publishes per-file
  **sha256** (integrity), not signatures. Trust rests on HTTPS + GitHub /
  update.flipperzero.one. Stated plainly.
- Supporting arbitrary third-party firmwares as *download* targets. The
  classifier recognizes Unleashed/RogueMaster but the downloader ships only
  official + Momentum sources; a local `.tgz` path covers everything else.
- Building firmware from source. Bundles are fetched or supplied pre-built.

## Background: how Flipper self-update works

Confirmed against `flipperdevices/flipperzero-firmware` `scripts/selfupdate.py`
and the OTA developer docs:

1. The update bundle is a `.tgz` that extracts to a **folder** containing
   `update.fuf` (manifest) plus `.dfu` (firmware image), a radio-stack `.bin`,
   and `resources.tar`.
2. The host `mkdir`s `/ext/update/<pkg>/` and **recursively pushes the whole
   folder** to the device SD card.
3. The host issues the update request pointing at the manifest, then reboots the
   device into UPDATE mode. The updater image runs from RAM, validates and
   writes the `.dfu`, reinstalls the radio stack via FUS (several restarts),
   corrects option bytes, and restores backed-up `/int` contents.
4. On failure there is **no automatic OTA fallback** — the device drops to DFU
   and requires PC recovery (qFlipper).

The vendored proto exposes this over RPC: `SystemUpdateRequest{update_manifest}`
→ `SystemUpdateResponse{UpdateResultCode}` (10 codes incl. `TargetMismatch`,
`ManifestInvalid`, `IntFull`), then `SystemRebootRequest{mode=UPDATE}`. We use
the RPC path (not the CLI `update install` path) because the server is
RPC-native.

### Upstream bundle sources (verified)

- **Official:** `https://update.flipperzero.one/firmware/directory.json` —
  top-level `channels` (`release`, `release-candidate`, `development`), each with
  `versions[]`; each version has `files[]` carrying `url`, `target` (`f7`,
  `f18`, `any`), `type` (we want `update_tgz`), and **`sha256`**. Current release
  at design time: `1.4.3`.
- **Momentum:** GitHub releases on `Next-Flip/Momentum-Firmware`. Each asset
  carries a `digest: "sha256:…"` field; the bundle asset is
  `flipper-z-<target>-update-<tag>.tgz` (e.g. `flipper-z-f7-update-mntm-012.tgz`).

Both sources publish a verifiable sha256, so integrity verification is mandatory
(not best-effort) and aborts the download on mismatch.

## Architecture

### Prerequisite: chunked `storage_write` (fixes a latent bug)

`storage_write` currently sends the entire payload in a single `WriteRequest`
(`has_next=False`, fixed 3 s timeout). The Flipper streaming protocol requires
`has_next`-chained frames for payloads beyond a couple KB, so the existing
single-shot write — and therefore the `flipperzero_fs_push` tool — silently
fails on large files. Firmware bundles contain multi-MB `.dfu`/radio/resource
files, so this must be fixed first.

The transport already has every primitive needed:

- `transport.send(_encode_varint(len)+payload)` sends one frame without awaiting
  a response (already used by `send_stop_session`).
- `_receive_main_message(timeout)` reads exactly one response frame.
- The receive side already reassembles `has_next` streams
  (`storage_read`/`device_info`/`storage_list`).

**Change:** fold chunking into `storage_write` (replace, don't deprecate) — same
`storage_write(path, content) -> bool` signature, so the sole caller
(`flipperzero_fs_push`) is unaffected. Internally:

- Small payload → existing single-frame path.
- Large payload → loop over slices (chunk size ~1 KB, validated on hardware):
  for each slice send
  `Main(command_id=cid, has_next=(not last), storage_write_request=WriteRequest{path, file=File{data=slice}})`
  via the raw send primitive; only the final frame awaits one response. Constant
  `command_id` across frames; all under `_io_lock`. Timeout becomes size-aware
  (per-chunk budget) instead of a fixed 3 s.

This slice has independent value (it repairs `fs_push`) and may merge as its own
PR ahead of the rest.

### New package `src/flipperzero_mcp/firmware/`

**`flavor.py`** — pure classifier, no hardware/network.
`classify(device_info: dict) -> FirmwareInfo` where
`FirmwareInfo = {flavor, version, origin_fork, origin_git, target}` and
`flavor ∈ {OFFICIAL, MOMENTUM, UNLEASHED, ROGUEMASTER, UNKNOWN}`. Primary signal
is `firmware_origin_git` (the Momentum fixture reports the Next-Flip URL),
fallback `firmware_origin_fork` then branch-name heuristics. `target` derives
from `hardware_target` (`7` → `f7`, `18` → `f18`). Channel is **not** inferred
from `device_info` — it is only meaningful as a download-selection input.

**`bundles.py`** — bundle acquisition. `resolve_bundle(source) -> LocalBundle`
where `source` is either a local `.tgz` path **or**
`{flavor, channel, version, target}`. For auto-download:

- Official → fetch `directory.json`, select channel → version (default latest) →
  the `target`/`update_tgz` file, download, **verify the published sha256**.
- Momentum → query the GitHub releases API (tag = version, default latest),
  select the `flipper-z-<target>-update-*.tgz` asset, download, **verify the
  asset `digest` sha256**.

Then extract the tgz to a temp dir and locate `update.fuf`. Download aborts on
sha256 mismatch or missing target.

**`installer.py`** — orchestrates the flash, building on chunked `storage_write`
plus `storage_mkdir`/`storage_md5sum`:

1. Read `device_info` → classify; guard bundle `target` == device `target`
   (belt-and-suspenders; the device also returns `TargetMismatch`).
2. `mkdir /ext/update/<pkg>/`; recursively push every bundle file, verifying
   each with md5sum.
3. `system_update(manifest=/ext/update/<pkg>/update.fuf)` → map all 10
   `UpdateResultCode` values to clear errors; abort on any non-`OK`.
4. `system_reboot(mode=UPDATE)`.
5. Tolerant reconnect poll (~5 min budget, multiple disconnect/reconnect cycles
   expected as FUS restarts). Re-read `device_info`; confirm new flavor/version.
   Return a before/after summary.

### New RPCs in `protobuf_rpc.py`

- `system_update(manifest_path: str) -> UpdateResultCode` (request tag 41,
  response tag 46).
- `system_reboot(mode: RebootMode)` — fire-and-forget; no response after an
  UPDATE reboot (request tag 31).

### New tool `flipperzero_firmware_install`

Annotations `readOnlyHint=False, idempotentHint=False, destructiveHint=True,
openWorldHint=True`.

Args:
- `source` — either `{path: "..."}` or
  `{flavor: "official"|"momentum", channel?: "release"|"release-candidate"|"development", version?: "latest"|"<ver>"}`.
- `confirm` — required token; the call is rejected unless it matches the
  connected device name (read from `device_info`).

Gating (all three required):
1. `enable_write_tools` (existing flag), and
2. `enable_firmware_flash` (new flag, env `FLIPPER_ENABLE_FIRMWARE_FLASH`,
   default-off), and
3. the `confirm` token check.

Returns before/after `FirmwareInfo`, the bundle used (source + sha256), push
verification, and reboot/reconnect result.

### Firmware-awareness (additive, read-only)

- `flipperzero_system_info` gains a `firmware` block from the classifier
  (`flavor`, `version`, `origin_fork`, `origin_git`, `target`).
- `/flipper-install` prompt: SDK selection branches on flavor — official →
  `ufbt update --channel=<release|rc|dev>`; Momentum → its own SDK index — while
  keeping the existing "STOP and report on unsupported firmware" guard. (ufbt
  self-detects the connected device firmware, so the prompt does not infer
  channel from `device_info`.)
- `/flipper-doctor` prompt: report firmware flavor + version.

### Config

Add `enable_firmware_flash: bool = False` (env `FLIPPER_ENABLE_FIRMWARE_FLASH`)
to `config.py`.

## Error handling

- Bundle sha256 mismatch → abort download with the expected/actual hashes.
- Target mismatch (pre-flight or device `TargetMismatch`) → abort with device vs
  bundle target.
- Any non-`OK` `UpdateResultCode` → mapped, actionable error naming the code.
- Reconnect timeout after reboot → error stating the device may still be
  applying the update or may have dropped to DFU, pointing at qFlipper recovery.
- All flash errors return MCP error objects, never raw exceptions; secrets/paths
  are never logged.

## Testing

- **Classifier** — table-driven units over `device_info` samples: official
  (each channel), Momentum, Unleashed, RogueMaster, unknown, and missing
  `firmware_origin_git`/`firmware_origin_fork`.
- **Chunked write** — fake-transport unit asserting the N-frame `has_next`
  pattern, constant `command_id`, single final response, and the small-payload
  single-frame path.
- **Bundle resolver** — VCR cassettes for `directory.json` and the GitHub
  releases response; assert channel/version/target selection and a
  **sha256-mismatch abort** path.
- **Installer** — fake RPC/transport asserting the
  `mkdir → recursive push → md5 → update → reboot` sequence and each failure
  branch (target mismatch, non-`OK` update code, reconnect timeout).
- **Golden fixtures** — capture an official-firmware `device_info` + key CLI
  fixtures after flashing; parametrize the golden suite over `{momentum,
  official}`.
- **Integration** (`integration`+`usb`, local-only, flag-gated) — real flash
  round-trip on the test device: official ↔ Momentum, asserting before/after
  flavor. This is the destructive validation.

## Phasing (tracer-bullet vertical slices)

1. **Chunked `storage_write`** — fix + fake-transport test. Ships standalone;
   repairs `fs_push` large-file writes.
2. **Classifier + `system_info` firmware block** — no hardware/network.
3. **`system_update`/`system_reboot` RPCs + installer** against a fake
   transport + units.
4. **Bundle acquisition** — local path first, then auto-download + sha256 +
   cassettes.
5. **`flipperzero_firmware_install` tool + `enable_firmware_flash` flag +
   confirm token.**
6. **Real-hardware validation** — flash the test device official ↔ Momentum,
   confirm chunk size, capture dual golden fixtures, parametrize golden tests,
   add the integration test.
7. **Prompts + docs** — `/flipper-install` ufbt channels, `/flipper-doctor`,
   README (both firmwares, the flash tool, both flags, supply-chain posture,
   DFU recovery), CLAUDE.md (firmware module, flash flag, dual fixtures), CLI
   reference (Momentum-only commands).

## Acceptance

Given a USB-connected Flipper, the server reports its firmware flavor/version;
with both flags set and the confirm token supplied, `flipperzero_firmware_install`
flashes a chosen official or Momentum bundle (auto-downloaded with verified
sha256, or from a local `.tgz`) and confirms the post-flash firmware; the golden
suite passes against both Momentum and official fixtures; and the README states
the supported firmwares, the flash flow, and DFU recovery honestly.
