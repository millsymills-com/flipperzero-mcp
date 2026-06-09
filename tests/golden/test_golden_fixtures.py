"""Replay golden fixtures captured from a real Flipper; assert behavior holds.

These run in the default (offline) suite and are the drift guard: if a parsing,
framing, or gating change makes the real captured bytes yield a different
result, the matching test fails and the fixture must be re-recorded with
``make record-fixtures`` against hardware. Capture lives in ``record.py``.
"""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastmcp.exceptions import ToolError
from tests.golden.harness import Fixture, ReplayTransport, load_all

from flipperzero_mcp.errors import FlipperCLIRefusedError, FlipperCLIUnavailableError
from flipperzero_mcp.rpc.client import FlipperClient, LinkMode
from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
from flipperzero_mcp.tools.storage import _md5_hex, _verify_md5


def _replay_client(fixture: Fixture) -> tuple[FlipperClient, ReplayTransport]:
    transport = ReplayTransport(fixture)
    client = FlipperClient(transport)
    client.rpc = ProtobufRPC(transport, io_lock=client._io_lock)
    client.connected = True
    if fixture.session_pre_started:
        client.rpc._rpc_session_started = True
    return client, transport


def _decode_main(frame: bytes) -> flipper_pb2.Main:
    """Decode one nanopb-delimited Main frame: [varint length][payload]."""
    value = shift = i = 0
    while True:
        byte = frame[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    msg = flipper_pb2.Main()
    msg.ParseFromString(frame[i : i + value])
    return msg


# --- drift / schema guard ----------------------------------------------------


def test_every_fixture_loads_with_current_schema():
    fixtures = load_all()
    assert {f.name for f in fixtures} == {
        "cli_exec_device_info",
        "cli_tx_gate_disabled",
        "fs_push_integrity",
        "lock_contention",
        "mode_switch",
        "wifi_cli_rejection",
    }
    for fixture in fixtures:
        assert fixture.description
        assert "transport" in fixture.meta
        assert fixture.expect


# --- 1. cli_exec output parsing ----------------------------------------------


async def test_cli_exec_parsing_matches_recorded_output():
    fixture = Fixture.load("cli_exec_device_info")
    client, _ = _replay_client(fixture)
    result = await client.cli_exec("device_info", timeout_s=5.0)
    assert result["output"] == fixture.expect["output"]
    assert result["completed"] == fixture.expect["completed"]
    assert result["risk"] == fixture.expect["risk"]
    assert result["warning"] == fixture.expect["warning"]


# --- 2. fs_push integrity: md5 match + mismatch ------------------------------


async def test_fs_push_integrity_verifies_on_match():
    fixture = Fixture.load("fs_push_integrity")
    local = base64.b64decode(fixture.meta["local_content_b64"])
    client, _ = _replay_client(fixture)
    rpc = client.rpc
    assert rpc is not None
    dest = fixture.expect["dest_path"]
    wrote = await rpc.storage_write(dest, local)
    device_md5 = await rpc.storage_md5sum(dest)
    assert wrote is True
    assert device_md5 == fixture.expect["device_md5"]
    _verify_md5(_md5_hex(local), device_md5, dest)  # must not raise
    assert _md5_hex(local) == fixture.expect["md5"]


async def test_fs_push_integrity_fails_loud_on_mismatch():
    fixture = Fixture.load("fs_push_integrity")
    local = base64.b64decode(fixture.meta["local_content_b64"])
    corrupted = local + b"!"  # host file differs from what the device hashed
    client, _ = _replay_client(fixture)
    rpc = client.rpc
    assert rpc is not None
    dest = fixture.expect["dest_path"]
    await rpc.storage_write(dest, corrupted)
    device_md5 = await rpc.storage_md5sum(dest)
    assert device_md5 == fixture.expect["device_md5"]
    with pytest.raises(ToolError, match=r"(?i)mismatch"):
        _verify_md5(_md5_hex(corrupted), device_md5, dest)


# --- 3. mode-switch in both directions ---------------------------------------


async def test_mode_switch_both_directions():
    fixture = Fixture.load("mode_switch")
    client, transport = _replay_client(fixture)
    rpc_mode = await client.enter_rpc()
    cli_mode = await client.enter_cli()
    assert rpc_mode is LinkMode.RPC
    assert cli_mode is LinkMode.CLI
    assert client.mode() is LinkMode.CLI
    sent_stop = any(
        (msg := _try_decode(frame)) is not None and msg.HasField("stop_session")
        for frame in transport.sent
    )
    assert sent_stop is fixture.expect["stop_session_sent"]


def _try_decode(frame: bytes) -> flipper_pb2.Main | None:
    try:
        return _decode_main(frame)
    except Exception:
        return None


# --- 4. shared _io_lock contention -------------------------------------------


def test_lock_contention_recording_is_not_interleaved():
    fixture = Fixture.load("lock_contention")
    dirs = [e.dir for e in fixture.events]
    first_rx = dirs.index("rx")
    second_tx = dirs.index("tx", dirs.index("tx") + 1)
    # The second request was not sent until the first response had been read:
    # proof the shared lock serialized the two round-trips on the one link.
    assert second_tx > first_rx


async def test_lock_contention_replays_both_round_trips():
    fixture = Fixture.load("lock_contention")
    client, _ = _replay_client(fixture)
    rpc = client.rpc
    assert rpc is not None
    first, second = await asyncio.gather(rpc.get_device_info(), rpc.get_device_info())
    expected_keys = set(fixture.expect["device_info_keys"])
    assert set(first) | set(second) == expected_keys
    assert first
    assert second


# --- 5. two-gate TX path: enabled + disabled ---------------------------------

_TX_COMMAND = "subghz tx 0x00 433920000 200 10"


async def test_tx_gate_disabled_refuses_before_io():
    fixture = Fixture.load("cli_tx_gate_disabled")
    client, transport = _replay_client(fixture)
    with pytest.raises(FlipperCLIRefusedError):
        await client.cli_exec(
            fixture.expect["command"],
            timeout_s=1.0,
            accept_responsibility=fixture.expect["accept_responsibility"],
            tx_tools_enabled=fixture.expect["tx_tools_enabled"],
        )
    assert transport.sent == []  # refused before any wire I/O


async def test_tx_gate_enabled_passes_both_gates_and_executes():
    # Reuse the benign captured CLI exchange to drive the gate-pass path; we do
    # not transmit on real hardware for safety/legality.
    fixture = Fixture.load("cli_exec_device_info")
    client, transport = _replay_client(fixture)
    result = await client.cli_exec(
        _TX_COMMAND, timeout_s=5.0, accept_responsibility=True, tx_tools_enabled=True
    )
    assert result["risk"] == "transmit"
    assert result["warning"]
    assert result["completed"] is True
    assert transport.sent  # the command actually went to the link


# --- 6. WiFi-CLI rejection ----------------------------------------------------


async def test_wifi_cli_rejection():
    fixture = Fixture.load("wifi_cli_rejection")
    client, transport = _replay_client(fixture)
    assert client.transport.supports_cli_text_mode is False
    with pytest.raises(FlipperCLIUnavailableError, match=r"WiFi"):
        await client.cli_exec("device_info", timeout_s=1.0)
    assert transport.sent == []
