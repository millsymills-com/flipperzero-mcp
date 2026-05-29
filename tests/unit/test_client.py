from flipperzero_mcp.rpc.client import FlipperClient


class FakeTransport:
    def __init__(self, connected=True):
        self._connected = connected

    def get_name(self):
        return "Fake"

    async def connect(self):
        return self._connected

    async def disconnect(self):
        self._connected = False

    async def is_connected(self):
        return self._connected


class FakeRPC:
    def __init__(self, transport):
        self._transport = transport

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Flipper", "firmware_version": "1.0.0"}

    async def storage_info(self, path):  # noqa: ARG002
        return (1000, 500)


async def test_health_connected_and_rpc_responsive(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    assert await client.connect() is True
    health = await client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    assert health["transport_connected"] is True
    assert health["rpc_responsive"] is True
    assert health["transport"]["type"] == "Fake"


async def test_health_reports_disconnected_transport(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport(connected=False))
    await client.connect()
    health = await client.get_connection_health(probe_rpc=True)
    assert health["connected"] is False


async def test_device_info_normalizes(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    info = await client.get_device_info()
    assert info["firmware"] == "1.0.0"


async def test_sd_card_available_true(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    assert await client.check_sd_card_available() is True
