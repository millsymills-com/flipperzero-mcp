"""Integration tests for P0/P1 RPC reads against a real USB Flipper.

These RPC tools work over both transports; they are exercised over USB because a
USB device is the default local rig. All are read-only and leave device state
untouched.
"""

import pytest


@pytest.mark.integration
@pytest.mark.usb
async def test_ping_echoes_payload(usb_client):
    echo = await usb_client.rpc.ping(b"flipper-mcp")
    assert echo == b"flipper-mcp"


@pytest.mark.integration
@pytest.mark.usb
async def test_get_property_returns_hardware_name(usb_client):
    value = await usb_client.rpc.get_property("devinfo.hardware.name")
    assert value is None or isinstance(value, str)


@pytest.mark.integration
@pytest.mark.usb
async def test_app_lock_status_returns_bool(usb_client):
    locked = await usb_client.rpc.app_lock_status()
    assert isinstance(locked, bool)


@pytest.mark.integration
@pytest.mark.usb
async def test_app_get_error_returns_code_and_text(usb_client):
    error = await usb_client.rpc.app_get_error()
    assert set(error) == {"code", "text"}
    assert isinstance(error["code"], int)
    assert isinstance(error["text"], str)


@pytest.mark.integration
@pytest.mark.usb
async def test_desktop_is_locked_returns_bool(usb_client):
    locked = await usb_client.rpc.desktop_is_locked()
    assert isinstance(locked, bool)


@pytest.mark.integration
@pytest.mark.usb
async def test_gpio_read_returns_structure(usb_client):
    # Pin 0 is unconfigured by default; the read reports that honestly rather
    # than erroring (firmware rejects mode/level reads on unconfigured pins).
    state = await usb_client.rpc.gpio_read(0)
    assert state["pin"] == 0
    assert state["mode"] in {"input", "output", "unconfigured"}
    assert state["value"] in {0, 1, None}
