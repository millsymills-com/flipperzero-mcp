# Plan: Raise typed-tool coverage of the Flipper CLI+RPC surface

**Date:** 2026-06-23
**Status:** Accepted target = ~80.5% buildable ceiling (Option b). Built by an
ultracode workflow, hardened against three adversarial review passes (honesty,
feasibility, safety), and revalidated against the codebase on 2026-06-23 (see
Appendix — revalidation).
**Repo:** `flipperzero-mcp`
**Denominator decision (from requester):** full CLI+RPC surface; the generic
`flipperzero_cli_exec` counts as a generic escape hatch, *not* as covering any
specific subsystem.

> **Headline up front (read this before the target):** the accepted target is the
> **66/82 ≈ 80.5% of the full surface, USB-attached** buildable ceiling (Option b,
> §4 tail). A literal **≥90%** was rejected: it is reachable only by splitting good
> bundled tools (`subghz rx` vs `rx raw` vs `decode raw`, `power 5v` vs `power 3v3`
> vs `gpio set`, …) into per-subcommand tools purely to raise the count, which this
> plan judges metric-gaming. Coverage over **WiFi** stays near the RPC-only baseline
> because every CLI-text tool is USB-only (TP-2).

---

## 1. Honest framing of the denominator and current %

The coverage analysis sets the denominator at **82** distinct CLI+RPC surface items.
That denominator already:

- excludes synthetic-input / streaming-only protobuf surfaces — GUI input injection
  (`SendInputEvent`), virtual-display push, app button-press injection, and the
  screen / desktop-status streams (continuous device→host, never a single typed
  return);
- dedups dual-reachable surfaces (e.g. `storage extract` == `Storage.TarExtractRequest`,
  `gpio set`/`power 5v` == `Gpio.*`), counted **once on the RPC side**.

**Current numerator = 17, i.e. 17/82 = 20.7%** (corrected from the workflow's first
pass, which double-counted a dedup against the numerator and reported 16/19.5%). The
derivation: **18 registered typed tools − `flipperzero_cli_exec`** (the generic
escape hatch, which adds 0). The surface-side dedup lives in the *denominator* (the 82)
and must not also be subtracted from the numerator.

Two honesty rules this plan holds itself to:

1. **Transport-qualified coverage.** Every CLI-text tool added below is **USB-only**
   (TP-2). All percentages here are *USB-attached* coverage. Over WiFi the device is
   reachable only through RPC, so WiFi coverage stays roughly at the RPC-only
   baseline (~P3-RPC level). Report coverage as a pair, never a single number.
2. **What counts as "covered".** A typed tool earns a numerator point only if it
   **parses/structures output or constrains arguments**. A one-line wrapper that
   forwards a fixed string and returns raw `output` is the escape hatch with a label
   and does **not** count. This disqualifies pure-passthrough candidates
   (`core_status`, `crypto_status`, `subghz_decode_file`, `ir_decode_file`) from
   numerator credit unless they add real structure.

The **accepted target** is the buildable ceiling of **66/82 ≈ 80.5%** (Option b,
§4) — i.e. **+49 new counting tools** from the 17 baseline, every non-excluded
single-return surface wrapped. Literal ≥90% (≥74 covered) was rejected as
bundle-splitting metric-gaming. The number is only meaningful with the exclusion list
intact — if anyone re-counts the GUI/stream surfaces into the denominator, it moves.

---

## 2. Roadmap tension (must reconcile)

`docs/superpowers/specs/2026-05-29-flipper-mcp-roadmap-design.md` phases this
differently on purpose:

- **v1** (shipped): docs + one generic `flipper_cli_exec`. Every prompt-returning
  subsystem is reachable by the exec tool *first*; typed ergonomics come later.
- **v2**: only *high-frequency, low-risk* typed tools — file transfer (done), app
  install/build.
- **v3** (last, "highest legal/safety surface"): typed radio
  `subghz`/`nfc`/`rfid`/`ikey`/`ir` read/save/emulate/replay, plus ESP32 flashing.
  v3 is where the **streaming execution model** is designed — explicitly *not* bolted
  onto `flipper_cli_exec`.

The "90% of the full surface" target collides with that phasing: ~40 of the needed
tools are exactly the v3 radio/streaming and CLI-text-mode subsystems the roadmap
defers. You cannot approach 80–90% without pulling v3's typed radio tools (and the
streaming model they require) forward.

