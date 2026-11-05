# CLAUDE.md

Guidance for Claude Code when working in this repository.

Inherits the workspace conventions in `../CLAUDE.md` and the global standards in
`~/.claude/CLAUDE.md`. Defer to those for code-quality limits, tooling, and
workflow.

## Canonical standards

This server is graded against the canonical MCP standards at
`consistency-check/docs/standards/` (`mcp.md` + `python.md` + `mcp-protocol.md` +
`stages.md`). Self-audit before opening a PR:

```bash
uv run consistency-check audit --repo flipperzero-mcp
```

Stage is declared in the README `## Status` section (currently **S2**); the
auditor scopes rules to the declared stage.

## Project

stdio MCP server (FastMCP) for the Flipper Zero, speaking protobuf RPC over USB
or WiFi.

## Project specifics

- **stdout is the JSON-RPC channel.** All logging goes to stderr (see
  `_logging.py`). Never `print` to stdout.
- **Tool idempotency annotations are behavioral, not just end-state based.**
  Tools that cycle state on every call (for example disconnect/reconnect) must
  use `idempotentHint=False` even if they usually converge to the same final
  state.
- **Protobuf runtime is pinned to `protobuf==7.35.1`** in `pyproject.toml`.
  Vendored bindings in `src/flipperzero_mcp/rpc/protobuf_gen/` were generated
  with protoc 6.33.2. Follow the upstream Python-specific compatibility
  guarantee (https://protobuf.dev/support/cross-version-runtime-guarantee/#python-specific-guarantees),
  rather than requiring matching major/minor versions. Validate generated
  imports and offline RPC tests for runtime upgrades; regenerate bindings
  when `.proto` sources change or the supported compatibility window requires it.
- **Harvest provenance.** The transport layer
  (`src/flipperzero_mcp/transport/`), the protobuf RPC implementation
  (`src/flipperzero_mcp/rpc/protobuf_rpc.py` and `proto/`), and the ESP32
  firmware (`firmware/tcp_uart_bridge/`) are harvested from
  busse/flipperzero-mcp under the MIT License. See `NOTICE`.
- **Integration tests require a real Flipper.** They are marked `integration`
  (plus `usb`/`wifi`) and are local-only. The default suite is
  `uv run pytest -m "not integration"`.
- **Firmware is not built in CI.** It is harvested as-is for WiFi users.
- **`firmware/` module** (`flavor.py`, `bundles.py`, `installer.py`,
  `codes.py`): classifies firmware flavor (Official vs Momentum), resolves and
  downloads bundles with sha256 verification, and drives the on-device installer
  via chunked `storage_write` (required for large files). Gated behind
  `FLIPPER_ENABLE_FIRMWARE_FLASH=true` (plus `FLIPPER_ENABLE_WRITE_TOOLS=true`).
- **Dual-firmware golden fixtures.** Recorded fixtures live under
  `tests/golden/fixtures/{momentum,official}/`. Re-record after changing the
  protobuf schema or adding tools that have firmware-specific output.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues for this repo, managed via the `gh` CLI
(which infers the repo from `git remote -v`). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles mapped to default label strings (`needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root (created
lazily). See `docs/agents/domain.md`.
