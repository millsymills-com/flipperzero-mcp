import os

import pytest

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.transport import get_transport


@pytest.fixture
async def usb_client():
    cfg = FlipperConfig(_env_file=None, transport="usb")
    client = FlipperClient(get_transport("usb", cfg.as_transport_config()))
    if not await client.connect():
        pytest.skip("No USB Flipper connected")
    yield client
    await client.disconnect()


@pytest.fixture
async def wifi_client():
    host = os.environ.get("FLIPPER_WIFI_HOST")
    if not host:
        pytest.skip("FLIPPER_WIFI_HOST not set")
    cfg = FlipperConfig(_env_file=None, transport="wifi", wifi_host=host)
    client = FlipperClient(get_transport("wifi", cfg.as_transport_config()))
    if not await client.connect():
        pytest.skip("WiFi Flipper not reachable")
    yield client
    await client.disconnect()
