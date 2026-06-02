"""Shared helpers for Flipper MCP tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flipperzero_mcp.errors import FlipperNotConnectedError

if TYPE_CHECKING:
    from fastmcp import Context

    from flipperzero_mcp.rpc.client import FlipperClient
    from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
    from flipperzero_mcp.server import ServerContext

logger = logging.getLogger(__name__)


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return ctx.lifespan_context  # ty: ignore[invalid-return-type]


def get_client(ctx: Context) -> FlipperClient:
    """Return the FlipperClient owned by the lifespan."""
    return get_server_context(ctx).client


async def ensure_connected(ctx: Context) -> FlipperClient:
    """Guarantee a live transport, attempting one reconnect on a mid-session drop.

    Every hardware-touching tool calls this first; the connection tools do NOT
    (they must run while the device is down).

    Raises:
        FlipperNotConnectedError: if the device is down and a single reconnect fails.
    """
    client = get_client(ctx)
    try:
        if await client.transport.is_connected():
            return client
    except (OSError, RuntimeError):
        logger.debug("transport.is_connected() raised; attempting reconnect", exc_info=True)
    await client.disconnect()
    if await client.connect():
        return client
    raise FlipperNotConnectedError(client.last_connection_error or "device unavailable")


async def get_rpc(ctx: Context) -> ProtobufRPC:
    """Return the live ProtobufRPC after guaranteeing a connection.

    Raises:
        FlipperNotConnectedError: If the device is down and a reconnect fails,
            or the RPC layer is somehow absent after a successful connect.
    """
    client = await ensure_connected(ctx)
    if client.rpc is None:
        raise FlipperNotConnectedError(client.last_connection_error or "RPC layer unavailable")
    return client.rpc
