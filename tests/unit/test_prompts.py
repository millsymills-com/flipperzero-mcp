from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


def _server():
    return create_server(FlipperConfig.model_construct())


async def test_prompts_registered():
    async with Client(_server()) as client:
        names = {p.name for p in await client.list_prompts()}
    assert {"manage_flipper", "troubleshoot_connection"} <= names


async def test_manage_flipper_prompt_renders():
    async with Client(_server()) as client:
        result = await client.get_prompt("manage_flipper")
    text = result.messages[0].content.text
    assert "flipper://reference/cli" in text
    assert "flipperzero_cli_exec" in text
