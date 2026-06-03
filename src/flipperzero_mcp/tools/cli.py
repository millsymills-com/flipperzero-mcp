"""Generic Flipper CLI command execution tool (USB only)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from flipperzero_mcp.errors import handle_client_error
from flipperzero_mcp.rpc.client import CliExecResult
from flipperzero_mcp.tools._common import ensure_connected, get_server_context


def register_cli_tools(mcp: FastMCP) -> None:
    """Register the CLI exec tool."""

    @mcp.tool(tags={"flipper", "cli"})
    async def flipperzero_cli_exec(
        ctx: Context,
        command: str,
        timeout_s: float = 10.0,
        i_accept_responsibility: bool = False,
    ) -> CliExecResult:
        """Run one Flipper CLI command over USB and return its output.

        Args:
            ctx: FastMCP request context carrying the shared Flipper client.
            command: Raw CLI command line, e.g. "storage list /ext".
            timeout_s: Seconds to wait for the ``>:`` prompt (default 10).
            i_accept_responsibility: Per-call intent for gated commands.

        Returns:
            CliExecResult with output (str), completed (bool), risk (str),
            warning (str | None).

        Raises:
            ToolError: if not connected, the transport has no CLI text mode, the
                command chains shells, or a gated command is missing a gate.

        USB only: this fails over the WiFi bridge transport. Send exactly one
        command per call; shell chaining (``;``, ``&&``, ``||``, ``|``, backticks,
        newlines) is rejected. Streaming/interactive commands (``subghz rx``,
        ``ir rx``, ``log``, ``input dump``) never return to the prompt and time
        out with ``completed=false`` and partial output.

        Transmit/destructive commands (``subghz tx``, ``ir tx``, ``rfid write``,
        ``ikey write``, ``factory reset``, ``storage format``, ``power off``,
        ``power reboot``, ``update install``) require BOTH the operator env flag
        ``FLIPPER_ENABLE_TX_TOOLS=true`` and ``i_accept_responsibility=true``;
        either missing and the command is refused.
        """
        try:
            config = get_server_context(ctx).config
            client = await ensure_connected(ctx)
            return await client.cli_exec(
                command,
                timeout_s=timeout_s,
                accept_responsibility=i_accept_responsibility,
                tx_tools_enabled=config.enable_tx_tools,
            )
        except Exception as e:
            handle_client_error(e)
