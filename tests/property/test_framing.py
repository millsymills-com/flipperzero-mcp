"""Property tests for the nanopb varint framing codec."""

from hypothesis import given
from hypothesis import strategies as st

from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


@given(st.integers(min_value=0, max_value=2**31 - 1))
def test_varint_roundtrip(n):
    encoded = ProtobufRPC._encode_varint(n)
    value = 0
    shift = 0
    for byte in encoded:
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    assert value == n


@given(st.integers(min_value=0, max_value=127))
def test_small_varint_is_single_byte(n):
    assert len(ProtobufRPC._encode_varint(n)) == 1
