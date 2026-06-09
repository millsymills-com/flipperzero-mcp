"""Push an update bundle to the device and trigger the on-device updater."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Protocol

from flipperzero_mcp.firmware.codes import update_code_message

logger = logging.getLogger(__name__)

_UPDATE_ROOT = "/ext/update"


class FlashError(RuntimeError):
    """Raised when a firmware flash cannot proceed safely."""


class _RPCLike(Protocol):
    async def get_device_info(self) -> dict[str, Any]: ...
    async def storage_mkdir(self, path: str) -> bool: ...
    async def storage_write(self, path: str, content: bytes) -> bool: ...
    async def storage_md5sum(self, path: str) -> str | None: ...
    async def system_update(self, manifest: str) -> int: ...
    async def system_reboot_update(self) -> None: ...


class _BundleLike(Protocol):
    manifest_name: str
    target: str
    files: list[tuple[str, bytes]]


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
    device_target = f"f{device_info.get('hardware_target', '').strip()}"
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
        device_md5 = await rpc.storage_md5sum(dest)
        expected_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if device_md5 != expected_md5:
            raise FlashError(f"md5 mismatch after writing {dest}")

    manifest = f"{pkg_dir}/{bundle.manifest_name}"
    code = await rpc.system_update(manifest)
    message = update_code_message(code)
    if message is not None:
        raise FlashError(f"device rejected update: {message}")

    await rpc.system_reboot_update()
