import pytest

import flipperzero_mcp.transport as transport_mod
from flipperzero_mcp.transport import get_transport
from flipperzero_mcp.transport.auto import AutoTransport
from flipperzero_mcp.transport.base import FlipperTransport


class FakeInner(FlipperTransport):
    def __init__(self, config, *, succeed):
        super().__init__(config)
        self._succeed = succeed
        self.sent: list[bytes] = []

    async def connect(self):
        self.connected = self._succeed
        return self._succeed

    async def disconnect(self):
        self.connected = False

    async def send(self, data):
        self.sent.append(data)

    async def receive(self, timeout=None):  # noqa: ARG002
        return b""

    async def is_connected(self):
        return self.connected


def test_unknown_transport_raises():
    with pytest.raises(ValueError, match="Unknown transport"):
        get_transport("serial", {"transport": {}})


async def test_auto_prefers_usb(monkeypatch):
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.USBTransport", lambda c: FakeInner(c, succeed=True)
    )
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=True)
    )
    auto = AutoTransport({"usb": {}, "wifi": {"host": "x"}})
    assert await auto.connect() is True
    assert auto.get_name() == "FakeInner"


async def test_auto_skips_wifi_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.USBTransport", lambda c: FakeInner(c, succeed=False)
    )
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=True)
    )
    auto = AutoTransport({"usb": {}, "wifi": {}})  # no host -> wifi not configured
    assert await auto.connect() is False


async def test_auto_falls_back_to_wifi(monkeypatch):
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.USBTransport", lambda c: FakeInner(c, succeed=False)
    )
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=True)
    )
    auto = AutoTransport({"usb": {}, "wifi": {"host": "10.0.0.1", "port": 8080}})
    assert await auto.connect() is True
    assert auto.connected is True


async def test_auto_send_receive_before_connect_raise():
    auto = AutoTransport({})
    assert await auto.is_connected() is False
    assert auto.get_name() == "Auto"
    with pytest.raises(RuntimeError, match="no active connection"):
        await auto.send(b"x")
    with pytest.raises(RuntimeError, match="no active connection"):
        await auto.receive()


async def test_auto_delegates_send_receive_and_disconnect(monkeypatch):
    inner = FakeInner({}, succeed=True)

    async def _recv(timeout=None):
        return b"pong"

    inner.receive = _recv
    monkeypatch.setattr("flipperzero_mcp.transport.auto.USBTransport", lambda _c: inner)
    monkeypatch.setattr(
        "flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=False)
    )
    auto = AutoTransport({"usb": {}})
    assert await auto.connect() is True

    await auto.send(b"hello")
    assert inner.sent == [b"hello"]
    assert await auto.receive() == b"pong"
    assert await auto.is_connected() is True
    assert auto.get_name() == "FakeInner"

    await auto.disconnect()
    assert auto.connected is False
    assert await auto.is_connected() is False


async def test_auto_is_connected_false_when_inner_raises(monkeypatch):
    inner = FakeInner({}, succeed=True)

    async def _raise():
        raise OSError("link down")

    inner.is_connected = _raise
    monkeypatch.setattr("flipperzero_mcp.transport.auto.USBTransport", lambda _c: inner)
    auto = AutoTransport({"usb": {}})
    await auto.connect()
    assert await auto.is_connected() is False


def test_get_transport_returns_usb(monkeypatch):
    captured = {}

    def factory(c):
        captured["cfg"] = c
        return FakeInner(c, succeed=True)

    # The factory resolves classes from the module-level _TRANSPORTS mapping.
    monkeypatch.setitem(transport_mod._TRANSPORTS, "usb", factory)
    t = get_transport("usb", {"transport": {"usb": {"port": "/dev/null", "baudrate": 9600}}})
    assert isinstance(t, FakeInner)
    assert captured["cfg"] == {"port": "/dev/null", "baudrate": 9600}


def test_get_transport_returns_wifi(monkeypatch):
    monkeypatch.setitem(transport_mod._TRANSPORTS, "wifi", lambda c: FakeInner(c, succeed=True))
    t = get_transport("wifi", {"transport": {"wifi": {"host": "x", "port": 8080}}})
    assert isinstance(t, FakeInner)


def test_get_transport_returns_auto():
    t = get_transport("auto", {"transport": {"usb": {}, "wifi": {}}})
    assert isinstance(t, AutoTransport)
