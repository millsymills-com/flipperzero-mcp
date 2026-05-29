"""Entry point for running flipperzero-mcp as a module."""

from __future__ import annotations

from flipperzero_mcp._logging import configure_logging
from flipperzero_mcp.server import create_server


def main() -> None:
    """Start the Flipper MCP server over stdio."""
    configure_logging()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
