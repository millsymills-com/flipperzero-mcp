"""System information tool for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.firmware.flavor import classify
from flipperzero_mcp.tools._common import ensure_connected, get_rpc


def register_systeminfo_tools(mcp: FastMCP) -> None:
    """Register the systeminfo tool."""

    @mcp.tool(
        tags={"flipper", "systeminfo"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_system_info(ctx: Context) -> dict[str, Any]:
        """Get system information about the connected Flipper Zero.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with connection status, transport, device info (name/hardware/firmware),
            and SD-card availability.
        """
        try:
            client = await ensure_connected(ctx)
            health = await client.get_connection_health(probe_rpc=True)
            device = await client.get_device_info()
            firmware = classify(device)
            sd = await client.check_sd_card_available()
        except Exception as e:
            _classify_client_error(e)
        return {
            "connected": health["connected"],
            "transport": health["transport"]["type"],
            "rpc_responsive": health["rpc_responsive"],
            "device": device,
            "firmware": {
                "flavor": firmware.flavor.value,
                "version": firmware.version,
                "origin_fork": firmware.origin_fork,
                "origin_git": firmware.origin_git,
                "target": firmware.target,
            },
            "sd_card_available": sd,
        }

    @mcp.tool(
        tags={"flipper", "systeminfo"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_system_power_info(ctx: Context) -> dict[str, Any]:
        """Return Flipper power/battery information.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with a ``power`` object containing firmware-reported key/value pairs.

        Raises:
            ToolError: If the device is unreachable or the power-info read fails.
        """
        try:
            rpc = await get_rpc(ctx)
            power = await rpc.system_power_info()
        except Exception as e:
            _classify_client_error(e)
        if power is None:
            raise ToolError("power info unavailable")
        return {"power": power}

    @mcp.tool(
        tags={"flipper", "systeminfo"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_system_protobuf_version(ctx: Context) -> dict[str, Any]:
        """Return the Flipper protobuf RPC version.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``protobuf_version`` containing integer ``major``/``minor`` fields.

        Raises:
            ToolError: If the device is unreachable or no version is returned.
        """
        try:
            rpc = await get_rpc(ctx)
            version = await rpc.system_protobuf_version()
        except Exception as e:
            _classify_client_error(e)
        if version is None:
            raise ToolError("protobuf version unavailable")
        return {"protobuf_version": version}

    @mcp.tool(
        tags={"flipper", "systeminfo"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_system_datetime(ctx: Context) -> dict[str, Any]:
        """Return the device date/time fields reported by firmware.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``datetime`` containing year/month/day/hour/minute/second/weekday.

        Raises:
            ToolError: If the device is unreachable or no datetime is returned.
        """
        try:
            rpc = await get_rpc(ctx)
            datetime_fields = await rpc.system_datetime()
        except Exception as e:
            _classify_client_error(e)
        if datetime_fields is None:
            raise ToolError("device datetime unavailable")
        return {"datetime": datetime_fields}
