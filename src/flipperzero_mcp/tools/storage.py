"""Native storage RPC tools for the Flipper Zero.

Provides `flipperzero_fs_list`, `flipperzero_fs_mkdir`, `flipperzero_fs_push`, and
`flipperzero_fs_pull`. Push/pull verify integrity by comparing the local MD5 to the
device's `storage_md5sum`, failing loud on mismatch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import handle_client_error
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

    @mcp.tool(tags={"flipper", "storage"})
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
            handle_client_error(e)
        return {"path": path, "entries": entries}

    @mcp.tool(tags={"flipper", "storage"})
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
            handle_client_error(e)
        if not created:
            raise ToolError(f"failed to create directory {path} on the device")
        return {"path": path, "created": True}

    @mcp.tool(tags={"flipper", "storage"})
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
            handle_client_error(e)
        local_md5 = _md5_hex(data)
        _verify_md5(local_md5, device_md5, dest_path)
        return {"dest_path": dest_path, "bytes": len(data), "md5": local_md5, "verified": True}

    @mcp.tool(tags={"flipper", "storage"})
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
            handle_client_error(e)
        destination = Path(local_path)
        try:
            destination.write_bytes(data)
            written = destination.read_bytes()
        except OSError as e:
            raise ToolError(f"cannot write local file {local_path}: {e}") from e
        local_md5 = _md5_hex(written)
        _verify_md5(local_md5, device_md5, src_path)
        return {"local_path": local_path, "bytes": len(written), "md5": local_md5, "verified": True}
