# Golden-fixture test harness

Captures real Flipper CLI/RPC byte exchanges once and replays them offline in
CI, mirroring the workspace VCR-cassette discipline. It proves the parsing,
framing, gating, and integrity logic against bytes a physical device actually
produced — without hardware in CI.

## Layout

- `tests/golden/harness.py` — `RecordingTransport` (wraps a real transport,
  logs every wire event), `ReplayTransport` (serves a fixture back offline), and
  the `Fixture` file format (`tests/golden/fixtures/*.json`).
- `tests/golden/record.py` — captures fixtures from a USB Flipper.
- `tests/golden/test_golden_fixtures.py` — replays each fixture and asserts the
  recorded behavior; runs in the default `not integration` suite.

## Replay model

Replay is **event-cursor** based. A fixture is an ordered list of `tx`
(host→device) and `rx` (device→host) events. `ReplayTransport.receive()` serves
the next `rx` event only once every `tx` recorded before it has been sent;
otherwise it returns `b""` (an idle link). This gates device output behind the
matching request, so the time-based drain/read loops in the RPC and CLI code
reproduce the recorded exchange faithfully, with no dependence on wall-clock
timing. Sent payloads are recorded for assertions but not matched, so a replay
may legitimately send different request bytes (e.g. a corrupted local file in
the push-integrity mismatch test).

## Coverage

| Behavior | Fixture | Capture |
|----------|---------|---------|
| `cli_exec` echo/prompt parsing | `cli_exec_device_info` | hardware |
| `fs_push` MD5 match + mismatch | `fs_push_integrity` | hardware |
| mode switch (RPC↔CLI) | `mode_switch` | hardware |
| shared `_io_lock` non-interleave | `lock_contention` | hardware |
| TX two-gate (enabled) | reuses `cli_exec_device_info` | — |
| TX two-gate (disabled) | `cli_tx_gate_disabled` | offline (no wire I/O) |
| WiFi-CLI rejection | `wifi_cli_rejection` | offline (no wire I/O) |

The enabled-gate test reuses the benign `device_info` exchange to drive the
gate-pass path; the harness never transmits on real hardware.

## Drift / freshness

`make verify-fixtures` (also part of the default CI suite) replays every fixture
and asserts the committed `expect` result. A parsing/framing/gating change that
alters how the real captured bytes are interpreted fails the matching test —
signal to re-record. Fixtures carry a `schema_version`; a mismatch is a hard
load error.

## Re-recording

With a Flipper on USB:

```bash
make record-fixtures      # captures + verifies, overwrites tests/golden/fixtures/
```

Commit the updated fixtures. Re-record after changing request shapes, the
`.proto` sources, or the CLI/RPC wire logic. Offline fixtures are regenerated on
every run; hardware fixtures only when a device is reachable.
