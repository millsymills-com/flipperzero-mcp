# Contributing

Thanks for contributing to flipperzero-mcp!

## Local development

```bash
uv sync --extra dev
uv run pre-commit install
```

## Tests

| Tier | Command | Hardware |
|---|---|---|
| Default suite | `uv run pytest -m "not integration"` | None |
| Integration | `uv run pytest -m integration` | Real Flipper (USB or WiFi dev board) |

Integration tests are local-only; they require a connected Flipper and, for the
WiFi tier, `FLIPPER_WIFI_HOST` pointing at a running bridge.

### Golden fixtures

CLI/RPC behaviors are pinned by replayed byte fixtures captured from a real
Flipper (`tests/golden/`, see `docs/agents/golden-fixtures.md`). The default
suite replays them offline. If you change wire shapes, the `.proto` sources, or
the CLI/RPC logic and a `tests/golden/` test fails, re-capture on hardware with
`make record-fixtures` and commit the updated fixtures.

## Code style

- `uv run ruff format` formats; `uv run ruff check` lints.
- `uv run ty check src/flipperzero_mcp/` for type checking.
- Run `uv run pre-commit run --all-files` (or `prek run`) before committing.

## Commits

- Imperative mood, <=72 char subject line.
- One logical change per commit.
- Add a co-author tag for AI-assisted contributions.

## Harvest provenance

The transport layer, the protobuf RPC implementation, and the ESP32 WiFi-bridge
firmware are harvested from
[busse/flipperzero-mcp](https://github.com/busse/flipperzero-mcp) under the MIT
License. See `NOTICE`. When changing harvested code, keep the attribution
accurate.
