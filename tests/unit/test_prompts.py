from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


def _server():
    return create_server(FlipperConfig.model_construct())


async def test_prompts_registered():
    async with Client(_server()) as client:
        names = {p.name for p in await client.list_prompts()}
    assert {
        "manage_flipper",
        "troubleshoot_connection",
        "flipper_doctor",
        "flipper_install",
    } <= names


async def test_manage_flipper_prompt_renders():
    async with Client(_server()) as client:
        result = await client.get_prompt("manage_flipper")
    text = result.messages[0].content.text
    assert "flipper://reference/cli" in text
    assert "flipperzero_cli_exec" in text


async def test_flipper_doctor_prompt_renders():
    async with Client(_server()) as client:
        result = await client.get_prompt("flipper_doctor")
    text = result.messages[0].content.text
    assert "flipperzero_connection_health" in text
    assert "flipperzero_system_protobuf_version" in text


async def test_flipper_install_prompt_embeds_url_and_pipeline():
    url = "https://github.com/example/flipper-app"
    async with Client(_server()) as client:
        result = await client.get_prompt("flipper_install", {"github_url": url})
    text = result.messages[0].content.text
    assert url in text
    assert "flipperzero_fs_push" in text
    assert "flipper://workflow/install-app" in text
