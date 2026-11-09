import logging

import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperCLIRefusedError,
    FlipperCLIUnavailableError,
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


def test__classify_client_error_maps_cli_unavailable():
    with pytest.raises(ToolError, match="CLI text mode unavailable"):
        _classify_client_error(FlipperCLIUnavailableError("wifi transport"))


def test__classify_client_error_maps_cli_refused():
    with pytest.raises(ToolError, match="CLI command refused"):
        _classify_client_error(FlipperCLIRefusedError("transmit gate disabled"))


def test__classify_client_error_maps_base_flipper_error():
    with pytest.raises(ToolError, match="Flipper error"):
        _classify_client_error(FlipperError("generic"))


def test__classify_client_error_wraps_unknown():
    with pytest.raises(ToolError, match="unexpected"):
        _classify_client_error(ValueError("boom"))


def test_unknown_error_logs_supplied_exception(caplog):
    caplog.set_level(logging.ERROR, logger="flipperzero_mcp.errors")
    error = ValueError("boom")
    with pytest.raises(ToolError, match="unexpected"):
        _classify_client_error(error)
    record = next(r for r in caplog.records if r.name == "flipperzero_mcp.errors")
    assert record.exc_info is not None
    assert record.exc_info[1] is error


def test_unknown_error_keeps_original_traceback(caplog):
    caplog.set_level(logging.ERROR, logger="flipperzero_mcp.errors")
    try:
        raise ValueError("original failure")
    except ValueError as error:
        original = error
    with pytest.raises(ToolError, match="unexpected"):
        _classify_client_error(original)
    record = next(r for r in caplog.records if r.name == "flipperzero_mcp.errors")
    assert record.exc_info is not None
    assert record.exc_info[1] is original
    assert record.exc_info[2] is original.__traceback__
