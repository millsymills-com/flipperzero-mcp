"""High-level Flipper client over the protobuf RPC layer."""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from flipperzero_mcp.errors import (
    FlipperCLIRefusedError,
    FlipperCLIUnavailableError,
    FlipperNotConnectedError,
)
from flipperzero_mcp.rpc.cli_risk import classify
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC

if TYPE_CHECKING:
    from flipperzero_mcp.transport.base import FlipperTransport

logger = logging.getLogger(__name__)


class LinkMode(enum.Enum):
    """Operating mode of the link to the Flipper.

    A single physical link (USB CDC or WiFi TCP) multiplexes a text CLI and the
    nanopb-delimited RPC protocol. The mode tracks which one the device is in.
    """

    UNKNOWN = "unknown"
    CLI = "cli"
    RPC = "rpc"


class TransportInfo(TypedDict):
    """Transport identity reported in connection health."""

    type: str


class ConnectionHealth(TypedDict):
    """Authoritative connection-health snapshot returned by get_connection_health."""

    timestamp: str
    connected: bool
    transport_connected: bool
    rpc_responsive: bool | None
    transport: TransportInfo
    last_error: str | None


class ReconnectHealth(ConnectionHealth):
    """Connection health plus the outcome of an explicit reconnect attempt."""

    reconnect_ok: bool


_HEALTH_PROBE = b"mcp_health"

_CLI_PROMPT = b">:"
_CLI_READ_SLICE_S = 0.2
# Characters that compose multiple shell commands; rejected so one call runs one command.
_SHELL_CHAINING = (";", "&&", "||", "|", "`", "\n", "\r")


class CliExecResult(TypedDict):
    """Structured result of a single CLI command execution."""

    output: str
    completed: bool
    risk: str
    warning: str | None


_NORMALIZED_SOURCE_KEYS = {
    "hardware_name",
    "name",
    "hardware_model",
    "hardware",
    "firmware_version",
    "firmware",
    "version",
}


def _strip_cli_output(raw: bytes, command: str) -> str:
    """Remove the echoed command line and the trailing ``>:`` prompt."""
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    if lines and command.strip() in lines[0]:
        lines = lines[1:]
    return "\n".join(lines).replace(">:", "").strip()


