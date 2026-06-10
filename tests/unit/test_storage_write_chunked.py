"""Unit tests for chunked storage_write framing."""

import pytest

from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class RecordingTransport:
    """Captures sent frames and replies with one canned WriteResponse (OK)."""

    def __init__(self):
        self.sent: list[bytes] = []
        ok = flipper_pb2.Main()
        ok.command_status = flipper_pb2.CommandStatus.OK
        ok.empty.CopyFrom(flipper_pb2.Empty())
        payload = ok.SerializeToString()
        self._reply = ProtobufRPC._encode_varint(len(payload)) + payload
        self._reply_pos = 0

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive_exact(self, n: int, timeout: float | None = None) -> bytes:  # noqa: ARG002
        chunk = self._reply[self._reply_pos : self._reply_pos + n]
        self._reply_pos += n
        return chunk

    async def is_connected(self) -> bool:
        return True


def _decode_frames(sent: list[bytes]) -> list[flipper_pb2.Main]:
    frames = []
    for raw in sent:
        idx, shift, length = 0, 0, 0
        while True:
            byte = raw[idx]
            length |= (byte & 0x7F) << shift
            idx += 1
            if not (byte & 0x80):
                break
            shift += 7
        msg = flipper_pb2.Main()
        msg.ParseFromString(raw[idx : idx + length])
        frames.append(msg)
    return frames


@pytest.mark.asyncio
async def test_large_write_is_chunked_with_has_next():
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True  # skip CLI negotiation
    content = b"A" * 3000  # > one 1024-byte chunk

    ok = await rpc.storage_write("/ext/big.bin", content)

    assert ok is True
    frames = _decode_frames(transport.sent)
    assert len(frames) == 3  # 1024 + 1024 + 952
    assert all(f.command_id == frames[0].command_id for f in frames)
    assert [f.has_next for f in frames] == [True, True, False]
    rebuilt = b"".join(f.storage_write_request.file.data for f in frames)
    assert rebuilt == content
    assert all(f.storage_write_request.path == "/ext/big.bin" for f in frames)


@pytest.mark.asyncio
async def test_large_write_paces_fragments_to_device_throughput(monkeypatch):
    slept: list[float] = []

    async def _record(seconds):
        slept.append(seconds)

    monkeypatch.setattr("flipperzero_mcp.rpc.protobuf_rpc.asyncio.sleep", _record)
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    content = b"A" * 3000  # 3 fragments: 1024, 1024, 952

    ok = await rpc.storage_write("/ext/big.bin", content)

    assert ok is True
    # One pacing sleep per non-final fragment; none after the final fragment.
    assert len(slept) == 2
    expected = sum(len(f) for f in transport.sent[:-1]) / rpc._WRITE_THROUGHPUT_BYTES_S
    assert sum(slept) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_large_write_inserts_burst_settles(monkeypatch):
    slept: list[float] = []

    async def _record(seconds):
        slept.append(seconds)

    monkeypatch.setattr("flipperzero_mcp.rpc.protobuf_rpc.asyncio.sleep", _record)
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    # Two-and-a-bit bursts so the burst settle fires after each full burst.
    content = b"Z" * (2 * rpc._WRITE_BURST_BYTES + 5000)

    assert await rpc.storage_write("/ext/huge.bin", content) is True

    burst_settles = [s for s in slept if s == rpc._WRITE_BURST_SETTLE_S]
    assert len(burst_settles) == 2  # one drain window per completed burst
    slept: list[float] = []

    async def _record(seconds):
        slept.append(seconds)

    monkeypatch.setattr("flipperzero_mcp.rpc.protobuf_rpc.asyncio.sleep", _record)
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True

    assert await rpc.storage_write("/ext/small.bin", b"hi") is True
    assert slept == []  # a one-fragment write needs no backpressure


@pytest.mark.asyncio
async def test_small_write_is_single_frame():
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    ok = await rpc.storage_write("/ext/small.bin", b"hi")
    assert ok is True
    frames = _decode_frames(transport.sent)
    assert len(frames) == 1
    assert frames[0].has_next is False


@pytest.mark.asyncio
async def test_empty_write_sends_one_frame():
    transport = RecordingTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    ok = await rpc.storage_write("/ext/empty.bin", b"")
    assert ok is True
    frames = _decode_frames(transport.sent)
    assert len(frames) == 1
    assert frames[0].has_next is False
    assert frames[0].storage_write_request.file.data == b""