**Reconciliation (recommended): stage this as a "v2.5" band** that pulls v3's *typed
radio* tools forward but keeps ESP32 flashing in v3.

1. Keep v2 as-is (file transfer landed; app install/build proceeds independently).
2. Insert **v2.5 = P0–P6 below**. P0–P3 are pure RPC/CLI read/write tools that need
   no new execution model — these belong in v2 anyway. P4–P6 require the streaming
   model and the TX safety posture the roadmap scoped for v3; pulling them forward is
   the real cost and must be labeled to stakeholders as "v3 radio-capture work, done
   early, under the v3 safety posture."
3. Leave ESP32 flashing (`esp32_detect`/`esp32_flash`) in v3 — out of the 82-item
   denominator, out of scope here.

If pulling v3 forward is rejected, the alternative is to **renegotiate the metric**:
declare the streaming/TX radio subsystems "v3-deferred" and compute coverage against a
v2.5 denominator that excludes them — which lands ≈ P3 (~52%) and never reaches the
target until v3. **Decision needed before P4 starts.**

---

## 3. Transport prerequisites that BLOCK whole tool families

Infrastructure, not tools. Each unblocks a family and must land before the dependent
batch.

**Sequence:** TP-1 (exists, reuse) → TP-2 (document) → TP-3 (before P2/P3-CLI) →
TP-4a (before P4) → TP-4b + TP-5 (before P5).

### TP-1 — Link-mode manager already in place (reuse, harden)
`FlipperClient` (`src/flipperzero_mcp/rpc/client.py`) already has `enter_rpc()` /
`enter_cli()` / `mode()` driving a `LinkMode` state machine, and a single
client-level `self._io_lock` (`asyncio.Lock`) shared into
`ProtobufRPC(..., io_lock=self._io_lock)`. Every RPC round-trip and the whole
`cli_exec` exchange already acquire it, so frames never interleave across a mode
switch. **No new lock needed.** Obligation: every new RPC tool routes through
`get_rpc(ctx)`; every new CLI-text tool goes through the TP-3 helper that holds
`_io_lock` across the full exchange. Unblocks all P0–P3 RPC items; prerequisite for
the CLI families.

### TP-2 — WiFi-CLI gap is permanent for this band (hard constraint)
`WiFiTransport.supports_cli_text_mode` is `False` (`transport/wifi.py:37`);
`cli_exec` raises `FlipperCLIUnavailableError` over WiFi. **Every CLI-text tool
(P2, P3-CLI, P4, P5, P6-CLI) is USB-only** and must raise the same typed error over
WiFi. The RPC tools (P0, P1, P3-RPC) work over both transports. Document in each CLI
tool's docstring and the matrix; this is why all percentages here are USB-attached.

### TP-3 — Shared typed-CLI helper (`_cli_typed`) — new, blocks all CLI families
Today only `flipperzero_cli_exec` calls `client.cli_exec(...)`. Add one private
helper in `tools/_common.py` (or `tools/_cli.py`) that wraps `client.cli_exec(...)`
with a fixed command, **parses output into structure**, and re-raises via
`_classify_client_error`. Reuses the existing `_io_lock`-holding `cli_exec` verbatim
— no new transport code. **Invariant (safety): a `_cli_typed` tool may bundle only
benign commands**; never hide a gated subcommand inside a bundle (it would evade the
`cli_risk.classify()` prefix match). Blocks `flipperzero_fs_tree`,
`flipperzero_loader_list`, `flipperzero_i2c_scan`, and the LED/vibro/buzzer/loader
CLI tools.

### TP-4a — Bounded-capture streaming primitive — new, blocks P4
`cli_exec` is request/response; streaming commands (`subghz rx`, `ir rx`,
`nfc scanner`, `log`, `input dump`) never return to the prompt and time out with
`completed=false`. Add `cli_capture(command, duration_s, max_bytes)` on
`FlipperClient`: holds `_io_lock`, sends the command, accumulates for a bounded
window, then sends the interrupt (`\x03`) **in a `finally`** to return to the prompt
and re-drain. Returns `{output, truncated: bool, duration_s}`. Single largest new
piece; gates every streaming *reader* (P4).

