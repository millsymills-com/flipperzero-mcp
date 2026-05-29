import json
import logging
import sys

import pytest

from flipperzero_mcp._logging import JSONFormatter, configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_configure_logging_installs_single_stderr_json_handler():
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert isinstance(handler.formatter, JSONFormatter)


def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()
    assert len(logging.getLogger().handlers) == 1


def test_json_formatter_emits_required_keys():
    record = logging.LogRecord(
        name="flipper.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    parsed = json.loads(JSONFormatter().format(record))
    assert set(parsed) >= {"time", "level", "logger", "message"}
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "flipper.test"
    assert parsed["message"] == "hello world"
    assert "exc_info" not in parsed


def test_json_formatter_includes_exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="flipper.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="failed",
        args=(),
        exc_info=exc_info,
    )
    parsed = json.loads(JSONFormatter().format(record))
    assert "exc_info" in parsed
    assert "ValueError: boom" in parsed["exc_info"]
