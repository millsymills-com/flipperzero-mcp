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
# The device is off the bus while the on-device updater applies the bundle and
# reboots. A larger firmware (Momentum's resources) was observed to re-enumerate
# just past 300 s, so the old budget raised a false "did not reconnect" on an
# update that had in fact succeeded; 600 s covers the slow apply.
_RECONNECT_BUDGET_S = 600.0


async def _resolve(source: dict[str, Any], target: str) -> Any:
    if "path" in source:
        return load_local_bundle(source["path"])
    if "flavor" not in source:
        raise BundleError("source must specify either 'path' or 'flavor'")
    try:
        flavor = FirmwareFlavor(source["flavor"])
    except ValueError as e:
        choices = ", ".join(f.value for f in FirmwareFlavor)
        raise BundleError(f"unknown flavor {source['flavor']!r}; expected one of: {choices}") from e
    return await download_bundle(
        flavor,
        channel=source.get("channel", "release"),
        version=source.get("version", "latest"),
        target=target,
    )


async def _reconnect_and_classify(client: Any, before: Any) -> tuple[Any, bool]:
    """Poll for the device to come back after the update reboot.

    ``system_reboot_update`` is fire-and-forget, so an early reconnect can land
    before the device boots the new image and still read the old firmware.
    Prefer a reading whose ``(version, flavor)`` identity differs from
    ``before``; fall back to the last successful reading (best-effort) once the
    budget is exhausted.

    Gating on ``(version, flavor)`` rather than version alone confirms a
    same-version fork swap (e.g. Official -> Momentum at a matching version),
    which a version-only check misses. A same-version, same-flavor reflash
    leaves no observable identity change, so it stays best-effort.

    Returns:
        ``(classification, confirmed)`` where ``confirmed`` is True only if a
        post-reboot identity change was observed against a known baseline.
    """
    before_identity = (before.version, before.flavor)
    waited = 0.0
    last = None
    while waited < _RECONNECT_BUDGET_S:
        await asyncio.sleep(5.0)
        waited += 5.0
        await client.disconnect()
        if not await client.connect():
            continue
        try:
            last = classify(await client.get_device_info())
        except (OSError, RuntimeError, ValueError):
            continue  # device still settling; keep polling
        if before.version is not None and (last.version, last.flavor) != before_identity:
            return last, True
    if last is not None:
        return last, False
    raise ToolError(
        "device did not reconnect after the update; it may still be applying or "
        "may have dropped to DFU - recover with qFlipper if it does not return"
    )


async def _resync_session(client: Any) -> Any:
    """Reconnect the transport to clear a wedged RPC session.

    Large multi-MB writes can wedge the device's RPC session; a transport
    teardown + reconnect re-establishes a fresh session that responds again.

    Returns:
        The fresh RPC client after a successful reconnect.

    Raises:
        FlashError: If the device cannot be reconnected.
    """
    await client.disconnect()
    if not await client.connect() or client.rpc is None:
        raise FlashError("could not re-establish the device session after a session wedge")
    return client.rpc


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
            Dict with ``before`` and ``after`` firmware blocks, the bundle
            target, and ``after_confirmed`` (True only if a post-reboot
            ``(version, flavor)`` identity change was observed against a known
            baseline; False means ``after`` is best-effort and may still
            reflect the pre-reboot image).

        Raises:
            ToolError: If flashing is disabled, the confirm token is wrong, the
                bundle is invalid, or the device rejects the update.
        """
        require_firmware_flash(ctx)
        try:
            client = await ensure_connected(ctx)
            rpc = await get_rpc(ctx)
            device = await rpc.get_device_info()
        except Exception as e:
            _classify_client_error(e)
        device_name = device.get("hardware_name")
        if not device_name:
            raise ToolError("could not read device identity (hardware_name); aborting flash")
        before = classify(device)
        if confirm != device_name:
            raise ToolError(
                f"confirm token {confirm!r} does not match connected device {device_name!r}"
            )
        if not before.target:
            raise ToolError("device did not report a hardware target; cannot select a bundle")

        try:
            bundle = await _resolve(source, before.target)
            await install_bundle(
                rpc, bundle, pkg_name=_PKG_NAME, resync=lambda: _resync_session(client)
            )
        except (BundleError, FlashError) as e:
            raise ToolError(str(e)) from e

        after, after_confirmed = await _reconnect_and_classify(client, before)
        return {
            "before": {"flavor": before.flavor.value, "version": before.version},
            "after": {"flavor": after.flavor.value, "version": after.version},
            "after_confirmed": after_confirmed,
            "target": bundle.target,
        }
