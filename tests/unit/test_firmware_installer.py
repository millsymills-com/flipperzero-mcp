"""Unit tests for the firmware installer orchestration."""

import hashlib
from typing import ClassVar

import pytest

from flipperzero_mcp.errors import FlipperTimeoutError
from flipperzero_mcp.firmware.installer import (
    FlashError,
    _check_md5,
    _push_file,
    _trigger_update,
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
async def test_check_md5_matches_after_digest_becomes_readable():
    rpc = _Md5RPC([None, None, "abc"])
    assert await _check_md5(rpc, "/ext/x", "abc", settle_s=0.0) == "match"
    assert rpc.calls == 3


@pytest.mark.asyncio
async def test_check_md5_reports_mismatch_immediately():
    rpc = _Md5RPC(["deadbeef", "abc"])
    assert await _check_md5(rpc, "/ext/x", "abc", settle_s=0.0) == "mismatch"
    assert rpc.calls == 1  # did not retry past a non-None mismatch


@pytest.mark.asyncio
async def test_check_md5_reports_unreadable_when_digest_never_returns():
    rpc = _Md5RPC([None, None, None, None, None])
    assert await _check_md5(rpc, "/ext/x", "abc", settle_s=0.0) == "unreadable"
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
async def test_install_aborts_when_session_wedges_with_no_resync():
    # A wedged session leaves the post-write digest unreadable; with no resync
    # hook there is no recovery, so the flash must fail closed before reboot.
    rpc = _WedgeRPC()
    with pytest.raises(FlashError, match="stopped responding"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


class _WedgeRPC(FakeRPC):
    """FakeRPC modelling a wedged session: the digest reads unreadable.

    ``store`` is shared across instances to model a single SD card surviving
    reconnects, so a file written on a wedged session verifies on a fresh one.
    """

    def __init__(self, *, alive=False, store=None):
        super().__init__()
        self.alive = alive
        if store is not None:
            self.store = store

    async def storage_md5sum(self, path):
        if not self.alive:
            return None  # wedged: digest unreadable until the session is re-synced
        return await super().storage_md5sum(path)


@pytest.mark.asyncio
async def test_push_file_recovers_by_verifying_after_resync():
    shared: dict[str, bytes] = {}
    wedged = _WedgeRPC(store=shared)
    healthy = _WedgeRPC(alive=True, store=shared)

    async def resync():
        return healthy

    out = await _push_file(wedged, "/ext/update/x/f.bin", b"payload", resync=resync)
    assert out is healthy
    # The data was written once on the wedged session and verified after the
    # reconnect; it was not rewritten on the healthy session.
    assert "write:/ext/update/x/f.bin" in wedged.calls
    assert "write:/ext/update/x/f.bin" not in healthy.calls


@pytest.mark.asyncio
async def test_push_file_fails_closed_when_resync_never_recovers():
    shared: dict[str, bytes] = {}

    async def resync():
        return _WedgeRPC(store=shared)  # every fresh session is still wedged

    with pytest.raises(FlashError, match="stopped responding"):
        await _push_file(_WedgeRPC(store=shared), "/ext/update/x/f.bin", b"x", resync=resync)


@pytest.mark.asyncio
async def test_push_file_fails_on_persistent_md5_mismatch():
    # A wedged session can return a garbage (non-None, wrong) digest, so a single
    # mismatch is not trusted - it is re-verified after a reconnect. A mismatch
    # that survives every reconnect is a real corrupt transfer and fails closed.
    class BadMd5RPC(FakeRPC):
        async def storage_md5sum(self, path):  # noqa: ARG002
            return "deadbeef"  # never the expected digest, even on a fresh session

    resyncs = 0

    async def resync():
        nonlocal resyncs
        resyncs += 1
        return BadMd5RPC()

    with pytest.raises(FlashError, match="md5 mismatch"):
        await _push_file(BadMd5RPC(), "/ext/update/x/f.bin", b"payload", resync=resync)
    assert resyncs == 2  # exhausted the reconnect retries before declaring mismatch


@pytest.mark.asyncio
async def test_install_resyncs_and_resumes_after_wedge():
    shared: dict[str, bytes] = {}
    wedged = _WedgeRPC(store=shared)  # first session wedges (digest unreadable)
    healthy = _WedgeRPC(alive=True, store=shared)  # reconnect lands a live session

    async def resync():
        return healthy

    await install_bundle(wedged, FakeBundle(), pkg_name="upd-test", resync=resync)
    assert healthy.rebooted is True
    assert wedged.rebooted is False


class _UpdateCodeRPC(FakeRPC):
    """Returns a scripted sequence of system_update codes."""

    def __init__(self, codes):
        super().__init__()
        self._codes = list(codes)

    async def system_update(self, manifest_path):  # noqa: ARG002
        return self._codes.pop(0)


@pytest.mark.asyncio
async def test_trigger_update_returns_on_ok():
    rpc = _UpdateCodeRPC([system_pb2.UpdateResponse.OK])
    assert await _trigger_update(rpc, "/m.fuf", resync=None) is rpc


@pytest.mark.asyncio
async def test_trigger_update_retries_transient_unspecified_then_succeeds():
    first = _UpdateCodeRPC([system_pb2.UpdateResponse.UnspecifiedError])
    healthy = _UpdateCodeRPC([system_pb2.UpdateResponse.OK])
    resyncs = 0

    async def resync():
        nonlocal resyncs
        resyncs += 1
        return healthy

    out = await _trigger_update(first, "/m.fuf", resync=resync)
    assert out is healthy
    assert resyncs == 1


@pytest.mark.asyncio
async def test_trigger_update_fails_on_persistent_unspecified():
    rpc = _UpdateCodeRPC([system_pb2.UpdateResponse.UnspecifiedError] * 3)

    async def resync():
        return rpc

    with pytest.raises(FlashError, match="unspecified update error"):
        await _trigger_update(rpc, "/m.fuf", resync=resync)


@pytest.mark.asyncio
async def test_trigger_update_fails_immediately_on_specific_code():
    resyncs = 0

    async def resync():
        nonlocal resyncs
        resyncs += 1
        return rpc

    rpc = _UpdateCodeRPC([system_pb2.UpdateResponse.ManifestInvalid])
    with pytest.raises(FlashError, match="manifest"):
        await _trigger_update(rpc, "/m.fuf", resync=resync)
    assert resyncs == 0  # a definitive rejection is not retried


@pytest.mark.asyncio
async def test_trigger_update_wraps_link_drop():
    class LinkDropRPC(FakeRPC):
        async def system_update(self, manifest_path):  # noqa: ARG002
            raise FlipperTimeoutError("no response to system_update")

    with pytest.raises(FlashError, match="link dropped"):
        await _trigger_update(LinkDropRPC(), "/m.fuf", resync=None)