### TP-4b — Timed-transmit primitive — new, blocks P5 emulate/chat
**Distinct from TP-4a.** `nfc_emulate` / `rfid_emulate` / `ikey_emulate` /
`subghz_chat` *transmit/emulate for a bounded window then interrupt back to the
prompt* — a send-and-hold primitive, not a capture. Add
`cli_transmit_timed(command, duration_s)` with the same `_io_lock`/`finally`-interrupt
discipline. (The original plan collapsed these into one "TP-4" and mislabeled the
emulate tools — corrected here.) Gates the P5 emulate/chat tools.

### TP-5 — `require_tx` gate helper — new, blocks P4-RF and P5
`_common.py` has `require_write_tools` and the firmware gate but **no `require_tx`**.
`client._enforce_tx_gate` is a `@staticmethod(warning, accept_responsibility,
tx_tools_enabled)` — not a per-call `ctx` gate, and it only fires the `cli_risk`
warning for CLI strings. RPC-side TX/destructive tools never touch `cli_risk` and
would ship **ungated** on a naive copy-paste. Add
`require_tx(ctx, accept_responsibility, *, flavor)` to `_common.py` that enforces
`FLIPPER_ENABLE_TX_TOOLS` + per-call `i_accept_responsibility`, and selects the
**warning flavor** so a filesystem wipe never ships with RF-spectrum warning text.
`flavor` reuses the existing `cli_risk.Category` (`"transmit"` / `"destructive"`) and
its `_WARNINGS` dict (both already present, confirmed at revalidation) — no new
warning text is invented; RF tools additionally append the region note. Must land
before P4 — the first TX-gated batch.

---

## 4. Phased tool batches

`RO` = `readOnlyHint`, `D` = `destructiveHint`, `I` = `idempotentHint` (omitted = `—`,
FastMCP default). Gate: `none` / `WRITE` (`FLIPPER_ENABLE_WRITE_TOOLS` via
`require_write_tools`) / `TX` (`FLIPPER_ENABLE_TX_TOOLS` + per-call
`i_accept_responsibility` via `require_tx`). "Reuse" = existing `protobuf_rpc.py`
method; "NEW" = new method. Per project CLAUDE.md, any state-cycling tool uses
`idempotentHint=False` even when it converges.

Cumulative coverage starts at **17/82 = 20.7%**.

### P0 — Trivial RPC reads (wrap existing methods) — gate `none`
New file `tools/diagnostics.py` (or extend `systeminfo.py`).

| Tool | Signature | RO/D/I | Wraps | Reuse/NEW |
|---|---|---|---|---|
| `flipperzero_system_ping` | `(ctx) -> dict` | T/—/T | RPC `System.PingRequest` | Reuse `rpc.ping()` |
| `flipperzero_system_property_get` | `(ctx, key: str) -> dict` | T/—/T | RPC `Property.GetRequest` | Reuse `rpc.get_property(key)` |

**+2 → 19/82 = 23.2%**

### P1 — Benign RPC reads (new methods, existing proto messages) — gate `none`
New file `tools/device.py`. Messages confirmed in
`protobuf_gen/{application,desktop,gpio}_pb2.py`.

| Tool | Signature | RO/D/I | Wraps | Reuse/NEW |
|---|---|---|---|---|
| `flipperzero_app_lock_status` | `(ctx) -> dict` | T/—/T | RPC `App.LockStatusRequest` | NEW `rpc.app_lock_status()` |
| `flipperzero_app_get_error` | `(ctx) -> dict` | T/—/T | RPC `App.GetErrorRequest` | NEW `rpc.app_get_error()` |
| `flipperzero_desktop_is_locked` | `(ctx) -> dict` | T/—/T | RPC `Desktop.IsLockedRequest` | NEW `rpc.desktop_is_locked()` |
| `flipperzero_gpio_read` | `(ctx, pin: int) -> dict` | T/—/T | RPC `Gpio.GetPinMode`/`ReadPin`/`GetOtgMode` | NEW `rpc.gpio_read(pin)` |

**+4 → 23/82 = 28.0%**

### P2 — Benign CLI-text reads (USB-only; needs TP-3) — gate `none`
New file `tools/cli_typed.py`. Each wraps a fixed CLI command via `_cli_typed` and
**must parse output** to earn its point (raw passthrough does not count, §1). All
raise `FlipperCLIUnavailableError` over WiFi (TP-2).

