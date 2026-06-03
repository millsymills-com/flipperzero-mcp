"""FastMCP server creation and lifespan for the Flipper MCP server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.transport import get_transport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerContext:
    """Lifespan context passed to all tools via ctx.lifespan_context."""

    config: FlipperConfig
    client: FlipperClient


def _build_lifespan(config: FlipperConfig):  # type: ignore[no-untyped-def]
    @lifespan  # ty: ignore[invalid-argument-type]
    async def server_lifespan(_server: FastMCP) -> AsyncIterator[ServerContext]:
        transport = get_transport(config.transport, config.as_transport_config())
        client = FlipperClient(transport)
        if await client.connect():
            logger.info("Connected to Flipper via %s", transport.get_name())
        else:
            logger.warning(
                "Flipper not connected at startup (%s). Connection tools remain usable.",
                client.last_connection_error or "no device found",
            )
        try:
            yield ServerContext(config=config, client=client)
        finally:
            await client.disconnect()

    return server_lifespan


def create_server(config: FlipperConfig | None = None) -> FastMCP:
    """Create and configure the FastMCP server."""
    if config is None:
        config = FlipperConfig()
    server = FastMCP(
        name="flipperzero-mcp",
        instructions=(
            "Flipper Zero MCP server. Inspect connection health and system info, manage "
            "files, and run Flipper CLI commands over USB with flipperzero_cli_exec. Read "
            "the flipper://reference/* and flipper://workflow/* resources to choose safe "
            "commands. Call flipperzero_connection_health before other tools if the device "
            "may have disconnected."
        ),
        lifespan=_build_lifespan(config),
    )
    from flipperzero_mcp.prompts import register_prompts
    from flipperzero_mcp.resources_registry import register_resources
    from flipperzero_mcp.tools import register_all_tools

    register_all_tools(server)
    register_resources(server)
    register_prompts(server)
    return server
