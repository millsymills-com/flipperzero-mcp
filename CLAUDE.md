# CLAUDE.md

Guidance for Claude Code when working in this repository.

Inherits the workspace conventions in `../CLAUDE.md` and the global standards in
`~/.claude/CLAUDE.md`. Defer to those for code-quality limits, tooling, and
workflow.

Canonical MCP standards live in `~/Desktop/Projects/consistency-check/docs/standards/`
(`mcp.md` + `python.md` + `mcp-protocol.md`); audit with
`uv run consistency-check audit --repo flipperzero-mcp`. This path is
workspace-internal — external clones won't have it.

## Project

stdio MCP server (FastMCP) for the Flipper Zero, speaking protobuf RPC over USB
or WiFi.

## Project specifics

- **stdout is the JSON-RPC channel.** All logging goes to stderr (see
  `_logging.py`). Never `print` to stdout.
- **Protobuf runtime is pinned to `protobuf==6.33.5`** (forward-compatible with
  the vendored bindings in `src/flipperzero_mcp/rpc/protobuf_gen/`, which embed a
  6.33.2 assertion; bumped for CVE-2026-0994). Keep the pin's major.minor at
  `6.33`. Regenerate the bindings if you change the pin's major.minor or the
  `.proto` sources in `proto/`.
- **Harvest provenance.** The transport layer
  (`src/flipperzero_mcp/transport/`), the protobuf RPC implementation
  (`src/flipperzero_mcp/rpc/protobuf_rpc.py` and `proto/`), and the ESP32
  firmware (`firmware/tcp_uart_bridge/`) are harvested from
  busse/flipperzero-mcp under the MIT License. See `NOTICE`.
- **Integration tests require a real Flipper.** They are marked `integration`
  (plus `usb`/`wifi`) and are local-only. The default suite is
  `uv run pytest -m "not integration"`.
- **Firmware is not built in CI.** It is harvested as-is for WiFi users.

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
