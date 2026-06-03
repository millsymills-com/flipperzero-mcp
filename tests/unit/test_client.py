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
    def __init__(self, transport, *, io_lock=None):  # noqa: ARG002
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


class RaisingConnectTransport(FakeTransport):
    async def connect(self):
        raise OSError("port busy")


async def test_connect_returns_false_when_transport_raises(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(RaisingConnectTransport())
    assert await client.connect() is False
    assert client.connected is False
    assert client.rpc is None
    assert client.last_connection_error == "port busy"


async def test_connect_returns_false_when_transport_returns_false(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport(connected=False))
    assert await client.connect() is False
    assert client.rpc is None


async def test_health_transport_connected_false_when_is_connected_raises(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)

    class T(FakeTransport):
        async def is_connected(self):
            raise RuntimeError("link down")

    client = FlipperClient(T())
    await client.connect()
    health = await client.get_connection_health(probe_rpc=True)
    assert health["transport_connected"] is False
    assert health["connected"] is False
    assert client.last_connection_error == "link down"


async def test_health_rpc_responsive_false_when_ping_raises(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()

    async def boom(_data):
        raise OSError("no echo")

    client.rpc.ping = boom
    health = await client.get_connection_health(probe_rpc=True)
    assert health["transport_connected"] is True
    assert health["rpc_responsive"] is False
    assert health["connected"] is False
    assert client.last_connection_error == "no echo"


async def test_health_rpc_unresponsive_records_reason_when_ping_returns_none(monkeypatch):
    class NoEchoRPC(FakeRPC):
        async def ping(self, data=b"ping"):  # noqa: ARG002
            return None

    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", NoEchoRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    health = await client.get_connection_health(probe_rpc=True)
    assert health["transport_connected"] is True
    assert health["rpc_responsive"] is False
    assert health["connected"] is False
    assert health["last_error"] == "RPC ping unanswered"
    assert client.last_connection_error == "RPC ping unanswered"


async def test_health_without_probe_reports_none(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    health = await client.get_connection_health(probe_rpc=False)
    assert health["rpc_responsive"] is None
    assert health["connected"] == health["transport_connected"] is True


async def test_device_info_unknown_when_rpc_none():
    client = FlipperClient(FakeTransport())
    info = await client.get_device_info()
    assert info == {"name": "Flipper Zero", "hardware": "Unknown", "firmware": "Unknown"}


async def test_device_info_fallback_when_rpc_raises(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()

    async def boom():
        raise RuntimeError("rpc dead")

    client.rpc.get_device_info = boom
    info = await client.get_device_info()
    assert info == {"name": "Flipper Zero", "hardware": "Unknown", "firmware": "Unknown"}
    assert client.last_connection_error == "rpc dead"


async def test_sd_card_false_when_rpc_none():
    client = FlipperClient(FakeTransport())
    assert await client.check_sd_card_available() is False


async def test_sd_card_caches_result(monkeypatch):
    calls = {"n": 0}

    class CountingRPC(FakeRPC):
        async def storage_info(self, path):  # noqa: ARG002
            calls["n"] += 1
            return (1000, 500)

    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", CountingRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    assert await client.check_sd_card_available() is True
    assert await client.check_sd_card_available() is True
    assert calls["n"] == 1


async def test_sd_card_false_when_storage_info_raises(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()

    async def boom(_path):
        raise OSError("no sd")

    client.rpc.storage_info = boom
    assert await client.check_sd_card_available() is False
    assert client.last_connection_error == "no sd"


async def test_disconnect_records_error(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)

    class T(FakeTransport):
        async def disconnect(self):
            raise RuntimeError("usb yanked")

    client = FlipperClient(T())
    await client.connect()
    await client.disconnect()
    assert client.connected is False
    assert client.rpc is None
    assert client.last_connection_error == "usb yanked"