| Tool | Signature | RO/D/I | Wraps (CLI) | Notes |
|---|---|---|---|---|
| `flipperzero_core_status` | `(ctx) -> dict` | T/—/T | `uptime`+`free` (benign bundle) | parse into `{uptime, heap_free}`; benign-only bundle |
| `flipperzero_fs_tree` | `(ctx, path: str) -> dict` | T/—/T | `storage tree` | parse into a tree structure |
| `flipperzero_loader_list` | `(ctx) -> dict` | T/—/T | `loader list` | parse into app list |
| `flipperzero_i2c_scan` | `(ctx) -> dict` | T/—/T | `i2c` | parse detected addresses |
| `flipperzero_crypto_status` | `(ctx) -> dict` | T/—/T | `crypto` | parse key-slot state |

**+5 → 28/82 = 34.1%**

### P3 — WRITE-gated mutations, no streaming — gate `WRITE`
Split into **P3-RPC (unblocked today, both transports)** and **P3-CLI (USB-only, needs
TP-3)** so the RPC half is not held behind the CLI helper. All call
`require_write_tools(ctx)`. State-cycling → `I=false`; destructive → `D=true`.

**P3-RPC** (new file `tools/device_write.py`):

| Tool | Signature | RO/D/I | Wraps | Reuse/NEW |
|---|---|---|---|---|
| `flipperzero_system_datetime_set` | `(ctx, year,month,day,hour,minute,second: int) -> dict` | F/F/T | RPC `System.SetDateTimeRequest` | NEW `rpc.system_set_datetime(...)` |
| `flipperzero_system_play_alert` | `(ctx) -> dict` | F/F/F | RPC `System.PlayAudiovisualAlertRequest` | NEW `rpc.system_play_alert()` |
| `flipperzero_app_exit` | `(ctx) -> dict` | F/F/F | RPC `App.AppExitRequest` | NEW `rpc.app_exit()` |
| `flipperzero_app_load_file` | `(ctx, path: str) -> dict` | F/F/F | RPC `App.AppLoadFileRequest` | NEW `rpc.app_load_file(path)` |
| `flipperzero_gpio_write` | `(ctx, pin:int, value:int) -> dict` | F/F/F | RPC `Gpio.SetPinMode`/`WritePin` | NEW `rpc.gpio_write(pin,value)` |
| `flipperzero_storage_backup_create` | `(ctx, archive_path: str) -> dict` | F/F/T | RPC `Storage.BackupCreateRequest` | NEW `rpc.storage_backup_create(path)` |
| `flipperzero_storage_backup_restore` | `(ctx, archive_path: str) -> dict` | F/T/F | RPC `Storage.BackupRestoreRequest` | NEW `rpc.storage_backup_restore(path)` |
| `flipperzero_storage_tar_extract` | `(ctx, tar_path: str, dest_path: str) -> dict` | F/T/F | RPC `Storage.TarExtractRequest` | NEW `rpc.storage_tar_extract(...)` |

**P3-CLI** (USB-only, via TP-3):

| Tool | Signature | RO/D/I | Wraps (CLI) |
|---|---|---|---|
| `flipperzero_storage_copy` | `(ctx, src:str, dest:str) -> dict` | F/T/F | `storage copy` |
| `flipperzero_loader_close` | `(ctx) -> dict` | F/F/F | `loader close` |
| `flipperzero_loader_signal` | `(ctx, signal:int, arg:str="") -> dict` | F/F/F | `loader signal` |
| `flipperzero_led_set` | `(ctx, channel:Literal["r","g","b","bl"], value:int) -> dict` | F/F/T | `led <c> <v>` |
| `flipperzero_vibro` | `(ctx, on:bool) -> dict` | F/F/T | `vibro <0/1>` |
| `flipperzero_buzzer` | `(ctx, freq:int, kind:Literal["freq","note"]="freq") -> dict` | F/F/F | `buzzer freq`/`note` |

> **Gating corrections (safety pass):**
> - `flipperzero_storage_copy` was `D=T/I=T`; an overwriting copy is not idempotent
>   in the "no additional effect" sense — set **`D=T/I=F`**.
> - `flipperzero_system_reboot` is **removed from P3 and moved to P5** (TX +
>   acceptance). The existing `DENYLIST` already classifies `power reboot`/`power off`
>   as destructive; a WRITE-only typed reboot would be inconsistent and can interrupt
>   a flash in `dfu`/`update` mode.

**P3 = 14 tools (8 RPC + 6 CLI). +14 → 42/82 = 51.2%**

