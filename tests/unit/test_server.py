from fastmcp import FastMCP

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


def test_create_server_with_default_config():
    config = FlipperConfig(_env_file=None)
    assert config.transport == "auto"

    server = create_server(config)
    assert isinstance(server, FastMCP)
    assert server.name == "flipperzero-mcp"
