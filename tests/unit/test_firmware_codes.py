from flipperzero_mcp.firmware.codes import update_code_message
from flipperzero_mcp.rpc.protobuf_gen import system_pb2


def test_ok_is_none():
    assert update_code_message(system_pb2.UpdateResponse.OK) is None


def test_target_mismatch_message():
    msg = update_code_message(system_pb2.UpdateResponse.TargetMismatch)
    assert msg is not None
    assert "target" in msg.lower()


def test_unknown_code_falls_back():
    msg = update_code_message(99)
    assert msg is not None
    assert "code 99" in msg.lower()
