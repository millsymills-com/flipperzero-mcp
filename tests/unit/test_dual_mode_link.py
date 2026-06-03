"""Dual-mode link manager and shared I/O lock (#38)."""

import asyncio

from flipperzero_mcp.rpc.client import FlipperClient, LinkMode
from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
from flipperzero_mcp.transport.base import FlipperTransport


def _decode_frame(frame: bytes) -> flipper_pb2.Main:
    """Decode one nanopb-delimited Main frame: [varint length][payload]."""
    value = 0
    shift = 0
    i = 0
    while True:
        byte = frame[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    payload = frame[i : i + value]
    msg = flipper_pb2.Main()
    msg.ParseFromString(payload)
    return msg


def _ping_response_frame(command_id: int, data: bytes = b"mcp") -> bytes:
    """Build a nanopb-delimited PingResponse frame the RPC layer will accept."""
    msg = flipper_pb2.Main()
    msg.command_id = command_id
    msg.command_status = flipper_pb2.CommandStatus.OK
    msg.system_ping_response.data = data
    payload = msg.SerializeToString()
    return ProtobufRPC._encode_varint(len(payload)) + payload


class RpcReadyTransport(FlipperTransport):
    """Fake transport already in RPC mode: every probe ping gets a ping response."""

    def __init__(self) -> None:
        super().__init__({})
        self.connected = True
        self.sent: list[bytes] = []
        self._command_id = 0

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        self._command_id += 1
        self._rx_buffer.extend(_ping_response_frame(self._command_id))

    async def receive(self, timeout=None) -> bytes:  # noqa: ARG002
        if self._rx_buffer:
            out = bytes(self._rx_buffer)
            self._rx_buffer.clear()
            return out
        return b""

    async def is_connected(self) -> bool:
        return self.connected


async def test_mode_starts_unknown():
    client = FlipperClient(RpcReadyTransport())
    await client.connect()
    assert client.mode() is LinkMode.UNKNOWN


async def test_enter_rpc_sets_mode_rpc():
    client = FlipperClient(RpcReadyTransport())
    await client.connect()
    await client.enter_rpc()
    assert client.mode() is LinkMode.RPC


async def test_enter_cli_sets_mode_cli_and_sends_stop_session():
    transport = RpcReadyTransport()
    client = FlipperClient(transport)
    await client.connect()
    await client.enter_cli()
    assert client.mode() is LinkMode.CLI
    decoded = [_decode_frame(f) for f in transport.sent if f]
    assert any(m.HasField("stop_session") for m in decoded)


async def test_mode_switch_rpc_to_cli():
    client = FlipperClient(RpcReadyTransport())
    await client.connect()
    await client.enter_rpc()
    assert client.mode() is LinkMode.RPC
    await client.enter_cli()
    assert client.mode() is LinkMode.CLI


async def test_mode_switch_cli_to_rpc():
    client = FlipperClient(RpcReadyTransport())
    await client.connect()
    await client.enter_cli()
    assert client.mode() is LinkMode.CLI
    await client.enter_rpc()
    assert client.mode() is LinkMode.RPC


async def test_enter_cli_resets_rpc_session():
    client = FlipperClient(RpcReadyTransport())
    await client.connect()
    await client.enter_rpc()
    assert client.rpc._rpc_session_started is True
    await client.enter_cli()
    assert client.rpc._rpc_session_started is False


class InterleaveProbeTransport(FlipperTransport):
    """Records an ordered event log and yields on every send/receive.

    Each multi-frame round-trip is modeled as: one send (request), then two
    receives (a streamed has_next=True frame followed by a final frame). The
    log lets a test assert that two concurrent operations do not interleave.
    """

    def __init__(self) -> None:
        super().__init__({})
        self.connected = True
        self.events: list[str] = []
        self._frames: list[bytes] = []
        self._command_id = 0

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.connected = False

    def _device_info_frame(self, *, has_next: bool, key: str) -> bytes:
        msg = flipper_pb2.Main()
        self._command_id += 1
        msg.command_id = self._command_id
        msg.command_status = flipper_pb2.CommandStatus.OK
        msg.has_next = has_next
        msg.system_device_info_response.key = key
        msg.system_device_info_response.value = "v"
        payload = msg.SerializeToString()
        return ProtobufRPC._encode_varint(len(payload)) + payload

    async def send(self, data: bytes) -> None:
        msg = _decode_frame(data)
        if msg.HasField("system_ping_request"):
            # Answer RPC-session probe pings so negotiation succeeds quickly.
            self._command_id += 1
            self._rx_buffer.extend(
                _ping_response_frame(self._command_id, msg.system_ping_request.data)
            )
            return
        tag = _tag_for(data)
        self.events.append(f"send-{tag}")
        await asyncio.sleep(0)
        self._frames = [
            self._device_info_frame(has_next=True, key=f"{tag}_a"),
            self._device_info_frame(has_next=False, key=f"{tag}_b"),
        ]

    async def receive(self, timeout=None) -> bytes:  # noqa: ARG002
        await asyncio.sleep(0)
        if self._rx_buffer:
            out = bytes(self._rx_buffer)
            self._rx_buffer.clear()
            return out
        if self._frames:
            frame = self._frames.pop(0)
            self.events.append("recv")
            return frame
        return b""

    async def is_connected(self) -> bool:
        return self.connected


def _tag_for(data: bytes) -> str:
    """Label a device-info request frame by its command id."""
    msg = _decode_frame(data)
    if msg.HasField("system_device_info_request"):
        return f"req{msg.command_id}"
    return "other"


async def test_concurrent_round_trips_do_not_interleave():
    transport = InterleaveProbeTransport()
    client = FlipperClient(transport)
    await client.connect()
    await client.enter_rpc()
    transport.events.clear()

    await asyncio.gather(
        client.rpc.get_device_info(),
        client.rpc.get_device_info(),
    )

    sends = [i for i, e in enumerate(transport.events) if e.startswith("send")]
    assert len(sends) == 2
    first, second = sends
    between = transport.events[first + 1 : second]
    assert all(e == "recv" for e in between)
    assert "recv" in between


async def test_protobuf_rpc_accepts_default_io_lock():
    transport = RpcReadyTransport()
    rpc = ProtobufRPC(transport)
    assert isinstance(rpc._io_lock, asyncio.Lock)
    assert await rpc.ping(b"mcp") == b"mcp"
