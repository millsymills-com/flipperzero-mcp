from importlib.resources import files

from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.resources_registry import _RESOURCES
from flipperzero_mcp.server import create_server

_EXPECTED = {
    "flipper://reference/cli",
    "flipper://reference/connection",
    "flipper://reference/filesystem",
    "flipper://workflow/install-app",
    "flipper://workflow/transfer-files",
    "flipper://workflow/flash-esp32",
    "flipper://workflow/capture-replay",
}


def _server():
    return create_server(FlipperConfig.model_construct())


def test_bundled_markdown_files_packaged():
    """Every mapped resource file ships in the package (guards hatch excludes)."""
    pkg = files("flipperzero_mcp.resources")
    present = {p.name for p in pkg.iterdir() if p.name.endswith(".md")}
    assert present == set(_RESOURCES.values())


async def test_all_resources_registered():
    async with Client(_server()) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
    assert uris >= _EXPECTED


async def test_resources_resolve_to_nonempty_markdown():
    async with Client(_server()) as client:
        for uri in _EXPECTED:
            contents = await client.read_resource(uri)
            text = contents[0].text
            assert text
            assert len(text) > 20
            assert "# " in text
