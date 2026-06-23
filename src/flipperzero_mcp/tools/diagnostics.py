"""Trivial RPC read tools (ping, property get) for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.tools._common import get_rpc

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)


def register_diagnostics_tools(mcp: FastMCP) -> None:
    """Register the diagnostics tools."""

    @mcp.tool(tags={"flipper", "diagnostics"}, annotations=_READ_ONLY)
    async def flipperzero_system_ping(ctx: Context) -> dict[str, Any]:
        """Ping the Flipper RPC layer and return the echoed payload.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``responded`` (bool) and the decoded ``echo`` string.

        Raises:
            ToolError: If the device is unreachable or does not echo a response.
        """
        try:
            rpc = await get_rpc(ctx)
            echo = await rpc.ping()
        except Exception as e:
            _classify_client_error(e)
        if echo is None:
            raise ToolError("ping failed: no response from device")
        return {"responded": True, "echo": echo.decode("utf-8", errors="replace")}

    @mcp.tool(tags={"flipper", "diagnostics"}, annotations=_READ_ONLY)
    async def flipperzero_system_property_get(ctx: Context, key: str) -> dict[str, Any]:
        """Read a single firmware property value by key.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.
            key: Property key (e.g. ``hardware.name``, ``firmware.version``).

        Returns:
            Dict with the requested ``key`` and its ``value``.

        Raises:
            ToolError: If the device is unreachable or the key is unavailable.
        """
        try:
            rpc = await get_rpc(ctx)
            value = await rpc.get_property(key)
        except Exception as e:
            _classify_client_error(e)
        if value is None:
            raise ToolError(f"property {key!r} unavailable")
        return {"key": key, "value": value}