> `storage format` (destructive) → P5 (TX-gated). `factory reset`,
> `App.FactoryResetRequest`, `App.DataExchangeRequest` stay **out of scope**
> (irreversible wipe / opaque channel). They remain reachable only via `cli_exec`,
> which keeps `factory reset` in `DENYLIST` (gated).

### P4 — Streaming benign / RX readers (needs TP-4a + TP-5) — gate per item
New file `tools/streaming.py`. RX/scanner/read tools energize a coil or RX path; their
*RF-field* risk is TX-class even when they only read, so they are TX-gated and **must
call `require_tx` themselves** (the `cli_risk` classifier returns benign for
`subghz rx`/`nfc scanner` — see §5). `subghz_chat` moved to P5 (it transmits).

| Tool | Signature | RO/D/I | Gate | Wraps (CLI) |
|---|---|---|---|---|
| `flipperzero_log_stream` | `(ctx, duration_s:float=5.0) -> dict` | T/—/F | none | `log` |
| `flipperzero_input_dump` | `(ctx, duration_s:float=5.0) -> dict` | T/—/F | WRITE | `input dump` |
| `flipperzero_subghz_rx` | `(ctx, frequency:int, duration_s:float=5.0, i_accept_responsibility:bool=False) -> dict` | T/—/F | TX | `subghz rx`/`rx raw`/`decode raw` |
| `flipperzero_ir_rx` | `(ctx, duration_s:float=5.0, i_accept_responsibility:bool=False) -> dict` | T/—/F | TX | `ir rx`/`rx raw`/`decode` |
| `flipperzero_nfc_scanner` | `(ctx, duration_s:float=5.0, i_accept_responsibility:bool=False) -> dict` | T/—/F | TX | `nfc scanner`/`nfc field` |
| `flipperzero_rfid_read` | `(ctx, duration_s:float=5.0, i_accept_responsibility:bool=False) -> dict` | T/—/F | TX | `rfid read` |
| `flipperzero_ikey_read` | `(ctx, duration_s:float=5.0, i_accept_responsibility:bool=False) -> dict` | T/—/F | TX | `ikey read` |

**P4 = 7 tools. +7 → 49/82 = 59.8%**

### P5 — TX/transmit writes (needs TP-4b + TP-5 + region notice) — gate `TX`
Highest-risk band; every tool requires `FLIPPER_ENABLE_TX_TOOLS` + per-call
`i_accept_responsibility=true` + a region/legality notice in the result (§5). New file
`tools/transmit.py`.

| Tool | Signature | RO/D/I | Wraps (CLI) | Prim |
|---|---|---|---|---|
| `flipperzero_subghz_tx` | `(ctx, frequency:int, data:str, i_accept_responsibility:bool=False) -> dict` | F/F/F | `subghz tx`/`tx from file` | TP-4b |
| `flipperzero_subghz_chat` | `(ctx, frequency:int, message:str, i_accept_responsibility:bool=False) -> dict` | F/F/F | `subghz chat` | TP-4b (moved from P4 — transmits) |
| `flipperzero_ir_tx` | `(ctx, protocol:str, address:str, command:str, i_accept_responsibility:bool=False) -> dict` | F/F/F | `ir tx` | — |
| `flipperzero_ir_universal` | `(ctx, category:str, button:str, i_accept_responsibility:bool=False) -> dict` | F/F/F | `ir universal` | — |
| `flipperzero_nfc_emulate` | `(ctx, file:str, duration_s:float=10.0, i_accept_responsibility:bool=False) -> dict` | F/F/F | `nfc emulate f` | TP-4b |
| `flipperzero_rfid_emulate` | `(ctx, file:str, duration_s:float=10.0, i_accept_responsibility:bool=False) -> dict` | F/F/F | `rfid emulate` | TP-4b |
| `flipperzero_rfid_write` | `(ctx, key_type:str, data:str, i_accept_responsibility:bool=False) -> dict` | F/T/F | `rfid write` | — |
| `flipperzero_ikey_emulate` | `(ctx, file:str, duration_s:float=10.0, i_accept_responsibility:bool=False) -> dict` | F/F/F | `ikey emulate` | TP-4b |
| `flipperzero_ikey_write` | `(ctx, key_type:str, data:str, i_accept_responsibility:bool=False) -> dict` | F/T/F | `ikey write dallas` | — |
| `flipperzero_storage_format` | `(ctx, i_accept_responsibility:bool=False) -> dict` | F/T/F | `storage format` | — (destructive flavor) |
| `flipperzero_system_reboot` | `(ctx, mode:Literal["os","dfu","update"]="os", i_accept_responsibility:bool=False) -> dict` | F/T/F | RPC `System.RebootRequest` | NEW `rpc.system_reboot(mode)`; destructive flavor |

