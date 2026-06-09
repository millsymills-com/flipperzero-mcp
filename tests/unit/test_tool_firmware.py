"""Unit tests for the firmware_install tool gating and confirm token."""

from __future__ import annotations

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
