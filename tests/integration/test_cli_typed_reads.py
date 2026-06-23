"""Integration tests for P2 typed CLI-text reads against a real USB Flipper.

CLI text mode is USB-only (TP-2), so these are ``usb``-marked and cannot run over
WiFi. All are read-only. ``storage tree`` is exercised against a small subtree:
walking a whole volume (e.g. ``/ext``) can exceed the read window and leave the CLI
mid-stream.
"""

import pytest

from flipperzero_mcp.tools.cli_typed import _parse_free, _parse_i2c, _parse_tree


@pytest.mark.integration
@pytest.mark.usb
async def test_free_reports_heap(usb_client):
    result = await usb_client.cli_exec("free", timeout_s=8.0)
    heap = _parse_free(result["output"])
    assert heap.get("free_heap_size", 0) > 0


@pytest.mark.integration
@pytest.mark.usb
async def test_storage_tree_small_subtree_parses(usb_client):
    result = await usb_client.cli_exec("storage tree /ext/badusb", timeout_s=8.0)
    entries = _parse_tree(result["output"])
    assert all(e["type"] in {"dir", "file"} for e in entries)
    assert all(e["path"].startswith("/ext/badusb") for e in entries)


@pytest.mark.integration
@pytest.mark.usb
async def test_i2c_scan_returns_address_list(usb_client):
    result = await usb_client.cli_exec("i2c", timeout_s=8.0)
    addresses = _parse_i2c(result["output"])
    assert all(a.startswith("0x") for a in addresses)


@pytest.mark.integration
@pytest.mark.usb
async def test_loader_list_completes(usb_client):
    result = await usb_client.cli_exec("loader list", timeout_s=8.0)
    assert result["completed"] is True
