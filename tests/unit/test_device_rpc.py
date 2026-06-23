"""Unit tests for P1 device RPC reads (app/desktop/gpio)."""

import pytest

from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, gpio_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class ReplyTransport:
    """Serves one or more pre-serialized Main replies in order."""

    def __init__(self, *replies):
        self.sent: list[bytes] = []
        buf = b""
        for reply in replies:
            payload = reply.SerializeToString()
            buf += ProtobufRPC._encode_varint(len(payload)) + payload
        self._buf = buf
        self._pos = 0

    async def send(self, data):
        self.sent.append(data)

    async def receive_exact(self, n, timeout=None):  # noqa: ARG002
        out = self._buf[self._pos : self._pos + n]
        self._pos += n
        return out

    async def is_connected(self):
        return True


def _make_rpc(*replies):
    rpc = ProtobufRPC(ReplyTransport(*replies))  # ty: ignore[invalid-argument-type]
    rpc._rpc_session_started = True
    return rpc


@pytest.mark.asyncio
async def test_app_lock_status_returns_locked_bool():
    reply = flipper_pb2.Main()
    reply.command_status = flipper_pb2.CommandStatus.OK
    reply.app_lock_status_response.locked = True
    rpc = _make_rpc(reply)
    assert await rpc.app_lock_status() is True


@pytest.mark.asyncio
async def test_app_lock_status_returns_none_on_error_status():
    reply = flipper_pb2.Main()
    reply.command_status = flipper_pb2.CommandStatus.ERROR
    rpc = _make_rpc(reply)
    assert await rpc.app_lock_status() is None


@pytest.mark.asyncio
async def test_app_get_error_returns_code_and_text():
    reply = flipper_pb2.Main()
    reply.command_status = flipper_pb2.CommandStatus.OK
    reply.app_get_error_response.code = 5
    reply.app_get_error_response.text = "boom"
    rpc = _make_rpc(reply)
    assert await rpc.app_get_error() == {"code": 5, "text": "boom"}


@pytest.mark.asyncio
async def test_desktop_is_locked_true_when_status_ok():
    # Firmware returns OK when locked (rpc_desktop.c).
    reply = flipper_pb2.Main()
    reply.command_id = 1  # firmware echoes the request id; never a zero-length frame
    reply.command_status = flipper_pb2.CommandStatus.OK
    rpc = _make_rpc(reply)
    assert await rpc.desktop_is_locked() is True


@pytest.mark.asyncio
async def test_desktop_is_locked_false_when_status_error():
    # Firmware returns plain ERROR when unlocked.
    reply = flipper_pb2.Main()
    reply.command_id = 1
    reply.command_status = flipper_pb2.CommandStatus.ERROR
    rpc = _make_rpc(reply)
    assert await rpc.desktop_is_locked() is False


@pytest.mark.asyncio
async def test_desktop_is_locked_none_on_unexpected_status():
    reply = flipper_pb2.Main()
    reply.command_id = 1
    reply.command_status = flipper_pb2.CommandStatus.ERROR_BUSY
    rpc = _make_rpc(reply)
    assert await rpc.desktop_is_locked() is None


@pytest.mark.asyncio
async def test_gpio_read_returns_mode_and_value_for_input_pin():
    mode_reply = flipper_pb2.Main()
    mode_reply.command_status = flipper_pb2.CommandStatus.OK
    mode_reply.gpio_get_pin_mode_response.mode = gpio_pb2.GpioPinMode.INPUT
    value_reply = flipper_pb2.Main()
    value_reply.command_status = flipper_pb2.CommandStatus.OK
    value_reply.gpio_read_pin_response.value = 1
    rpc = _make_rpc(mode_reply, value_reply)
    assert await rpc.gpio_read(3) == {"pin": 3, "mode": "input", "value": 1}


@pytest.mark.asyncio
async def test_gpio_read_unconfigured_pin_reports_no_mode_or_value():
    mode_reply = flipper_pb2.Main()
    mode_reply.command_status = flipper_pb2.CommandStatus.ERROR_GPIO_UNKNOWN_PIN_MODE
    value_reply = flipper_pb2.Main()
    value_reply.command_status = flipper_pb2.CommandStatus.ERROR_GPIO_MODE_INCORRECT
    rpc = _make_rpc(mode_reply, value_reply)
    assert await rpc.gpio_read(0) == {"pin": 0, "mode": "unconfigured", "value": None}


@pytest.mark.asyncio
async def test_gpio_read_output_pin_has_no_readable_value():
    mode_reply = flipper_pb2.Main()
    mode_reply.command_status = flipper_pb2.CommandStatus.OK
    mode_reply.gpio_get_pin_mode_response.mode = gpio_pb2.GpioPinMode.OUTPUT
    value_reply = flipper_pb2.Main()
    value_reply.command_status = flipper_pb2.CommandStatus.ERROR_GPIO_MODE_INCORRECT
    rpc = _make_rpc(mode_reply, value_reply)
    assert await rpc.gpio_read(4) == {"pin": 4, "mode": "output", "value": None}


@pytest.mark.asyncio
async def test_gpio_read_none_on_unexpected_mode_status():
    mode_reply = flipper_pb2.Main()
    mode_reply.command_id = 1
    mode_reply.command_status = flipper_pb2.CommandStatus.ERROR_BUSY
    rpc = _make_rpc(mode_reply)
    assert await rpc.gpio_read(0) is None
