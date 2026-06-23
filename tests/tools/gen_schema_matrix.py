"""Regenerate ``docs/tool-schema-matrix.md`` from the live FastMCP server.

Run after intentionally changing a tool, then review the diff:

    uv run python tests/tools/gen_schema_matrix.py
    uv run pytest tests/unit/test_schema_matrix_drift.py

The drift test parses the generated tables independently and asserts them against
the live server, so a stale matrix fails CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server

# Env/argument interlock enforced at call time. Informational only: the drift test
# asserts the four hint columns, not this. Keep in sync with the require_* guards
# in src/flipperzero_mcp/tools/.
GATE: dict[str, str] = {
    "flipperzero_app_get_error": "none",
    "flipperzero_app_lock_status": "none",
    "flipperzero_app_start": "WRITE",
    "flipperzero_cli_exec": "TX + i_accept_responsibility",
    "flipperzero_connection_health": "none",
    "flipperzero_connection_reconnect": "none",
    "flipperzero_core_status": "none",
    "flipperzero_desktop_is_locked": "none",
    "flipperzero_fs_tree": "none",
    "flipperzero_i2c_scan": "none",
    "flipperzero_loader_list": "none",
    "flipperzero_firmware_install": "WRITE + FIRMWARE_FLASH",
    "flipperzero_fs_delete": "WRITE",
    "flipperzero_fs_info": "none",
    "flipperzero_fs_list": "none",
    "flipperzero_fs_mkdir": "WRITE",
    "flipperzero_fs_pull": "none",
    "flipperzero_fs_push": "WRITE",
    "flipperzero_fs_rename": "WRITE",
    "flipperzero_fs_stat": "none",
    "flipperzero_fs_timestamp": "none",
    "flipperzero_gpio_read": "none",
    "flipperzero_system_datetime": "none",
    "flipperzero_system_info": "none",
    "flipperzero_system_ping": "none",
    "flipperzero_system_power_info": "none",
    "flipperzero_system_property_get": "none",
    "flipperzero_system_protobuf_version": "none",
}

_DOC = Path(__file__).resolve().parents[2] / "docs" / "tool-schema-matrix.md"

_HEADER = """# Tool ↔ schema coverage matrix

Canonical, checked-in inventory of every MCP tool this server registers and the
exact input schema + behavioral annotations each exposes.
`tests/unit/test_schema_matrix_drift.py` parses the two tables below and asserts
them against the live `FastMCP` server, so any added/removed tool, renamed or
retyped parameter, changed default, or flipped annotation hint fails CI until this
file is regenerated in the same change.

Do not hand-edit. Regenerate after intentional tool changes, then review the diff:

```bash
uv run python tests/tools/gen_schema_matrix.py
uv run pytest tests/unit/test_schema_matrix_drift.py
```
"""


def _type_str(prop: dict[str, Any]) -> str:
    if "type" in prop:
        return str(prop["type"])
    if "anyOf" in prop:
        return "|".join(str(opt.get("type", "?")) for opt in prop["anyOf"])
    return "?"


def _group(tags: set[str]) -> str:
    group = next((tag for tag in sorted(tags) if tag != "flipper"), None)
    if group is None:
        raise ValueError("tool has no group tag besides 'flipper'")
    return group


def _bool_cell(value: bool | None) -> str:
    if value is None:
        return "—"
    return "true" if value else "false"


def _default_cell(prop: dict[str, Any], required: bool) -> str:
    if required:
        return "—"
    default = prop.get("default")
    if default == "":
        return '`""`'
    if isinstance(default, bool):
        return f"`{str(default).lower()}`"
    return f"`{default}`"


def _annotation_rows(tools: list[Any]) -> list[str]:
    rows = [
        "| Tool | Group | readOnly | destructive | idempotent | openWorld | Gate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tool in tools:
        ann = tool.annotations
        rows.append(
            f"| `{tool.name}` | {_group(tool.tags)} "
            f"| {_bool_cell(ann.readOnlyHint)} | {_bool_cell(ann.destructiveHint)} "
            f"| {_bool_cell(ann.idempotentHint)} | {_bool_cell(ann.openWorldHint)} "
            f"| {GATE[tool.name]} |"
        )
    return rows


def _parameter_rows(tools: list[Any]) -> list[str]:
    rows = [
        "| Tool | Parameter | Type | Required | Default |",
        "| --- | --- | --- | --- | --- |",
    ]
    for tool in tools:
        props = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        if not props:
            rows.append(f"| `{tool.name}` | — | — | — | — |")
            continue
        for name, prop in props.items():
            is_required = name in required
            rows.append(
                f"| `{tool.name}` | `{name}` | {_type_str(prop)} "
                f"| {'required' if is_required else 'optional'} "
                f"| {_default_cell(prop, is_required)} |"
            )
    return rows


def _render(tools: list[Any]) -> str:
    groups = sorted({_group(t.tags) for t in tools})
    sections = [
        _HEADER,
        f"**{len(tools)} tools** across {len(groups)} groups: {', '.join(groups)}.",
        "## Annotations",
        "`Gate` is the env/argument interlock enforced at call time (informational; the\n"
        "drift test asserts the four hint columns, not `Gate`). `WRITE` =\n"
        "`FLIPPER_ENABLE_WRITE_TOOLS`, `FIRMWARE_FLASH` = `FLIPPER_ENABLE_FIRMWARE_FLASH`,\n"
        "`TX` = `FLIPPER_ENABLE_TX_TOOLS`.",
        "\n".join(_annotation_rows(tools)),
        "## Parameters",
        "One row per parameter (`ctx` is injected by FastMCP and omitted). Tools with no\n"
        "caller-supplied parameters show a single `—` row. `Default` is `—` for required\n"
        "parameters.",
        "\n".join(_parameter_rows(tools)),
    ]
    return "\n\n".join(sections) + "\n"


async def _build() -> str:
    server = create_server(FlipperConfig(_env_file=None))  # ty: ignore[unknown-argument]
    tools = sorted(await server.list_tools(), key=lambda t: t.name)
    return _render(tools)


def main() -> None:
    _DOC.write_text(asyncio.run(_build()), encoding="utf-8")


if __name__ == "__main__":
    main()
