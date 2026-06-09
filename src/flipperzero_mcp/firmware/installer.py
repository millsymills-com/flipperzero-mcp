"""Push an update bundle to the device and trigger the on-device updater."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from flipperzero_mcp.errors import FlipperTimeoutError
from flipperzero_mcp.firmware.codes import update_code_message

logger = logging.getLogger(__name__)

_UPDATE_ROOT = "/ext/update"
# storage_md5sum returns None while the device is still flushing a large write
# to SD; retry across this many attempts with a settle delay before trusting it.
_MD5_ATTEMPTS = 5
_MD5_SETTLE_S = 2.0
# A multi-MB storage_write transfers the data but can wedge the RPC session, so
# the post-write digest reads back unreadable. The wedge clears on a transport
# reconnect; reconnect and re-verify (without rewriting) this many times.
_RESYNC_ATTEMPTS = 2

_Md5Status = Literal["match", "mismatch", "unreadable"]


class FlashError(RuntimeError):
    """Raised when a firmware flash cannot proceed safely."""


class _RPCLike(Protocol):
    async def get_device_info(self) -> dict[str, Any]: ...
    async def storage_mkdir(self, path: str) -> bool: ...
    async def storage_write(self, path: str, content: bytes) -> bool: ...
    async def storage_md5sum(self, path: str) -> str | None: ...
    async def system_update(self, manifest_path: str) -> int: ...
    async def system_reboot_update(self) -> None: ...


class _BundleLike(Protocol):
    manifest_name: str
    target: str
    files: list[tuple[str, bytes]]


class _Md5Reader(Protocol):
    async def storage_md5sum(self, path: str) -> str | None: ...


_Resync = Callable[[], Awaitable["_RPCLike"]]


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
    """Write one file and confirm its on-device md5, recovering a wedged session.

    A multi-MB ``storage_write`` transfers the data correctly but can wedge the
    RPC session, after which ``storage_md5sum`` reads back ``None`` or a garbage
    digest. The wedge clears on a transport reconnect, after which the
    already-written data verifies, so a non-matching digest is treated as
    untrusted: ``resync`` and re-verify on the fresh session *without* rewriting
    (a fresh write would just re-wedge). Only a digest that keeps disagreeing
    after a clean reconnect is a real mismatch.

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
    status: _Md5Status = "unreadable"
    for attempt in range(_RESYNC_ATTEMPTS + 1):
        try:
            await rpc.storage_write(dest, data)
            status = await _check_md5(rpc, dest, expected)
        except (OSError, RuntimeError, FlipperTimeoutError):
            status = "unreadable"  # link wedged mid-write; verify after reconnect
        if status == "match":
            return rpc
        if resync is None or attempt == _RESYNC_ATTEMPTS:
            break
        rpc = await resync()
        try:
            status = await _check_md5(rpc, dest, expected)
        except (OSError, RuntimeError, FlipperTimeoutError):
            status = "unreadable"
        if status == "match":
            return rpc  # data landed; only the stale session was wedged
    if status == "mismatch":
        raise FlashError(
            f"md5 mismatch after writing {dest}; the on-device data does not match "
            "the bundle even after reconnecting - corrupt transfer, flash aborted"
        )
    raise FlashError(
        f"device RPC session stopped responding after writing {dest}; the update was "
        "not applied - reconnect to re-establish the session and retry (a transport "
        "reconnect clears the wedge; power-cycle only if it persists)"
    )


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
    try:
        code = await rpc.system_update(manifest)
    except FlipperTimeoutError as e:
        raise FlashError(f"device link dropped during update validation: {e}") from e
    message = update_code_message(code)
    if message is not None:
        raise FlashError(f"device rejected update: {message}")

    await rpc.system_reboot_update()
