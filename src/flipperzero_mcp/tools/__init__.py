"""MCP tool registration for the Flipper Zero."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register every Flipper tool on the server."""
    from flipperzero_mcp.tools.apps import register_app_tools
    from flipperzero_mcp.tools.cli import register_cli_tools
    from flipperzero_mcp.tools.connection import register_connection_tools
    from flipperzero_mcp.tools.firmware import register_firmware_tools
    from flipperzero_mcp.tools.storage import register_storage_tools
    from flipperzero_mcp.tools.systeminfo import register_systeminfo_tools

    register_connection_tools(mcp)
    register_systeminfo_tools(mcp)
    register_storage_tools(mcp)
    register_cli_tools(mcp)
    register_app_tools(mcp)
    register_firmware_tools(mcp)
