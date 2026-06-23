"""Tool-level tests for P1 device reads (app/desktop/gpio)."""

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

    async def app_lock_status(self):
        return False

    async def app_get_error(self):
        return {"code": 0, "text": ""}

    async def desktop_is_locked(self):
        return True

    async def gpio_read(self, pin):
        return {"pin": pin, "mode": "input", "value": 1}


def _server(monkeypatch, rpc=FakeRPC):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", rpc)
    return create_server(FlipperConfig(_env_file=None))


async def test_app_lock_status_returns_locked(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_app_lock_status", {})
        assert result.data == {"locked": False}


async def test_app_lock_status_raises_when_unavailable(monkeypatch):
    class DeadRPC(FakeRPC):
        async def app_lock_status(self):
            return None

    async with Client(_server(monkeypatch, DeadRPC)) as client:
        with pytest.raises(ToolError, match="lock status"):
            await client.call_tool("flipperzero_app_lock_status", {})


async def test_app_get_error_returns_code_text(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_app_get_error", {})
        assert result.data == {"code": 0, "text": ""}


async def test_desktop_is_locked_returns_locked(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_desktop_is_locked", {})
        assert result.data == {"locked": True}


async def test_gpio_read_returns_structure(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_gpio_read", {"pin": 3})
        assert result.data == {"pin": 3, "mode": "input", "value": 1}


async def test_gpio_read_rejects_out_of_range_pin(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        with pytest.raises(ToolError, match="pin"):
            await client.call_tool("flipperzero_gpio_read", {"pin": 99})
