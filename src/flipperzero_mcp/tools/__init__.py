"""MCP tool registration for the Flipper Zero."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register every Flipper tool on the server."""
    from flipperzero_mcp.tools.connection import register_connection_tools

    register_connection_tools(mcp)
