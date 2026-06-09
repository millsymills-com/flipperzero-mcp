"""Unit tests for system_update / system_reboot RPCs."""

import pytest

from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, system_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class UpdateTransport:
    def __init__(self, code):
        self.sent: list[bytes] = []
        reply = flipper_pb2.Main()
        reply.command_status = flipper_pb2.CommandStatus.OK
        reply.system_update_response.code = code
        payload = reply.SerializeToString()
        self._reply = ProtobufRPC._encode_varint(len(payload)) + payload
        self._pos = 0

    async def send(self, data):
        self.sent.append(data)

    async def receive_exact(self, n, timeout=None):  # noqa: ARG002
        out = self._reply[self._pos : self._pos + n]
        self._pos += n
        return out

    async def is_connected(self):
        return True


@pytest.mark.asyncio
async def test_system_update_returns_ok_code():
    rpc = ProtobufRPC(UpdateTransport(system_pb2.UpdateResponse.OK))  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    code = await rpc.system_update("/ext/update/x/update.fuf")
    assert code == system_pb2.UpdateResponse.OK


@pytest.mark.asyncio
async def test_system_update_returns_target_mismatch_code():
    rpc = ProtobufRPC(UpdateTransport(system_pb2.UpdateResponse.TargetMismatch))  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    code = await rpc.system_update("/ext/update/x/update.fuf")
    assert code == system_pb2.UpdateResponse.TargetMismatch


@pytest.mark.asyncio
async def test_system_reboot_update_sends_frame_without_awaiting_response():
    class RebootTransport:
        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

        async def is_connected(self):
            return True

    transport = RebootTransport()
    rpc = ProtobufRPC(transport)  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    await rpc.system_reboot_update()
    assert len(transport.sent) == 1
