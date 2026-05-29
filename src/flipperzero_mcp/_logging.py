"""Stderr-bound JSON logging for MCP stdio transport.

stdio reserves stdout for the protocol channel — anything we print or log to
stdout corrupts client framing. This module configures the root logger to
write structured JSON lines to ``sys.stderr`` and is invoked once from
``__main__.py`` before the FastMCP server starts.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """Render log records as one JSON object per line.

    Keeps the schema small and stable so ``jq``/log-aggregator filters can
    pin on field names: ``time``, ``level``, ``logger``, ``message``, plus
    optional ``exc_info`` for tracebacks.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Bind a stderr ``StreamHandler`` with ``JSONFormatter`` to the root logger.

    Idempotent: subsequent calls replace the handler list rather than
    appending, so test runners that ``importlib.reload`` the module don't
    double-up handlers.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
