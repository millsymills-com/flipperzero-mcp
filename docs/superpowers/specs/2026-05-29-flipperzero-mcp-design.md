# flipperzero-mcp — Design Spec

- **Date:** 2026-05-29
- **Status:** Approved (design); implementation plan pending
- **Owner:** mills
- **Repo:** `millsymills-com/flipperzero-mcp` (private)

## 1. Context & decision

A third-party Flipper Zero MCP server exists (`busse/flipperzero-mcp`, ~1 week old,
~5,200 hand-written Python LOC, alpha). It has genuinely valuable hardware work —
working USB + WiFi protobuf RPC and a proven ESP32 TCP↔UART bridge firmware — but its
MCP scaffolding diverges from this workspace's house style on nearly every axis (raw
`mcp.server.Server` + a bespoke plugin registry, `pip`/`requirements.txt`/setuptools,
`black`/`mypy`, no CI, no `uv.lock`, ~10% test ratio, 100 broad `except`, committed
temp dirs).

**Decision:** build a fresh server in the house style (FastMCP, `uv`, hatchling,
`ruff`/`ty`, pydantic-settings, tiered tests, CI, pre-commit) and **harvest** the
hard, framework-agnostic parts (transport, protobuf framing/RPC, firmware, domain
docs). Contributing upstream was rejected because adopting it means inheriting and
maintaining a divergent low-level stack we'd largely rewrite anyway.

The harvest source is preserved locally at
`../flipperzero-mcp-upstream/` (retains its own git history and `busse` remote).

## 2. Goals / non-goals

**Goals**
- House-style FastMCP server, stdio transport, talks to a Flipper over USB or WiFi.
- v1 tracer-bullet: `connection` + `systeminfo` tools working end-to-end against real
  hardware (a Flipper + WiFi dev board are on hand for integration testing).
- Reuse the proven transport / protobuf-RPC / firmware rather than reinventing it.

**Non-goals (v1)**
- `badusb` and `music` modules (deferred to later phases).
- Bluetooth transport (upstream ships a non-functional stub; dropped).
- Remote HTTP deployment (stdio only).

## 3. Architecture

Fresh FastMCP server. The single biggest departure from upstream: **delete the
bespoke plugin system** (`FlipperModule` ABC + `ModuleRegistry` auto-discovery + raw
`mcp.server.Server`) and replace it with house-style FastMCP — `@mcp.tool` functions
grouped by domain under `tools/`, composed via `register_*_tools(mcp)`.

```
flipperzero-mcp/
├── src/flipperzero_mcp/
│   ├── __init__.py  __main__.py  server.py     # FastMCP + lifespan
│   ├── config.py        # pydantic-settings, reads FLIPPER_* env
│   ├── errors.py        # FlipperError hierarchy → ToolError
│   ├── transport/       # HARVESTED: base, usb, wifi, auto (no bluetooth)
│   ├── rpc/             # HARVESTED: protobuf framing + RPC client
│   │   ├── protobuf_gen/   # regenerated from proto/ via committed script
│   │   └── client.py
│   └── tools/
│       ├── _common.py   # get_client(ctx), ensure_connected(ctx)
│       ├── connection.py   # phase 1
│       └── systeminfo.py   # phase 1
├── proto/               # HARVESTED .protos + PROTO_VERSION + regen script
├── firmware/tcp_uart_bridge/   # HARVESTED ESP32 bridge (sanitized)
├── tests/  docs/  .github/workflows/  .pre-commit-config.yaml
├── pyproject.toml  uv.lock  NOTICE
└── CHANGELOG.md SECURITY.md CLAUDE.md CONTRIBUTING.md README.md .env.example
```

### 3.1 Connection lifecycle & resilience

Upstream's auto-reconnect/health logic lived only in the central `call_tool` wrapper
(`server.py:54-130`). FastMCP's `@mcp.tool` model has no equivalent central intercept,
so that logic must move:

- The **FastMCP lifespan** constructs a single `FlipperClient`, validates the
  connection, and yields it via the request context.
- `tools/_common.py` provides `async def ensure_connected(ctx)` — a shared guard every
  hardware-touching tool calls. It detects a known-bad transport and performs the
  one-shot reconnect that used to live in the wrapper.
- `flipper_connection_health` and `flipper_connection_reconnect` remain the explicit
  recovery tools and are usable even when disconnected.

### 3.2 Logging & stdout discipline

Under stdio MCP, stdout is reserved for JSON-RPC. House style uses `logging` (not
`print`), whose default handler writes to stdout. The entry point therefore calls
`logging.basicConfig(stream=sys.stderr, ...)` **before** `mcp.run()`. All harvested
`print(..., file=sys.stderr)` calls are converted to `logging` calls on the same
stderr stream.

### 3.3 Configuration

`pydantic-settings` `BaseSettings` reading `FLIPPER_*` env vars: `FLIPPER_TRANSPORT`
(`auto`|`usb`|`wifi`), `FLIPPER_PORT`, `FLIPPER_WIFI_HOST`, `FLIPPER_WIFI_PORT`,
`FLIPPER_DEBUG`. Auto mode prefers USB, falls back to WiFi only when
`FLIPPER_WIFI_HOST` is set.

### 3.4 Error handling

A structured `FlipperError` hierarchy (connection/timeout/not-connected/protocol
errors) mapped to `fastmcp.exceptions.ToolError` via a `handle_client_error` helper —
replacing upstream's 100 broad `except Exception` + emoji-string returns. No silent
swallows.

