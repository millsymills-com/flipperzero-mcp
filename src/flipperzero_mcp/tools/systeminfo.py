"""System information tool for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from flipperzero_mcp.errors import handle_client_error
from flipperzero_mcp.tools._common import ensure_connected


def register_systeminfo_tools(mcp: FastMCP) -> None:
    """Register the systeminfo tool."""

    @mcp.tool(tags={"flipper", "systeminfo"})
    async def flipper_system_info(ctx: Context) -> dict[str, Any]:
        """Get system information about the connected Flipper Zero.

        Args:
            ctx: FastMCP request context (injected).

        Returns:
            Dict with connection status, transport, device info (name/hardware/firmware),
            and SD-card availability.

        Raises:
            ToolError: If the Flipper is unreachable or the RPC call fails.
        """
        try:
            client = await ensure_connected(ctx)
            health = await client.get_connection_health(probe_rpc=True)
            device = await client.get_device_info()
            sd = await client.check_sd_card_available()
        except Exception as e:
            handle_client_error(e)
        return {
            "connected": health["connected"],
            "transport": health["transport"]["type"],
            "rpc_responsive": health["rpc_responsive"],
            "device": device,
            "sd_card_available": sd,
        }
