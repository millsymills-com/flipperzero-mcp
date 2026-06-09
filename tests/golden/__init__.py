"""Golden-fixture harness: capture real Flipper byte exchanges, replay offline.

Mirrors the workspace VCR-cassette discipline. ``RecordingTransport`` wraps a
real transport and logs every wire event during an integration-marked capture
run; ``ReplayTransport`` serves those events back deterministically in CI with
no hardware. See ``docs/agents/golden-fixtures.md``.
"""
