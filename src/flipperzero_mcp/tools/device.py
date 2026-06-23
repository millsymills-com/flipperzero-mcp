"""Benign device-state read tools (app/desktop/gpio) for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.tools._common import get_rpc

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

# GpioPin enum (proto/gpio.proto) covers indices PC0..PA7.
_GPIO_PIN_MAX = 7


def register_device_tools(mcp: FastMCP) -> None:
    """Register the device-state read tools."""

    @mcp.tool(tags={"flipper", "device"}, annotations=_READ_ONLY)
    async def flipperzero_app_lock_status(ctx: Context) -> dict[str, Any]:
        """Report whether a running app currently holds the system lock.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``locked`` (bool).

        Raises:
            ToolError: If the device is unreachable or the read fails.
        """
        try:
            rpc = await get_rpc(ctx)
            locked = await rpc.app_lock_status()
        except Exception as e:
            _classify_client_error(e)
        if locked is None:
            raise ToolError("app lock status unavailable")
        return {"locked": locked}

    @mcp.tool(tags={"flipper", "device"}, annotations=_READ_ONLY)
    async def flipperzero_app_get_error(ctx: Context) -> dict[str, Any]:
        """Return the last error reported by the app subsystem.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with integer ``code`` and ``text`` describing the last app error
            (``code`` 0 / empty ``text`` means no error).

        Raises:
            ToolError: If the device is unreachable or the read fails.
        """
        try:
            rpc = await get_rpc(ctx)
            error = await rpc.app_get_error()
        except Exception as e:
            _classify_client_error(e)
        if error is None:
            raise ToolError("app error status unavailable")
        return error

    @mcp.tool(tags={"flipper", "device"}, annotations=_READ_ONLY)
    async def flipperzero_desktop_is_locked(ctx: Context) -> dict[str, Any]:
        """Report whether the Flipper desktop is locked.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.

        Returns:
            Dict with ``locked`` (bool).

        Raises:
            ToolError: If the device is unreachable or returns an unexpected status.
        """
        try:
            rpc = await get_rpc(ctx)
            locked = await rpc.desktop_is_locked()
        except Exception as e:
            _classify_client_error(e)
        if locked is None:
            raise ToolError("desktop lock state unavailable")
        return {"locked": locked}

    @mcp.tool(tags={"flipper", "device"}, annotations=_READ_ONLY)
    async def flipperzero_gpio_read(ctx: Context, pin: int) -> dict[str, Any]:
        """Read the mode and level of a GPIO pin.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.
            pin: GpioPin index in the range 0-7 (PC0, PC1, PC3, PB2, PB3, PA4,
                PA6, PA7).

        Returns:
            Dict with the ``pin`` index, its ``mode``
            (``"input"``/``"output"``/``"unconfigured"``), and its current
            ``value`` (0/1, or ``None`` when the pin is not an input and so has no
            readable level).

        Raises:
            ToolError: If ``pin`` is out of range, the device is unreachable, or
                the read fails.
        """
        if not 0 <= pin <= _GPIO_PIN_MAX:
            raise ToolError(f"pin must be in range 0-{_GPIO_PIN_MAX}, got {pin}")
        try:
            rpc = await get_rpc(ctx)
            state = await rpc.gpio_read(pin)
        except Exception as e:
            _classify_client_error(e)
        if state is None:
            raise ToolError(f"gpio pin {pin} read unavailable")
        return state