## 4. Harvest map

Lift = copy + adapt to the new package; the adaptations below are mandatory, not
optional cleanup.

| Upstream | Action |
|---|---|
| `core/transport/{base,usb,wifi,auto}.py` | **Lift.** USB: serialize access with an `asyncio.Lock`, drop the shared-`serial.timeout` mutation race (`usb.py:160-174`). WiFi already fully async. |
| `core/protobuf_rpc.py` | **Lift.** Keep hand-coded varint framing. Convert blocking `time.sleep(0.01)` (`:148`) → `await asyncio.sleep`. |
| `core/rpc.py` | **Lift thin layer only.** Delete `send_command` (custom non-Flipper frame, never the live path) and all non-protobuf CLI fallbacks; keep only `ProtobufRPC` delegates. |
| `core/flipper_client.py` | **Lift** device methods used by phase-1 tools. |
| `proto/*.proto` | **Lift.** Pin `protobuf==6.33.2` + matching `protoc`; regenerate `_pb2.py` via committed script; record upstream `flipperzero-protobuf` commit in `proto/PROTO_VERSION`. Diff `.tmp_proto/` vs `proto/` to confirm canonical source first. |
| `firmware/tcp_uart_bridge/` | **Lift wholesale**, sanitized: grep `sdkconfig` for WiFi credentials, gitignore it, commit `sdkconfig.defaults` as reference; drop `sdkconfig.old`. Firmware excluded from Python CI (documented). |
| `docs/{wifi_dev_board,protobuf_rpc}.md` | **Lift** domain knowledge, reformat. |
| `modules/{systeminfo,connection}` logic | **Rewrite** as `tools/*.py` FastMCP functions. |
| `modules/{badusb,music}` | **Defer** to later phases. |
| `server.py`, `registry.py`, `base_module.py` | **Drop/rewrite** (FastMCP replaces them). |
| `transport/bluetooth.py` (bare `print` to stdout), `.tmp_proto/`, root `test_*.py`, `requirements.txt`, setuptools/black/mypy | **Drop.** |

### 4.1 Why regenerate protobuf

Committed `_pb2.py` were generated by **protoc 6.33.2** and assert that runtime at
import (`flipper_pb2.py:12-18`); upstream's pin is `protobuf>=4.25`, which crashes on a
fresh install. Regenerating against a pinned matching runtime removes the mismatch. No
nanopb `.options` files exist — regen is plain `protoc --python_out`. The varint
framing is hand-coded and independent of the generated code.

## 5. Testing strategy

Tiered, mirroring house style:

- **Unit** (`tests/unit/`): framing codec, RPC command construction, and tool logic
  against a **mock transport**. No hardware.
- **Property** (`tests/property/`, hypothesis): round-trip the varint length-delimited
  framing codec — it's a parser, the right place for generative tests.
- **Integration** (`tests/integration/`): opt-in (env-gated), real USB **and** WiFi
  against the on-hand hardware.
- **Coverage gate: ~80%** on hand-written, non-generated Python. `_ensure_rpc_session_started`
  (~130 LOC of hardware-only session negotiation) is `# pragma: no cover`-excluded and
  documented as integration-only — a 90% gate would be dishonest given hardware coupling.

## 6. Safety & write-tool gating (later phases)

Principle set now, enforced when `badusb` lands: write/execute tools are tagged and
gated behind an explicit env flag (mirroring `GANDI_MODE` / `UNRAID_ENABLE_WRITE_TOOLS`),
and `badusb_execute` keeps a `confirm=true` guard. Phase-1 `connection`/`systeminfo`
are read-only and ship ungated.

## 7. Licensing / attribution

Upstream is MIT (`Copyright (c) 2024 Flipper MCP Contributors`). We lift substantial
code + firmware, so MIT requires the copyright + permission notice travel with it. A
`NOTICE` file in the new repo carries busse's original copyright line for the harvested
transport / RPC / firmware portions. A README mention alone is insufficient.

## 8. Phasing

1. **Phase 1 — tracer bullet:** repo scaffold (done: repo created, cloned),
   pyproject/uv/ruff/ty/CI/pre-commit, harvested transport + rpc + regenerated
   protobuf, FastMCP server + lifespan, `connection` + `systeminfo` tools working
   end-to-end on real hardware. Unit + property + opt-in integration tests green.
2. **Phase 2 — badusb:** rewrite as gated write tools (`confirm=true`), storage RPC.
3. **Phase 3 — music:** FMF save/play.
4. **Firmware/WiFi hardening** as needed.

## 9. Setup status

Done as part of executing this design:
- Upstream moved to `../flipperzero-mcp-upstream/` (harvest source, history intact).
- Private repo `millsymills-com/flipperzero-mcp` created and cloned to this path.

## 10. Risks (from adversarial review)

- **protobuf runtime pin** must match the regen `protoc` major.minor or imports crash.
- **`.tmp_proto/` vs `proto/`** may differ; confirm canonical source before regen.
- **`sdkconfig` credential leak** — must sanitize before committing firmware.
- **Event-loop blocking** — `time.sleep` and the USB timeout race must be fixed on lift.
- **Reconnect coverage** — `ensure_connected` must replicate the old central-wrapper
  recovery, or mid-session drops fail silently.