> **Gating corrections (safety pass):**
> - `rfid_write`/`ikey_write` warning text must name **credential-cloning / access-
>   control-fraud** risk, not just RF spectrum.
> - `storage_format`/`system_reboot` use the **destructive** warning flavor of
>   `require_tx`, not the RF-region text.
> - `input_send` and `desktop_unlock` are **NOT here** — they are not RF/destructive.
>   Bundling them under the TX flag turns it into an omnibus "danger on" switch and
>   violates least authority. They move to P6 under `WRITE`.

**P5 = 11 tools. +11 → 60/82 = 73.2%**

### P6 — Remaining tail — gate per item
Residual uncovered surfaces. Items already counted via dedup (e.g. `power 5v` as
`gpio_write`) are not re-listed.

| Tool | Signature | RO/D/I | Gate | Wraps |
|---|---|---|---|---|
| `flipperzero_gpio_otg_set` | `(ctx, enabled:bool) -> dict` | F/F/T | WRITE | RPC `Gpio.SetOtgMode` (`power 5v`/`3v3`) |
| `flipperzero_input_send` | `(ctx, key:str, kind:Literal["press","release","short","long"]="short") -> dict` | F/F/F | **WRITE** | `input send` (moved from P5: not RF) |
| `flipperzero_desktop_unlock` | `(ctx) -> dict` | F/F/F | **WRITE** (security-relevant) | RPC `Desktop.UnlockRequest` (moved from TX) |
| `flipperzero_subghz_decode_file` | `(ctx, path:str) -> dict` | T/—/T | none | `subghz decode raw` (file) — counts only if it parses |
| `flipperzero_ir_decode_file` | `(ctx, path:str) -> dict` | T/—/T | none | `ir decode` (file) — counts only if it parses |
| `flipperzero_nfc_apdu` | `(ctx, apdu:str, i_accept_responsibility:bool=False) -> dict` | F/F/F | TX | `nfc apdu d` |

**P6 = 6 tools. +6 → 66/82 = 80.5%** — **this is the honest buildable ceiling.**

#### The 90% decision — RESOLVED: Option (b), accept the ~80.5% ceiling

P0–P6 as scoped land at **66/82 ≈ 80.5% USB-attached**. The remaining ~8 points to
reach **74/82 = 90.2%** exist only as **dedup-collapsed / bundled surfaces**. Hitting
literal 90% would require splitting good bundled tools into per-subcommand tools
(`subghz rx` vs `rx raw` vs `decode raw`; `nfc scanner` vs `nfc field`; `gpio write`
vs `power 5v` vs `power 3v3`; …) purely to raise the count.

- **Option (a) — chase literal 90% (rejected):** split the bundles → ~74 counting
  tools → ≥90%. Cost: more tools for the same surface, worse UX, and it re-splits in
  the numerator exactly what the denominator deduped — internally inconsistent
  accounting.
- **Option (b) — accept the honest ceiling (ACCEPTED 2026-06-23):** stop at
  **66/82 ≈ 80.5%**, treated as "100% of the non-excluded single-return surface."
  Literal 90%-by-tool-count is recorded as metric-gaming not worth the sprawl.

**Decision: Option (b).** The program completes at P6 (66/82). No bundle-splitting
batch is planned. If a literal ≥90% number ever becomes a hard external requirement,
re-baseline the *denominator* to un-dedup those surfaces so both sides of the ratio
agree, rather than splitting only the numerator.

---

## 5. Safety / legal gating for transmit subsystems

- **Two-key gate:** every P4-RF / P5 / TX-classed P6 tool requires both
  `FLIPPER_ENABLE_TX_TOOLS=true` (operator env, `config.enable_tx_tools`) **and**
  per-call `i_accept_responsibility=true`, enforced by the new `require_tx`
  (TP-5). The env flag is the trust boundary; the per-call flag is an intent signal.
