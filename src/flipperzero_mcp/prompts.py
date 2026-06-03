"""MCP prompts that orient an agent toward Flipper management workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register Flipper workflow prompts."""

    @mcp.prompt
    def manage_flipper() -> str:
        """Orient the agent to manage a connected Flipper Zero."""
        return (
            "You are managing a Flipper Zero via this MCP server.\n\n"
            "1. Check the link with `flipperzero_system_info` or "
            "`flipperzero_connection_health`.\n"
            "2. Read `flipper://reference/cli` for the command surface, "
            "`flipper://reference/connection` for transport details, and "
            "`flipper://reference/filesystem` for SD-card layout.\n"
            "3. Prefer typed storage tools (`flipperzero_fs_list`, `flipperzero_fs_push`, "
            "`flipperzero_fs_pull`) over CLI storage commands.\n"
            "4. Run CLI commands with `flipperzero_cli_exec` (USB only; one command per call).\n"
            "5. Transmit/destructive commands need `FLIPPER_ENABLE_TX_TOOLS=true` "
            "on the server AND `i_accept_responsibility=true` on the call.\n"
            "6. For multi-step jobs, consult the relevant `flipper://workflow/*` resource."
        )

    @mcp.prompt
    def troubleshoot_connection() -> str:
        """Guide the agent through diagnosing a Flipper connection."""
        return (
            "Diagnose the Flipper connection:\n"
            "1. Call `flipperzero_connection_health` with `probe_rpc=true`.\n"
            "2. If transport_connected is false, check USB cable / `FLIPPER_USB_PORT`, "
            "or set `FLIPPER_WIFI_HOST` for the WiFi bridge.\n"
            "3. If transport is connected but rpc_responsive is false, call "
            "`flipperzero_connection_reconnect`.\n"
            "4. See `flipper://reference/connection` for transport and mode details.\n"
            "5. Remember: `flipperzero_cli_exec` is USB-only."
        )
