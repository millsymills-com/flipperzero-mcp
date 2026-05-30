from fastmcp import FastMCP

from flipperzero_mcp.server import create_server


def test_create_server_with_default_config():
    server = create_server()
    assert isinstance(server, FastMCP)
    assert server.name == "flipperzero-mcp"