- **`require_tx` carries the correct warning flavor:** `transmit`-with-region for RF
  tools; `destructive` for `storage_format` / `system_reboot`. Never attach
  RF-spectrum text to a filesystem wipe (and vice versa). `rfid_write`/`ikey_write`
  add credential-cloning language.
- **RX-as-TX tools enforce the gate themselves:** `subghz_rx`, `ir_rx`,
  `nfc_scanner`, `rfid_read`, `ikey_read` build CLI strings the `cli_risk` classifier
  scores **benign**, so the TX gate must come from the tool's own `require_tx` call
  *before* `_cli_typed`/`cli_capture`, not from the classifier. Each gets a unit test
  asserting refusal when the env flag or acceptance is absent (named, not generic).
- **Region notice is informational only:** surface region as `FLIPPER_SUBGHZ_REGION`
  (default `US` per `MEMORY.md` `subghz-region-default-us`). The result `warning`
  states the active region assumption and that **no frequency legality is enforced** —
  an agent must not read the region field as a safety guarantee.
- **TX flag stays RF/clone-only:** `input_send`, `desktop_unlock`, `system_reboot`,
  `storage_format` do not widen the *RF* env flag. Reboot/format use TX because they
  are destructive (need per-call acceptance); input/unlock use WRITE. The TX flag must
  not become an omnibus "danger on" switch.
- **Classifier fail-open caveat (carried from roadmap):** `rpc/cli_risk.py` is an
  ordered-prefix denylist that **fails open**. Add `ir universal`, `nfc emulate`,
  `rfid emulate`, `ikey emulate` prefixes as their typed tools land (defense-in-depth
  for `cli_exec`), but the boundary is the typed tool's own `require_tx`, never the
  classifier.
- **Bundled `_cli_typed` tools: benign commands only** (TP-3 invariant) — a gated
  subcommand hidden in a bundle evades the per-command prefix match.

---

## 6. Test + drift-doc obligations (per batch, non-negotiable)

1. **Regenerate the schema matrix:** `uv run python tests/tools/gen_schema_matrix.py`
   then `uv run pytest tests/unit/test_schema_matrix_drift.py`. The drift test parses
   `docs/tool-schema-matrix.md` and asserts the four hint columns + parameter
   types/defaults against the live server; a new tool fails CI until the matrix is
   regenerated **in the same change**.
2. **Extend the `GATE` map** in `tests/tools/gen_schema_matrix.py` with every new tool
   name and its gate string — `gen_schema_matrix.py:108` does `GATE[tool.name]` and
   `KeyError`s otherwise.
3. **Unit tests** in `tests/unit/` for each new `protobuf_rpc.py` method (frame
   encode/decode against vendored `_pb2`) and each tool's gating (assert refusal when
   env flag or `i_accept_responsibility` is absent). Mirror `test_client.py` /
   `test_cli_risk.py`; mock the transport boundary only. **Name the RX-as-TX refusal
   tests explicitly.**
4. **Golden dual-firmware fixtures:** any tool with firmware-specific output (system
   info, app errors, loader list, subghz/nfc/ir shapes) records fixtures under
   `tests/golden/fixtures/{momentum,official}/`; re-record after protobuf-schema
   changes. New RPC messages → regenerate bindings only if `.proto` sources or the
   `6.33` pin change.
5. **Integration markers:** every hardware-touching tool gets `@pytest.mark.integration`
   plus `@pytest.mark.usb` (CLI/streaming — cannot run over WiFi, TP-2) or
   `@pytest.mark.wifi` (RPC-only). Default suite stays `uv run pytest -m "not integration"`;
   streaming/TX tools must be exercised against a real Flipper before merge (a Flipper
   is almost always on USB — do not defer the `usb` runs).
6. **Self-audit** before each PR: `uv run consistency-check audit --repo flipperzero-mcp`
   (PROTO-005/006: read/write separation, write/TX gates default-off).
7. **Update `docs/tool-schema-matrix.md`** group count and the roadmap doc so the v2.5
   band is recorded against the v1→v3 design.

---

## 7. Risks

- **Firmware CLI churn.** P2–P6 CLI tools parse free-form output (`storage tree`,
  `i2c`, `crypto`, `subghz`, `nfc`); format differs across Official vs Momentum and
  firmware versions and is unversioned. Mitigation: lenient parsing, return raw
  `output` alongside structured fields, lock with dual-firmware golden fixtures (§6.4).
  This is the main reason the roadmap kept these on generic `cli_exec`.
