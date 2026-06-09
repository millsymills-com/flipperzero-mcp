"""Firmware-flash tool for the Flipper Zero (gated, destructive)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.firmware.bundles import BundleError, download_bundle, load_local_bundle
from flipperzero_mcp.firmware.flavor import FirmwareFlavor, classify
from flipperzero_mcp.firmware.installer import FlashError, install_bundle
from flipperzero_mcp.tools._common import ensure_connected, get_rpc, require_firmware_flash

_PKG_NAME = "mcp-update"
_RECONNECT_BUDGET_S = 300.0


async def _resolve(source: dict[str, Any], target: str) -> Any:
    if "path" in source:
        return load_local_bundle(source["path"])
    flavor = FirmwareFlavor(source["flavor"])
    return await download_bundle(
        flavor,
        channel=source.get("channel", "release"),
        version=source.get("version", "latest"),
        target=target,
    )


async def _reconnect_and_classify(client: Any) -> Any:
    """Poll for the device to come back after the update reboot."""
    waited = 0.0
    while waited < _RECONNECT_BUDGET_S:
        await asyncio.sleep(5.0)
        waited += 5.0
        await client.disconnect()
        if await client.connect():
            try:
                return classify(await client.get_device_info())
            except Exception:  # noqa: S112  # nosec B112 - device still settling; keep polling
                continue
    raise ToolError(
        "device did not reconnect after the update; it may still be applying or "
        "may have dropped to DFU - recover with qFlipper if it does not return"
    )


def register_firmware_tools(mcp: FastMCP) -> None:
    """Register the firmware-flash tool."""

    @mcp.tool(
        tags={"flipper", "firmware"},
        annotations=ToolAnnotations(
            readOnlyHint=False,
            idempotentHint=False,
            destructiveHint=True,
            openWorldHint=True,
        ),
    )
    async def flipperzero_firmware_install(
        ctx: Context, source: dict[str, Any], confirm: str
    ) -> dict[str, Any]:
        """Flash firmware onto the connected Flipper Zero over USB.

        Args:
            ctx: FastMCP request context.
            source: Either ``{"path": "<local .tgz>"}`` or
                ``{"flavor": "official"|"momentum", "channel": ..., "version": ...}``.
            confirm: Must equal the connected device's name (a safety interlock).

        Returns:
            Dict with ``before`` and ``after`` firmware blocks and the bundle target.

        Raises:
            ToolError: If flashing is disabled, the confirm token is wrong, the
                bundle is invalid, or the device rejects the update.
        """
        require_firmware_flash(ctx)
        try:
            client = await ensure_connected(ctx)
            rpc = await get_rpc(ctx)
            device = await client.get_device_info()
        except Exception as e:
            _classify_client_error(e)
        before = classify(device)

        device_name = device.get("name") or device.get("hardware_name")
        if confirm != device_name:
            raise ToolError(
                f"confirm token {confirm!r} does not match connected device {device_name!r}"
            )

        try:
            bundle = await _resolve(source, before.target or "f7")
            await install_bundle(rpc, bundle, pkg_name=_PKG_NAME)
        except (BundleError, FlashError) as e:
            raise ToolError(str(e)) from e

        after = await _reconnect_and_classify(client)
        return {
            "before": {"flavor": before.flavor.value, "version": before.version},
            "after": {"flavor": after.flavor.value, "version": after.version},
            "target": bundle.target,
        }
