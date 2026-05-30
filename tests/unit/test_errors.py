import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperConnectionError,
    FlipperError,
    FlipperNotConnectedError,
    FlipperProtocolError,
    FlipperTimeoutError,
    handle_client_error,
)


def test_not_connected_is_flipper_error():
    assert issubclass(FlipperNotConnectedError, FlipperError)


def test_connection_error_is_flipper_error():
    assert issubclass(FlipperConnectionError, FlipperError)


def test_handle_client_error_maps_not_connected_to_toolerror():
    with pytest.raises(ToolError, match="not connected"):
        handle_client_error(FlipperNotConnectedError("device not connected"))


def test_handle_client_error_maps_timeout():
    with pytest.raises(ToolError, match="timed out"):
        handle_client_error(FlipperTimeoutError("rpc timed out"))


def test_handle_client_error_maps_connection_error():
    with pytest.raises(ToolError, match="connection error"):
        handle_client_error(FlipperConnectionError("usb gone"))


def test_handle_client_error_maps_protocol_error():
    with pytest.raises(ToolError, match="protocol error"):
        handle_client_error(FlipperProtocolError("malformed frame"))


def test_handle_client_error_maps_base_flipper_error():
    with pytest.raises(ToolError, match="Flipper error"):
        handle_client_error(FlipperError("generic"))


def test_handle_client_error_wraps_unknown():
    with pytest.raises(ToolError, match="unexpected"):
        handle_client_error(ValueError("boom"))
