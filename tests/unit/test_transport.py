import pytest

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
