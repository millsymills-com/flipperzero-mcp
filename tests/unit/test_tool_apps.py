import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def get_name(self):
        return "Fake"

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def is_connected(self):
        return True


class FakeRPC:
    def __init__(self, _transport, *, io_lock=None):
        _ = io_lock
        self.started: list[tuple[str, str]] = []

    async def ping(self, data=b"ping"):
        return data

    async def app_start(self, name, args=""):
        if name == "Missing":
            return False
        self.started.append((name, args))
        return True


async def _server(monkeypatch, *, enable_write_tools=False):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    return create_server(FlipperConfig(_env_file=None, enable_write_tools=enable_write_tools))


async def test_app_start_is_gated_by_write_flag(monkeypatch):
    server = await _server(monkeypatch)
    async with Client(server) as client:
        with pytest.raises(ToolError, match=r"(?i)write tools are disabled"):
            await client.call_tool("flipperzero_app_start", {"name": "Infrared"})


async def test_app_start_returns_started(monkeypatch):
    server = await _server(monkeypatch, enable_write_tools=True)
    async with Client(server) as client:
        result = await client.call_tool(
            "flipperzero_app_start", {"name": "Infrared", "args": "/ext/foo.ir"}
        )
        assert result.data == {"name": "Infrared", "args": "/ext/foo.ir", "started": True}


async def test_app_start_fails_loud_when_firmware_refuses(monkeypatch):
    server = await _server(monkeypatch, enable_write_tools=True)
    async with Client(server) as client:
        with pytest.raises(ToolError, match="failed to start app"):
            await client.call_tool("flipperzero_app_start", {"name": "Missing"})
