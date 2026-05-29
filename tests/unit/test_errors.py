import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperConnectionError,
    FlipperError,
    FlipperNotConnectedError,
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


def test_handle_client_error_wraps_unknown():
    with pytest.raises(ToolError, match="unexpected"):
        handle_client_error(ValueError("boom"))
