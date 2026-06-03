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
        return {"hardware_name": "Flipper", "firmware_version": "1.2.3"}

    async def storage_info(self, _path):
        return (1000, 500)

    async def system_power_info(self):
        return {"battery_charge": "90", "charge_state": "charging"}

    async def system_protobuf_version(self):
        return {"major": 1, "minor": 4}

    async def system_datetime(self):
        return {
            "year": 2026,
            "month": 6,
            "day": 3,
            "hour": 12,
            "minute": 34,
            "second": 56,
            "weekday": 3,
        }


async def test_systeminfo_returns_structured(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_system_info", {})
        data = result.data
        assert data["connected"] is True
        assert data["device"]["firmware"] == "1.2.3"
        assert data["sd_card_available"] is True
        assert data["transport"] == "Fake"


async def test_system_power_info_returns_key_values(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_system_power_info", {})
        assert result.data["power"]["battery_charge"] == "90"


async def test_system_protobuf_version_returns_major_minor(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_system_protobuf_version", {})
        assert result.data == {"protobuf_version": {"major": 1, "minor": 4}}


async def test_system_datetime_returns_device_fields(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_system_datetime", {})
        assert result.data["datetime"]["year"] == 2026
        assert result.data["datetime"]["second"] == 56


async def test_systeminfo_surfaces_error_when_unreachable(monkeypatch):
    class DeadTransport:
        def get_name(self):
            return "Dead"

        async def connect(self):
            return False

        async def disconnect(self):
            return None

        async def is_connected(self):
            return False

    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: DeadTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="not connected"):
            await client.call_tool("flipperzero_system_info", {})