class FlipperClient:
    """Connect/health/device-info wrapper around a transport + ProtobufRPC."""

    def __init__(self, transport: FlipperTransport) -> None:
        self.transport = transport
        self.connected = False
        self.rpc: ProtobufRPC | None = None
        self.last_connection_error: str | None = None
        self._sd_card_available: bool | None = None
        # Single client-level lock shared with ProtobufRPC. Every CLI and RPC
        # round-trip acquires it so frames never interleave on the one link.
        self._io_lock = asyncio.Lock()
        self._mode = LinkMode.UNKNOWN

    async def connect(self) -> bool:
        try:
            ok = await self.transport.connect()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
            return False
        if not ok:
            return False
        self.rpc = ProtobufRPC(self.transport, io_lock=self._io_lock)
        self.connected = True
        self.last_connection_error = None
        self._sd_card_available = None
        self._mode = LinkMode.UNKNOWN
        return True

    async def disconnect(self) -> None:
        try:
            await self.transport.disconnect()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
        self.connected = False
        self.rpc = None
        self._sd_card_available = None
        self._mode = LinkMode.UNKNOWN

    def mode(self) -> LinkMode:
        """Return the current link mode (UNKNOWN until the first enter_*)."""
        return self._mode

    async def enter_rpc(self) -> LinkMode:
        """Drive the link into nanopb RPC mode and record it.

        Holds the shared I/O lock for the whole negotiation so no CLI or RPC
        traffic interleaves with the mode switch.

        Returns:
            The resulting link mode (RPC on success, UNKNOWN if no RPC layer).
        """
        if self.rpc is None:
            return self._mode
        async with self._io_lock:
            await self.rpc._ensure_rpc_session_started()
            self._mode = LinkMode.RPC
        return self._mode

    async def enter_cli(self) -> LinkMode:
        """Drive the link into text CLI mode and record it.

        Sends a StopSession frame to leave RPC mode, drains residual output to
        the CLI prompt, and resets the RPC session flag. Holds the shared I/O
        lock for the whole switch so no traffic interleaves.

        Returns:
            The resulting link mode (CLI on success, UNKNOWN if no RPC layer).
        """
        if self.rpc is None:
            return self._mode
        async with self._io_lock:
            await self.rpc.send_stop_session()
            self._mode = LinkMode.CLI
        return self._mode

    async def get_connection_health(self, probe_rpc: bool = True) -> ConnectionHealth:
        ts = datetime.now(UTC).isoformat()
        transport_connected = False
        try:
            transport_connected = bool(await self.transport.is_connected())
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)

        rpc_responsive: bool | None = None
        if probe_rpc:
            rpc_responsive = False
            if transport_connected and self.rpc is not None:
                try:
                    echoed = await self.rpc.ping(_HEALTH_PROBE)
                    rpc_responsive = echoed == _HEALTH_PROBE
                except (OSError, RuntimeError) as exc:
                    self.last_connection_error = str(exc)
                if not rpc_responsive and self.last_connection_error is None:
                    self.last_connection_error = "RPC ping unanswered"

        connected = transport_connected and (rpc_responsive if probe_rpc else True)
        return {
            "timestamp": ts,
            "connected": bool(connected),
            "transport_connected": transport_connected,
            "rpc_responsive": rpc_responsive,
            "transport": {"type": self.transport.get_name()},
            "last_error": self.last_connection_error,
        }

    async def get_device_info(self) -> dict[str, Any]:
        if self.rpc is None:
            return {"name": "Flipper Zero", "hardware": "Unknown", "firmware": "Unknown"}
        try:
            info = await self.rpc.get_device_info()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
            info = {}
        return {
            "name": info.get("hardware_name") or info.get("name") or "Flipper Zero",
            "hardware": info.get("hardware_model") or info.get("hardware") or "Unknown",
            "firmware": info.get("firmware_version") or info.get("firmware") or "Unknown",
            **{k: v for k, v in info.items() if k not in _NORMALIZED_SOURCE_KEYS},
        }

    async def check_sd_card_available(self) -> bool:
        """Report whether an SD card is mounted at /ext.

        The result is cached for the lifetime of the current connection; the
        cache is reset on every connect/disconnect.
        """
        if self._sd_card_available is not None:
            return self._sd_card_available
        available = False
        if self.rpc is not None:
            try:
                info = await self.rpc.storage_info("/ext")
                available = bool(info and info[0] > 0)
            except (OSError, RuntimeError) as exc:
                self.last_connection_error = str(exc)
        self._sd_card_available = available
        return available

    async def cli_exec(
        self,
        command: str,
        timeout_s: float = 10.0,
        accept_responsibility: bool = False,
        tx_tools_enabled: bool = False,
    ) -> CliExecResult:
        """Run one Flipper CLI command in CLI text mode (USB only).

        Drives the device into CLI mode, sends one command, and reads output up
        to the ``>:`` prompt. Streaming/interactive commands (e.g. ``subghz rx``,
        ``ir rx``, ``log``) never return to the prompt and time out with
        ``completed=False`` and partial output.

        Gated (transmit/destructive) commands require BOTH gates: the operator
        env flag (``tx_tools_enabled``, from ``FLIPPER_ENABLE_TX_TOOLS``) and the
        per-call ``accept_responsibility``. Either missing -> refused.

        Args:
            command: Raw CLI command line; one command only (no shell chaining).
            timeout_s: Seconds to wait for the ``>:`` prompt before returning.
            accept_responsibility: Per-call intent for gated commands.
            tx_tools_enabled: Operator env opt-in for gated commands.

        Returns:
            A CliExecResult with output, completed, risk, and warning.

        Raises:
            FlipperNotConnectedError: if no live RPC layer is available.
            FlipperCLIUnavailableError: if the transport has no CLI text mode.
            FlipperCLIRefusedError: on shell chaining or a gated command missing a gate.
        """
        if self.rpc is None:
            raise FlipperNotConnectedError(self.last_connection_error or "device unavailable")
        if not self.transport.supports_cli_text_mode:
            raise FlipperCLIUnavailableError("CLI text mode unavailable over WiFi bridge")
        self._reject_shell_chaining(command)
        risk = classify(command)
        if risk.gated:
            self._enforce_tx_gate(risk.warning, accept_responsibility, tx_tools_enabled)
        rpc = self.rpc
        async with self._io_lock:
            output, completed = await self._cli_exchange(rpc, command, timeout_s)
        return {
            "output": output,
            "completed": completed,
            "risk": risk.category,
            "warning": risk.warning,
        }

    @staticmethod
    def _reject_shell_chaining(command: str) -> None:
        for token in _SHELL_CHAINING:
            if token in command:
                raise FlipperCLIRefusedError(
                    "shell chaining is not allowed; send exactly one command per call "
                    f"(found {token!r})"
                )

    @staticmethod
    def _enforce_tx_gate(
        warning: str | None, accept_responsibility: bool, tx_tools_enabled: bool
    ) -> None:
        if not tx_tools_enabled:
            raise FlipperCLIRefusedError(
                "transmit/destructive commands are disabled on this server; the operator "
                "must set FLIPPER_ENABLE_TX_TOOLS=true to allow them"
            )
        if not accept_responsibility:
            raise FlipperCLIRefusedError(warning or "command requires i_accept_responsibility=true")

    async def _cli_exchange(
        self, rpc: ProtobufRPC, command: str, timeout_s: float
    ) -> tuple[str, bool]:
        """Switch to CLI mode, send one command, and read output to the prompt.

        Caller must hold ``_io_lock``: this drives the shared link directly and
        must not interleave with RPC traffic.
        """
        await rpc.send_stop_session()
        self._mode = LinkMode.CLI
        self.transport.clear_receive_buffer()
        # Ctrl-C cancels any partially typed line; CR yields a fresh prompt.
        await self.transport.send(b"\x03\r")
        await self._read_until_prompt(timeout_s=2.0)
        self.transport.clear_receive_buffer()
        await self.transport.send(command.encode() + b"\r")
        raw, completed = await self._read_until_prompt(timeout_s)
        return _strip_cli_output(raw, command), completed

    async def _read_until_prompt(self, timeout_s: float) -> tuple[bytes, bool]:
        buf = bytearray()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), 0.0)
            chunk = await self.transport.receive(timeout=min(_CLI_READ_SLICE_S, remaining))
            if chunk:
                buf.extend(chunk)
                if buf.rstrip().endswith(_CLI_PROMPT):
                    return bytes(buf), True
        return bytes(buf), False
