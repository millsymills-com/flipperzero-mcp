"""P2 typed CLI-text read tools and their parsers (USB only)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server
from flipperzero_mcp.tools.cli_typed import (
    _parse_free,
    _parse_i2c,
    _parse_loader_list,
    _parse_tree,
)

# Real device output captured over USB (see PR notes); ANSI escapes preserved.
_FREE = (
    "Free heap size: 120488\nTotal heap size: 189648\nMinimum heap size: 110144\n"
    "Maximum heap block: 108784\nPool free: 1092\nMaximum pool block: 888"
)
_TREE = (
    "[D] /ext/badusb\n\t[D] /ext/badusb/Demos\n"
    "\t[F] /ext/badusb/Demos/demo_macos.txt 1636b\n"
    "\t[F] /ext/badusb/Demos/test_mouse.txt 628b"
)
_APP_OPEN_UPTIME = "\x1b[31mthis command cannot be run while an application is open\x1b[0m"
# Real `i2c` scan grid: 16 columns (low nibble), rows are the high nibble.
_I2C_EMPTY = (
    "Scanning external i2c on PC0(SCL)/PC1(SDA)\nClock: 100khz, 7bit address\n\n"
    "  | 0 1 2 3 4 5 6 7 8 9 A B C D E F\n"
    "--+--------------------------------\n"
    "0 | - - - - - - - - - - - - - - - - \n"
    "6 | - - - - - - - - - - - - - - - - \n"
    "7 | - - - - - - - - - - - - - - - -"
)
# Same grid with a device responding at 0x68 (row 6, column 8).
_I2C_ONE = (
    "  | 0 1 2 3 4 5 6 7 8 9 A B C D E F\n"
    "--+--------------------------------\n"
    "6 | - - - - - - - - 68 - - - - - - - "
)


# --- parsers (pure, format-grounded) -----------------------------------------


def test_parse_free_extracts_named_int_fields():
    heap = _parse_free(_FREE)
    assert heap["free_heap_size"] == 120488
    assert heap["total_heap_size"] == 189648
    assert heap["maximum_pool_block"] == 888


def test_parse_free_ignores_non_numeric_and_blank_lines():
    assert _parse_free("garbage\nFree heap size: 42\n\nName: not_a_number") == {
        "free_heap_size": 42
    }


def test_parse_tree_tags_type_size_and_depth():
    entries = _parse_tree(_TREE)
    assert entries[0] == {"type": "dir", "path": "/ext/badusb", "size_bytes": None, "depth": 0}
    assert entries[1] == {
        "type": "dir",
        "path": "/ext/badusb/Demos",
        "size_bytes": None,
        "depth": 1,
    }
    assert entries[2] == {
        "type": "file",
        "path": "/ext/badusb/Demos/demo_macos.txt",
        "size_bytes": 1636,
        "depth": 1,
    }


def test_parse_tree_skips_unrecognized_lines():
    assert _parse_tree("Storage error: not found\n>: ") == []


def test_parse_i2c_maps_grid_position_to_address():
    assert _parse_i2c(_I2C_ONE) == ["0x68"]


def test_parse_i2c_empty_grid_has_no_addresses():
    assert _parse_i2c(_I2C_EMPTY) == []


def test_parse_loader_list_drops_headers_and_blanks():
    out = "Applications:\nSubGHz\nNFC\n\nPlugins:\nSnake Game"
    assert _parse_loader_list(out) == ["SubGHz", "NFC", "Snake Game"]


# --- tool end-to-end ---------------------------------------------------------


class FakeTransport:
    def __init__(self, supports_cli=True):
        self._supports_cli = supports_cli

    @property
    def supports_cli_text_mode(self):
        return self._supports_cli

    def get_name(self):
        return "USB" if self._supports_cli else "WiFi"

    def clear_receive_buffer(self):
        return None

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def is_connected(self):
        return True


def _server(monkeypatch, outputs, *, supports_cli=True):
    """Build a server whose client.cli_exec replays `outputs` keyed by command."""

    async def fake_cli_exec(self, command, timeout_s=10.0, **_kwargs):
        if not self.transport.supports_cli_text_mode:
            from flipperzero_mcp.errors import FlipperCLIUnavailableError

            raise FlipperCLIUnavailableError("CLI text mode unavailable over WiFi bridge")
        return {"output": outputs[command], "completed": True, "risk": "benign", "warning": None}

    monkeypatch.setattr(
        "flipperzero_mcp.server.get_transport",
        lambda _t, _c: FakeTransport(supports_cli=supports_cli),
    )
    monkeypatch.setattr("flipperzero_mcp.rpc.client.FlipperClient.cli_exec", fake_cli_exec)
    return create_server(FlipperConfig(_env_file=None))


async def test_core_status_parses_heap_and_app_open_uptime(monkeypatch):
    server = _server(monkeypatch, {"free": _FREE, "uptime": _APP_OPEN_UPTIME})
    async with Client(server) as client:
        data = (await client.call_tool("flipperzero_core_status", {})).data
        assert data["heap_free_bytes"] == 120488
        assert data["uptime"] is None  # refused while an app is open
        assert data["raw"]["free"] == _FREE


async def test_fs_tree_returns_entries_and_complete(monkeypatch):
    server = _server(monkeypatch, {"storage tree /ext/badusb": _TREE})
    async with Client(server) as client:
        data = (await client.call_tool("flipperzero_fs_tree", {"path": "/ext/badusb"})).data
        assert data["complete"] is True
        assert data["truncated"] is False
        assert len(data["entries"]) == 4


async def test_fs_tree_rejects_relative_path(monkeypatch):
    server = _server(monkeypatch, {})
    async with Client(server) as client:
        with pytest.raises(ToolError, match="absolute"):
            await client.call_tool("flipperzero_fs_tree", {"path": "ext/badusb"})


async def test_i2c_scan_reports_addresses(monkeypatch):
    server = _server(monkeypatch, {"i2c": _I2C_ONE})
    async with Client(server) as client:
        data = (await client.call_tool("flipperzero_i2c_scan", {})).data
        assert data["addresses"] == ["0x68"]
        assert data["count"] == 1


async def test_loader_list_returns_apps(monkeypatch):
    # Real `loader list` groups under "Apps:"/"Settings:" headers, tab-indented.
    server = _server(monkeypatch, {"loader list": "Apps:\n\tSub-GHz\n\tNFC\nSettings:\n\tPower"})
    async with Client(server) as client:
        data = (await client.call_tool("flipperzero_loader_list", {})).data
        assert data["apps"] == ["Sub-GHz", "NFC", "Power"]


async def test_cli_typed_tool_unavailable_over_wifi(monkeypatch):
    server = _server(monkeypatch, {"i2c": ""}, supports_cli=False)
    async with Client(server) as client:
        with pytest.raises(ToolError, match="CLI text mode unavailable"):
            await client.call_tool("flipperzero_i2c_scan", {})
