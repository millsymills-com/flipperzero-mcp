# flipperzero-mcp — Shortcut Roadmap Representation

**Date:** 2026-06-01
**Status:** Approved structure; execution pending Shortcut API token
**Purpose:** Mirror flipperzero-mcp's shipped + planned versions into Shortcut
using the `shortcut-mcp` server, as a roadmap layer *above* the GitHub issues.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Version → Shortcut model | **Objective per version**; Epics = workstreams; Stories = tasks |
| Granularity | **Full breakdown** (Objectives + Epics + Stories) |
| GitHub overlap | **Roadmap above issues** — Stories link out to GitHub issues; the consistency-audit issues (#21–36) are *not* recreated |

## Source material

- `docs/superpowers/specs/2026-05-29-flipper-mcp-roadmap-design.md` (v1→v3)
- `docs/superpowers/specs/2026-06-01-public-launch-readiness-design.md` (launch)
- `CHANGELOG.md` (v0.1.0 shipped surface)

## Structure to create

### Objective 1 — `flipperzero-mcp v0.1.0 — Phase 1`  *(state: done)*

**Epic: Connection & systeminfo foundation** *(done; story_type chore/feature)*
- USB transport + WiFi transport + `auto` selector
- Protobuf RPC framing (nanopb-delimited) + vendored bindings
- ESP32 TCP↔UART bridge firmware (`firmware/tcp_uart_bridge/`)
- `FLIPPER_*` config + stderr JSON logging
- Tools shipped: `flipper_connection_health`, `flipper_connection_reconnect`, `systeminfo_get`

### Objective 2 — `flipperzero-mcp — Public Launch (v1 + storage slice)`  *(state: in progress)*

Six Epics, dependency order from launch-readiness §3 (1 → (2∥3) → 5 → 4 → 6):

1. **Epic: Dual-mode link manager + shared `_io_lock`** *(foundation)*
   - `enter_cli()` sends `StopSession` + drains to `>:` prompt
   - `enter_rpc()` sends `start_rpc_session`; `mode()` query
   - single client `_io_lock` acquired by **both** CLI and RPC round-trips
   - unit test: RPC ping blocks while CLI round-trip holds the lock
   - WiFi `supports_cli_text_mode` capability property
2. **Epic: `flipper_cli_exec` + risk classifier + TX two-gate**
   - `flipper_cli_exec(command, timeout_s=10.0, i_accept_responsibility=False)` — USB-only, one command/call, typed result (`output`/`completed`/`risk`/`warning`)
   - prefix-list risk classifier (`subghz tx*`, `*write`, `ir tx*`, `factory reset`, `storage format`, `power off/reboot`, `update install`)
   - `FLIPPER_ENABLE_TX_TOOLS` env gate (default off) — the real boundary
   - per-call `i_accept_responsibility` intent signal
   - WiFi rejection error; streaming-unsupported documentation
3. **Epic: Storage RPC slice**
   - `flipper_fs_push`, `flipper_fs_pull`, `flipper_fs_list`, `flipper_fs_mkdir`
   - recursive directory support
   - `Md5sumRequest` integrity verify (native RPC, no per-file mode switch)
4. **Epic: Knowledge & Claude Code surface**
   - resources `flipper://reference/{cli,connection,filesystem}`
   - resources `flipper://workflow/{install-app,transfer-files}`
   - prompts `manage_flipper`, `troubleshoot_connection`
   - slash commands `/flipper-install <github_url>`, `/flipper-doctor`
   - flagship install pipeline (clone→build→push→verify→launch)
   - rename `systeminfo_get` → `flipper_system_info` (links GH #27)
5. **Epic: Golden-fixture test harness**
   - capture real CLI/RPC output; replay in CI
   - covers cli_exec parsing, fs_push integrity, both-direction mode switch, shared-lock contention, two-gate TX, WiFi-CLI rejection
6. **Epic: Launch hygiene & gates**
   - Story: close audit MUSTs — links GH #22, #21, #23, #24, #27, #28, #30, #34
   - Story: triage SHOULD-tier audit issues — links GH #25, #26, #29, #31, #32, #33
   - README rewrite (honest scope/limits + tools table)
   - firmware-baseline statement
   - hardware-proof capture (asciinema/video/screenshots)
   - issue/PR templates + CONTRIBUTING accuracy + fresh-clone install verification

### Objective 3 — `flipperzero-mcp v2 — Typed workflow tools`  *(state: planned)*

- **Epic: App install / build (ufbt)** — `flipper_app_list`, `flipper_app_install`, `flipper_app_build`, catalog browse, ufbt SDK-channel match + fail-loud, absorb `build_faps.py`
- **Epic: File-transfer ergonomics** — recursive/catalog features beyond the launch storage slice

### Objective 4 — `flipperzero-mcp v3 — Higher-risk integrations`  *(state: planned)*

- **Epic: ESP32 dev-board flashing** — `esp32_detect`, `esp32_flash` (download→SHA-256 verify→esptool→confirm), port-contention guard, Marauder + bridge-firmware targets
- **Epic: Radio capture / replay** — streaming execution model (bounded timeout, partial results, cancellation/interrupt), typed `subghz`/`nfc`/`rfid`/`ikey`/`ir` read/save/emulate/replay, per-TX confirmation + region/legality notice

## Execution procedure (run after MCP connected with readwrite token)

1. `shortcut_get_current_member` — confirm auth + identity.
2. `shortcut_list_groups` — pick the Team that owns the Stories.
3. `shortcut_list_workflows` — get default + workflow_state_ids (unstarted/started/done).
4. Create Objectives 1–4 (`shortcut_create_objective`), set states.
5. Per Objective, create Epics (`shortcut_create_epic`, `objective_id` set), set Epic state.
6. Per Epic, create Stories (`shortcut_bulk_create_stories`, `epic_id` + `group_id` + `workflow_state_id`), embedding GitHub issue links in descriptions where noted.
7. Report created IDs + app.shortcut.com URLs.

## Connection setup

- Server: `shortcut-mcp` (this workspace), run from its directory so `.env` loads.
- Required env: `SHORTCUT_API_TOKEN` (secret, from user), `SHORTCUT_MODE=readwrite`,
  `SHORTCUT_TOOLS=objective,epic,story,group,workflow,member,label,search`.
- `SHORTCUT_ALLOW_DESTRUCTIVE` stays unset/false — no deletes needed.
