"""End-to-end USB firmware-flash round-trip against a real Flipper.

Destructive and slow: each flash pushes a full update bundle, reboots the
device into the on-device updater, and waits for it to come back (minutes per
direction). Guarded behind ``FLIPPER_RUN_FLASH_TEST`` so it never runs as part
of the ordinary ``integration``/``usb`` sweep. The test always attempts to
flash back to the starting flavor, even when the forward flash fails, so a
green or assertion-failed run leaves no net change; only a wedged device can
strand the swap.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.firmware.flavor import FirmwareFlavor, classify
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.server import create_server
from flipperzero_mcp.transport import get_transport

_FLASH_GATE = "FLIPPER_RUN_FLASH_TEST"
_OPPOSITE = {FirmwareFlavor.OFFICIAL: "momentum", FirmwareFlavor.MOMENTUM: "official"}


async def _read_identity() -> tuple[str, FirmwareFlavor]:
    """Read the device name and firmware flavor over a throwaway connection."""
    cfg = FlipperConfig(_env_file=None, transport="usb")  # ty: ignore[unknown-argument]
    client = FlipperClient(get_transport("usb", cfg.as_transport_config()))
    if not await client.connect() or client.rpc is None:
        pytest.skip("No USB Flipper connected")
    try:
        info = await client.rpc.get_device_info()
    finally:
        await client.disconnect()
    name = info.get("hardware_name")
    flavor = classify(info).flavor
    if not name or flavor not in _OPPOSITE:
        pytest.skip(f"device identity unusable for a flash: name={name!r} flavor={flavor}")
    return name, flavor


async def _flash(client: Client, flavor: str, confirm: str) -> dict[str, Any]:
    source = {"flavor": flavor, "channel": "release", "version": "latest"}
    result = await client.call_tool(
        "flipperzero_firmware_install", {"source": source, "confirm": confirm}
    )
    return result.data


@pytest.mark.integration
@pytest.mark.usb
async def test_usb_firmware_flash_roundtrip():
    if not os.environ.get(_FLASH_GATE):
        pytest.skip(f"set {_FLASH_GATE}=1 to run the destructive flash round-trip")

    name, origin = await _read_identity()
    other = _OPPOSITE[origin]

    cfg = FlipperConfig(
        _env_file=None,  # ty: ignore[unknown-argument]
        transport="usb",
        enable_write_tools=True,
        enable_firmware_flash=True,
    )
    async with Client(create_server(cfg)) as client:
        try:
            forward = await _flash(client, other, name)
            assert forward["after_confirmed"] is True
            assert forward["after"]["flavor"] == other
        finally:
            back = await _flash(client, origin.value, name)
        assert back["after_confirmed"] is True
        assert back["after"]["flavor"] == origin.value
