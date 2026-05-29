import pytest


@pytest.mark.integration
@pytest.mark.usb
async def test_usb_health_and_device_info(usb_client):
    health = await usb_client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    assert health["rpc_responsive"] is True
    info = await usb_client.get_device_info()
    assert info["firmware"] != "Unknown"


@pytest.mark.integration
@pytest.mark.wifi
async def test_wifi_health_and_device_info(wifi_client):
    health = await wifi_client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    info = await wifi_client.get_device_info()
    assert info["firmware"] != "Unknown"
