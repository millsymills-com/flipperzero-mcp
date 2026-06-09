"""MCP prompts that orient an agent toward Flipper management workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register Flipper workflow prompts.

    Args:
        mcp: The FastMCP server to attach the workflow prompts to.

    Returns:
        None. Prompts are registered as a side effect.
    """

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

    @mcp.prompt
    def flipper_doctor() -> str:
        """Run a full diagnostic sweep over the connected Flipper (the /flipper-doctor command)."""
        return (
            "Diagnose the Flipper end to end and report a verdict for each check:\n"
            "1. Transport + RPC: `flipperzero_connection_health` with `probe_rpc=true`. "
            "On failure, follow the `troubleshoot_connection` prompt.\n"
            "2. Device + firmware: `flipperzero_system_info` — record name, hardware, "
            "firmware channel/version, and `sd_card_available`.\n"
            "3. Protobuf compatibility: `flipperzero_system_protobuf_version`.\n"
            '4. CLI shell (USB only): `flipperzero_cli_exec "help"` to confirm the text '
            "console responds; expect it to fail over WiFi (see `flipper://reference/cli`).\n"
            "5. TX/destructive gate: report whether `FLIPPER_ENABLE_TX_TOOLS` is enabled; "
            "do not run gated commands here.\n"
            "Summarize as pass/warn/fail per check with the next action for any non-pass."
        )

    @mcp.prompt
    def flipper_install(github_url: str) -> str:
        """Build and install a Flipper app from a GitHub repo (the /flipper-install command)."""
        return (
            f"Install the Flipper app at {github_url}. Follow "
            "`flipper://workflow/install-app` and fail loud rather than ship an "
            "incompatible `.fap`:\n"
            "1. Preflight: `flipperzero_system_info` — confirm USB link, read the firmware "
            "channel/version, and check `sd_card_available`. Confirm "
            "`FLIPPER_ENABLE_WRITE_TOOLS=true` (steps 5-6 are gated on it); STOP before "
            "cloning or building if it is off rather than fail at the push.\n"
            f"2. Clone {github_url} on the host and locate the ufbt app "
            "(`application.fam`).\n"
            "3. Pick the ufbt SDK matching the device firmware channel/version. "
            "If the repo targets a different channel or custom firmware, STOP and report — "
            "do not push a mismatched build.\n"
            "4. Build the `.fap` with ufbt against that SDK; abort on any build error.\n"
            "5. `flipperzero_fs_mkdir` for `/ext/apps/<Category>` if absent, then "
            "`flipperzero_fs_push` the `.fap` (it verifies the device MD5 and raises on "
            "mismatch).\n"
            "6. Confirm placement with `flipperzero_fs_list` for that directory.\n"
            '7. Launch: `flipperzero_cli_exec "loader open <AppName>"`; stop with '
            "`loader close`.\n"
            "8. Report channel/version, built `.fap`, push verification, and launch result."
        )
