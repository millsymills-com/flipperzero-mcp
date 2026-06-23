"""Tool-level tests for P0 diagnostics reads (ping, property_get)."""

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

    async def get_property(self, key):
        return {"hardware.name": "Flipper"}.get(key)


def _server(monkeypatch, rpc=FakeRPC):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", rpc)
    return create_server(FlipperConfig(_env_file=None))


async def test_system_ping_returns_echo(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_system_ping", {})
        assert result.data["responded"] is True
        assert result.data["echo"] == "ping"


async def test_system_ping_raises_when_no_response(monkeypatch):
    class DeadRPC(FakeRPC):
        async def ping(self, data=b"ping"):  # noqa: ARG002
            return None

    async with Client(_server(monkeypatch, DeadRPC)) as client:
        with pytest.raises(ToolError, match="ping"):
            await client.call_tool("flipperzero_system_ping", {})


async def test_system_property_get_returns_value(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        result = await client.call_tool("flipperzero_system_property_get", {"key": "hardware.name"})
        assert result.data == {"key": "hardware.name", "value": "Flipper"}


async def test_system_property_get_raises_when_absent(monkeypatch):
    async with Client(_server(monkeypatch)) as client:
        with pytest.raises(ToolError, match="unavailable"):
            await client.call_tool("flipperzero_system_property_get", {"key": "missing.key"})
