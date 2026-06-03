"""Application lifecycle tools for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.tools._common import get_rpc, require_write_tools


def register_app_tools(mcp: FastMCP) -> None:
    """Register application lifecycle tools."""

    @mcp.tool(
        tags={"flipper", "apps"},
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
        ),
    )
    async def flipperzero_app_start(ctx: Context, name: str, args: str = "") -> dict[str, Any]:
        """Start a Flipper application by name via protobuf RPC.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.
            name: Application name/path understood by firmware, e.g. ``Infrared``.
            args: Optional argument string passed to the app.

        Returns:
            Dict with ``name``, ``args``, and ``started`` (True on success).

        Raises:
            ToolError: If write tools are disabled, the device is unreachable, or
                firmware refuses to start the app.

        Starting apps changes device UI state and some apps can disrupt USB mode,
        so this tool is gated behind ``FLIPPER_ENABLE_WRITE_TOOLS=true``.
        """
        require_write_tools(ctx)
        try:
            rpc = await get_rpc(ctx)
            started = await rpc.app_start(name, args=args)
        except Exception as e:
            _classify_client_error(e)
        if not started:
            raise ToolError(f"failed to start app {name!r}")
        return {"name": name, "args": args, "started": True}
