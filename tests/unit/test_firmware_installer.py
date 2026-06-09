"""Unit tests for the firmware installer orchestration."""

import hashlib
from typing import ClassVar

import pytest

from flipperzero_mcp.errors import FlipperTimeoutError
from flipperzero_mcp.firmware.installer import (
    FlashError,
    _probe_session,
    _verify_md5,
    install_bundle,
)
from flipperzero_mcp.rpc.protobuf_gen import system_pb2


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("flipperzero_mcp.firmware.installer.asyncio.sleep", _instant)


class _Md5RPC:
    """Minimal RPC stub returning a scripted sequence of md5sum results."""

    def __init__(self, results: list[str | None]):
        self._results = results
        self.calls = 0

    async def storage_md5sum(self, path: str) -> str | None:
        _ = path
        result = self._results[self.calls]
        self.calls += 1
        return result


@pytest.mark.asyncio
async def test_verify_md5_retries_while_digest_unreadable():
    rpc = _Md5RPC([None, None, "abc"])
    assert await _verify_md5(rpc, "/ext/x", "abc", settle_s=0.0) is True
    assert rpc.calls == 3


@pytest.mark.asyncio
async def test_verify_md5_fails_immediately_on_definitive_mismatch():
    rpc = _Md5RPC(["deadbeef", "abc"])
    assert await _verify_md5(rpc, "/ext/x", "abc", settle_s=0.0) is False
    assert rpc.calls == 1  # did not retry past a non-None mismatch


@pytest.mark.asyncio
async def test_verify_md5_gives_up_if_digest_never_readable():
    rpc = _Md5RPC([None, None, None, None, None])
    assert await _verify_md5(rpc, "/ext/x", "abc", settle_s=0.0) is False
    assert rpc.calls == 5


class FakeBundle:
    manifest_name: ClassVar[str] = "update.fuf"
    target: ClassVar[str] = "f7"
    files: ClassVar[list[tuple[str, bytes]]] = [
        ("update.fuf", b"manifest"),
        ("firmware.dfu", b"DFU" * 100),
    ]


class FakeRPC:
    def __init__(self, *, update_code=system_pb2.UpdateResponse.OK, target="7"):
        self._update_code = update_code
        self._target = target
        self.store: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.rebooted = False

    async def get_device_info(self):
        return {"hardware_target": self._target, "hardware_name": "Lun10n"}

    async def storage_mkdir(self, path):
        self.calls.append(f"mkdir:{path}")
        return True

    async def storage_write(self, path, content):
        self.store[path] = bytes(content)
        self.calls.append(f"write:{path}")
        return True

    async def storage_md5sum(self, path):
        return hashlib.md5(self.store[path], usedforsecurity=False).hexdigest()

    async def ping(self):
        self.calls.append("ping")
        return b"ping"

    async def system_update(self, manifest_path):
        self.calls.append(f"update:{manifest_path}")
        return self._update_code

    async def system_reboot_update(self):
        self.rebooted = True


@pytest.mark.asyncio
async def test_install_pushes_files_then_updates_then_reboots():
    rpc = FakeRPC()
    await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert "mkdir:/ext/update/upd-test" in rpc.calls
    assert "write:/ext/update/upd-test/firmware.dfu" in rpc.calls
    assert "update:/ext/update/upd-test/update.fuf" in rpc.calls
    assert rpc.rebooted is True


@pytest.mark.asyncio
async def test_install_aborts_on_target_mismatch():
    rpc = FakeRPC(target="18")  # device f18, bundle f7
    with pytest.raises(FlashError, match="target"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_install_aborts_on_missing_hardware_target():
    rpc = FakeRPC(target="")
    with pytest.raises(FlashError, match="hardware_target"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_install_aborts_on_non_ok_update_code():
    rpc = FakeRPC(update_code=system_pb2.UpdateResponse.ManifestInvalid)
    with pytest.raises(FlashError, match="manifest"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_install_wraps_link_drop_during_update_as_flash_error():
    class LinkDropRPC(FakeRPC):
        async def system_update(self, manifest_path):  # noqa: ARG002
            raise FlipperTimeoutError("no response to system_update")

    rpc = LinkDropRPC()
    with pytest.raises(FlashError, match="link dropped"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_install_aborts_when_session_wedges_after_write():
    class WedgeRPC(FakeRPC):
        async def ping(self):
            return None  # session unresponsive after the write

    rpc = WedgeRPC()
    with pytest.raises(FlashError, match="stopped responding"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_probe_session_false_when_ping_raises():
    class WedgeRPC:
        async def ping(self):
            raise FlipperTimeoutError("no response to ping")

    assert await _probe_session(WedgeRPC(), settle_s=0.0) is False


@pytest.mark.asyncio
async def test_probe_session_true_when_ping_answers():
    class HealthyRPC:
        async def ping(self):
            return b"ping"

    assert await _probe_session(HealthyRPC(), settle_s=0.0) is True
