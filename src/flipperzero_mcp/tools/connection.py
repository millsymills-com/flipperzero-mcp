"""Connection health and reconnect tools (always callable, even when disconnected)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from flipperzero_mcp.rpc.client import ReconnectHealth
from flipperzero_mcp.tools._common import get_client


def register_connection_tools(mcp: FastMCP) -> None:
    """Register connection health/reconnect tools."""

    @mcp.tool(tags={"flipper", "connection"})
    async def flipperzero_connection_health(ctx: Context, probe_rpc: bool = True) -> dict[str, Any]:
        """Return authoritative Flipper connection health.

        Args:
            probe_rpc: If true, send a protobuf RPC ping to confirm RPC responsiveness.

        Returns:
            Health dict: timestamp, connected, transport_connected, rpc_responsive,
            transport, last_error.
        """
        return dict(await get_client(ctx).get_connection_health(probe_rpc=probe_rpc))

    @mcp.tool(tags={"flipper", "connection"})
    async def flipperzero_connection_reconnect(
        ctx: Context, probe_rpc: bool = True
    ) -> dict[str, Any]:
        """Disconnect and reconnect to the Flipper, then return updated health.

        Args:
            probe_rpc: If true, ping RPC after reconnect to confirm responsiveness.

        Returns:
            Health dict plus reconnect_ok (bool).
        """
        client = get_client(ctx)
        await client.disconnect()
        reconnect_ok = await client.connect()
        health = await client.get_connection_health(probe_rpc=probe_rpc)
        result: ReconnectHealth = {**health, "reconnect_ok": reconnect_ok}
        return dict(result)
