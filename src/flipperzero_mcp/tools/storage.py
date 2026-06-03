"""Native storage RPC tools for the Flipper Zero.

Provides storage info/stat/list, mkdir/delete/rename, and push/pull tools.
Push/pull verify integrity by comparing the local MD5 to the
device's `storage_md5sum`, failing loud on mismatch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.tools._common import get_rpc, require_write_tools


def _md5_hex(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _verify_md5(local_md5: str, device_md5: str | None, path: str) -> None:
    """Raise a ToolError unless the device MD5 matches the local MD5.

    Args:
        local_md5: Hex digest computed on the host side.
        device_md5: Hex digest reported by the device, or None if unavailable.
        path: Device path, included in the error message.

    Raises:
        ToolError: If the device did not report a digest, or it mismatches.
    """
    if device_md5 is None:
        raise ToolError(f"integrity check failed for {path}: device did not return an MD5 digest")
    if device_md5.lower() != local_md5.lower():
        raise ToolError(
            f"integrity mismatch for {path}: local MD5 {local_md5} != device MD5 {device_md5}"
        )


def register_storage_tools(mcp: FastMCP) -> None:
    """Register the native storage RPC tools."""

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_fs_info(ctx: Context, path: str = "/ext") -> dict[str, Any]:
        """Return storage capacity information for a device path.

        Args:
            path: Absolute device storage path, usually ``/ext`` for the SD card.

        Returns:
            Dict with ``path``, ``total_space``, and ``free_space`` byte counts.

        Raises:
            ToolError: If the device is unreachable or no storage info is returned.
        """
        try:
            rpc = await get_rpc(ctx)
            info = await rpc.storage_info(path)
        except Exception as e:
            _classify_client_error(e)
        if info is None:
            raise ToolError(f"storage info unavailable for {path}")
        total_space, free_space = info
        return {"path": path, "total_space": total_space, "free_space": free_space}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_fs_stat(ctx: Context, path: str) -> dict[str, Any]:
        """Return metadata for a file or directory on the Flipper.

        Args:
            path: Absolute device path to inspect.

        Returns:
            Dict with ``path`` and ``entry`` metadata (name, type, size, optional md5sum).

        Raises:
            ToolError: If the device is unreachable or the path cannot be statted.
        """
        try:
            rpc = await get_rpc(ctx)
            entry = await rpc.storage_stat(path)
        except Exception as e:
            _classify_client_error(e)
        if entry is None:
            raise ToolError(f"stat unavailable for {path}")
        return {"path": path, "entry": entry}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_fs_timestamp(ctx: Context, path: str) -> dict[str, Any]:
        """Return the device timestamp for a file or directory.

        Args:
            path: Absolute device path to inspect.

        Returns:
            Dict with ``path`` and integer ``timestamp`` as reported by firmware.

        Raises:
            ToolError: If the device is unreachable or no timestamp is returned.
        """
        try:
            rpc = await get_rpc(ctx)
            timestamp = await rpc.storage_timestamp(path)
        except Exception as e:
            _classify_client_error(e)
        if timestamp is None:
            raise ToolError(f"timestamp unavailable for {path}")
        return {"path": path, "timestamp": timestamp}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def flipperzero_fs_list(ctx: Context, path: str) -> dict[str, Any]:
        """List a directory on the Flipper's storage.

        Args:
            path: Absolute device directory path (e.g. ``/ext`` or ``/ext/apps``).

        Returns:
            Dict with ``path`` and ``entries``; each entry has ``name``, ``type``
            (``FILE`` or ``DIR``), ``size``, and optionally ``md5sum``.

        Raises:
            ToolError: If the device is unreachable or the RPC fails.
        """
        try:
            rpc = await get_rpc(ctx)
            entries = await rpc.storage_list_detailed(path)
        except Exception as e:
            _classify_client_error(e)
        return {"path": path, "entries": entries}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
        ),
    )
    async def flipperzero_fs_mkdir(ctx: Context, path: str) -> dict[str, Any]:
        """Create a directory on the Flipper's storage.

        Args:
            path: Absolute device directory path to create (e.g. ``/ext/apps_data``).

        Returns:
            Dict with ``path`` and ``created`` (True on success).

        Raises:
            ToolError: If write tools are disabled, the device is unreachable, or
                the directory cannot be created.
        """
        require_write_tools(ctx)
        try:
            rpc = await get_rpc(ctx)
            created = await rpc.storage_mkdir(path)
        except Exception as e:
            _classify_client_error(e)
        if not created:
            raise ToolError(f"failed to create directory {path} on the device")
        return {"path": path, "created": True}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
        ),
    )
    async def flipperzero_fs_delete(
        ctx: Context, path: str, recursive: bool = False
    ) -> dict[str, Any]:
        """Delete a file or directory on the Flipper's storage.

        Args:
            path: Absolute device path to delete.
            recursive: If true, allow recursive directory deletion.

        Returns:
            Dict with ``path``, ``recursive``, and ``deleted`` (True on success).

        Raises:
            ToolError: If write tools are disabled, the device is unreachable, or
                the delete fails.
        """
        require_write_tools(ctx)
        try:
            rpc = await get_rpc(ctx)
            deleted = await rpc.storage_delete(path, recursive=recursive)
        except Exception as e:
            _classify_client_error(e)
        if not deleted:
            raise ToolError(f"failed to delete {path} on the device")
        return {"path": path, "recursive": recursive, "deleted": True}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
        ),
    )
    async def flipperzero_fs_rename(ctx: Context, old_path: str, new_path: str) -> dict[str, Any]:
        """Rename or move a file/directory on the Flipper's storage.

        Args:
            old_path: Existing absolute device path.
            new_path: New absolute device path.

        Returns:
            Dict with ``old_path``, ``new_path``, and ``renamed`` (True on success).

        Raises:
            ToolError: If write tools are disabled, the device is unreachable, or
                the rename fails.
        """
        require_write_tools(ctx)
        try:
            rpc = await get_rpc(ctx)
            renamed = await rpc.storage_rename(old_path, new_path)
        except Exception as e:
            _classify_client_error(e)
        if not renamed:
            raise ToolError(f"failed to rename {old_path} to {new_path} on the device")
        return {"old_path": old_path, "new_path": new_path, "renamed": True}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
        ),
    )
    async def flipperzero_fs_push(ctx: Context, local_path: str, dest_path: str) -> dict[str, Any]:
        """Push a local file to the Flipper and verify its integrity.

        Reads ``local_path`` from the host, writes it to ``dest_path`` on the
        device, then compares the local MD5 to the device's reported MD5.

        Args:
            local_path: Host filesystem path of the file to upload.
            dest_path: Absolute destination path on the device (e.g. ``/ext/foo.bin``).

        Returns:
            Dict with ``dest_path``, ``bytes`` (size written), ``md5``, and
            ``verified`` (True).

        Raises:
            ToolError: If write tools are disabled, the local file is missing, the
                write fails, or the device MD5 does not match the local MD5.
        """
        require_write_tools(ctx)
        source = Path(local_path)
        try:
            data = source.read_bytes()
        except OSError as e:
            raise ToolError(f"cannot read local file {local_path}: {e}") from e
        try:
            rpc = await get_rpc(ctx)
            wrote = await rpc.storage_write(dest_path, data)
            if not wrote:
                raise ToolError(f"failed to write {dest_path} to the device")
            device_md5 = await rpc.storage_md5sum(dest_path)
        except ToolError:
            raise
        except Exception as e:
            _classify_client_error(e)
        local_md5 = _md5_hex(data)
        _verify_md5(local_md5, device_md5, dest_path)
        return {"dest_path": dest_path, "bytes": len(data), "md5": local_md5, "verified": True}

    @mcp.tool(
        tags={"flipper", "storage"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
        ),
    )
    async def flipperzero_fs_pull(ctx: Context, src_path: str, local_path: str) -> dict[str, Any]:
        """Pull a file from the Flipper to the host and verify its integrity.

        Reads ``src_path`` from the device, writes it to ``local_path`` on the
        host, then compares the written file's MD5 to the device's reported MD5.

        Args:
            src_path: Absolute source path on the device (e.g. ``/ext/foo.bin``).
            local_path: Host filesystem path to write the downloaded file to.

        Returns:
            Dict with ``local_path``, ``bytes`` (size written), ``md5``, and
            ``verified`` (True).

        Raises:
            ToolError: If the device read fails, the local write fails, or the
                written file's MD5 does not match the device MD5.
        """
        try:
            rpc = await get_rpc(ctx)
            data = await rpc.storage_read(src_path)
            device_md5 = await rpc.storage_md5sum(src_path)
        except Exception as e:
            _classify_client_error(e)
        destination = Path(local_path)
        try:
            destination.write_bytes(data)
            written = destination.read_bytes()
        except OSError as e:
            raise ToolError(f"cannot write local file {local_path}: {e}") from e
        local_md5 = _md5_hex(written)
        _verify_md5(local_md5, device_md5, src_path)
        return {"local_path": local_path, "bytes": len(written), "md5": local_md5, "verified": True}
