"""Streamed storage_list framing: full collection, truncation, and error status.

Regression coverage for the bug where a multi-frame listing slower than a fixed
outer timeout silently returned an empty list. A truncated or failed listing
must raise, never masquerade as an empty directory.
"""

from __future__ import annotations

import pytest

from flipperzero_mcp.errors import FlipperProtocolError, FlipperTimeoutError
from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, storage_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


def _frame(names: list[str], *, has_next: bool, status: int = flipper_pb2.CommandStatus.OK):
    main = flipper_pb2.Main()
    main.command_status = status
    main.has_next = has_next
    for name in names:
        entry = main.storage_list_response.file.add()
        entry.name = name
        entry.type = storage_pb2.File.DIR
        entry.size = 0
    return main


class _StubRPC(ProtobufRPC):
    def __init__(self, first, continuations):
        super().__init__(transport=None)  # transport unused by the framing path
        self._first = first
        self._continuations = list(continuations)

    async def _send_rpc_message(self, _request):
        return self._first

    async def _receive_main_message(self, timeout: float = 2.5):  # noqa: ARG002
        return self._continuations.pop(0) if self._continuations else None


async def test_collects_all_frames():
    rpc = _StubRPC(
        _frame(["a", "b"], has_next=True),
        [_frame(["c"], has_next=True), _frame(["d"], has_next=False)],
    )
    assert await rpc.storage_list("/ext") == ["a", "b", "c", "d"]


async def test_single_frame_empty_directory_is_not_an_error():
    rpc = _StubRPC(_frame([], has_next=False), [])
    assert await rpc.storage_list("/ext/empty") == []


async def test_truncated_stream_raises_timeout():
    rpc = _StubRPC(_frame(["a"], has_next=True), [])  # promises more, none arrive
    with pytest.raises(FlipperTimeoutError):
        await rpc.storage_list_detailed("/ext")


async def test_non_ok_first_status_raises_protocol_error():
    rpc = _StubRPC(
        _frame([], has_next=False, status=flipper_pb2.CommandStatus.ERROR_STORAGE_NOT_EXIST), []
    )
    with pytest.raises(FlipperProtocolError):
        await rpc.storage_list("/ext/missing")


async def test_non_ok_mid_stream_status_raises_protocol_error():
    rpc = _StubRPC(
        _frame(["a"], has_next=True),
        [_frame([], has_next=False, status=flipper_pb2.CommandStatus.ERROR_BUSY)],
    )
    with pytest.raises(FlipperProtocolError):
        await rpc.storage_list_detailed("/ext")


async def test_no_first_response_raises_timeout():
    rpc = _StubRPC(None, [])
    with pytest.raises(FlipperTimeoutError):
        await rpc.storage_list("/ext")
