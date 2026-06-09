"""Push an update bundle to the device and trigger the on-device updater."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Protocol

from flipperzero_mcp.firmware.codes import update_code_message

logger = logging.getLogger(__name__)

_UPDATE_ROOT = "/ext/update"
# storage_md5sum returns None while the device is still flushing a large write
# to SD; retry across this many attempts with a settle delay before trusting it.
_MD5_ATTEMPTS = 5
_MD5_SETTLE_S = 2.0


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


async def _verify_md5(
    rpc: _Md5Reader, path: str, expected: str, *, settle_s: float = _MD5_SETTLE_S
) -> bool:
    """Confirm the device-side md5 matches, retrying while the digest is unreadable.

    ``storage_md5sum`` returns ``None`` when the device is still flushing a large
    write to SD, so a ``None`` is treated as "not ready yet" and retried after a
    settle delay. A non-``None`` digest that differs is a definitive mismatch and
    fails immediately.

    Args:
        rpc: Live RPC client.
        path: Device path just written.
        expected: Expected lowercase hex md5 of the local data.
        settle_s: Delay between retries (0 in tests for determinism).

    Returns:
        True if the device digest matches; False on a definitive mismatch or if
        the digest stays unreadable across all attempts.
    """
    for attempt in range(_MD5_ATTEMPTS):
        device_md5 = await rpc.storage_md5sum(path)
        if device_md5 == expected:
            return True
        if device_md5 is not None:
            return False
        if attempt + 1 < _MD5_ATTEMPTS:
            await asyncio.sleep(settle_s)
    return False


async def install_bundle(rpc: _RPCLike, bundle: _BundleLike, *, pkg_name: str) -> None:
    """Push ``bundle`` to ``/ext/update/<pkg_name>`` and reboot into the updater.

    Args:
        rpc: Live RPC client.
        bundle: Resolved local bundle (manifest + files + target).
        pkg_name: Update subfolder name on the device.

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
        if not await rpc.storage_write(dest, data):
            raise FlashError(f"failed to write {dest}")
        expected_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if not await _verify_md5(rpc, dest, expected_md5):
            raise FlashError(f"md5 mismatch after writing {dest}")

    manifest = f"{pkg_dir}/{bundle.manifest_name}"
    code = await rpc.system_update(manifest)
    message = update_code_message(code)
    if message is not None:
        raise FlashError(f"device rejected update: {message}")

    await rpc.system_reboot_update()
