"""Assert ``docs/tool-schema-matrix.md`` matches the live MCP tool schemas.

The matrix is the checked-in source of truth for every registered tool's input
schema and behavioral annotations. This test parses the two markdown tables and
compares them, field by field, against what ``create_server`` actually exposes,
so a tool added, removed, retyped, re-defaulted, or re-annotated without updating
the doc fails here. Regenerate with ``tests/tools/gen_schema_matrix.py``.

The parser here is deliberately independent of the generator: the doc is the only
shared artifact, so a bug in one code path cannot mask drift in the other.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server

_DOC = Path(__file__).resolve().parents[2] / "docs" / "tool-schema-matrix.md"

_BOOL_CELL = {"true": True, "false": False, "—": None}

DocView = tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]


def _table_rows(markdown: str, header: list[str]) -> list[list[str]]:
    """Return body rows of the markdown table whose header row equals ``header``."""
    rows: list[list[str]] = []
    capturing = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            capturing = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells == header:
            capturing = True
            continue
        if not capturing or set(cells[0]) <= {"-"}:
            continue
        rows.append(cells)
    return rows


def _unbacktick(cell: str) -> str:
    return cell.strip("`")


def _doc_annotations(markdown: str) -> dict[str, dict[str, Any]]:
    header = ["Tool", "Group", "readOnly", "destructive", "idempotent", "openWorld", "Gate"]
    result: dict[str, dict[str, Any]] = {}
    for tool, group, read_only, destructive, idempotent, open_world, _gate in _table_rows(
        markdown, header
    ):
        result[_unbacktick(tool)] = {
            "group": group,
            "readOnlyHint": _BOOL_CELL[read_only],
            "destructiveHint": _BOOL_CELL[destructive],
            "idempotentHint": _BOOL_CELL[idempotent],
            "openWorldHint": _BOOL_CELL[open_world],
        }
    return result


def _doc_parameters(markdown: str) -> dict[str, list[dict[str, Any]]]:
    header = ["Tool", "Parameter", "Type", "Required", "Default"]
    result: dict[str, list[dict[str, Any]]] = {}
    for tool, name, type_, required, default in _table_rows(markdown, header):
        params = result.setdefault(_unbacktick(tool), [])
        if name == "—":  # a parameterless tool; keep the empty list
            continue
        params.append(
            {
                "name": _unbacktick(name),
                "type": type_,
                "required": required == "required",
                "default": _unbacktick(default),
            }
        )
    return result


def _live_type(prop: dict[str, Any]) -> str:
    if "type" in prop:
        return str(prop["type"])
    if "anyOf" in prop:
        return "|".join(str(opt.get("type", "?")) for opt in prop["anyOf"])
    return "?"


def _live_default(prop: dict[str, Any], required: bool) -> str:
    if required:
        return "—"
    default = prop.get("default")
    if default == "":
        return '""'
    if isinstance(default, bool):
        return str(default).lower()
    return str(default)


def _live_view(tools: list[Any]) -> DocView:
    annotations: dict[str, dict[str, Any]] = {}
    parameters: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        ann = tool.annotations
        annotations[tool.name] = {
            "group": next(tag for tag in sorted(tool.tags) if tag != "flipper"),
            "readOnlyHint": ann.readOnlyHint,
            "destructiveHint": ann.destructiveHint,
            "idempotentHint": ann.idempotentHint,
            "openWorldHint": ann.openWorldHint,
        }
        props = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        parameters[tool.name] = [
            {
                "name": name,
                "type": _live_type(prop),
                "required": name in required,
                "default": _live_default(prop, name in required),
            }
            for name, prop in props.items()
        ]
    return annotations, parameters


@pytest.fixture(scope="module")
def live() -> DocView:
    server = create_server(FlipperConfig(_env_file=None))  # ty: ignore[unknown-argument]
    return _live_view(list(asyncio.run(server.list_tools())))


@pytest.fixture(scope="module")
def markdown() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_tool_set_matches(markdown: str, live: DocView) -> None:
    live_annotations, _ = live
    assert set(_doc_annotations(markdown)) == set(live_annotations), (
        "tool set drift between docs/tool-schema-matrix.md and the live server; "
        "regenerate with tests/tools/gen_schema_matrix.py"
    )


def test_annotations_match(markdown: str, live: DocView) -> None:
    doc = _doc_annotations(markdown)
    live_annotations, _ = live
    for name, live_ann in live_annotations.items():
        assert doc[name] == live_ann, f"annotation drift for {name}"


def test_parameters_match(markdown: str, live: DocView) -> None:
    doc = _doc_parameters(markdown)
    _, live_parameters = live
    for name, live_params in live_parameters.items():
        assert doc.get(name, []) == live_params, f"parameter drift for {name}"
