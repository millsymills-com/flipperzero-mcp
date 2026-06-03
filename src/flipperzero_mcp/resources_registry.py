"""Register bundled markdown files as MCP resources under flipper:// URIs."""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

_RESOURCES: dict[str, str] = {
    "flipper://reference/cli": "reference_cli.md",
    "flipper://reference/connection": "reference_connection.md",
    "flipper://reference/filesystem": "reference_filesystem.md",
    "flipper://reference/system": "reference_system.md",
    "flipper://workflow/install-app": "workflow_install_app.md",
    "flipper://workflow/transfer-files": "workflow_transfer_files.md",
    "flipper://workflow/flash-esp32": "workflow_flash_esp32.md",
    "flipper://workflow/capture-replay": "workflow_capture_replay.md",
}


def _read(filename: str) -> str:
    return (files("flipperzero_mcp.resources") / filename).read_text(encoding="utf-8")


def _reader_for(filename: str) -> Callable[[], str]:
    def _reader() -> str:
        return _read(filename)

    return _reader


def register_resources(mcp: FastMCP) -> None:
    """Register every bundled markdown resource on the server.

    Args:
        mcp: The FastMCP server to attach the ``flipper://`` resources to.

    Returns:
        None. Resources are registered as a side effect.
    """
    for uri, filename in _RESOURCES.items():
        mcp.resource(uri, mime_type="text/markdown")(_reader_for(filename))
