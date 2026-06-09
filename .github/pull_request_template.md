## What

<!-- What this PR changes, in the present tense. Describe what's in the diff, not discarded approaches. -->

Closes #

## Why

<!-- The problem this solves. -->

## Testing

- [ ] `uv run pytest -m "not integration"` passes
- [ ] `uv run ruff check` and `uv run ruff format --check` clean
- [ ] `uv run ty check src/flipperzero_mcp/` clean
- [ ] If wire shapes / `.proto` / CLI-RPC logic changed: re-recorded golden fixtures (`make record-fixtures`) on hardware
- [ ] If hardware-touching: verified against a real Flipper (note firmware + transport)
