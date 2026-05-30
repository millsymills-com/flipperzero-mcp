# Flipper MCP v1 (Documentation-forward + CLI exec) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a USB-only CLI text channel, one gated `flipper_cli_exec` tool, and bundled MCP reference/workflow resources + prompts, so Claude can drive the Flipper's full CLI surface guided by server-provided documentation.

**Architecture:** A new `cli/` package adds a link-mode manager (`CLIChannel`) that leaves the RPC session (`StopSession`), drains to the `>:` prompt, runs one command, and strips echo/prompt. `ProtobufRPC` gains the missing RPC→CLI direction. `FlipperClient` owns a single `_io_lock` that **both** the CLI path and the RPC-initiating client methods acquire at the top of each round-trip, so CLI and RPC exchanges never interleave on the shared serial port. A `flipper_cli_exec` tool exposes the channel and returns a typed result; transmit/destructive commands are gated behind an operator env flag (`FLIPPER_ENABLE_TX_TOOLS`, the PROTO-006 control) **and** a per-call `i_accept_responsibility` intent flag. Transport CLI availability is exposed as an explicit `supports_cli_text_mode` capability rather than name-sniffing. Reference and workflow knowledge ships as bundled markdown served via `@mcp.resource`, with two `@mcp.prompt` entry points.

**Namespace:** This repo officially adopts the **`flipper_`** tool prefix (a documented PROTO-002 deviation; the literal rule would be `flipperzero_`). Task 0 renames the shipped `systeminfo_get` → `flipper_system_info` so the surface is consistent before the new tool lands.

**Tech Stack:** Python 3.13, `uv`, FastMCP 3.x, pyserial, protobuf 6.33.5 (vendored bindings), pytest + pytest-asyncio (`asyncio_mode=auto`), ruff, ty.

**Scope:** v1 only. Typed per-subsystem tools (file transfer, app build, ESP32 flash, radio capture/replay) and WiFi CLI / streaming-capture support are explicitly out of scope and get their own plans.

**Spec:** `docs/superpowers/specs/2026-05-29-flipper-mcp-roadmap-design.md`

**Conventions to follow (observed in the codebase):**
- `from __future__ import annotations` at the top of new modules.
- Tools registered via `register_*_tools(mcp)` and wired in `tools/__init__.py`.
- Hardware-touching tools call `ensure_connected(ctx)` first; map errors via `handle_client_error`.
- Unit tests use `fastmcp.Client` against `create_server(...)` with fake transport/RPC (see `tests/unit/test_tool_connection.py`). No real hardware in the default suite.
- Run targets: `uv run pytest -m "not integration"`, `uv run ruff check`, `uv run ruff format`, `uv run ty check`.

---

### Task 0: Namespace rename + transmit-tools config flag

Two repo-wide prerequisites the later tasks depend on: rename `systeminfo_get` to
`flipper_system_info` (PROTO-002 consistency — this repo's adopted `flipper_`
namespace) and add the operator env flag that gates transmit/destructive commands
(PROTO-006).

**Files:**
- Modify: `src/flipperzero_mcp/tools/systeminfo.py`
- Modify: `src/flipperzero_mcp/config.py`
- Modify: `tests/unit/test_tool_systeminfo.py` (rename references), `README.md`
- Test: `tests/unit/test_config.py` (append)

- [ ] **Step 1: Rename the tool**

In `src/flipperzero_mcp/tools/systeminfo.py`, rename the registered function
`systeminfo_get` → `flipper_system_info` (the function name is the tool name).
Keep the body unchanged. Update its docstring's first line accordingly.

- [ ] **Step 2: Update every reference to the old name**

Grep the repo for `systeminfo_get` and update each hit to `flipper_system_info`:
existing tests (`tests/unit/test_tool_systeminfo.py`), the README tool table, and
the server `instructions` string. Run `rg -n systeminfo_get` and confirm zero
remaining hits (outside this plan doc).

- [ ] **Step 3: Add the transmit-tools env flag**

In `src/flipperzero_mcp/config.py`, add a field to `FlipperConfig` (env prefix is
already `flipper_`, so this reads `FLIPPER_ENABLE_TX_TOOLS`):

```python
    enable_tx_tools: bool = False
```

Append to `tests/unit/test_config.py`:

```python
def test_tx_tools_disabled_by_default():
    assert FlipperConfig(_env_file=None).enable_tx_tools is False


def test_tx_tools_enabled_from_env(monkeypatch):
    monkeypatch.setenv("FLIPPER_ENABLE_TX_TOOLS", "true")
    assert FlipperConfig(_env_file=None).enable_tx_tools is True
```

- [ ] **Step 4: Run tests, lint, format, type-check**

Run: `uv run pytest tests/unit/test_tool_systeminfo.py tests/unit/test_config.py -q && uv run ruff check && uv run ruff format --check && uv run ty check`
Expected: PASS, no errors, no remaining `systeminfo_get` references.

- [ ] **Step 5: Commit**

```bash
git add src/flipperzero_mcp/tools/systeminfo.py src/flipperzero_mcp/config.py tests README.md
git commit -m "refactor: rename systeminfo_get->flipper_system_info; add FLIPPER_ENABLE_TX_TOOLS"
```

---

### Task 1: CLI command safety classifier

Classifies a raw CLI command line as benign, destructive, or transmit/regulated, deciding *which* commands require gating.

> **Trust-boundary note.** This is an ordered prefix **denylist** and therefore fails open: anything unlisted (e.g. `loader open <app>` launching an app that transmits, future subcommands, argument reordering) is treated as benign. It is **defense-in-depth / advisory**, not the security boundary. The real control is the operator env flag `FLIPPER_ENABLE_TX_TOOLS` (Task 0) checked alongside the per-call acceptance flag in `cli_exec` (Task 5). Keep the lists conservative but do not rely on them to be exhaustive.

**Files:**
- Create: `src/flipperzero_mcp/cli/__init__.py`
- Create: `src/flipperzero_mcp/cli/safety.py`
- Test: `tests/unit/test_cli_safety.py`

- [ ] **Step 1: Create the package marker**

Create `src/flipperzero_mcp/cli/__init__.py`:

```python
"""CLI text-mode channel for the Flipper Zero (USB-only)."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_cli_safety.py`:

```python
from flipperzero_mcp.cli.safety import CommandRisk, classify_command


def test_benign_command_is_allowed():
    risk = classify_command("storage list /ext")
    assert risk.category == "benign"
    assert risk.requires_acceptance is False
    assert risk.warning is None


def test_transmit_command_requires_acceptance():
    risk = classify_command("subghz tx 0x00112233 433920000 200 10")
    assert risk.category == "transmit"
    assert risk.requires_acceptance is True
    assert "transmit" in risk.warning.lower()


def test_destructive_command_requires_acceptance():
    risk = classify_command("storage format /ext")
    assert risk.category == "destructive"
    assert risk.requires_acceptance is True
    assert risk.warning


def test_classification_ignores_leading_whitespace_and_case():
    risk = classify_command("   RFID WRITE EM4100 1234567890")
    assert risk.requires_acceptance is True


def test_subghz_rx_is_benign():
    risk = classify_command("subghz rx 433920000")
    assert risk.category == "benign"
    assert risk.requires_acceptance is False
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_safety.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'flipperzero_mcp.cli.safety'`.

- [ ] **Step 4: Implement the classifier**

