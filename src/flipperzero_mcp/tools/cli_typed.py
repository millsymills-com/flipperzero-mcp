"""Benign CLI-text read tools (USB only) that parse output into structure (P2).

Every tool here goes through ``cli_typed`` (TP-3), so all are USB-only and raise a
typed ``CLI text mode unavailable`` error over the WiFi bridge (TP-2). Firmware CLI
output is free-form and unversioned, so each parser is lenient and always returns
the raw ``output`` alongside the structured fields.
"""

from __future__ import annotations

import re
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.tools._common import cli_typed

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TREE_LINE = re.compile(r"^\[(?P<kind>[DF])\]\s+(?P<path>.+?)(?:\s+(?P<size>\d+)b)?$")
# A populated row of the `i2c` scan grid: "<high-nibble> | <16 cells>". Rows
# only span the 7-bit space, so the high nibble is 0-7.
_I2C_ROW = re.compile(r"^(?P<high>[0-7])\s*\|\s*(?P<cells>.+)$")
_APP_OPEN = "application is open"


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _parse_free(output: str) -> dict[str, int]:
    """Parse ``free`` output (``Name: <int>`` lines) into a heap dict."""
    heap: dict[str, int] = {}
    for line in _strip_ansi(output).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        token = value.strip().split(" ", 1)[0]
        if token.isdigit():
            heap[key.strip().lower().replace(" ", "_")] = int(token)
    return heap


def _parse_tree(output: str) -> list[dict[str, Any]]:
    """Parse ``storage tree`` output into depth-tagged file/dir entries."""
    entries: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line)
        depth = len(line) - len(line.lstrip("\t"))
        match = _TREE_LINE.match(line.strip())
        if match is None:
            continue
        size = match["size"]
        entries.append(
            {
                "type": "dir" if match["kind"] == "D" else "file",
                "path": match["path"],
                "size_bytes": int(size) if size is not None else None,
                "depth": depth,
            }
        )
    return entries


def _parse_i2c(output: str) -> list[str]:
    """Extract responding 7-bit addresses from the ``i2c`` scan grid.

    The scan prints a 16-column grid; rows are the high address nibble (0-7),
    columns the low nibble. A cell holding anything but ``-`` marks a responding
    device, whose address is its (row, column) position regardless of the glyph.
    """
    addresses: list[str] = []
    for line in _strip_ansi(output).splitlines():
        match = _I2C_ROW.match(line.strip())
        if match is None:
            continue
        high = int(match["high"], 16)
        for col, cell in enumerate(match["cells"].split()):
            if col >= 16:
                break
            if cell != "-":
                addresses.append(f"0x{high * 16 + col:02x}")
    return addresses


def _parse_loader_list(output: str) -> list[str]:
    """Extract application names from ``loader list`` output.

    Header lines (ending in ``:``) and blank lines are dropped; everything else is
    treated as one application entry.
    """
    apps: list[str] = []
    for line in _strip_ansi(output).splitlines():
        name = line.strip()
        if name and not name.endswith(":"):
            apps.append(name)
    return apps


def register_cli_typed_tools(mcp: FastMCP) -> None:
    """Register the P2 typed CLI-text read tools (USB only)."""

    @mcp.tool(tags={"flipper", "cli_typed"}, annotations=_READ_ONLY)
    async def flipperzero_core_status(ctx: Context) -> dict[str, Any]:
        """Report core runtime status: free heap and uptime (USB only).

        Bundles two benign reads (``free`` then ``uptime``) into one result. Each
        runs as its own CLI exchange. ``uptime`` is unavailable while a foreground
        app holds the device, in which case ``uptime`` is ``None``.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``heap`` (parsed ``free`` fields), ``heap_free_bytes``
            (``int`` or ``None``), ``uptime`` (``str`` or ``None``), and ``raw``
            (the unparsed ``free``/``uptime`` output).

        Raises:
            ToolError: If the device is unreachable or the transport has no CLI
                text mode (WiFi bridge).
        """
        free = await cli_typed(ctx, "free")
        uptime = await cli_typed(ctx, "uptime")
        heap = _parse_free(free["output"])
        uptime_text = _strip_ansi(uptime["output"]).strip()
        return {
            "heap": heap,
            "heap_free_bytes": heap.get("free_heap_size"),
            "uptime": None if _APP_OPEN in uptime_text else (uptime_text or None),
            "raw": {"free": free["output"], "uptime": uptime["output"]},
        }

    @mcp.tool(tags={"flipper", "cli_typed"}, annotations=_READ_ONLY)
    async def flipperzero_fs_tree(ctx: Context, path: str) -> dict[str, Any]:
        """List a storage subtree recursively (USB only).

        Wraps ``storage tree <path>``. A large subtree (e.g. ``/ext``) can exceed
        the read window: ``complete`` is then ``false``, ``truncated`` is ``true``,
        and ``entries`` holds only the prefix read so far. Pass a specific
        subdirectory rather than a whole volume.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.
            path: Absolute device path to walk (must start with ``/``), e.g.
                ``/ext/subghz``.

        Returns:
            Dict with ``path``, ``entries`` (each ``{type, path, size_bytes,
            depth}``; ``size_bytes`` is ``None`` for directories), ``complete``
            (bool), ``truncated`` (bool), and ``raw`` (unparsed output).

        Raises:
            ToolError: If ``path`` is not absolute, the device is unreachable, or
                the transport has no CLI text mode (WiFi bridge).
        """
        if not path.startswith("/"):
            raise ToolError(f"path must be absolute (start with '/'), got {path!r}")
        result = await cli_typed(ctx, f"storage tree {path}")
        return {
            "path": path,
            "entries": _parse_tree(result["output"]),
            "complete": result["completed"],
            "truncated": not result["completed"],
            "raw": result["output"],
        }

    @mcp.tool(tags={"flipper", "cli_typed"}, annotations=_READ_ONLY)
    async def flipperzero_loader_list(ctx: Context) -> dict[str, Any]:
        """List the applications the loader can start (USB only).

        Wraps ``loader list``.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``apps`` (list of application names) and ``raw`` (unparsed
            output).

        Raises:
            ToolError: If the device is unreachable or the transport has no CLI
                text mode (WiFi bridge).
        """
        result = await cli_typed(ctx, "loader list")
        return {"apps": _parse_loader_list(result["output"]), "raw": result["output"]}

    @mcp.tool(tags={"flipper", "cli_typed"}, annotations=_READ_ONLY)
    async def flipperzero_i2c_scan(ctx: Context) -> dict[str, Any]:
        """Scan the external I2C bus and report responding addresses (USB only).

        Wraps ``i2c``.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``addresses`` (detected 7-bit addresses as ``0x..`` strings),
            ``count`` (int), and ``raw`` (unparsed output).

        Raises:
            ToolError: If the device is unreachable or the transport has no CLI
                text mode (WiFi bridge).
        """
        result = await cli_typed(ctx, "i2c")
        addresses = _parse_i2c(result["output"])
        return {"addresses": addresses, "count": len(addresses), "raw": result["output"]}
