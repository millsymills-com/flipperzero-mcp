"""Transport layer factory."""

from __future__ import annotations

from flipperzero_mcp.transport.auto import AutoTransport
from flipperzero_mcp.transport.base import FlipperTransport
from flipperzero_mcp.transport.usb import USBTransport
from flipperzero_mcp.transport.wifi import WiFiTransport

__all__ = ["AutoTransport", "FlipperTransport", "USBTransport", "WiFiTransport", "get_transport"]

_TRANSPORTS: dict[str, type[FlipperTransport]] = {
    "auto": AutoTransport,
    "usb": USBTransport,
    "wifi": WiFiTransport,
}


def get_transport(transport_type: str, config: dict) -> FlipperTransport:
    """Create a transport instance from a config dict (see FlipperConfig.as_transport_config)."""
    transport_type = transport_type.lower()
    if transport_type not in _TRANSPORTS:
        raise ValueError(
            f"Unknown transport type: {transport_type}. Available: {', '.join(_TRANSPORTS)}"
        )
    section = config.get("transport", {}) or {}
    if transport_type == "auto":
        return AutoTransport(section)
    return _TRANSPORTS[transport_type](section.get(transport_type, {}) or {})
