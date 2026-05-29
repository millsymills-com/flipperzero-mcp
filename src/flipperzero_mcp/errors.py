"""Exception hierarchy and error mapping for the Flipper MCP server."""

from __future__ import annotations

import logging
from typing import NoReturn

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


class FlipperError(Exception):
    """Base exception for all Flipper errors."""


class FlipperNotConnectedError(FlipperError):
    """No live connection to the Flipper device."""


class FlipperConnectionError(FlipperError):
    """Transport-level connection failure (USB/WiFi)."""


class FlipperTimeoutError(FlipperError):
    """An RPC call exceeded its timeout."""


class FlipperProtocolError(FlipperError):
    """A protobuf RPC response was malformed or unexpected."""


def handle_client_error(error: Exception) -> NoReturn:
    """Map a Flipper exception to a FastMCP ToolError with an agent-readable message.

    Raises:
        ToolError: Always.
    """
    if isinstance(error, FlipperNotConnectedError):
        raise ToolError(
            f"Flipper not connected: {error}. Call flipper_connection_reconnect, "
            "or check USB / FLIPPER_WIFI_HOST."
        ) from error
    if isinstance(error, FlipperTimeoutError):
        raise ToolError(
            f"Flipper RPC timed out: {error}. The device may be busy; retry."
        ) from error
    if isinstance(error, FlipperConnectionError):
        raise ToolError(f"Flipper connection error: {error}.") from error
    if isinstance(error, FlipperProtocolError):
        raise ToolError(f"Flipper protocol error: {error}.") from error
    if isinstance(error, FlipperError):
        raise ToolError(f"Flipper error: {error}.") from error
    logger.exception("Unexpected error in tool")
    raise ToolError(f"unexpected error: {error}.") from error