Create `src/flipperzero_mcp/cli/safety.py`:

```python
"""Risk classification for raw Flipper CLI command lines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal["benign", "destructive", "transmit"]

# Ordered (prefix, category) rules; first match wins. Prefixes are matched against
# the normalized (lowercased, whitespace-collapsed) command line.
_RULES: tuple[tuple[str, Category], ...] = (
    ("subghz tx", "transmit"),
    ("ir tx", "transmit"),
    ("rfid write", "transmit"),
    ("ikey write", "transmit"),
    ("nfc raw", "transmit"),
    ("factory reset", "destructive"),
    ("storage format", "destructive"),
    ("update install", "destructive"),
    ("power off", "destructive"),
    ("power reboot", "destructive"),
)

_WARNINGS: dict[Category, str] = {
    "transmit": (
        "This command makes the Flipper TRANSMIT on a radio/RF interface. Transmitting "
        "outside permitted frequencies/power is illegal in most regions and is your "
        "responsibility. Re-call with i_accept_responsibility=True to proceed."
    ),
    "destructive": (
        "This command is destructive (data loss, reset, or reboot). Re-call with "
        "i_accept_responsibility=True to proceed."
    ),
}


@dataclass(frozen=True)
class CommandRisk:
    """Classification of a single CLI command line."""

    category: Category
    requires_acceptance: bool
    warning: str | None


def _normalize(command: str) -> str:
    return " ".join(command.strip().lower().split())


def classify_command(command: str) -> CommandRisk:
    """Classify a raw CLI command line by risk.

    Args:
        command: The raw command line as it would be sent to the Flipper CLI.

    Returns:
        CommandRisk with the matched category, whether explicit acceptance is
        required, and a human-readable warning (None for benign commands).
    """
    normalized = _normalize(command)
    for prefix, category in _RULES:
        if normalized == prefix or normalized.startswith(prefix + " "):
            return CommandRisk(category=category, requires_acceptance=True, warning=_WARNINGS[category])
    return CommandRisk(category="benign", requires_acceptance=False, warning=None)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_cli_safety.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/cli tests/unit/test_cli_safety.py && uv run ruff check src/flipperzero_mcp/cli tests/unit/test_cli_safety.py && uv run ty check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/cli/__init__.py src/flipperzero_mcp/cli/safety.py tests/unit/test_cli_safety.py
git commit -m "feat(cli): add command risk classifier for CLI exec gating"
```

---

### Task 2: Add the RPC→CLI direction (`stop_rpc_session`)

The codebase only switches CLI→RPC. To run CLI text commands after an RPC session is live, the device must be returned to CLI mode by sending `StopSession` (`flipper.proto` field 19).

**Files:**
- Modify: `src/flipperzero_mcp/rpc/protobuf_rpc.py` (class `ProtobufRPC`, near `_ensure_rpc_session_started`, around line 140)
- Test: `tests/unit/test_protobuf_rpc_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_protobuf_rpc_session.py`:

```python
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class RecordingTransport:
    def __init__(self):
        self.sent = bytearray()
        self._buf = bytearray()

    def get_name(self):
        return "USB"

    async def send(self, data: bytes) -> None:
        self.sent.extend(data)

    async def receive(self, timeout=None) -> bytes:
        return b""

    async def receive_exact(self, n: int, timeout=None) -> bytes:
        return b""

    def clear_receive_buffer(self) -> None:
        self._buf.clear()


async def test_stop_rpc_session_sends_stop_and_clears_flag():
    rpc = ProtobufRPC(RecordingTransport())
    rpc._rpc_session_started = True

    await rpc.stop_rpc_session()

    assert rpc.rpc_session_started is False
    # A StopSession Main message must have been sent (non-empty framed bytes).
    assert len(rpc.transport.sent) > 0


async def test_stop_rpc_session_is_noop_when_not_started():
    rpc = ProtobufRPC(RecordingTransport())
    rpc._rpc_session_started = False

    await rpc.stop_rpc_session()

    assert rpc.rpc_session_started is False
    assert len(rpc.transport.sent) == 0


class FailingTransport(RecordingTransport):
    async def send(self, data: bytes) -> None:
        raise OSError("link dropped")


async def test_stop_rpc_session_keeps_flag_and_raises_on_send_failure():
    import pytest

    rpc = ProtobufRPC(FailingTransport())
    rpc._rpc_session_started = True

    with pytest.raises(OSError):
        await rpc.stop_rpc_session()

    # Flag must stay set: the device is still in RPC mode.
    assert rpc.rpc_session_started is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_protobuf_rpc_session.py -q`
Expected: FAIL — `AttributeError: 'ProtobufRPC' object has no attribute 'stop_rpc_session'`.

- [ ] **Step 3: Implement `rpc_session_started` property and `stop_rpc_session`**

In `src/flipperzero_mcp/rpc/protobuf_rpc.py`, add these methods to the `ProtobufRPC` class immediately after `_ensure_rpc_session_started` (i.e., after the block ending near line 289). Match existing indentation (4 spaces, methods on the class):

```python
    @property
    def rpc_session_started(self) -> bool:
        """True when the device is currently in nanopb RPC mode (not CLI mode)."""
        return self._rpc_session_started

    async def stop_rpc_session(self) -> None:
        """Return the device to CLI text mode by sending StopSession.

        No-op when no RPC session is active. On a successful send the session flag
        is cleared (device is back in CLI mode). On a send failure the flag is
        **left set** and the error propagates: clearing it would let the next CLI
        round-trip run against a device still in RPC mode and corrupt the stream.

        Raises:
            OSError | FlipperProtocolError: if the StopSession send fails.
        """
        if not self._rpc_session_started:
            return
        msg = flipper_pb2.Main()
        msg.command_id = self._get_next_command_id()
        msg.has_next = False
        msg.stop_session.CopyFrom(flipper_pb2.StopSession())
        payload = msg.SerializeToString()
        try:
            await self.transport.send(self._encode_varint(len(payload)) + payload)
        except (OSError, FlipperProtocolError):
            logger.warning("StopSession send failed; device may still be in RPC mode", exc_info=True)
            raise
        self._rpc_session_started = False
```

> **Why no `except Exception` + `finally`:** a failed mode switch that silently clears the flag is the exact corruption case Task 4/5 guard against. Narrow the catch to the transport/serialization errors actually expected (`OSError`, `FlipperProtocolError`); ensure both are importable in this module. The test below covers the success path; add a third test asserting the flag stays set and the error propagates when `transport.send` raises `OSError`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_protobuf_rpc_session.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_protobuf_rpc_session.py && uv run ruff check src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_protobuf_rpc_session.py && uv run ty check`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_protobuf_rpc_session.py
git commit -m "feat(rpc): add stop_rpc_session for RPC->CLI mode switch"
```

---

### Task 3: CLI channel errors

Two dedicated exceptions: WiFi-unavailable and command-refused (acceptance required).

**Files:**
- Modify: `src/flipperzero_mcp/errors.py`
- Test: `tests/unit/test_errors.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_errors.py`:

