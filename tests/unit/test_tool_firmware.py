"""Unit tests for the firmware_install tool gating and confirm token."""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.firmware.flavor import classify
from flipperzero_mcp.server import create_server
from flipperzero_mcp.tools.firmware import _reconnect_and_classify


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
    def __init__(self, transport, *, io_lock=None):
        pass

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Lun10n", "hardware_target": "7", "firmware_version": "1.2.3"}

    async def storage_info(self, _path):
        return (1000, 500)


@pytest.mark.asyncio
async def test_firmware_install_blocked_without_flag():
    server = create_server(FlipperConfig(_env_file=None, enable_write_tools=True))  # ty: ignore[unknown-argument]
    async with Client(server) as client:
        with pytest.raises(ToolError, match="FLIPPER_ENABLE_FIRMWARE_FLASH"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"path": "/tmp/x.tgz"}, "confirm": "Lun10n"},  # noqa: S108
            )


@pytest.mark.asyncio
async def test_firmware_install_rejects_wrong_confirm_token(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(
        FlipperConfig(_env_file=None, enable_write_tools=True, enable_firmware_flash=True)  # ty: ignore[unknown-argument]
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="confirm"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"path": "/tmp/x.tgz"}, "confirm": "WRONG"},  # noqa: S108
            )


def _firmware_flash_server():
    return create_server(
        FlipperConfig(_env_file=None, enable_write_tools=True, enable_firmware_flash=True)  # ty: ignore[unknown-argument]
    )


@pytest.mark.asyncio
async def test_firmware_install_rejects_unknown_flavor(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    async with Client(_firmware_flash_server()) as client:
        with pytest.raises(ToolError, match="unknown flavor"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"flavor": "bogus"}, "confirm": "Lun10n"},
            )


@pytest.mark.asyncio
async def test_firmware_install_rejects_source_without_path_or_flavor(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    async with Client(_firmware_flash_server()) as client:
        with pytest.raises(ToolError, match=r"path.*flavor"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"channel": "release"}, "confirm": "Lun10n"},
            )


class FakeRPCNoTarget:
    def __init__(self, transport, *, io_lock=None):
        pass

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Lun10n", "hardware_target": "", "firmware_version": "1.2.3"}

    async def storage_info(self, _path):
        return (1000, 500)


@pytest.mark.asyncio
async def test_firmware_install_aborts_when_device_reports_no_target(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPCNoTarget)
    async with Client(_firmware_flash_server()) as client:
        with pytest.raises(ToolError, match="hardware target"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"flavor": "official"}, "confirm": "Lun10n"},
            )


class FakeRPCEmptyDeviceInfo:
    def __init__(self, transport, *, io_lock=None):
        pass

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {}

    async def storage_info(self, _path):
        return (1000, 500)


@pytest.mark.asyncio
async def test_firmware_install_fails_closed_when_hardware_name_missing(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPCEmptyDeviceInfo)
    server = create_server(
        FlipperConfig(_env_file=None, enable_write_tools=True, enable_firmware_flash=True)  # ty: ignore[unknown-argument]
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="identity"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"path": "/tmp/x.tgz"}, "confirm": "Flipper Zero"},  # noqa: S108
            )


def _info(version: str):
    return {"hardware_target": "7", "firmware_version": version}


class FakeReconnectClient:
    """Replays a queue of device_info dicts across reconnect polls."""

    def __init__(self, readings):
        self._readings = list(readings)
        self._info: dict[str, str] | None = None

    async def disconnect(self):
        return None

    async def connect(self):
        self._info = self._readings.pop(0) if self._readings else None
        return self._info is not None

    async def get_device_info(self):
        assert self._info is not None
        return self._info


@pytest.fixture
def _no_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("flipperzero_mcp.tools.firmware.asyncio.sleep", _instant)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_no_sleep")
async def test_reconnect_confirms_on_version_change():
    before = classify(_info("1.2.3"))
    client = FakeReconnectClient([_info("1.2.3"), _info("2.0.0")])
    after, confirmed = await _reconnect_and_classify(client, before)
    assert confirmed is True
    assert after.version == "2.0.0"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_no_sleep")
async def test_reconnect_best_effort_when_version_never_changes(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.tools.firmware._RECONNECT_BUDGET_S", 15.0)
    before = classify(_info("1.2.3"))
    client = FakeReconnectClient([_info("1.2.3"), _info("1.2.3"), _info("1.2.3")])
    after, confirmed = await _reconnect_and_classify(client, before)
    assert confirmed is False
    assert after.version == "1.2.3"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_no_sleep")
async def test_reconnect_raises_when_device_never_returns(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.tools.firmware._RECONNECT_BUDGET_S", 15.0)
    before = classify(_info("1.2.3"))
    client = FakeReconnectClient([])  # connect() always fails
    with pytest.raises(ToolError, match="did not reconnect"):
        await _reconnect_and_classify(client, before)
