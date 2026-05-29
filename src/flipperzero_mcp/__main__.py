"""Entry point for running flipperzero-mcp as a module."""

from __future__ import annotations

import logging

from flipperzero_mcp._logging import configure_logging
from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


def main() -> None:
    """Start the Flipper MCP server over stdio."""
    config = FlipperConfig()
    configure_logging(logging.DEBUG if config.debug else logging.INFO)
    server = create_server(config)
    server.run()


if __name__ == "__main__":
    main()
