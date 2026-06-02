# Flipper Zero MCP — Public Launch Readiness Design

**Date:** 2026-06-01
**Status:** Approved (brainstorming)
**Repo:** `flipperzero-mcp`
**Relates to:** `docs/superpowers/specs/2026-05-29-flipper-mcp-roadmap-design.md` (v1→v3 roadmap)

## Purpose

Define what "ready for public launch" means for `flipperzero-mcp` — the bar that
must be true before posting publicly and inviting heavy scrutiny. The driving
fears: (a) claims outrun reality, (b) it breaks on someone else's
firmware/hardware, (c) a reviewer finds core behavior untested.

The public pitch is: **parity with Flipper CLI functionality, optimized for
Claude Code, with runbooks for common action chains** — flagship being
"install this on my flipper: `$github_link`".

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Launch feature bar | **v1** (`flipper_cli_exec` + CLI reference resources + workflow runbooks) — the smallest bar that honestly backs the "CLI parity" claim |
| Flagship file-push | **Pull the storage-RPC slice forward** (`fs_push`/`fs_pull`/`fs_list`/`fs_mkdir`) — binary push over text CLI is too fragile for the headline demo |
| Claude Code delivery | **MCP resources + prompts** (portable) **plus slash commands** (`/flipper-install`, `/flipper-doctor`). No standalone skill or CLAUDE.md snippet. |
| Anti-embarrassment gates | **All four**: golden-fixture tests, hardware proof artifacts, firmware-baseline statement, honest scope/limitations |
| Distribution | **git-clone + `uv`** only at launch (no PyPI yet) — so the fresh-clone install path must be airtight |

## Section 1 — Launch scope (what ships)

Build target = **"v1 + storage slice"**.

### New surface

- **Dual-mode link manager** (real engineering, not a rename):
  - `enter_cli()` sends `StopSession` (`flipper.proto` field 19) and drains to
    the `>:` prompt; `enter_rpc()` sends `start_rpc_session`; `mode()` query.
  - A single shared `_io_lock` on the client that **both** CLI and RPC
    round-trips acquire, eliminating frame interleaving (the per-call lock in
    `usb.py` is insufficient). Lower-level helpers must not re-acquire it
    (asyncio locks are not reentrant).
- **`flipper_cli_exec(command, timeout_s=10.0, i_accept_responsibility=False)`**
  — USB-only; one command per call; no shell chaining; typed result
  (`output`, `completed`, `risk`, `warning`). WiFi transport returns a clear
  "CLI text mode unavailable over WiFi bridge" error via an explicit
  `supports_cli_text_mode` capability property. Streaming/interactive commands
  unsupported (documented).
- **Storage-RPC slice:** `flipper_fs_push`, `flipper_fs_pull`, `flipper_fs_list`,
  `flipper_fs_mkdir`, with `Md5sumRequest` (`storage.proto`) integrity
  verification — native RPC, no per-file mode switch.
