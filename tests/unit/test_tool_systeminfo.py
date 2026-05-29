from fastmcp import Client

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
    def __init__(self, transport):
        pass

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Flipper", "firmware_version": "1.2.3"}

    async def storage_info(self, _path):
        return (1000, 500)


async def test_systeminfo_returns_structured(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("systeminfo_get", {})
        data = result.data
        assert data["connected"] is True
        assert data["device"]["firmware"] == "1.2.3"
        assert data["sd_card_available"] is True
        assert data["transport"] == "Fake"