```python
import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperCLIRefusedError,
    FlipperCLIUnavailableError,
    handle_client_error,
)


def test_cli_unavailable_maps_to_tool_error():
    with pytest.raises(ToolError) as exc:
        handle_client_error(FlipperCLIUnavailableError("no CLI over WiFi"))
    assert "no CLI over WiFi" in str(exc.value)


def test_cli_refused_maps_to_tool_error():
    with pytest.raises(ToolError) as exc:
        handle_client_error(FlipperCLIRefusedError("needs acceptance"))
    assert "needs acceptance" in str(exc.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: FAIL — `ImportError: cannot import name 'FlipperCLIUnavailableError'`.

- [ ] **Step 3: Add the exception classes and mappings**

In `src/flipperzero_mcp/errors.py`, add after `FlipperProtocolError` (before `handle_client_error`):

```python
class FlipperCLIUnavailableError(FlipperError):
    """CLI text mode is not available on the active transport (e.g. WiFi)."""


class FlipperCLIRefusedError(FlipperError):
    """A gated CLI command was refused because acceptance was not given."""
```

Then in `handle_client_error`, add these branches before the generic `if isinstance(error, FlipperError):` branch:

```python
    if isinstance(error, FlipperCLIUnavailableError):
        raise ToolError(f"Flipper CLI unavailable: {error}.") from error
    if isinstance(error, FlipperCLIRefusedError):
        raise ToolError(f"Command refused: {error}.") from error
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/errors.py tests/unit/test_errors.py && uv run ruff check src/flipperzero_mcp/errors.py tests/unit/test_errors.py && uv run ty check`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): add CLI unavailable/refused exceptions"
```

---

### Task 4: CLIChannel link-mode manager

Sends one command in CLI mode and returns stripped output plus a completeness flag. Rejects transports without CLI text mode. Leaves the RPC session first.

`CLIChannel` does **not** own a lock: serialization against RPC round-trips is the caller's job (Task 5 acquires `FlipperClient._io_lock` around the whole exchange). Transport CLI availability is read from an explicit `supports_cli_text_mode` capability, not by sniffing the transport name.

**Files:**
- Modify: `src/flipperzero_mcp/transport/base.py`, `transport/usb.py` (add capability)
- Create: `src/flipperzero_mcp/cli/channel.py`
- Test: `tests/unit/test_cli_channel.py`

- [ ] **Step 0: Add the `supports_cli_text_mode` transport capability**

In `src/flipperzero_mcp/transport/base.py`, add a default property to `FlipperTransport` (default `False` — a new transport opts in explicitly):

```python
    @property
    def supports_cli_text_mode(self) -> bool:
        """True when the transport can carry the Flipper CLI text shell (USB CDC)."""
        return False
```

In `src/flipperzero_mcp/transport/usb.py`, override it on `USBTransport`:

```python
    @property
    def supports_cli_text_mode(self) -> bool:
        return True
```

`WiFiTransport` inherits the `False` default (the bridge speaks protobuf only).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_channel.py`:

```python
import pytest

from flipperzero_mcp.cli.channel import CLIChannel
from flipperzero_mcp.errors import FlipperCLIUnavailableError


class ScriptedTransport:
    """Transport that replays a queued sequence of receive() chunks."""

    def __init__(self, chunks, supports_cli=True):
        self._chunks = list(chunks)
        self._supports_cli = supports_cli
        self.sent = bytearray()
        self.cleared = 0

    @property
    def supports_cli_text_mode(self):
        return self._supports_cli

    async def send(self, data: bytes) -> None:
        self.sent.extend(data)

    async def receive(self, timeout=None) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def clear_receive_buffer(self) -> None:
        self.cleared += 1


class StubRPC:
    def __init__(self, started=False):
        self._started = started
        self.stopped = False

    @property
    def rpc_session_started(self):
        return self._started

    async def stop_rpc_session(self):
        self.stopped = True
        self._started = False


async def test_exec_strips_echo_and_prompt():
    # Prompt-drain for enter_cli, then command echo + output + prompt.
    transport = ScriptedTransport([b">: ", b"device info\r\n", b"hardware: flipper\r\n", b">: "])
    channel = CLIChannel(transport, StubRPC())

    output, complete = await channel.exec("device info", timeout_s=1.0)

    assert complete is True
    assert output == "hardware: flipper"  # echoed command line and prompt both gone


async def test_exec_leaves_rpc_session_first():
    transport = ScriptedTransport([b">: ", b">: "])
    rpc = StubRPC(started=True)
    channel = CLIChannel(transport, rpc)

    await channel.exec("storage info /ext", timeout_s=1.0)

    assert rpc.stopped is True


async def test_exec_times_out_returns_incomplete():
    # No prompt ever returned after the command -> streaming/never-terminating case.
    transport = ScriptedTransport([b">: ", b"scanning...\r\n"])
    channel = CLIChannel(transport, StubRPC())

    output, complete = await channel.exec("subghz rx 433920000", timeout_s=0.3)

    assert complete is False
    assert "scanning" in output


