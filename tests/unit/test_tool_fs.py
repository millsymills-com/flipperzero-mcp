import hashlib

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def get_name(self):
        return "Fake"

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def is_connected(self):
        return True


def _make_rpc(*, store=None, md5_override=None, corrupt_read=False):
    """Build a FakeRPC class with controllable storage behavior.

    Args:
        store: Shared dict acting as the device filesystem (path -> bytes).
        md5_override: If set, storage_md5sum returns this regardless of content.
        corrupt_read: If True, storage_read returns mangled bytes.
    """
    store = store if store is not None else {}

    class FakeRPC:
        def __init__(self, _transport, *, io_lock=None):
            self.store = store
            self.io_lock = io_lock

        async def ping(self, data=b"ping"):
            return data

        async def get_device_info(self):
            return {"hardware_name": "Flipper", "firmware_version": "1.2.3"}

        async def storage_info(self, _path):
            return (1000, 500)

        async def storage_write(self, path, content):
            self.store[path] = bytes(content)
            return True

        async def storage_read(self, path):
            data = self.store.get(path, b"")
            return b"corrupt" + data if corrupt_read else data

        async def storage_mkdir(self, path):
            self.store[path] = None
            return True

        async def storage_list_detailed(self, _path, **_kwargs):
            return [
                {"name": "a.txt", "type": "FILE", "size": 3},
                {"name": "sub", "type": "DIR", "size": 0},
            ]

        async def storage_md5sum(self, path):
            if md5_override is not None:
                return md5_override
            data = self.store.get(path)
            if data is None:
                return None
            return hashlib.md5(data, usedforsecurity=False).hexdigest()

    return FakeRPC


async def _server(monkeypatch, rpc_cls):
    monkeypatch.setattr("flipperzero_mcp.server.get_transport", lambda _t, _c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", rpc_cls)
    return create_server(FlipperConfig(_env_file=None))


async def test_fs_list_returns_entries(monkeypatch):
    server = await _server(monkeypatch, _make_rpc())
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_fs_list", {"path": "/ext"})
        entries = result.data["entries"]
        names = {e["name"] for e in entries}
        assert names == {"a.txt", "sub"}
        assert any(e["type"] == "DIR" for e in entries)


async def test_fs_mkdir_creates_directory(monkeypatch):
    store: dict = {}
    server = await _server(monkeypatch, _make_rpc(store=store))
    async with Client(server) as client:
        result = await client.call_tool("flipperzero_fs_mkdir", {"path": "/ext/newdir"})
        assert result.data["created"] is True
        assert "/ext/newdir" in store


async def test_fs_push_verifies_md5(monkeypatch, tmp_path):
    store: dict = {}
    local = tmp_path / "payload.bin"
    local.write_bytes(b"hello flipper")
    server = await _server(monkeypatch, _make_rpc(store=store))
    async with Client(server) as client:
        result = await client.call_tool(
            "flipperzero_fs_push",
            {"local_path": str(local), "dest_path": "/ext/payload.bin"},
        )
        assert result.data["verified"] is True
        assert store["/ext/payload.bin"] == b"hello flipper"


async def test_fs_push_fails_loud_on_md5_mismatch(monkeypatch, tmp_path):
    local = tmp_path / "payload.bin"
    local.write_bytes(b"hello flipper")
    server = await _server(monkeypatch, _make_rpc(md5_override="deadbeef"))
    async with Client(server) as client:
        with pytest.raises(ToolError, match=r"(?i)mismatch|integrity"):
            await client.call_tool(
                "flipperzero_fs_push",
                {"local_path": str(local), "dest_path": "/ext/payload.bin"},
            )


async def test_fs_pull_verifies_md5(monkeypatch, tmp_path):
    content = b"down to host"
    store = {"/ext/src.bin": content}
    out = tmp_path / "out.bin"
    server = await _server(monkeypatch, _make_rpc(store=store))
    async with Client(server) as client:
        result = await client.call_tool(
            "flipperzero_fs_pull",
            {"src_path": "/ext/src.bin", "local_path": str(out)},
        )
        assert result.data["verified"] is True
        assert out.read_bytes() == content


async def test_fs_pull_fails_loud_on_md5_mismatch(monkeypatch, tmp_path):
    content = b"down to host"
    store = {"/ext/src.bin": content}
    out = tmp_path / "out.bin"
    server = await _server(monkeypatch, _make_rpc(store=store, corrupt_read=True))
    async with Client(server) as client:
        with pytest.raises(ToolError, match=r"(?i)mismatch|integrity"):
            await client.call_tool(
                "flipperzero_fs_pull",
                {"src_path": "/ext/src.bin", "local_path": str(out)},
            )
