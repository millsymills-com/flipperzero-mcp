"""Shared helpers for Flipper MCP tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import FlipperNotConnectedError, _classify_client_error
from flipperzero_mcp.rpc.cli_risk import classify

if TYPE_CHECKING:
    from fastmcp import Context

    from flipperzero_mcp.rpc.client import CliExecResult, FlipperClient
    from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
    from flipperzero_mcp.server import ServerContext

logger = logging.getLogger(__name__)


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return ctx.lifespan_context  # ty: ignore[invalid-return-type]


def require_write_tools(ctx: Context) -> None:
    """Gate device-mutating tools behind the write-tools opt-in.

    Args:
        ctx: FastMCP request context carrying the server config.

    Raises:
        ToolError: If ``FLIPPER_ENABLE_WRITE_TOOLS`` is not enabled.
    """
    if not get_server_context(ctx).config.enable_write_tools:
        raise ToolError(
            "Write tools are disabled. Set FLIPPER_ENABLE_WRITE_TOOLS=true to allow "
            "device-mutating storage operations (fs_push, fs_mkdir)."
        )


def require_firmware_flash(ctx: Context) -> None:
    """Gate the firmware-flash tool behind its dedicated opt-in.

    Args:
        ctx: FastMCP request context carrying the server config.

    Raises:
        ToolError: If write tools or firmware flashing are not both enabled.
    """
    require_write_tools(ctx)
    if not get_server_context(ctx).config.enable_firmware_flash:
        raise ToolError(
            "Firmware flashing is disabled. Set FLIPPER_ENABLE_FIRMWARE_FLASH=true "
            "(in addition to FLIPPER_ENABLE_WRITE_TOOLS) to allow flashing firmware."
        )


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


async def cli_typed(ctx: Context, command: str, *, timeout_s: float = 8.0) -> CliExecResult:
    """Run one benign CLI command over USB and return its raw result (TP-3).

    Shared by the typed CLI-text read tools. Reuses ``client.cli_exec`` and its
    single ``_io_lock``-held exchange verbatim, passing no transmit gate, so a
    gated subcommand can never hide behind a typed tool (it would evade the
    per-command ``cli_risk`` prefix match). Each caller parses the raw ``output``.

    Args:
        ctx: FastMCP request context carrying the shared Flipper client.
        command: Fixed benign CLI command line (one command, no shell chaining).
        timeout_s: Seconds to wait for the ``>:`` prompt before returning.

    Returns:
        The raw CliExecResult (``output``, ``completed``, ``risk``, ``warning``).

    Raises:
        ToolError: If the command is gated, the device is unreachable, the
            transport has no CLI text mode (WiFi), or the exchange fails.
    """
    if classify(command).gated:
        raise ToolError(f"cli_typed is benign-only; refusing gated command: {command!r}")
    try:
        client = await ensure_connected(ctx)
        return await client.cli_exec(command, timeout_s=timeout_s)
    except Exception as e:
        _classify_client_error(e)


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
