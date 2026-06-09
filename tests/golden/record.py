"""Capture golden fixtures from a real, USB-connected Flipper.

Run with a Flipper attached::

    make record-fixtures            # or: uv run python -m tests.golden.record

Offline fixtures (no wire I/O: pre-transport refusals) are regenerated every
run; hardware fixtures are captured only when a device is reachable. Commit the
resulting ``tests/golden/fixtures/*.json`` so CI can replay them offline.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging

from tests.golden.harness import Fixture, RecordingTransport

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.rpc.client import FlipperClient, LinkMode
from flipperzero_mcp.transport import get_transport

logger = logging.getLogger("golden.record")

_PROBE_PATH = "/ext/.golden_fixture_probe.bin"
_PROBE_CONTENT = b"flipperzero-mcp golden fixture probe\n"


def _record_offline_fixtures() -> list[str]:
    """Write the pre-transport-refusal fixtures that need no hardware."""
    written: list[str] = []

    wifi_rejection = Fixture(
        name="wifi_cli_rejection",
        description=(
            "CLI text mode is unavailable over the WiFi bridge: cli_exec must refuse "
            "before any wire I/O via the supports_cli_text_mode capability."
        ),
        meta={"transport": "wifi", "supports_cli_text_mode": False},
        events=[],
        expect={"raises": "FlipperCLIUnavailableError", "message_contains": "WiFi"},
        session_pre_started=True,
    )
    written.append(str(wifi_rejection.save()))

    tx_disabled = Fixture(
        name="cli_tx_gate_disabled",
        description=(
            "A transmit command is refused before any wire I/O when the operator "
            "env gate (FLIPPER_ENABLE_TX_TOOLS) is off, even with i_accept_responsibility."
        ),
        meta={"transport": "usb", "supports_cli_text_mode": True},
        events=[],
        expect={
            "command": "subghz tx 0x00 433920000 200 10",
            "accept_responsibility": True,
            "tx_tools_enabled": False,
            "raises": "FlipperCLIRefusedError",
        },
        session_pre_started=True,
    )
    written.append(str(tx_disabled.save()))
    return written


async def _fresh_client() -> tuple[FlipperClient, RecordingTransport]:
    cfg = FlipperConfig(_env_file=None, transport="usb")
    recorder = RecordingTransport(get_transport("usb", cfg.as_transport_config()))
    client = FlipperClient(recorder)
    if not await client.connect():
        raise RuntimeError("no USB Flipper connected; cannot record hardware fixtures")
    return client, recorder


async def _firmware(client: FlipperClient) -> str:
    info = await client.get_device_info()
    return str(info.get("firmware") or info.get("firmware_version") or "unknown")


async def _record_cli_exec(firmware: str) -> str:
    client, recorder = await _fresh_client()
    try:
        await client.enter_rpc()
        recorder.clear()
        result = await client.cli_exec("device_info", timeout_s=5.0)
    finally:
        await client.disconnect()
    fixture = recorder.to_fixture(
        name="cli_exec_device_info",
        description="cli_exec('device_info'): echo+prompt stripping, benign risk, completed.",
        meta={"transport": "usb", "firmware": firmware},
        expect={
            "output": result["output"],
            "completed": result["completed"],
            "risk": result["risk"],
            "warning": result["warning"],
        },
        session_pre_started=True,
    )
    return str(fixture.save())


async def _record_fs_push(firmware: str) -> str:
    client, recorder = await _fresh_client()
    try:
        await client.enter_rpc()
        recorder.clear()
        wrote = await client.rpc.storage_write(_PROBE_PATH, _PROBE_CONTENT)
        device_md5 = await client.rpc.storage_md5sum(_PROBE_PATH)
        await client.rpc.storage_delete(_PROBE_PATH)
    finally:
        await client.disconnect()
    local_md5 = hashlib.md5(_PROBE_CONTENT, usedforsecurity=False).hexdigest()
    if not wrote or device_md5 is None:
        raise RuntimeError(f"fs_push capture failed: wrote={wrote} device_md5={device_md5}")
    # Drop the trailing storage_delete round-trip so the fixture is exactly the
    # write+md5sum sequence the flipperzero_fs_push tool performs.
    fixture = recorder.to_fixture(
        name="fs_push_integrity",
        description="storage_write + storage_md5sum: the fs_push integrity round-trip.",
        meta={
            "transport": "usb",
            "firmware": firmware,
            "dest_path": _PROBE_PATH,
            "local_content_b64": _b64(_PROBE_CONTENT),
        },
        expect={
            "dest_path": _PROBE_PATH,
            "bytes": len(_PROBE_CONTENT),
            "md5": local_md5,
            "device_md5": device_md5,
            "verified": True,
        },
        session_pre_started=True,
    )
    return str(fixture.save())


async def _record_mode_switch(firmware: str) -> str:
    client, recorder = await _fresh_client()
    try:
        rpc_mode = await client.enter_rpc()
        cli_mode = await client.enter_cli()
    finally:
        await client.disconnect()
    fixture = recorder.to_fixture(
        name="mode_switch",
        description="enter_rpc then enter_cli: full CLI<->RPC negotiation captured from CLI start.",
        meta={"transport": "usb", "firmware": firmware},
        expect={
            "enter_rpc_mode": rpc_mode.value,
            "enter_cli_mode": cli_mode.value,
            "final_mode": LinkMode.CLI.value,
            "stop_session_sent": True,
        },
        session_pre_started=False,
    )
    return str(fixture.save())


async def _record_lock_contention(firmware: str) -> str:
    client, recorder = await _fresh_client()
    try:
        await client.enter_rpc()
        recorder.clear()
        first, second = await asyncio.gather(
            client.rpc.get_device_info(),
            client.rpc.get_device_info(),
        )
    finally:
        await client.disconnect()
    keys = sorted(set(first) | set(second))
    fixture = recorder.to_fixture(
        name="lock_contention",
        description=(
            "Two concurrent get_device_info calls serialized by the shared _io_lock: "
            "request/response frames never interleave on the single link."
        ),
        meta={"transport": "usb", "firmware": firmware},
        expect={"calls": 2, "device_info_keys": keys},
        session_pre_started=True,
    )
    return str(fixture.save())


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


async def record_hardware_fixtures() -> list[str]:
    """Capture every hardware fixture; each uses its own fresh connection."""
    probe, _ = await _fresh_client()
    try:
        firmware = await _firmware(probe)
    finally:
        await probe.disconnect()
    written: list[str] = []
    written.append(await _record_cli_exec(firmware))
    written.append(await _record_fs_push(firmware))
    written.append(await _record_mode_switch(firmware))
    written.append(await _record_lock_contention(firmware))
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    written = _record_offline_fixtures()
    try:
        written.extend(asyncio.run(record_hardware_fixtures()))
    except RuntimeError as exc:
        logger.warning("skipped hardware fixtures: %s", exc)
    for path in written:
        logger.info("wrote %s", path)


if __name__ == "__main__":
    main()
