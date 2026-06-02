from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def __init__(self):
        self.connected = True

    def get_name(self):
        return "Fake"

    async def connect(self):
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False

    async def is_connected(self):
        return self.connected


class FakeRPC:
    def __init__(self, transport, *, io_lock=None):
        pass

    async def ping(self, data=b"ping"):
        return data


def _make_server(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    return create_server(FlipperConfig(_env_file=None))


async def test_health_tool_reports_connected(monkeypatch):
    server = _make_server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipper_connection_health", {"probe_rpc": True})
        assert result.data["connected"] is True


async def test_reconnect_tool_returns_health(monkeypatch):
    server = _make_server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipper_connection_reconnect", {})
        assert result.data["reconnect_ok"] is True