async def test_exec_rejects_transport_without_cli_text_mode():
    transport = ScriptedTransport([], supports_cli=False)
    channel = CLIChannel(transport, StubRPC())

    with pytest.raises(FlipperCLIUnavailableError):
        await channel.exec("device info", timeout_s=1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_channel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'flipperzero_mcp.cli.channel'`.

- [ ] **Step 3: Implement the channel**

Create `src/flipperzero_mcp/cli/channel.py`:

```python
"""USB-only CLI text-mode channel with RPC<->CLI mode arbitration.

Holds no lock of its own: the caller (FlipperClient.cli_exec) serializes this
exchange against RPC round-trips by holding FlipperClient._io_lock around the
whole call. Acquiring a lock here too would deadlock (stop_rpc_session runs under
the same held lock) or, if it were a different lock, would not actually serialize
against RPC — the bug this design avoids.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from flipperzero_mcp.errors import FlipperCLIUnavailableError

if TYPE_CHECKING:
    from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
    from flipperzero_mcp.transport.base import FlipperTransport

_PROMPT = b">:"
_READ_SLICE_S = 0.2


class CLIChannel:
    """Run single CLI commands over a CLI-capable transport, reading to `>:`.

    Not usable over transports without CLI text mode (e.g. the WiFi bridge, which
    speaks protobuf only); those are rejected via supports_cli_text_mode.
    """

    def __init__(
        self,
        transport: FlipperTransport,
        rpc: ProtobufRPC | None,
    ) -> None:
        self._transport = transport
        self._rpc = rpc

    async def exec(self, command: str, timeout_s: float = 10.0) -> tuple[str, bool]:
        """Run one CLI command and return (stripped_output, completed_to_prompt).

        The caller must hold FlipperClient._io_lock for the duration.

        Args:
            command: The raw CLI command line (no trailing CR needed).
            timeout_s: Max seconds to wait for the `>:` prompt before returning
                whatever was received so far (completed=False).

        Raises:
            FlipperCLIUnavailableError: if the active transport has no CLI mode.
        """
        if not self._transport.supports_cli_text_mode:
            raise FlipperCLIUnavailableError(
                "CLI text mode is unavailable on this transport (USB only; the WiFi "
                "bridge speaks protobuf RPC only)"
            )
        await self._enter_cli()
        self._transport.clear_receive_buffer()
        await self._transport.send(command.encode() + b"\r")
        raw, complete = await self._read_until_prompt(timeout_s)
        return _strip(raw, command), complete

    async def _enter_cli(self) -> None:
        if self._rpc is not None and self._rpc.rpc_session_started:
            await self._rpc.stop_rpc_session()
        self._transport.clear_receive_buffer()
        # Ctrl-C cancels any partially typed line; CR yields a fresh prompt.
        await self._transport.send(b"\x03\r")
        await self._read_until_prompt(timeout_s=2.0)

    async def _read_until_prompt(self, timeout_s: float) -> tuple[bytes, bool]:
        buf = bytearray()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            chunk = await self._transport.receive(timeout=min(_READ_SLICE_S, max(remaining, 0.0)))
            if chunk:
                buf.extend(chunk)
                if buf.rstrip().endswith(_PROMPT):
                    return bytes(buf), True
        return bytes(buf), False


def _strip(raw: bytes, command: str) -> str:
    """Remove the echoed command line and the trailing `>:` prompt."""
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    if lines and command.strip() in lines[0]:
        lines = lines[1:]
    joined = "\n".join(lines)
    return joined.replace(">:", "").strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_cli_channel.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/cli/channel.py src/flipperzero_mcp/transport/base.py src/flipperzero_mcp/transport/usb.py tests/unit/test_cli_channel.py && uv run ruff check src/flipperzero_mcp/cli/channel.py src/flipperzero_mcp/transport tests/unit/test_cli_channel.py && uv run ty check`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/cli/channel.py src/flipperzero_mcp/transport/base.py src/flipperzero_mcp/transport/usb.py tests/unit/test_cli_channel.py
git commit -m "feat(cli): add CLIChannel link-mode manager + supports_cli_text_mode capability"
```

---

### Task 5: Wire `cli_exec` into FlipperClient with a shared I/O lock

The client owns the single `_io_lock` that serializes CLI round-trips **and** RPC round-trips on the serial port (spec: widen the lock to span both paths). `cli_exec` also enforces the two-gate transmit/destructive policy: the operator env flag (`tx_tools_enabled`, threaded in from `FlipperConfig.enable_tx_tools` by the tool in Task 6) **and** the per-call `accept_responsibility`.

> **Lock correctness (review #4).** A lock that only `cli_exec` takes does not stop a concurrent `flipper_connection_health` RPC ping from interleaving bytes mid-drain — the exact corruption the spec set out to kill. So this task also wraps the RPC-initiating client methods (`get_connection_health`'s ping, `get_device_info`, `check_sd_card_available`) in `async with self._io_lock`. Lower-level helpers (`stop_rpc_session`, `_ensure_rpc_session_started`) must **not** acquire it — they run while a top-level caller already holds it, and asyncio locks are not reentrant.

**Files:**
- Modify: `src/flipperzero_mcp/rpc/client.py` (class `FlipperClient`)
- Test: `tests/unit/test_client_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_client_cli.py`:

```python
import asyncio

import pytest

from flipperzero_mcp.errors import FlipperCLIRefusedError, FlipperNotConnectedError
from flipperzero_mcp.rpc.client import FlipperClient


class FakeTransport:
    def __init__(self, supports_cli=True):
        self._supports_cli = supports_cli
        self.sent = bytearray()
        self._chunks = [b">: ", b"name: Flipper\r\n", b">: "]

    @property
    def supports_cli_text_mode(self):
        return self._supports_cli

    def get_name(self):
        return "USB"

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def is_connected(self):
        return True

    async def send(self, data):
        self.sent.extend(data)

    async def receive(self, timeout=None):
        return self._chunks.pop(0) if self._chunks else b""

    def clear_receive_buffer(self):
        pass


async def test_cli_exec_runs_benign_command():
    client = FlipperClient(FakeTransport())
    await client.connect()

    result = await client.cli_exec("device info", timeout_s=1.0)

    assert result["completed"] is True
    assert "Flipper" in result["output"]
    assert result["risk"] == "benign"


async def test_cli_exec_refuses_transmit_when_env_gate_off():
    client = FlipperClient(FakeTransport())
    await client.connect()

    # tx_tools_enabled defaults False -> refused regardless of acceptance.
    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(
            "subghz tx 0x00 433920000 200 10", timeout_s=1.0, accept_responsibility=True
        )


async def test_cli_exec_refuses_transmit_with_env_on_but_no_acceptance():
    client = FlipperClient(FakeTransport())
    await client.connect()

    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(
            "subghz tx 0x00 433920000 200 10", timeout_s=1.0, tx_tools_enabled=True
        )


async def test_cli_exec_runs_transmit_with_both_gates():
    client = FlipperClient(FakeTransport())
    await client.connect()

    result = await client.cli_exec(
        "subghz tx 0x00 433920000 200 10",
        timeout_s=1.0,
        accept_responsibility=True,
        tx_tools_enabled=True,
    )

    assert result["risk"] == "transmit"
    assert result["warning"]


async def test_cli_exec_without_connection_raises():
    client = FlipperClient(FakeTransport())
    # No connect() -> no rpc/channel yet.
    with pytest.raises(FlipperNotConnectedError):
        await client.cli_exec("device info", timeout_s=1.0)


async def test_rpc_round_trip_blocks_while_cli_holds_lock():
    """A concurrent RPC ping must not interleave with a CLI round-trip."""
    client = FlipperClient(FakeTransport())
    await client.connect()

    order: list[str] = []

    async def slow_cli():
        async with client._io_lock:
            order.append("cli-start")
            await asyncio.sleep(0.05)
            order.append("cli-end")

    async def rpc_after():
        await asyncio.sleep(0.01)  # ensure CLI grabs the lock first
        async with client._io_lock:
            order.append("rpc")

    await asyncio.gather(slow_cli(), rpc_after())

    assert order == ["cli-start", "cli-end", "rpc"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_client_cli.py -q`
Expected: FAIL — `AttributeError: 'FlipperClient' object has no attribute 'cli_exec'`.

- [ ] **Step 3: Implement the lock and `cli_exec`**

In `src/flipperzero_mcp/rpc/client.py`:

Add imports at the top (after the existing imports):

```python
import asyncio

from flipperzero_mcp.cli.channel import CLIChannel
from flipperzero_mcp.cli.safety import classify_command
from flipperzero_mcp.errors import FlipperCLIRefusedError, FlipperNotConnectedError
```

In `FlipperClient.__init__`, add at the end:

```python
        self._io_lock = asyncio.Lock()
```

Wrap the three existing RPC round-trips in the shared lock so they can't interleave with a CLI exchange. In `get_connection_health`, guard the ping:

```python
                try:
                    async with self._io_lock:
                        echoed = await self.rpc.ping(_HEALTH_PROBE)
                    rpc_responsive = echoed == _HEALTH_PROBE
```

In `get_device_info`, wrap the call:

```python
        try:
            async with self._io_lock:
                info = await self.rpc.get_device_info()
```

In `check_sd_card_available`, wrap the call:

```python
            try:
                async with self._io_lock:
                    info = await self.rpc.storage_info("/ext")
```

Add this method to `FlipperClient` (after `check_sd_card_available`):

```python
    async def cli_exec(
        self,
        command: str,
        timeout_s: float = 10.0,
        accept_responsibility: bool = False,
        tx_tools_enabled: bool = False,
    ) -> dict[str, Any]:
        """Run one Flipper CLI command in CLI text mode (USB only).

        Transmit/destructive commands need both gates: the operator env flag
        (tx_tools_enabled, from FLIPPER_ENABLE_TX_TOOLS) and per-call
        accept_responsibility. Either missing -> refused.

        Args:
            command: Raw CLI command line.
            timeout_s: Seconds to wait for the `>:` prompt.
            accept_responsibility: Per-call intent for gated commands.
            tx_tools_enabled: Operator opt-in (server env flag) for gated commands.

        Returns:
            Dict with output, completed, risk, and warning keys.

        Raises:
            FlipperNotConnectedError: if no live transport/RPC is available.
            FlipperCLIRefusedError: if a gated command lacks the env flag or acceptance.
            FlipperCLIUnavailableError: if the transport has no CLI mode.
        """
        if self.rpc is None:
            raise FlipperNotConnectedError(self.last_connection_error or "device unavailable")
        risk = classify_command(command)
        if risk.requires_acceptance:
            if not tx_tools_enabled:
                raise FlipperCLIRefusedError(
                    "transmit/destructive commands are disabled on this server; the "
                    "operator must set FLIPPER_ENABLE_TX_TOOLS=true to allow them"
                )
            if not accept_responsibility:
                raise FlipperCLIRefusedError(risk.warning or "command requires acceptance")
        channel = CLIChannel(self.transport, self.rpc)
        async with self._io_lock:
            output, completed = await channel.exec(command, timeout_s=timeout_s)
        return {
            "output": output,
            "completed": completed,
            "risk": risk.category,
            "warning": risk.warning,
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_client_cli.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full unit suite (no regressions)**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS (all prior tests still green).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/rpc/client.py tests/unit/test_client_cli.py && uv run ruff check src/flipperzero_mcp/rpc/client.py tests/unit/test_client_cli.py && uv run ty check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/rpc/client.py tests/unit/test_client_cli.py
git commit -m "feat(client): add gated cli_exec with shared I/O lock"
```

---

### Task 6: `flipper_cli_exec` MCP tool

**Files:**
- Create: `src/flipperzero_mcp/tools/cli.py`
- Modify: `src/flipperzero_mcp/tools/__init__.py`
- Test: `tests/unit/test_tool_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tool_cli.py`:

```python
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def __init__(self, supports_cli=True):
        self._supports_cli = supports_cli
        self._chunks = [b">: ", b"name: Flipper\r\n", b">: "]

    @property
    def supports_cli_text_mode(self):
        return self._supports_cli

    def get_name(self):
        return "USB" if self._supports_cli else "WiFi"

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def is_connected(self):
        return True

    async def send(self, data):
        pass

    async def receive(self, timeout=None):
        return self._chunks.pop(0) if self._chunks else b""

    def clear_receive_buffer(self):
        pass


class FakeRPC:
    def __init__(self, transport):
        self._started = False

    @property
    def rpc_session_started(self):
        return self._started

    async def stop_rpc_session(self):
        self._started = False

    async def ping(self, data=b"ping"):
        return data


def _make_server(monkeypatch, *, supports_cli=True, config=None):
    monkeypatch.setattr(
        "flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport(supports_cli)
    )
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    return create_server(config or FlipperConfig(_env_file=None))


async def test_cli_exec_tool_benign(monkeypatch):
    server = _make_server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipper_cli_exec", {"command": "device info"})
        assert "Flipper" in result.data["output"]
        assert result.data["risk"] == "benign"


async def test_cli_exec_tool_refuses_tx_when_env_disabled(monkeypatch):
    server = _make_server(monkeypatch)  # FLIPPER_ENABLE_TX_TOOLS off by default
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "flipper_cli_exec",
                {"command": "subghz tx 0x00 433920000 200 10", "i_accept_responsibility": True},
            )


async def test_cli_exec_tool_runs_tx_when_env_enabled_and_accepted(monkeypatch):
    config = FlipperConfig(_env_file=None, enable_tx_tools=True)
    server = _make_server(monkeypatch, config=config)
    async with Client(server) as client:
        result = await client.call_tool(
            "flipper_cli_exec",
            {"command": "subghz tx 0x00 433920000 200 10", "i_accept_responsibility": True},
        )
        assert result.data["risk"] == "transmit"


async def test_cli_exec_tool_errors_without_cli_transport(monkeypatch):
    server = _make_server(monkeypatch, supports_cli=False)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("flipper_cli_exec", {"command": "device info"})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_tool_cli.py -q`
Expected: FAIL — tool `flipper_cli_exec` not found (ToolError/lookup failure).

- [ ] **Step 3: Implement the tool**

Create `src/flipperzero_mcp/tools/cli.py`:

```python
"""Generic Flipper CLI command execution tool (USB only)."""

from __future__ import annotations

from typing import TypedDict

from fastmcp import Context, FastMCP

from flipperzero_mcp.errors import handle_client_error
from flipperzero_mcp.tools._common import ensure_connected, get_server_context


class CliExecResult(TypedDict):
    """Structured result of a single CLI command execution."""

    output: str
    completed: bool
    risk: str
    warning: str | None


def register_cli_tools(mcp: FastMCP) -> None:
    """Register the CLI exec tool."""

    @mcp.tool(tags={"flipper", "cli"})
    async def flipper_cli_exec(
        ctx: Context,
        command: str,
        timeout_s: float = 10.0,
        i_accept_responsibility: bool = False,
    ) -> CliExecResult:
        """Run one Flipper CLI command over USB and return its output.

        Reads the Flipper CLI reference resource (flipper://reference/cli) to choose
        commands. USB only: this fails over the WiFi bridge transport. Streaming
        commands (subghz rx, ir rx, log, input dump) do not return to the prompt and
        will time out with completed=false and partial output.

        Transmit/destructive commands (subghz tx, ir tx, rfid write, ikey write,
        factory reset, storage format, power off/reboot, update install) require BOTH
        the operator env flag FLIPPER_ENABLE_TX_TOOLS=true and i_accept_responsibility
        =true; either missing and the command is refused.

        Args:
            command: Raw CLI command line, e.g. "storage list /ext".
            timeout_s: Seconds to wait for the `>:` prompt (default 10).
            i_accept_responsibility: Per-call intent for gated transmit/destructive commands.

        Returns:
            CliExecResult with output (str), completed (bool), risk (str), warning (str|None).
        """
        try:
            config = get_server_context(ctx).config
            client = await ensure_connected(ctx)
            result = await client.cli_exec(
                command,
                timeout_s=timeout_s,
                accept_responsibility=i_accept_responsibility,
                tx_tools_enabled=config.enable_tx_tools,
            )
            return CliExecResult(**result)
        except Exception as e:
            handle_client_error(e)
```

- [ ] **Step 4: Register the tool**

In `src/flipperzero_mcp/tools/__init__.py`, update `register_all_tools`:

```python
def register_all_tools(mcp: FastMCP) -> None:
    """Register every Flipper tool on the server."""
    from flipperzero_mcp.tools.cli import register_cli_tools
    from flipperzero_mcp.tools.connection import register_connection_tools
    from flipperzero_mcp.tools.systeminfo import register_systeminfo_tools

    register_connection_tools(mcp)
    register_systeminfo_tools(mcp)
    register_cli_tools(mcp)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_tool_cli.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/tools/cli.py src/flipperzero_mcp/tools/__init__.py tests/unit/test_tool_cli.py && uv run ruff check src/flipperzero_mcp/tools/cli.py src/flipperzero_mcp/tools/__init__.py tests/unit/test_tool_cli.py && uv run ty check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/tools/cli.py src/flipperzero_mcp/tools/__init__.py tests/unit/test_tool_cli.py
git commit -m "feat(tools): add flipper_cli_exec MCP tool"
```

---

### Task 7: Bundled reference + workflow markdown resources

Create the markdown knowledge files and make hatchling package them.

**Files:**
- Create: `src/flipperzero_mcp/resources/__init__.py`
- Create: `src/flipperzero_mcp/resources/reference_cli.md`
- Create: `src/flipperzero_mcp/resources/reference_connection.md`
- Create: `src/flipperzero_mcp/resources/reference_filesystem.md`
- Create: `src/flipperzero_mcp/resources/workflow_install_app.md`
- Create: `src/flipperzero_mcp/resources/workflow_transfer_files.md`
- Create: `src/flipperzero_mcp/resources/workflow_flash_esp32.md`
- Create: `src/flipperzero_mcp/resources/workflow_capture_replay.md`
- Modify: `pyproject.toml` (ensure markdown is packaged)

- [ ] **Step 1: Create the resources package marker**

Create `src/flipperzero_mcp/resources/__init__.py`:

```python
"""Bundled markdown resources served over MCP (flipper:// URIs)."""
```

- [ ] **Step 2: Write `reference_cli.md`**

Create `src/flipperzero_mcp/resources/reference_cli.md`:

```markdown
# Flipper Zero CLI Reference

Baseline firmware: official 1.x. The CLI surface can change across firmware
releases — re-validate after firmware updates.

Connect over USB; the MCP `flipper_cli_exec` tool runs one command at a time in
CLI text mode and returns output up to the `>:` prompt. Streaming commands
(`subghz rx`, `ir rx`, `log`, `input dump`, `subghz chat`) never return to the
prompt and will time out with partial output — they are not usable via
`flipper_cli_exec` in v1.

## Core
- `help` / `?` — list commands
- `device info` / `!` — device information
- `date` — get/set date and time
- `uptime` — time since boot
- `free` — heap allocator info
- `power off` | `power reboot` | `power reboot2dfu` (destructive)
- `factory reset` (destructive)

## Storage (also available as typed RPC)
- `storage info /ext` | `/int`
- `storage list <path>` / `storage tree <path>`
- `storage read <path>` / `storage read chunks <path> <size>`
- `storage write <path> <text>` / `storage write chunk <path> <size>`
- `storage copy <src> <dst>` / `storage rename <path> <newpath>`
- `storage mkdir <path>` / `storage remove <path>`
- `storage md5 <path>` / `storage stat <path>` / `storage timestamp <path>`
- `storage extract <archive> <dir>`
- `storage format /ext` (destructive)

## Loader (apps)
- `loader list` — enumerate apps
- `loader open <app>` / `loader close`
- `loader signal <number> <arg>`

## GPIO
- `gpio mode <pin> <0|1>` / `gpio set <pin> <0|1>` / `gpio read <pin>`
- Pins: PA7 PA6 PA4 PB3 PB2 PC3 PC1 PC0
- `power 5v <0|1>` / `power 3v3 <0|1>` (debug)

## Sub-GHz (RF — transmit is regulated)
- `subghz rx <freq> [device]` (streaming)
- `subghz rx raw <freq>` (streaming)
- `subghz tx <key> <freq> <te> <repeat> [device]` (TRANSMIT — gated)
- `subghz tx from file <path> <repeat> [device]` (TRANSMIT — gated)
- `subghz decode raw <path>`
- `subghz chat <freq> <device>` (streaming)
- Bands: 299.9–348, 387–464, 779–928 MHz. device 0 = internal, 1 = external.

## NFC / RFID / iButton / IR
- `nfc scanner` / `nfc field` / `nfc emulate f <path>` / `nfc apdu d <data>`
- `rfid read` / `rfid emulate <type> <data>` / `rfid write <type> <data>` (TRANSMIT — gated)
- `ikey read` / `ikey emulate <type> <data>` / `ikey write dallas <data>` (gated)
- `ir rx` / `ir rx raw` (streaming) / `ir tx <protocol> <address> <command>` (TRANSMIT — gated)
- `ir decode` / `ir universal`

## Misc
- `led r|g|b <0-255>` / `led bl <0-255>`
- `vibro <0|1>` / `buzzer freq <hz> <dur>` / `buzzer note <note> <dur>`
- `input dump` (streaming) / `input send <key> <type>`
- `log [error|warn|info|debug|trace]` (streaming) / `i2c` / `crypto ...`
- `update install <path>` (destructive)
```

- [ ] **Step 3: Write `reference_connection.md`**

Create `src/flipperzero_mcp/resources/reference_connection.md`:

```markdown
# Connecting to the Flipper Zero

## Transports
- **USB** — serial CDC ACM. Supports both CLI text mode and protobuf RPC. This is
  the only transport that supports `flipper_cli_exec`.
- **WiFi** — TCP to an ESP32 dev board running the TCP↔UART bridge. Speaks
  protobuf RPC only; CLI text mode is NOT available. `flipper_cli_exec` errors on
  this transport.

## Baud rate
USB CDC ACM ignores the baud rate — the device does not honor it, so the
`FLIPPER_USB_BAUDRATE` config value (default 115200) has no effect over USB. A
230400 figure only applies to hardware-UART / WiFi-bridge paths.

## Modes (USB)
The same USB port starts in CLI text mode (prompt `>:`). Sending the CLI command
`start_rpc_session` switches it into nanopb-delimited protobuf RPC mode. Returning
to CLI mode requires the RPC `StopSession` message. The MCP arbitrates this
automatically; CLI commands and RPC probes are serialized by a shared lock so
they never interleave on the wire.

## Ports
- macOS: `/dev/cu.usbmodemflip_*`
- Linux: `/dev/ttyACM*`
Set `FLIPPER_USB_PORT` to override auto-detection.
```

- [ ] **Step 4: Write `reference_filesystem.md`**

Create `src/flipperzero_mcp/resources/reference_filesystem.md`:

```markdown
# Flipper Zero Filesystem

- `/int` — internal flash (small; settings, a few files).
- `/ext` — microSD card (where apps, dumps, and databases live).

Common locations on `/ext`:
- `/ext/apps/<Category>/` — installed `.fap` applications
- `/ext/subghz/` — saved SubGHz captures (`.sub`)
- `/ext/nfc/` — saved NFC cards (`.nfc`)
- `/ext/lfrfid/` — saved 125 kHz RFID cards (`.rfid`)
- `/ext/infrared/` — saved IR remotes (`.ir`)
- `/ext/ibutton/` — saved iButton keys

Paths must start with `/int` or `/ext`. Hex values are lowercase. Use
`storage md5 <path>` (or the RPC md5sum op) to verify transfers.
```

- [ ] **Step 5: Write the four workflow docs**

Create `src/flipperzero_mcp/resources/workflow_install_app.md`:

```markdown
# Workflow: Install an app

1. Confirm USB connection: call `flipper_system_info` (or `flipper_connection_health`).
2. Ensure the SD card is present (`flipper_system_info` -> sd_card_available).
3. Place the `.fap` on the SD card under `/ext/apps/<Category>/`. In v1, push the
   file with the CLI (`storage write chunk ...`) or qFlipper; typed
   `flipper_app_install` arrives in v2.
4. Verify: `flipper_cli_exec "storage list /ext/apps/<Category>"`.
5. Launch: `flipper_cli_exec "loader open <AppName>"`; stop with `loader close`.

Note: a `.fap` must match the device firmware API. Building with ufbt against the
matching SDK channel is a v2 capability.
```

Create `src/flipperzero_mcp/resources/workflow_transfer_files.md`:

```markdown
# Workflow: Transfer files

v1 (CLI): use `flipper_cli_exec` with `storage` commands.
- List: `storage list /ext/<dir>`
- Read a text file: `storage read /ext/<path>`
- Make a directory: `storage mkdir /ext/<dir>`
- Verify integrity: `storage md5 /ext/<path>`

Binary push/pull and recursive directory sync are awkward over single CLI calls —
typed `flipper_fs_push` / `flipper_fs_pull` tools (using the storage RPC and
md5sum verification) arrive in v2.
```

Create `src/flipperzero_mcp/resources/workflow_flash_esp32.md`:

```markdown
# Workflow: Flash the ESP32 dev board

This is a v3 capability (typed `esp32_detect` / `esp32_flash`). In v1, flash
manually with esptool on the host:

1. Identify the ESP32 serial port (NOT the Flipper port).
2. Download the firmware release and verify its SHA-256.
3. `esptool --port <port> write_flash <addr> <firmware.bin>`.

Caution: if you connect to the Flipper over WiFi, the bridge ESP32 may be the
very board you are flashing — flashing it tears down the WiFi link. Use a USB
Flipper connection while flashing the bridge board.
```

Create `src/flipperzero_mcp/resources/workflow_capture_replay.md`:

```markdown
# Workflow: Capture and replay (SubGHz / NFC / RFID / IR)

Capture commands are streaming: `subghz rx`, `ir rx`, and friends never return to
the `>:` prompt and so are NOT usable via v1 `flipper_cli_exec` (it will time out
with partial output). Use the Flipper UI or saved files for capture in v1.

Replaying or transmitting (`subghz tx`, `ir tx`, `rfid write`, `ikey write`) is
gated behind two independent controls: the server operator must set
`FLIPPER_ENABLE_TX_TOOLS=true` **and** the call must pass
`i_accept_responsibility=true`. With either missing, `flipper_cli_exec` refuses
the command. Transmitting outside permitted frequencies/power is illegal in most
regions and is the operator's responsibility.

Typed capture/replay tools with a cancellation-aware streaming model and per-tool
region/legality confirmation arrive in v3.
```

- [ ] **Step 6: Confirm markdown is packaged by hatchling (likely no change needed)**

`pyproject.toml` **already** has the wheel target:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/flipperzero_mcp"]
```

Do **not** add a second `[tool.hatch.build.targets.wheel]` table — that is a TOML duplicate-key error. hatchling already includes non-`.py` files that live inside a packaged directory, so the `.md` files under `src/flipperzero_mcp/resources/` are picked up by the existing `packages = [...]`. The Step 7 wheel check is the source of truth: if the `.md` files are present, change nothing here. Only if they are missing (e.g. excluded by `.gitignore`) **edit the existing table** to add `artifacts = ["**/*.md"]` — never create a new table.

- [ ] **Step 7: Verify the files build into the package**

Run: `uv build --wheel`
Expected: build succeeds. Then:
Run: `python -c "import zipfile,glob; z=zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]); print([n for n in z.namelist() if n.endswith('.md')])"`
Expected: lists `flipperzero_mcp/resources/reference_cli.md` and the other six `.md` files. If empty, apply the `artifacts` edit described in Step 6 and rebuild.

- [ ] **Step 8: Commit**

```bash
git add src/flipperzero_mcp/resources  # add pyproject.toml too only if Step 6 required an edit
git commit -m "feat(resources): add bundled CLI reference and workflow docs"
```

---

### Task 8: Register resources on the server

**Files:**
- Create: `src/flipperzero_mcp/resources_registry.py`
- Modify: `src/flipperzero_mcp/server.py`
- Test: `tests/unit/test_resources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_resources.py`:

```python
from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server

_EXPECTED = {
    "flipper://reference/cli",
    "flipper://reference/connection",
    "flipper://reference/filesystem",
    "flipper://workflow/install-app",
    "flipper://workflow/transfer-files",
    "flipper://workflow/flash-esp32",
    "flipper://workflow/capture-replay",
}


def _server():
    return create_server(FlipperConfig(_env_file=None))


async def test_all_resources_registered():
    async with Client(_server()) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
    assert _EXPECTED <= uris


async def test_resources_resolve_to_nonempty_markdown():
    async with Client(_server()) as client:
        for uri in _EXPECTED:
            contents = await client.read_resource(uri)
            text = contents[0].text
            assert text and len(text) > 20
            assert "# " in text  # has a markdown heading
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_resources.py -q`
Expected: FAIL — fewer/zero matching resources registered.

- [ ] **Step 3: Implement the registry**

Create `src/flipperzero_mcp/resources_registry.py`:

```python
"""Register bundled markdown files as MCP resources under flipper:// URIs."""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# uri -> bundled filename
_RESOURCES: dict[str, str] = {
    "flipper://reference/cli": "reference_cli.md",
    "flipper://reference/connection": "reference_connection.md",
    "flipper://reference/filesystem": "reference_filesystem.md",
    "flipper://workflow/install-app": "workflow_install_app.md",
    "flipper://workflow/transfer-files": "workflow_transfer_files.md",
    "flipper://workflow/flash-esp32": "workflow_flash_esp32.md",
    "flipper://workflow/capture-replay": "workflow_capture_replay.md",
}


def _read(filename: str) -> str:
    return (files("flipperzero_mcp.resources") / filename).read_text(encoding="utf-8")


def register_resources(mcp: FastMCP) -> None:
    """Register every bundled markdown resource on the server."""
    for uri, filename in _RESOURCES.items():

        def _make_reader(name: str):  # type: ignore[no-untyped-def]
            def _reader() -> str:
                return _read(name)

            return _reader

        mcp.resource(uri, mime_type="text/markdown")(_make_reader(filename))
```

- [ ] **Step 4: Wire it into the server**

In `src/flipperzero_mcp/server.py`, inside `create_server`, after `register_all_tools(server)`:

```python
    from flipperzero_mcp.resources_registry import register_resources

    register_resources(server)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_resources.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/resources_registry.py src/flipperzero_mcp/server.py tests/unit/test_resources.py && uv run ruff check src/flipperzero_mcp/resources_registry.py src/flipperzero_mcp/server.py tests/unit/test_resources.py && uv run ty check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/resources_registry.py src/flipperzero_mcp/server.py tests/unit/test_resources.py
git commit -m "feat(resources): register bundled docs as flipper:// MCP resources"
```

---

### Task 9: Workflow prompts

**Files:**
- Create: `src/flipperzero_mcp/prompts.py`
- Modify: `src/flipperzero_mcp/server.py`
- Test: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_prompts.py`:

```python
from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


def _server():
    return create_server(FlipperConfig(_env_file=None))


async def test_prompts_registered():
    async with Client(_server()) as client:
        names = {p.name for p in await client.list_prompts()}
    assert {"manage_flipper", "troubleshoot_connection"} <= names


async def test_manage_flipper_prompt_renders():
    async with Client(_server()) as client:
        result = await client.get_prompt("manage_flipper")
    text = result.messages[0].content.text
    assert "flipper://reference/cli" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_prompts.py -q`
Expected: FAIL — prompts not registered.

- [ ] **Step 3: Implement the prompts**

Create `src/flipperzero_mcp/prompts.py`:

```python
"""MCP prompts that orient an agent toward Flipper management workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register Flipper workflow prompts."""

    @mcp.prompt
    def manage_flipper() -> str:
        """Orient the agent to manage a connected Flipper Zero."""
        return (
            "You are managing a Flipper Zero over USB via this MCP server.\n\n"
            "1. Check the link with `flipper_system_info` (or `flipper_connection_health`).\n"
            "2. Read `flipper://reference/cli` for the command surface and "
            "`flipper://reference/filesystem` for SD-card layout.\n"
            "3. Run commands with `flipper_cli_exec` (USB only; one command per call).\n"
            "4. Transmit/destructive commands need the server's FLIPPER_ENABLE_TX_TOOLS "
            "flag set AND i_accept_responsibility=true on the call.\n"
            "5. For multi-step jobs, consult the relevant `flipper://workflow/*` resource."
        )

    @mcp.prompt
    def troubleshoot_connection() -> str:
        """Guide the agent through diagnosing a Flipper connection."""
        return (
            "Diagnose the Flipper connection:\n"
            "1. Call `flipper_connection_health` (probe_rpc=true).\n"
            "2. If transport_connected is false, check USB cable / FLIPPER_USB_PORT, "
            "or set FLIPPER_WIFI_HOST for the WiFi bridge.\n"
            "3. If transport is connected but rpc_responsive is false, call "
            "`flipper_connection_reconnect`.\n"
            "4. See `flipper://reference/connection` for transport and mode details."
        )
```

- [ ] **Step 4: Wire it into the server**

In `src/flipperzero_mcp/server.py`, inside `create_server`, after `register_resources(server)`:

```python
    from flipperzero_mcp.prompts import register_prompts

    register_prompts(server)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_prompts.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff format src/flipperzero_mcp/prompts.py src/flipperzero_mcp/server.py tests/unit/test_prompts.py && uv run ruff check src/flipperzero_mcp/prompts.py src/flipperzero_mcp/server.py tests/unit/test_prompts.py && uv run ty check`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/prompts.py src/flipperzero_mcp/server.py tests/unit/test_prompts.py
git commit -m "feat(prompts): add manage_flipper and troubleshoot_connection prompts"
```

---

### Task 10: Docs, full verification, server instructions

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `src/flipperzero_mcp/server.py` (FastMCP `instructions` string)

- [ ] **Step 1: Update the server instructions**

In `src/flipperzero_mcp/server.py`, extend the `instructions=` text in `create_server` to mention the new capability:

```python
        instructions=(
            "Flipper Zero MCP server. Inspect connection health and system info, and "
            "run Flipper CLI commands over USB with flipper_cli_exec. Read the "
            "flipper://reference/cli and flipper://workflow/* resources to choose "
            "commands. Call flipper_connection_health before other tools if the device "
            "may have disconnected."
        ),
```

- [ ] **Step 2: Update README**

In `README.md`, rename `systeminfo_get` → `flipper_system_info` in the "Available tools" table (Task 0), add `flipper_cli_exec` to it, and add a short "Resources & prompts" subsection listing the `flipper://` URIs and the two prompts. Document the `FLIPPER_ENABLE_TX_TOOLS` env flag alongside the other `FLIPPER_*` settings. Add a one-line note: "CLI exec is USB-only; transmit/destructive commands require both `FLIPPER_ENABLE_TX_TOOLS=true` on the server and `i_accept_responsibility=true` on the call."

- [ ] **Step 3: Update CHANGELOG**

Add an entry under an `## [Unreleased]` heading in `CHANGELOG.md`:

```markdown
### Added
- `flipper_cli_exec` tool: run Flipper CLI commands over USB with risk gating.
- RPC->CLI mode switch (`StopSession`) and a USB-only CLI text channel.
- Bundled MCP resources (`flipper://reference/*`, `flipper://workflow/*`) and
  `manage_flipper` / `troubleshoot_connection` prompts.
```

- [ ] **Step 4: Full verification**

Run: `uv run pytest -m "not integration" -q`
Expected: all pass.
Run: `uv run ruff check && uv run ruff format --check && uv run ty check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md src/flipperzero_mcp/server.py
git commit -m "docs: document flipper_cli_exec, resources, and prompts"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- v1 `flipper_cli_exec` (USB-only, two-gate) → Tasks 1, 4, 5, 6. ✓
- Namespace consistency (`flipper_*`; `systeminfo_get` → `flipper_system_info`) → Task 0. ✓ (review #2)
- RPC→CLI `StopSession` direction, **failure not swallowed** → Task 2. ✓ (review #5)
- Single `_io_lock` spanning CLI **and** RPC round-trips → Task 5 (both `cli_exec` and the three RPC client methods acquire it; contention test). ✓ (review #4)
- Two-gate transmit/destructive policy: env flag `FLIPPER_ENABLE_TX_TOOLS` (Task 0 config) + per-call `i_accept_responsibility`, enforced in `cli_exec` (Task 5), env value threaded by the tool (Task 6). ✓ (review #1)
- Classifier is advisory defense-in-depth, not the boundary → Task 1 note. ✓ (review #3)
- Transport capability `supports_cli_text_mode` replaces name-sniffing → Task 4. ✓ (review #8)
- Typed `CliExecResult` output schema → Task 6. ✓ (review #7)
- Streaming-command limitation surfaced → Task 4 (completed flag), Task 6 docstring, Task 7 capture-replay doc. ✓
- Resources `flipper://reference/*` + `flipper://workflow/*` → Tasks 7, 8. ✓
- Prompts `manage_flipper` / `troubleshoot_connection` → Task 9. ✓
- Resource content-lint / URI-resolve test → Task 8. ✓
- Baud nuance + mode docs → Task 7 (`reference_connection.md`). ✓
- No duplicate `[tool.hatch.build.targets.wheel]` table; rely on the existing one → Task 7 Step 6. ✓ (review #6)
- v2/v3 items (file-transfer RPC md5sum, ufbt channel, esp32 contention, capture streaming model) intentionally deferred and only referenced in workflow docs. ✓

**Placeholder scan:** No TBD/TODO; every code step contains complete code; README step (Task 10 Step 2) is prose-editing of an existing table, acceptable as it describes exact additions.

**Type consistency:** `cli_exec` returns `{output, completed, risk, warning}` (Task 5), wrapped into the typed `CliExecResult` by the tool (Task 6) and consumed unchanged by tests. `CLIChannel.exec` returns `(str, bool)` consistently (Tasks 4, 5) and holds no lock — arbitration is the caller's (Task 5). `classify_command -> CommandRisk(category, requires_acceptance, warning)` consistent across Tasks 1, 5. `rpc_session_started` property + `stop_rpc_session()` consistent across Tasks 2, 4. `supports_cli_text_mode` capability consistent across Tasks 4 (base/usb), 5, 6.

**Review-comment resolution:** All nine PR-7 review points (#1 env gate, #2 namespace, #3 denylist-advisory, #4 shared lock, #5 no swallowed mode-switch failure, #6 no duplicate TOML table, #7 typed output, #8 capability not name-sniff, #9 tightened echo-strip assertion) are folded into the tasks above.
