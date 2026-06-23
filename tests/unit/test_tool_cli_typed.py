"""P2 typed CLI-text read tools and their parsers (USB only)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server
from flipperzero_mcp.tools._common import cli_typed
from flipperzero_mcp.tools.cli_typed import (
    _parse_free,
    _parse_i2c,
    _parse_loader_list,
    _parse_tree,
)

# Real device output captured over USB (see PR notes). This `free` output carries
# no ANSI; the `_ANSI`-bearing variants below exercise the `_strip_ansi` path.
_FREE = (
    "Free heap size: 120488\nTotal heap size: 189648\nMinimum heap size: 110144\n"
    "Maximum heap block: 108784\nPool free: 1092\nMaximum pool block: 888"
)
# Same fields wrapped in SGR color escapes, as a color-enabled shell would emit.
_FREE_ANSI = (
    "\x1b[36mFree heap size:\x1b[0m \x1b[32m120488\x1b[0m\n"
    "Total heap size: 189648\nMinimum heap size: 110144\n"
    "Maximum heap block: 108784\nPool free: 1092\nMaximum pool block: 888"
)
_TREE = (
    "[D] /ext/badusb\n\t[D] /ext/badusb/Demos\n"
    "\t[F] /ext/badusb/Demos/demo_macos.txt 1636b\n"
    "\t[F] /ext/badusb/Demos/test_mouse.txt 628b"
)
# A tab-indented `[F]` row whose content is color-wrapped after the indentation.
_TREE_ANSI = "\t[F] \x1b[33m/ext/badusb/Demos/demo_macos.txt\x1b[0m 1636b"
# Same `i2c` grid as _I2C_ONE with the responding cell color-wrapped.
_I2C_ANSI = (
    "  | 0 1 2 3 4 5 6 7 8 9 A B C D E F\n"
    "--+--------------------------------\n"
    "6 | - - - - - - - - \x1b[32m68\x1b[0m - - - - - - - "
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
# Multiple responders: 0x00 (row 0, col 0), 0x3c (row 3, col 12), 0x77 (row 7, col 7).
_I2C_MANY = (
    "  | 0 1 2 3 4 5 6 7 8 9 A B C D E F\n"
    "--+--------------------------------\n"
    "0 | 00 - - - - - - - - - - - - - - - \n"
    "3 | - - - - - - - - - - - - 3c - - - \n"
    "7 | - - - - - - - 77 - - - - - - - - "
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


def test_parse_i2c_maps_multiple_responders_across_rows():
    assert _parse_i2c(_I2C_MANY) == ["0x00", "0x3c", "0x77"]


def test_parse_i2c_ignores_rows_outside_7bit_space():
    # A row labelled with a high nibble > 7 (or extra columns) cannot encode a
    # valid 7-bit address, so it is skipped rather than emitting a bogus 0x8x+.
    assert _parse_i2c("8 | - - 82 - - - - - - - - - - - - -") == []


def test_parse_i2c_ignores_cells_past_the_16th_column():
    # The grid only spans the low nibble (16 columns). A responder in a 17th cell
    # would map past 0x?f, so the `col >= 16` guard drops it.
    assert _parse_i2c("0 | - - - - - - - - - - - - - - - - 99") == []


def test_parse_i2c_keeps_col_15_and_drops_col_16():
    # Pins the `col >= 16` boundary on both sides: col 15 is the last valid low
    # nibble (0x0f) and must be kept, while the 17th cell (col 16) overflows the
    # grid and must be dropped. A `col >= 15` or `col > 16` mutation would fail this.
    row = "0 | - - - - - - - - - - - - - - - 0f 99"
    assert _parse_i2c(row) == ["0x0f"]


def test_parse_loader_list_drops_headers_and_blanks():
    out = "Applications:\nSubGHz\nNFC\n\nPlugins:\nSnake Game"
    assert _parse_loader_list(out) == ["SubGHz", "NFC", "Snake Game"]


# --- ANSI-bearing fixtures (the _strip_ansi path) ----------------------------


def test_parse_free_strips_ansi_escapes():
    assert _parse_free(_FREE_ANSI) == _parse_free(_FREE)


def test_parse_i2c_strips_ansi_escapes():
    assert _parse_i2c(_I2C_ANSI) == ["0x68"]


def test_parse_tree_strips_ansi_with_correct_depth():
    # ANSI wraps the content *after* the leading tab, so depth (counted on tabs)
    # is unaffected and the path/size still parse cleanly.
    assert _parse_tree(_TREE_ANSI) == [
        {
            "type": "file",
            "path": "/ext/badusb/Demos/demo_macos.txt",
            "size_bytes": 1636,
            "depth": 1,
        }
    ]


def test_parse_tree_file_without_size_has_none_size():
    assert _parse_tree("[F] /ext/badusb/script.txt") == [
        {"type": "file", "path": "/ext/badusb/script.txt", "size_bytes": None, "depth": 0}
    ]


def test_parse_tree_depth_counts_tabs_when_ansi_precedes_indentation():
    # ANSI is stripped before the depth count, so a leading escape ahead of the
    # tabs no longer defeats the `lstrip("\t")` count: the row reports its real depth.
    assert _parse_tree("\x1b[33m\t[F] /ext/a.txt 10b\x1b[0m") == [
        {"type": "file", "path": "/ext/a.txt", "size_bytes": 10, "depth": 1}
    ]


def test_parse_tree_depth_counts_all_tabs_when_ansi_precedes_indentation():
    # A leading escape before *multiple* tabs: stripping ANSI before the tab count
    # lets `lstrip("\t")` see every tab, pinning "count all tabs" (depth 2 here)
    # against an off-by-one that a single-tab row would not catch.
    assert _parse_tree("\x1b[33m\t\t[F] /ext/a.txt 10b\x1b[0m") == [
        {"type": "file", "path": "/ext/a.txt", "size_bytes": 10, "depth": 2}
    ]


# --- tool end-to-end ---------------------------------------------------------


class FakeTransport:
    def __init__(
        self, supports_cli=True, *, connected=True, can_connect=True, is_connected_raises=None
    ):
        self._supports_cli = supports_cli
        self._connected = connected
        self._can_connect = can_connect
        self._is_connected_raises = is_connected_raises

    @property
    def supports_cli_text_mode(self):
        return self._supports_cli

    def get_name(self):
        return "USB" if self._supports_cli else "WiFi"

    def clear_receive_buffer(self):
        return None

    async def connect(self):
        return self._can_connect

    async def disconnect(self):
        return None

    async def is_connected(self):
        if self._is_connected_raises is not None:
            raise self._is_connected_raises
        return self._connected


def _server(
    monkeypatch,
    outputs,
    *,
    supports_cli=True,
    completed=True,
    connected=True,
    can_connect=True,
    is_connected_raises=None,
):
    """Build a server whose client.cli_exec replays `outputs` keyed by command."""

    async def fake_cli_exec(self, command, timeout_s=10.0, **_kwargs):
        if not self.transport.supports_cli_text_mode:
            from flipperzero_mcp.errors import FlipperCLIUnavailableError

            raise FlipperCLIUnavailableError("CLI text mode unavailable over WiFi bridge")
        return {
            "output": outputs[command],
            "completed": completed,
            "risk": "benign",
            "warning": None,
        }

    monkeypatch.setattr(
        "flipperzero_mcp.server.get_transport",
        lambda _t, _c: FakeTransport(
            supports_cli=supports_cli,
            connected=connected,
            can_connect=can_connect,
            is_connected_raises=is_connected_raises,
        ),
    )
    monkeypatch.setattr("flipperzero_mcp.rpc.client.FlipperClient.cli_exec", fake_cli_exec)
    return create_server(FlipperConfig(_env_file=None))  # ty: ignore[unknown-argument]


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


async def test_fs_tree_marks_truncated_when_read_window_exceeded(monkeypatch):
    server = _server(monkeypatch, {"storage tree /ext": _TREE}, completed=False)
    async with Client(server) as client:
        data = (await client.call_tool("flipperzero_fs_tree", {"path": "/ext"})).data
        assert data["complete"] is False
        assert data["truncated"] is True
        assert len(data["entries"]) == 4  # partial prefix still parsed


async def test_cli_typed_tool_unavailable_over_wifi(monkeypatch):
    server = _server(monkeypatch, {"i2c": ""}, supports_cli=False)
    async with Client(server) as client:
        with pytest.raises(ToolError, match="CLI text mode unavailable"):
            await client.call_tool("flipperzero_i2c_scan", {})


@pytest.mark.parametrize("command", ["subghz tx 123456", "storage format /ext"])
async def test_cli_typed_refuses_gated_command(command):
    # Defense in depth: the shared helper rejects any gated command before it can
    # reach the device, so a transmit/destructive subcommand can never hide behind
    # a typed tool. The check runs ahead of connection, so no real ctx is needed.
    with pytest.raises(ToolError, match="benign-only"):
        await cli_typed(None, command)  # ty: ignore[invalid-argument-type]


async def test_cli_typed_surfaces_not_connected_as_toolerror(monkeypatch):
    # The real failure mode: ensure_connected calls client.connect(); when the
    # transport cannot reconnect (connect() returns falsy) it raises, and cli_typed
    # must surface a clean ToolError via _classify_client_error -- never fall
    # through to an implicit None return. Drive it through the connect()-returns-
    # false seam rather than monkeypatching ensure_connected, so the test couples
    # to the not-connected contract, not the helper name.
    server = _server(monkeypatch, {"free": _FREE}, connected=False, can_connect=False)
    async with Client(server) as client:
        with pytest.raises(ToolError, match="not connected"):
            await client.call_tool("flipperzero_core_status", {})


async def test_cli_typed_surfaces_unexpected_error_as_toolerror(monkeypatch):
    # The catch-all path: a non-Flipper exception escaping the real ensure_connected
    # seam is still mapped to a ToolError, so no error path returns None. A ValueError
    # from transport.is_connected() is not one of the (OSError, RuntimeError) drops
    # ensure_connected tolerates, so it propagates to the catch-all. Driven through the
    # transport, not by monkeypatching the helper, so the test couples to the contract
    # rather than the helper name. Both commands are seeded so the ValueError seam is
    # the only fault source: were `ensure_connected` to widen its except to swallow the
    # ValueError, reconnect would succeed and both calls would return, failing this test.
    server = _server(
        monkeypatch,
        {"free": _FREE, "uptime": _APP_OPEN_UPTIME},
        is_connected_raises=ValueError("usb fell out"),
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="unexpected error"):
            await client.call_tool("flipperzero_core_status", {})
