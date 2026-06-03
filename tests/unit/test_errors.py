import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperConnectionError,
    FlipperError,
    FlipperNotConnectedError,
    FlipperProtocolError,
    FlipperTimeoutError,
    _classify_client_error,
)


def test_not_connected_is_flipper_error():
    assert issubclass(FlipperNotConnectedError, FlipperError)


def test_connection_error_is_flipper_error():
    assert issubclass(FlipperConnectionError, FlipperError)


def test__classify_client_error_maps_not_connected_to_toolerror():
    with pytest.raises(ToolError, match="not connected"):
        _classify_client_error(FlipperNotConnectedError("device not connected"))


def test__classify_client_error_maps_timeout():
    with pytest.raises(ToolError, match="timed out"):
        _classify_client_error(FlipperTimeoutError("rpc timed out"))


def test__classify_client_error_maps_connection_error():
    with pytest.raises(ToolError, match="connection error"):
        _classify_client_error(FlipperConnectionError("usb gone"))


def test__classify_client_error_maps_protocol_error():
    with pytest.raises(ToolError, match="protocol error"):
        _classify_client_error(FlipperProtocolError("malformed frame"))


def test__classify_client_error_maps_base_flipper_error():
    with pytest.raises(ToolError, match="Flipper error"):
        _classify_client_error(FlipperError("generic"))


def test__classify_client_error_wraps_unknown():
    with pytest.raises(ToolError, match="unexpected"):
        _classify_client_error(ValueError("boom"))
