"""Push an update bundle to the device and trigger the on-device updater."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from flipperzero_mcp.errors import FlipperTimeoutError
from flipperzero_mcp.firmware.codes import update_code_message
from flipperzero_mcp.rpc.protobuf_gen import system_pb2

logger = logging.getLogger(__name__)

_UPDATE_ROOT = "/ext/update"
# storage_md5sum returns None while the device is still flushing a large write
# to SD; retry across this many attempts with a settle delay before trusting it.
_MD5_ATTEMPTS = 5
_MD5_SETTLE_S = 2.0
# storage_md5sum hashes the whole file on-device; for a multi-MB blob that is
# slow (60-120 s for 11 MB) and wedges the session. Above this size, verify by
# storage_stat size instead (immediate, no wedge) and let the device's own
# update validation provide cryptographic integrity on apply.
_MD5_VERIFY_MAX_BYTES = 2 * 1024 * 1024
# A multi-MB storage_write transfers the data but can wedge the RPC session, so
# the post-write digest reads back unreadable. The wedge clears on a transport
# reconnect; reconnect and re-verify (without rewriting) this many times.
_RESYNC_ATTEMPTS = 2
# After reconnecting from a large-write wedge, the device needs a moment to be
# ready to negotiate a new RPC session (past the negotiation cooldown) before
# the re-verify; settle this long so the fresh session's first call succeeds.
_POST_WRITE_SETTLE_S = 8.0
# system_update issued right after the final large write can return a transient
# UnspecifiedError while the device is still settling; settle this long before
# (re)trying the update trigger.
_UPDATE_SETTLE_S = 3.0

_Md5Status = Literal["match", "mismatch", "unreadable"]


class FlashError(RuntimeError):
    """Raised when a firmware flash cannot proceed safely."""


class _RPCLike(Protocol):
    async def get_device_info(self) -> dict[str, Any]: ...
    async def storage_mkdir(self, path: str) -> bool: ...
    async def storage_write(self, path: str, content: bytes) -> bool: ...
    async def storage_md5sum(self, path: str) -> str | None: ...
    async def storage_stat(self, path: str) -> dict[str, Any] | None: ...
    async def system_update(self, manifest_path: str) -> int: ...
    async def system_reboot_update(self) -> None: ...


class _BundleLike(Protocol):
    manifest_name: str
    target: str
    files: list[tuple[str, bytes]]


class _Md5Reader(Protocol):
    async def storage_md5sum(self, path: str) -> str | None: ...


class _StatReader(Protocol):
    async def storage_stat(self, path: str) -> dict[str, Any] | None: ...


_Resync = Callable[[], Awaitable["_RPCLike"]]


async def _check_size(rpc: _StatReader, path: str, expected_len: int) -> _Md5Status:
    """Verify a written file by its on-device size.

    Used for files too large to md5sum reliably: ``storage_stat`` returns the
    size immediately without hashing, so it neither stalls nor wedges the
    session. A size match catches the dominant transfer failure (a truncated
    push); cryptographic integrity is enforced by the device's update
    validation when the bundle is applied.

    Returns:
        ``"match"`` if the on-device size equals ``expected_len``, ``"mismatch"``
        if it differs, or ``"unreadable"`` if the file cannot be stat'd.
    """
    stat = await rpc.storage_stat(path)
    if stat is None:
        return "unreadable"
    return "match" if stat.get("size") == expected_len else "mismatch"


async def _verify_written(rpc: _RPCLike, dest: str, data: bytes, expected_md5: str) -> _Md5Status:
    """Verify a freshly written file, choosing the check by size.

    Small files use md5 (cryptographic); files above ``_MD5_VERIFY_MAX_BYTES``
    use size, because hashing a multi-MB blob on-device is slow and wedge-prone.
    """
    if len(data) > _MD5_VERIFY_MAX_BYTES:
        return await _check_size(rpc, dest, len(data))
    return await _check_md5(rpc, dest, expected_md5)


async def _check_md5(
    rpc: _Md5Reader, path: str, expected: str, *, settle_s: float = _MD5_SETTLE_S
) -> _Md5Status:
    """Classify the device-side md5 against ``expected``.

    ``storage_md5sum`` returns ``None`` while the device is still flushing a
    large write to SD, so a ``None`` is treated as "not ready yet" and retried
    after a settle delay.

    Args:
        rpc: Live RPC client.
        path: Device path just written.
        expected: Expected lowercase hex md5 of the local data.
        settle_s: Delay between retries (0 in tests for determinism).

    Returns:
        ``"match"`` if the digest equals ``expected``, ``"mismatch"`` for a
        definitive non-equal digest (corrupt transfer or wrong data), or
        ``"unreadable"`` if it stays ``None`` across all attempts.
    """
    for attempt in range(_MD5_ATTEMPTS):
        device_md5 = await rpc.storage_md5sum(path)
        if device_md5 == expected:
            return "match"
        if device_md5 is not None:
            return "mismatch"
        if attempt + 1 < _MD5_ATTEMPTS:
            await asyncio.sleep(settle_s)
    return "unreadable"


async def _push_file(
    rpc: _RPCLike, dest: str, data: bytes, *, resync: _Resync | None
) -> _RPCLike:
    """Write one file and verify it on-device, recovering a wedged session.

    A multi-MB ``storage_write`` transfers the data and acks it, but then wedges
    the RPC session so the immediate digest reads back ``None`` or garbage. A
    successful write means the data is durably on the SD card, so on a wedge the
    file is *not* rewritten (a rewrite just re-wedges and, for an 11 MB blob,
    wastes minutes): instead ``resync`` reconnects, settles past the negotiation
    cooldown, and re-verifies the existing data. Only a write that itself fails
    is re-sent, and only a digest that keeps disagreeing after a clean reconnect
    is a real mismatch.

    Args:
        rpc: Live RPC client.
        dest: Device path to write.
        data: File contents.
        resync: Reconnect callback returning a fresh RPC client, or ``None`` to
            fail closed without recovery.

    Returns:
        The live RPC client, which ``resync`` may have replaced.

    Raises:
        FlashError: If the digest never matches after the allotted reconnect
            retries (a persistent mismatch points at a corrupt transfer; a
            persistent unreadable digest points at an unrecoverable wedge).
    """
    expected = hashlib.md5(data, usedforsecurity=False).hexdigest()
    written = False
    status: _Md5Status = "unreadable"
    for attempt in range(_RESYNC_ATTEMPTS + 1):
        if not written:
            try:
                written = await rpc.storage_write(dest, data)
            except (OSError, RuntimeError, FlipperTimeoutError):
                written = False
        if written:
            try:
                status = await _verify_written(rpc, dest, data, expected)
            except (OSError, RuntimeError, FlipperTimeoutError):
                status = "unreadable"  # write wedged the session; verify after reconnect
            if status == "match":
                return rpc
            if status == "mismatch":
                written = False  # on-disk data disagrees; re-push on the next pass
        if resync is None or attempt == _RESYNC_ATTEMPTS:
            break
        rpc = await resync()
        await asyncio.sleep(_POST_WRITE_SETTLE_S)
    if status == "mismatch":
        raise FlashError(
            f"verification failed after writing {dest}; the on-device data does not "
            "match the bundle even after reconnecting - corrupt or truncated transfer, "
            "flash aborted"
        )
    raise FlashError(
        f"device RPC session stopped responding after writing {dest}; the update was "
        "not applied - reconnect to re-establish the session and retry (a transport "
        "reconnect clears the wedge; power-cycle only if it persists)"
    )


async def _trigger_update(rpc: _RPCLike, manifest: str, *, resync: _Resync | None) -> _RPCLike:
    """Stage the update via ``system_update``, retrying a transient error.

    Issued right after the final large write, ``system_update`` can return
    ``UnspecifiedError`` while the device is still settling - a short settle and
    a clean session clear it (the CLI ``update install`` succeeds the same way).
    A specific code (target/manifest/integrity mismatch) is a real rejection and
    fails immediately.

    Args:
        rpc: Live RPC client.
        manifest: Device path to the staged ``update.fuf``.
        resync: Reconnect callback for a fresh session between retries, or
            ``None`` to retry on the same session.

    Returns:
        The live RPC client to reboot with.

    Raises:
        FlashError: On a definitive rejection, a dropped link, or an
            ``UnspecifiedError`` that persists across retries.
    """
    for attempt in range(_RESYNC_ATTEMPTS + 1):
        await asyncio.sleep(_UPDATE_SETTLE_S)
        try:
            code = await rpc.system_update(manifest)
        except FlipperTimeoutError as e:
            raise FlashError(f"device link dropped during update validation: {e}") from e
        if code == system_pb2.UpdateResponse.OK:
            return rpc
        if code != system_pb2.UpdateResponse.UnspecifiedError or attempt == _RESYNC_ATTEMPTS:
            raise FlashError(f"device rejected update: {update_code_message(code)}")
        if resync is not None:
            rpc = await resync()
    raise FlashError("device rejected update: unspecified update error (persisted after retries)")


async def install_bundle(
    rpc: _RPCLike, bundle: _BundleLike, *, pkg_name: str, resync: _Resync | None = None
) -> None:
    """Push ``bundle`` to ``/ext/update/<pkg_name>`` and reboot into the updater.

    Args:
        rpc: Live RPC client.
        bundle: Resolved local bundle (manifest + files + target).
        pkg_name: Update subfolder name on the device.
        resync: Reconnect callback returning a fresh RPC client, used to recover
            a session wedged by a large write. ``None`` fails closed instead.

    Raises:
        FlashError: On target mismatch, push/verify failure, or a non-OK update
            result code. The device is not rebooted when this is raised.
    """
    device_info = await rpc.get_device_info()
    raw_target = device_info.get("hardware_target", "").strip()
    if not raw_target:
        raise FlashError(
            "device did not report hardware_target; cannot verify bundle compatibility"
        )
    device_target = f"f{raw_target}"
    if device_target != bundle.target:
        raise FlashError(
            f"bundle target {bundle.target} does not match device target {device_target}"
        )

    pkg_dir = f"{_UPDATE_ROOT}/{pkg_name}"
    await rpc.storage_mkdir(_UPDATE_ROOT)
    await rpc.storage_mkdir(pkg_dir)
    for rel_path, data in bundle.files:
        dest = f"{pkg_dir}/{rel_path}"
        parent = dest.rsplit("/", 1)[0]
        if parent != pkg_dir:
            await rpc.storage_mkdir(parent)
        rpc = await _push_file(rpc, dest, data, resync=resync)

    manifest = f"{pkg_dir}/{bundle.manifest_name}"
    rpc = await _trigger_update(rpc, manifest, resync=resync)
    await rpc.system_reboot_update()
