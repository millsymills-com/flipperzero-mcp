# Flipper Zero MCP — Roadmap Design (v1 → v3)

**Date:** 2026-05-29
**Status:** Draft for review (hardened after adversarial Codex review)
**Repo:** `flipperzero-mcp` (the product). References the sibling workspace repo
`flipper-projects` (the user's Flipper working tree) where noted.

## Context

Phase 1 of `flipperzero-mcp` is shipped: a FastMCP stdio server with USB and WiFi
protobuf-RPC transports and three tools (`flipper_connection_health`,
`flipper_connection_reconnect`, `systeminfo_get`). Vendored protobuf bindings
cover **system, gui, desktop, application, storage, property, gpio**.

The user manages a Flipper today with ad-hoc tooling that lives inside
`flipper-projects/.venv/` — a throwaway directory rebuilt with the venv:
`flipctl.py` (raw-serial CLI helper reading to the `>:` prompt), `build_faps.py`
(ufbt FAP builds), and `push_*.log` / `faillogs/` artifacts. FAPs are built with
`ufbt`, the ESP32 Marauder board is flashed with `esptool`, and qFlipper handles
firmware. The goal: make managing, provisioning, and customizing the Flipper
easy from Claude Code via the MCP.

### The driving constraint

The Flipper exposes two modes over the same USB CDC serial link:

- a **CLI text shell** (prompt `>:`) — the **only** way to reach `subghz`,
  `nfc`, `ir`, `rfid`, `ikey`, `led`, `vibro`, `buzzer`, `loader`, etc.
- a **protobuf RPC session** (started by sending the CLI command
  `start_rpc_session`) — typed messages for system / storage / app-loader / gpio.

**There is no generic "run arbitrary CLI" message in the RPC protocol.** The
radio subsystems have no native RPC messages and are unreachable over RPC. (A
narrow exception exists: a custom FAP can expose its own RPC via
`App.DataExchangeRequest`, but that requires shipping a FAP and is out of scope.)
This is why the roadmap adds a CLI text channel rather than extending protobuf.

### Current transport reality (verified against the codebase)

These facts shape v1 and were confirmed by reading the source:

- `protobuf_rpc.py` implements **only the CLI→RPC switch** (`_ensure_rpc_session_started`
  sends `start_rpc_session`). The reverse — RPC→CLI — is **not implemented**.
  Returning to CLI text mode requires sending the `StopSession` message
  (`flipper.proto:58`, field 19 of `Main`) and then draining to the `>:` prompt.
- The **WiFi transport has no CLI mode at all** (`protobuf_rpc.py:231-256`): the
  TCP↔UART bridge speaks nanopb-delimited protobuf only, and sending
  `start_rpc_session` bytes over it would corrupt the session. CLI text commands
  cannot be issued over the WiFi transport as it stands.
- `USBTransport`'s `asyncio.Lock` (`usb.py:143,150`) guards **individual**
  `send`/`receive` calls, not a compound mode-switch round-trip.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| v1 knowledge delivery | MCP **resources + prompts** (server-exposed, portable) |
| v1 action surface | **One generic CLI exec tool** (full power, documented guardrails) — see Safety for one Codex-driven amendment awaiting confirmation |
| v2+ priorities | All four: file transfer, app install/build, ESP32 flashing, radio capture/replay |
| Existing tooling | **Supersede + rescue logic** — fold `flipctl.py` / `build_faps.py` into the MCP |
| Foundation | Approach A: dual-mode link + bundled-markdown resources |

## Guiding architecture (all versions)

Three layers, stable across the roadmap:

1. **Transport** (`transport/`) — owns the USB/WiFi link and a **link-mode
   manager** that arbitrates CLI-text mode vs RPC-session mode. Single source of
   truth for current mode.
2. **Access primitives** — the existing typed **RPC client** (`rpc/`) and a new
   **CLI channel** (`cli/`) carrying the prompt-draining read loop rescued from
   `flipctl.py`.
3. **Surface** — **tools** (actions), **resources** (knowledge), **prompts**
   (workflow entry points). Later versions add to the surface without reshaping
   the layers below.

**Principle:** every *prompt-returning* subsystem command is reachable by v1's
generic exec tool first; v2+ adds typed ergonomics and safety on top of paths
that already work. Streaming commands are the explicit exception (see v1
limitations).

### Rejected alternatives

- **RPC-only** — infeasible; radio subsystems are not in the protobuf surface.
- **Shell out to host CLI tools** (`clipper.py`, `pyserial-miniterm`) — brittle
  subprocess glue, breaks the WiFi-bridge path, contradicts the supersede choice.

## v1 — Documentation-forward, one action tool

**Goal:** Claude can do anything the Flipper CLI can *that returns to a prompt*,
guided by bundled knowledge, through one generic action tool — over USB.

### New surface

- **Tool `flipper_cli_exec(command: str, timeout_s: float = 10.0)`** — sends one
  CLI line over the **USB** link in CLI-text mode; returns stripped output (echo
  and trailing `>:` removed). One command per call; no shell chaining.
  - **USB-only in v1.** When the active transport is WiFi, the tool returns a
    clear error: CLI text mode is unavailable over the WiFi bridge (see
    Limitations). Adding WiFi CLI support is deferred (requires bridge/firmware
    work).
  - **Streaming commands are unsupported in v1** (see Limitations).
  - **Safety gating** — see the Safety section; radio-TX commands are *not*
    freely executable in v1 under the amended posture.
- **Resources** (bundled markdown under `src/flipperzero_mcp/resources/`, served
  via `@mcp.resource`):
  - `flipper://reference/cli` — complete CLI command reference (every subsystem,
    args, examples, region/legal notes). **Versioned to a firmware baseline**
    (see Risks).
  - `flipper://reference/connection` — ports; the USB-CDC baud nuance (CDC ACM
    ignores baud — the `FLIPPER_USB_BAUDRATE=115200` config value is not honored
    by the device; 230400 is only relevant to a hardware-UART path, to be
    verified against `firmware/tcp_uart_bridge/`); CLI↔RPC mode switching incl.
    `StopSession`; which transports support which mode.
  - `flipper://reference/filesystem` — `/int` vs `/ext`, path conventions,
    app/data layout.
  - `flipper://workflow/install-app`, `.../transfer-files`, `.../flash-esp32`,
    `.../capture-replay` — recipe docs that double as the v2/v3 typed-tool specs.
- **Prompts** — `manage_flipper` (orient Claude: discover connection, read
  reference, plan) and `troubleshoot_connection`.

### Transport work

Implement the link-mode manager + CLI channel:

- **Add the missing RPC→CLI direction.** `enter_cli()` must send `StopSession`
  (`flipper.proto` field 19) and drain to the `>:` prompt before any text
  command. The current code only does CLI→RPC; this asymmetry is real work, not a
  rename.
- Provide idempotent `enter_cli()` / `enter_rpc()` and a `mode()` query.
- Drain the boot/banner output to a clean prompt before the first command (rescue
  `flipctl.py`'s drain loop).
- **Widen the lock to span whole CLI round-trips.** The per-call `asyncio.Lock`
  in `usb.py` does not prevent a concurrent `flipper_connection_health` RPC ping
  from interleaving bytes mid-drain. Mode transitions and CLI command round-trips
  must hold an exclusive lock end-to-end.

This supersedes `flipctl.py`'s serial logic for prompt-returning commands.

### v1 limitations (explicit)

- **Streaming/interactive commands** (`subghz rx`, `ir rx`, `log`, `input dump`,
  `subghz chat`) never emit `>:` until interrupted (Ctrl+C). The single-call
  read-until-prompt model can only time out and return a truncated buffer,
  leaving the device mid-stream. v1 does **not** support these; the capture
  workflow doc describes the limitation. A cancellation-aware streaming execution
  model is designed in v3 (radio capture), not bolted onto `flipper_cli_exec`.
- **WiFi + CLI** is unsupported (see above).

### Out of v1

Typed per-subsystem tools; ufbt/esptool orchestration; streaming capture; WiFi
CLI; unrestricted radio TX.

## v2 — Typed tools for high-frequency, low-risk workflows

Ordered by dependency and risk (lowest first). Each typed tool's behavioural
spec is the `flipper://workflow/*` doc written in v1.

- **File transfer** (first — storage RPC already vendored, lowest risk):
  `flipper_fs_push`, `flipper_fs_pull`, `flipper_fs_list`, `flipper_fs_mkdir`,
  recursive directory support. **Integrity verification uses the RPC
  `Md5sumRequest`** (`storage.proto:75`) — a native RPC op — not a CLI `storage
  md5`, so no mode switch is needed per file. Backbone for IR DBs, SubGHz
  captures, NFC/RFID dumps, Amiibo, assets.
- **App install / build**: `flipper_app_list`, `flipper_app_install` (push
  `.fap` → `/ext/apps`), `flipper_app_build` (host-side **ufbt** orchestration),
  catalog browse across the user's `external/` clones. Absorbs `build_faps.py`.
  **ufbt SDK-channel handling must be explicit:** before building, read the
  connected Flipper's firmware channel/version and select the matching ufbt SDK;
  fail loudly (not silently produce an incompatible `.fap`) when the channel
  mismatches or the firmware is custom/unofficial; document whether `ufbt` is
  expected on `PATH` or invoked from a pinned location.

## v3 — Higher-surface / higher-risk integrations

- **ESP32 dev-board flashing** (`firmware/`): `esp32_detect`, `esp32_flash`
  (download release → verify SHA-256 → `esptool` flash → confirm), targeting
  Marauder and the WiFi-bridge firmware. **Port-contention guard required:** the
  WiFi-bridge ESP32 may be the very board being flashed. `esp32_flash` must
  assert the Flipper link is USB (not the WiFi transport) — or tear the WiFi
  transport down first — and verify the target ESP32 port is not the device
  currently serving the bridge. Rescues the Marauder flow.
- **Radio capture / replay** (last — highest legal/safety surface): typed
  `subghz` / `nfc` / `rfid` / `ikey` / `ir` read/save/emulate/replay tools. These
  introduce the **streaming execution model** v1 lacks: bounded `timeout_s` with
  explicit partial-result semantics, cancellation (sending the interrupt), and
  streamed result accumulation. Each TX path carries a structured pre-TX
  confirmation + region/legality notice.

## Cross-cutting concerns

### Safety posture (one amendment from the Codex review — needs confirmation)

The locked decision was a single full-power exec tool. Codex flagged that an
agent able to run `subghz tx` / `subghz tx from file` with only a warning string
can transmit on arbitrary frequencies — an FCC Part 15 / CE RED violation with
personal liability, and not an adequate control for an autonomous agent.

**Amended default in this spec:** v1 `flipper_cli_exec` **refuses radio-TX
commands** (`subghz tx*`, `rfid write`, `ikey write`, `ir tx*`, plus
`factory reset` and `storage format`) unless an explicit
`i_accept_responsibility=True` argument is passed in the same call. Read/scan/RX
and all benign commands run freely. This keeps the "one tool, full reach"
shape while putting a deliberate gate in front of physically-transmitting,
destructive, or regulated actions. Non-TX destructive commands still surface the
warning string.

> This narrows the original "full power, warn-and-proceed" decision. **Confirm or
> override before implementation.** If you prefer the unrestricted original, the
> gate becomes a warning-only string and this paragraph is removed.

v3 graduates the gate into per-tool structured confirmations with region notices.

### Tooling consolidation (the "supersede" choice)

- v1 folds `flipctl.py`'s serial logic into the CLI channel **for
  prompt-returning commands**. `flipctl.py` remains useful for multi-command
  batches and any streaming use until v2/v3 close the gap — it is not "disposable"
  the moment v1 ships.
- v2 absorbs `build_faps.py` into app-build; `push_*.log` / `faillogs/` become
  structured tool output.
- **Cross-repo caveat:** those scripts live in `flipper-projects`, a separate
  repo. This MCP cannot delete across repos, so the deliverable there is a short
  migration note in `flipper-projects` pointing at the MCP tools. Nothing is
  silently lost.

### Testing

- Unit tests mock the link: CLI drain loop, **`StopSession` round-trip and mode
  switching in both directions**, exclusive-lock coverage across a round-trip,
  resource registration, radio-TX/destructive gating, WiFi-CLI rejection.
- `integration` / `usb` / `wifi`-marked tests hit a real Flipper (existing
  convention). CI stays `uv run pytest -m "not integration"`.
- Resource content-lint test: every documented command parses; no dead workflow
  links; every `flipper://` URI resolves.

### Risks

- **CLI firmware churn.** The Flipper CLI surface (command names, args, output
  format) changes across firmware releases. `flipper://reference/cli` and any
  output parsing are brittle across versions. Mitigation: pin the reference to a
  stated firmware baseline and re-validate on firmware bumps — mirroring the
  existing protobuf-version pinning discipline in `CLAUDE.md`.
- **Mode-switch corruption.** Interleaving RPC frames and CLI text corrupts both;
  mitigated by the exclusive round-trip lock and explicit mode manager.

### Success criteria

- **v1:** given only the resources + `flipper_cli_exec`, Claude can install an
  app, transfer a file, and read device state on a **USB-connected** Flipper
  without host scripts.
- **v2 / v3:** the same outcomes via typed tools with verification and gating;
  v3 additionally supports streaming capture and gated replay/TX.

## Open questions (blocking)

1. **Radio-TX safety gate** — confirm the amended `i_accept_responsibility`
   posture above, or revert to warning-only full power.
2. **WiFi CLI** — accept USB-only CLI for v1 (recommended), or pull WiFi-bridge
   CLI support forward (firmware work)?
3. **Region default** for SubGHz legality notices (US vs EU) — needed by v3, not
   v1.
