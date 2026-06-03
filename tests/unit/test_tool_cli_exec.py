"""flipperzero_cli_exec tool, client.cli_exec, and the TX two-gate (#39)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.errors import (
    FlipperCLIRefusedError,
    FlipperCLIUnavailableError,
    FlipperNotConnectedError,
)
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.server import create_server
from flipperzero_mcp.transport.base import FlipperTransport


class ScriptedCLITransport(FlipperTransport):
    """USB-style transport that replays a queued sequence of receive() chunks."""

    def __init__(self, chunks=None, supports_cli=True):
        super().__init__({})
        self.connected = True
        self._chunks = list(
            chunks
            if chunks is not None
            else [b">: ", b"device info\r\n", b"hardware: flipper\r\n", b">: "]
        )
        self._supports_cli = supports_cli
        self.sent: list[bytes] = []

    @property
    def supports_cli_text_mode(self) -> bool:
        return self._supports_cli

    def get_name(self) -> str:
        return "USB" if self._supports_cli else "WiFi"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    async def receive(self, timeout=None) -> bytes:  # noqa: ARG002
        return self._chunks.pop(0) if self._chunks else b""

    async def is_connected(self) -> bool:
        return self.connected


class StubRPC:
    """RPC double that records StopSession without touching real protobuf."""

    def __init__(self, transport, *, io_lock=None):  # noqa: ARG002
        self.transport = transport
        self._rpc_session_started = False
        self.stop_calls = 0

    async def send_stop_session(self) -> None:
        self.stop_calls += 1
        self._rpc_session_started = False

    async def ping(self, data: bytes = b"ping") -> bytes:
        return data


def _connected_client(chunks=None, supports_cli=True) -> FlipperClient:
    transport = ScriptedCLITransport(chunks=chunks, supports_cli=supports_cli)
    client = FlipperClient(transport)
    client.rpc = StubRPC(transport, io_lock=client._io_lock)  # type: ignore[assignment]
    client.connected = True
    return client


# --- client.cli_exec: parsing ------------------------------------------------


async def test_cli_exec_strips_echo_and_prompt():
    client = _connected_client()
    result = await client.cli_exec("device info", timeout_s=1.0)
    assert result["completed"] is True
    assert result["output"] == "hardware: flipper"
    assert result["risk"] == "benign"
    assert result["warning"] is None


async def test_cli_exec_times_out_returns_incomplete():
    # No terminating prompt after the command -> streaming case.
    client = _connected_client(chunks=[b">: ", b"scanning...\r\n"])
    result = await client.cli_exec("subghz rx 433920000", timeout_s=0.3)
    assert result["completed"] is False
    assert "scanning" in result["output"]


async def test_cli_exec_without_connection_raises():
    client = FlipperClient(ScriptedCLITransport())
    with pytest.raises(FlipperNotConnectedError):
        await client.cli_exec("device info", timeout_s=1.0)


# --- client.cli_exec: shell chaining rejection -------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "device info; power off",
        "storage list && storage format /ext",
        "a || b",
        "a | b",
        "echo `id`",
        "line1\nline2",
    ],
)
async def test_cli_exec_rejects_shell_chaining(command):
    client = _connected_client()
    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(command, timeout_s=1.0)


# --- client.cli_exec: TX two-gate --------------------------------------------

_TX = "subghz tx 0x00 433920000 200 10"


async def test_cli_exec_refuses_tx_when_env_gate_off():
    client = _connected_client()
    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(_TX, timeout_s=1.0, accept_responsibility=True)


async def test_cli_exec_refuses_tx_with_env_on_but_no_acceptance():
    client = _connected_client()
    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(_TX, timeout_s=1.0, tx_tools_enabled=True)


async def test_cli_exec_runs_tx_with_both_gates():
    client = _connected_client(chunks=[b">: ", b"sending...\r\n", b">: "])
    result = await client.cli_exec(
        _TX, timeout_s=1.0, accept_responsibility=True, tx_tools_enabled=True
    )
    assert result["risk"] == "transmit"
    assert result["warning"]
    assert result["completed"] is True


# --- client.cli_exec: WiFi rejection via capability property -----------------


async def test_cli_exec_rejects_transport_without_cli_text_mode():
    client = _connected_client(supports_cli=False)
    with pytest.raises(FlipperCLIUnavailableError) as exc:
        await client.cli_exec("device info", timeout_s=1.0)
    assert "WiFi" in str(exc.value)


# --- MCP tool end-to-end -----------------------------------------------------


def _make_server(monkeypatch, *, supports_cli=True, config=None):
    transport = ScriptedCLITransport(supports_cli=supports_cli)
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: transport)
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", StubRPC)
    return create_server(config or FlipperConfig(_env_file=None))


async def test_cli_exec_tool_benign(monkeypatch):
    server = _make_server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_cli_exec", {"command": "device info"})
        assert result.data.output == "hardware: flipper"
        assert result.data.risk == "benign"


async def test_cli_exec_tool_refuses_tx_when_env_disabled(monkeypatch):
    server = _make_server(monkeypatch)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "flipperzero_cli_exec",
                {"command": _TX, "i_accept_responsibility": True},
            )


async def test_cli_exec_tool_runs_tx_when_env_enabled_and_accepted(monkeypatch):
    config = FlipperConfig(_env_file=None, enable_tx_tools=True)
    server = _make_server(monkeypatch, config=config)
    async with Client(server) as client:
        result = await client.call_tool(
            "flipperzero_cli_exec",
            {"command": _TX, "i_accept_responsibility": True},
        )
        assert result.data.risk == "transmit"


async def test_cli_exec_tool_errors_without_cli_transport(monkeypatch):
    server = _make_server(monkeypatch, supports_cli=False)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("flipperzero_cli_exec", {"command": "device info"})
