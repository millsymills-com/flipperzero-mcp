"""Shared helpers for Flipper MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flipperzero_mcp.errors import FlipperNotConnectedError

if TYPE_CHECKING:
    from fastmcp import Context

    from flipperzero_mcp.rpc.client import FlipperClient
    from flipperzero_mcp.server import ServerContext


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return ctx.lifespan_context  # ty: ignore[invalid-return-type]


def get_client(ctx: Context) -> FlipperClient:
    """Return the FlipperClient owned by the lifespan."""
    return get_server_context(ctx).client


async def ensure_connected(ctx: Context) -> FlipperClient:
    """Guarantee a live transport, attempting one reconnect on a mid-session drop.

    Replaces upstream's central call_tool reconnect wrapper. Every hardware-touching
    tool calls this first; the connection tools do NOT (they must run while down).

    Raises:
        FlipperNotConnectedError: if the device is down and a single reconnect fails.
    """
    client = get_client(ctx)
    try:
        if await client.transport.is_connected():
            return client
    except (OSError, RuntimeError):
        pass  # transport check failed — fall through to reconnect attempt
    await client.disconnect()
    if await client.connect():
        return client
    raise FlipperNotConnectedError(client.last_connection_error or "device unavailable")