- **Rename** `systeminfo_get` → `flipper_system_info` (PROTO-002 namespace fix,
  issue #27). New tools all use the `flipper_*` prefix.

### Knowledge + Claude Code surface

- **Resources** (bundled markdown, `@mcp.resource`):
  `flipper://reference/{cli,connection,filesystem}`,
  `flipper://workflow/{install-app,transfer-files}`.
- **Prompts:** `manage_flipper`, `troubleshoot_connection`.
- **Slash commands:** `/flipper-install <github_url>`, `/flipper-doctor` —
  thin executable wrappers over the same runbooks.

### Flagship pipeline: `/flipper-install <github_url>`

1. Clone/fetch repo to a temp dir (host Bash).
2. Detect ufbt FAP project → read connected Flipper's firmware channel/version →
   select matching ufbt SDK → build. **Fail loud** on channel mismatch or
   custom/unofficial firmware; never silently produce an incompatible `.fap`.
3. `flipper_fs_mkdir` + `flipper_fs_push` the `.fap` → `/ext/apps/<category>/`.
4. `Md5sumRequest` verify.
5. `loader open` via `flipper_cli_exec`.
6. Structured report (built version, install path, launch result).

### Explicitly NOT in launch

Typed radio/NFC/IR/SubGHz/RFID tools; ESP32 flashing; streaming capture;
WiFi-CLI; PyPI publishing; full `build_faps.py` catalog absorption. These remain
roadmap v2/v3.

## Section 2 — Launch gates (all must be TRUE before posting)

| Gate | Definition of done |
|---|---|
| **A. Feature complete** | Scope in §1 implemented; unit tests green; `uv run pytest -m "not integration"` clean; lint + type checks clean. |
| **B. Golden-fixture harness** | Real CLI/RPC output captured once, replayed in CI (mirrors the workspace VCR-cassette discipline). Covers `cli_exec` parsing, `fs_push` integrity, mode-switch in both directions, shared-lock contention, the two-gate TX path, and WiFi-CLI rejection. |
| **C. Hardware proof** | asciinema/video/screenshots of the real `github→build→install` run on hardware, linked from README. |
| **D. Firmware baseline** | CLI reference pinned to a stated firmware version; README states "tested on firmware X.Y" + drift caveat; re-validate on firmware bumps (mirrors the protobuf-version pinning discipline in CLAUDE.md). |
| **E. Honest scope/limits** | README states USB-only CLI, WiFi-CLI gap, streaming unsupported, and TX legal posture — zero phantom features. Tools table updated (currently lists only the 3 Phase-1 tools). |
| **F. Audit MUSTs closed** | Issues #23 (MCP-006), #24 (MCP-007), #27 (PROTO-002), #28 (PROTO-004), #30 (PROTO-006), #34 (PY-015), umbrella #22, and #21 (non-portable CLAUDE.md path). SHOULDs (#25, #26, #29, #31, #32, #33) triaged: fix-or-defer, each with a recorded decision. |
| **G. Safety/legal** | TX two-gate wired into `cli_exec`: `FLIPPER_ENABLE_TX_TOOLS` env flag (default off) **and** per-call `i_accept_responsibility` — both required for gated commands. Risk classifier covers `subghz tx*`, `*write` (rfid/ikey), `ir tx*`, `factory reset`, `storage format`, `power off/reboot`, `update install`; it is an advisory ordered-prefix list that fails open, so the env flag is the real boundary. Region/legality notice in the TX runbook. SECURITY.md private-disclosure path verified. |
| **H. Contributor hygiene** | Issue + PR templates; CONTRIBUTING accuracy; README install path verified clean from a fresh clone. |

## Section 3 — Sequencing & decomposition

This is too large for one implementation plan; it decomposes into sub-projects,
each with its own spec → plan → build cycle:

1. **Transport: dual-mode link manager + shared `_io_lock`** — foundation; blocks
   everything else.
2. **`flipper_cli_exec` + risk classifier + TX two-gate** — depends on 1.
3. **Storage slice `fs_*` + `Md5sumRequest` verify** — depends on 1.
4. **Knowledge surface: resources + prompts + slash commands** — depends on 2, 3
   for accurate runbooks.
5. **Golden-fixture test harness** — cross-cuts 2–3; built alongside, not after.
6. **Launch hygiene pass** — audit MUSTs, README rewrite, firmware-baseline
   statement, hardware-proof capture, issue/PR templates.

**Recommended order:** 1 → (2 ∥ 3) → 5 → 4 → 6. The flagship runbook (#4) cannot
be written honestly until 2 + 3 exist and 5 proves they work.

## Success criteria

Given only a fresh clone, the README, and a USB-connected Flipper on the stated
firmware baseline, a user can say "install this on my flipper: `$github_link`"
and Claude Code completes the clone → build → push → verify → launch pipeline —
and every claim in the README is backed by a passing test or a linked proof
artifact.

## Open questions

1. **Region default** for SubGHz legality notices (US vs EU) — needed when the
   TX runbook ships; pick one and document it.
2. **SHOULD-tier audit issues** — confirm the fix-or-defer split during the
   hygiene pass (gate F).