- **Streaming truncation (TP-4a/b).** `cli_capture`/`cli_transmit_timed` return partial
  output by design; `truncated`/`completed` must be explicit so an agent never treats a
  clipped capture as the whole signal. Mitigation: surface `duration_s` and `truncated`
  in every streaming result; conservative default windows.
- **Mode-switch corruption.** Interleaving an RPC frame with a CLI exchange corrupts the
  link. `_io_lock` serializes this, but TP-4a/b must hold it across the *entire*
  capture/transmit + interrupt + re-drain, not just the send — releasing before
  `\x03` leaves the device mid-stream and wedges the next call. Model on the existing
  `_io_lock`-held `_cli_exchange`; always interrupt and re-read to a prompt in a
  `finally`. (A long held-lock capture is not a hang — do not conflate.)
- **Metric vs. design tension at the tail (§4).** Literal 90% requires splitting good
  bundled tools purely to raise the count. Flagged for a decision, not gamed.
- **Transport-asymmetric coverage.** All percentages are USB-attached; WiFi coverage
  stays near the RPC-only baseline. Report as a pair so the number is not read as
  whole-fleet.

---

## Appendix — files touched

**Create:** `tools/diagnostics.py`, `tools/device.py`, `tools/device_write.py`,
`tools/cli_typed.py`, `tools/streaming.py`, `tools/transmit.py`; `_cli_typed` +
`require_tx` helpers in `tools/_common.py`; `cli_capture` + `cli_transmit_timed` on
`FlipperClient` (`rpc/client.py`).
**Extend:** `rpc/protobuf_rpc.py` (new RPC methods), `rpc/cli_risk.py` (DENYLIST
prefixes), `config.py` (`FLIPPER_SUBGHZ_REGION`), `tools/__init__.py` (register_*),
`tests/tools/gen_schema_matrix.py` (`GATE` map), `docs/tool-schema-matrix.md`
(regenerated).

## Appendix — revalidation (2026-06-23)

Every load-bearing claim was checked against the working tree. All held:

| Claim | Verified |
|---|---|
| 18 registered tools; `GATE` map drives the matrix | 18 `@mcp.tool` decorators; `GATE` dict at `gen_schema_matrix.py:24`, indexed `GATE[tool.name]` at `:108` |
| Link-mode manager exists, no new lock | `rpc/client.py`: `LinkMode` (:26), `self._io_lock` (:109), `enter_rpc`/`enter_cli`/`mode` (:141/:157/:137), shared via `ProtobufRPC(..., io_lock=self._io_lock)` (:120) |
| WiFi has no CLI text mode | `transport/wifi.py:37-39` `supports_cli_text_mode` returns `False` |
| `_enforce_tx_gate` is a staticmethod, not a per-call `ctx` gate | `rpc/client.py:297` `(warning, accept_responsibility, tx_tools_enabled)` |
| `require_tx` is net-new | `tools/_common.py` has `require_write_tools` (:27) + `require_firmware_flash` (:43) only |
| `ping`/`get_property` reusable; general reboot is NEW | `protobuf_rpc.py`: `ping` (:389), `get_property` (:687); `system_reboot_update` (:474) is UPDATE-only |
| All new-tool proto messages exist | `application/desktop/system/storage/gpio _pb2.py` contain every referenced message incl. GPIO `SetPinMode`/`WritePin`/`SetOtgMode`/`ReadPin`/`GetPinMode` |
| Config flags present; `subghz_region` absent | `config.py:26-28` `enable_tx_tools`/`enable_write_tools`/`enable_firmware_flash`; no region field |
| `cli_risk` warning flavors already exist | `cli_risk.py:15` `Category = "benign"\|"transmit"\|"destructive"`; `_WARNINGS` (:32) covers transmit + destructive |

**Refinement folded in:** `require_tx`'s warning flavor reuses `cli_risk._WARNINGS`
rather than inventing text (TP-5, §5).

## Appendix — out of scope (not in the 82)

GUI input injection (`SendInputEvent`, app button-press), virtual display, screen /
desktop-status streams (excluded as non-agent-facing); `App.DataExchangeRequest`
(opaque app channel); `App.FactoryResetRequest` / CLI `factory reset` (irreversible,
stays `cli_exec`-only and `DENYLIST`-gated); ESP32 flashing (`esp32_*`, v3).
