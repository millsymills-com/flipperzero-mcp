# flipperzero-mcp Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a house-style FastMCP Flipper Zero server (stdio) whose `connection` and `systeminfo` tools work end-to-end against real hardware over USB and WiFi, harvesting the proven transport + protobuf-RPC layer from the upstream repo.

**Architecture:** A fresh `src/flipperzero_mcp` package on FastMCP 3.x. A `transport/` layer (harvested USB/WiFi/auto) feeds a `rpc/` layer (harvested `ProtobufRPC` + a slim `FlipperClient` wrapper). The FastMCP **lifespan** owns one `FlipperClient`; tools reach it via `ctx.lifespan_context` and a shared `ensure_connected()` guard that replaces upstream's central reconnect wrapper. Config is `pydantic-settings`; errors are a `FlipperError` hierarchy mapped to `ToolError`; logging is stderr-bound JSON.

**Tech Stack:** Python 3.13, `uv`, `fastmcp>=3.2.4,<4`, `pyserial`, `protobuf==6.33.2`, `pydantic-settings`, `ruff`, `ty`, `bandit`, `pytest`/`pytest-asyncio`/`hypothesis`, ESP-IDF (firmware, not in CI).

**Harvest source:** `../flipperzero-mcp-upstream/` (paths below are relative to it unless noted). **House-style reference:** `../gandi-mcp/`.

**Spec:** `docs/superpowers/specs/2026-05-29-flipperzero-mcp-design.md`.

**Conventions for every task:** work on `main` only for Task 0 (repo init); from Task 1 on, the repo follows `no-commit-to-branch: main`, so create a branch `phase1` first and commit there. Run `uv run ruff check . && uv run ruff format --check . && uv run ty check src/flipperzero_mcp/` before each commit; fix all findings (zero-warning policy).

---

### Task 0: Repo skeleton + pyproject

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `NOTICE`, `.env.example`, `src/flipperzero_mcp/__init__.py`, `src/flipperzero_mcp/py.typed`
- Reference: `../gandi-mcp/pyproject.toml`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "flipperzero-mcp"
version = "0.1.0"
description = "MCP server for the Flipper Zero (USB + WiFi protobuf RPC)"
readme = "README.md"
license = "MIT"
requires-python = ">=3.13"
authors = [{ name = "millsmillsymills" }]
keywords = ["flipper", "flipper-zero", "mcp", "model-context-protocol", "hardware", "fastmcp", "claude"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Typing :: Typed",
]
dependencies = [
    "fastmcp>=3.2.4,<4.0.0",
    "pyserial>=3.5",
    "protobuf==6.33.2",
    "pydantic>=2.13.3",
    "pydantic-settings>=2.14.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=1.3.0",
    "pytest-cov>=7.1.0",
    "hypothesis>=6.152.4",
    "ruff>=0.15.12",
    "ty>=0.0.34",
    "bandit[toml]>=1.9.4",
    "pip-audit>=2.7.3",
    "pre-commit>=4.6.0",
    "grpcio-tools>=1.68.0",
]

[project.scripts]
flipperzero-mcp = "flipperzero_mcp.__main__:main"

[tool.ruff]
target-version = "py313"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E","W","F","I","N","UP","B","S","A","C4","DTZ","T20","SIM","TCH","RUF","PT","ARG","PTH","ERA","PL","PERF","FURB","LOG","TID"]
ignore = ["S101","PLR0913","PLR0915","PLR2004","PLC0415"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101","ARG001","PLR2004","S106"]
"src/flipperzero_mcp/tools/**/*.py" = ["TC001","TC002"]
"src/flipperzero_mcp/rpc/protobuf_gen/**/*.py" = ["ALL"]

[tool.ruff.lint.isort]
known-first-party = ["flipperzero_mcp"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ty.environment]
python-version = "3.13"

[tool.ty.src]
respect-ignore-files = true

[tool.ty.rules]
unresolved-attribute = "error"
invalid-argument-type = "error"
invalid-return-type = "error"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: requires a real Flipper (USB or WiFi). LOCAL ONLY.",
    "usb: integration test that needs a USB-connected Flipper.",
    "wifi: integration test that needs a WiFi dev board (FLIPPER_WIFI_HOST set).",
]
addopts = ["-ra","--strict-markers","--strict-config"]
filterwarnings = ["error"]

[tool.coverage.run]
source = ["flipperzero_mcp"]
branch = true
omit = ["tests/*","src/flipperzero_mcp/__main__.py","src/flipperzero_mcp/rpc/protobuf_gen/*"]

[tool.coverage.report]
show_missing = true
skip_covered = true
exclude_lines = ["pragma: no cover","if TYPE_CHECKING:","if __name__ == .__main__.","@overload","raise NotImplementedError","\\.\\.\\."]

[tool.bandit]
exclude_dirs = ["tests"]
skips = ["B101"]

[tool.hatch.build.targets.wheel]
packages = ["src/flipperzero_mcp"]
```

- [ ] **Step 2: Create `src/flipperzero_mcp/__init__.py`**

```python
"""MCP server for the Flipper Zero."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create `src/flipperzero_mcp/py.typed`** (empty file marking the package as typed)

```
```

- [ ] **Step 4: Create `LICENSE`** — MIT, copyright `2026 millsmillsymills`. **Step 5: Create `NOTICE`**

```
flipperzero-mcp
Copyright (c) 2026 millsmillsymills

This product includes software harvested from the flipperzero-mcp project
by Chris Busse (https://github.com/busse/flipperzero-mcp), used under the MIT
License:

    MIT License
    Copyright (c) 2024 Flipper MCP Contributors

The harvested portions are the transport layer (src/flipperzero_mcp/transport/),
the protobuf RPC implementation (src/flipperzero_mcp/rpc/protobuf_rpc.py and
proto/), and the ESP32 WiFi-bridge firmware (firmware/tcp_uart_bridge/).
```

- [ ] **Step 6: Create `.gitignore`** (Python + venv + caches)

```
__pycache__/
*.py[cod]
build/
dist/
*.egg-info/
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
.ruff_cache/
.ty_cache/
.DS_Store
.env
firmware/tcp_uart_bridge/sdkconfig
*.log
```

- [ ] **Step 7: Create `.env.example`**

```
# Transport: auto (USB first, WiFi fallback if FLIPPER_WIFI_HOST set), usb, or wifi
FLIPPER_TRANSPORT=auto
# FLIPPER_USB_PORT=/dev/tty.usbmodemflip_1
# FLIPPER_WIFI_HOST=192.168.1.100
FLIPPER_WIFI_PORT=8080
FLIPPER_DEBUG=false
```

- [ ] **Step 8: Sync the environment**

Run: `uv sync --extra dev`
Expected: a `.venv/` and `uv.lock` are created; exits 0.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Scaffold package skeleton, pyproject, license/notice"
```

---

### Task 1: Branch, CI, pre-commit

**Files:**
- Create: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`
- Reference: `../gandi-mcp/.github/workflows/ci.yml`, `../gandi-mcp/.pre-commit-config.yaml`

- [ ] **Step 1: Create the working branch** (later tasks can't commit to `main`)

Run: `git checkout -b phase1`

- [ ] **Step 2: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
        args: ["--maxkb=500"]
      - id: check-merge-conflict
      - id: debug-statements
      - id: detect-private-key
      - id: no-commit-to-branch
        args: ["--branch", "main"]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format
  - repo: local
    hooks:
      - id: ty
        name: ty (type-check)
        language: system
        entry: uv run ty check src/flipperzero_mcp/
        pass_filenames: false
        types: [python]
  - repo: https://github.com/PyCQA/bandit
    rev: 1.9.4
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml", "-r", "src/flipperzero_mcp/"]
        additional_dependencies: ["bandit[toml]"]
        pass_filenames: false
```

- [ ] **Step 3: Create `.github/workflows/ci.yml`** (verify the action SHAs are current at execution time with `gh api`; the version comments are the source of truth)

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
        with:
          enable-cache: true
      - run: uv sync --extra dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run ty check src/flipperzero_mcp/
      - run: uv run bandit -r src/flipperzero_mcp/ -c pyproject.toml
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
        with:
          enable-cache: true
          python-version: "3.13"
      - run: uv sync --extra dev
      - run: uv run pytest -m "not integration" --cov=flipperzero_mcp --cov-report=term --cov-fail-under=80
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
      - run: uv sync --extra dev
      - run: uv run pip-audit
      - run: pipx run zizmor==1.24.1 .github/workflows/
```

- [ ] **Step 4: Install hooks and validate workflow**

Run: `uv run pre-commit install && actionlint .github/workflows/ci.yml`
Expected: hooks installed; actionlint reports no errors.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add CI workflow and pre-commit hooks"
```

---

### Task 2: Stderr JSON logging

**Files:**
- Create: `src/flipperzero_mcp/_logging.py`
- Reference: `../gandi-mcp/src/gandi_mcp/_logging.py`

- [ ] **Step 1: Copy `../gandi-mcp/src/gandi_mcp/_logging.py` to `src/flipperzero_mcp/_logging.py` verbatim** (it is package-agnostic — `JSONFormatter` + `configure_logging(level)` binding a stderr `StreamHandler` to the root logger).

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "from flipperzero_mcp._logging import configure_logging; configure_logging()"`
Expected: exits 0, no stdout output.

- [ ] **Step 3: Commit**

```bash
git add src/flipperzero_mcp/_logging.py
git commit -m "Add stderr-bound JSON logging"
```

---

### Task 3: Error hierarchy

**Files:**
- Create: `src/flipperzero_mcp/errors.py`
- Test: `tests/unit/test_errors.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_errors.py`

```python
import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.errors import (
    FlipperConnectionError,
    FlipperError,
    FlipperNotConnectedError,
    FlipperTimeoutError,
    handle_client_error,
)


def test_not_connected_is_flipper_error():
    assert issubclass(FlipperNotConnectedError, FlipperError)


def test_handle_client_error_maps_not_connected_to_toolerror():
    with pytest.raises(ToolError, match="not connected"):
        handle_client_error(FlipperNotConnectedError("device not connected"))


def test_handle_client_error_maps_timeout():
    with pytest.raises(ToolError, match="timed out"):
        handle_client_error(FlipperTimeoutError("rpc timed out"))


def test_handle_client_error_wraps_unknown():
    with pytest.raises(ToolError, match="unexpected"):
        handle_client_error(ValueError("boom"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: FAIL with `ModuleNotFoundError: flipperzero_mcp.errors`.

- [ ] **Step 3: Create `src/flipperzero_mcp/errors.py`**

```python
"""Exception hierarchy and error mapping for the Flipper MCP server."""

from __future__ import annotations

import logging
from typing import NoReturn

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


class FlipperError(Exception):
    """Base exception for all Flipper errors."""


class FlipperNotConnectedError(FlipperError):
    """No live connection to the Flipper device."""


class FlipperConnectionError(FlipperError):
    """Transport-level connection failure (USB/WiFi)."""


class FlipperTimeoutError(FlipperError):
    """An RPC call exceeded its timeout."""


class FlipperProtocolError(FlipperError):
    """A protobuf RPC response was malformed or unexpected."""


def handle_client_error(error: Exception) -> NoReturn:
    """Map a Flipper exception to a FastMCP ToolError with an agent-readable message.

    Raises:
        ToolError: Always.
    """
    if isinstance(error, FlipperNotConnectedError):
        raise ToolError(
            f"Flipper not connected: {error}. Call flipper_connection_reconnect, "
            "or check USB / FLIPPER_WIFI_HOST."
        ) from error
    if isinstance(error, FlipperTimeoutError):
        raise ToolError(f"Flipper RPC timed out: {error}. The device may be busy; retry.") from error
    if isinstance(error, FlipperConnectionError):
        raise ToolError(f"Flipper connection error: {error}.") from error
    if isinstance(error, FlipperProtocolError):
        raise ToolError(f"Flipper protocol error: {error}.") from error
    if isinstance(error, FlipperError):
        raise ToolError(f"Flipper error: {error}.") from error
    logger.exception("Unexpected error in tool")
    raise ToolError(f"Unexpected error: {error}.") from error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/flipperzero_mcp/errors.py tests/unit/test_errors.py
git commit -m "Add FlipperError hierarchy and ToolError mapping"
```

---

### Task 4: Configuration (pydantic-settings)

**Files:**
- Create: `src/flipperzero_mcp/config.py`
- Test: `tests/unit/test_config.py`
- Reference: `../gandi-mcp/src/gandi_mcp/config.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_config.py`

```python
from flipperzero_mcp.config import FlipperConfig


def test_defaults_to_auto_transport():
    cfg = FlipperConfig(_env_file=None)
    assert cfg.transport == "auto"
    assert cfg.wifi_port == 8080


def test_wifi_configured_only_when_host_set():
    assert FlipperConfig(_env_file=None).wifi_configured is False
    assert FlipperConfig(_env_file=None, wifi_host="192.168.1.5").wifi_configured is True


def test_as_transport_config_shape():
    cfg = FlipperConfig(_env_file=None, usb_port="/dev/ttyACM0", wifi_host="10.0.0.2")
    tc = cfg.as_transport_config()["transport"]
    assert tc["usb"]["port"] == "/dev/ttyACM0"
    assert tc["wifi"]["host"] == "10.0.0.2"
    assert tc["wifi"]["port"] == 8080


def test_usb_port_omitted_when_unset():
    tc = FlipperConfig(_env_file=None).as_transport_config()["transport"]
    assert "port" not in tc["usb"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: flipperzero_mcp.config`.

- [ ] **Step 3: Create `src/flipperzero_mcp/config.py`**

```python
"""Configuration for the Flipper MCP server using pydantic-settings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FlipperConfig(BaseSettings):
    """Configuration loaded from FLIPPER_* environment variables and .env."""

    model_config = SettingsConfigDict(
        env_prefix="flipper_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: Literal["auto", "usb", "wifi"] = "auto"
    usb_port: str | None = None
    usb_baudrate: int = Field(default=115200, gt=0)
    wifi_host: str | None = None
    wifi_port: int = Field(default=8080, gt=0)
    debug: bool = False

    @property
    def wifi_configured(self) -> bool:
        """WiFi is usable only when a host is explicitly set."""
        return bool(self.wifi_host and self.wifi_host.strip())

    def as_transport_config(self) -> dict[str, Any]:
        """Build the nested dict shape expected by transport.get_transport()."""
        usb: dict[str, Any] = {"baudrate": self.usb_baudrate}
        if self.usb_port:
            usb["port"] = self.usb_port
        wifi: dict[str, Any] = {"port": self.wifi_port}
        if self.wifi_host:
            wifi["host"] = self.wifi_host
        return {"transport": {"type": self.transport, "usb": usb, "wifi": wifi}}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/flipperzero_mcp/config.py tests/unit/test_config.py
git commit -m "Add FlipperConfig (pydantic-settings)"
```

---

### Task 5: Harvest protos + regenerate protobuf bindings

**Files:**
- Create: `proto/*.proto` (copied), `proto/PROTO_VERSION`, `scripts/gen_proto.sh`, `src/flipperzero_mcp/rpc/__init__.py`, `src/flipperzero_mcp/rpc/protobuf_gen/__init__.py` (+ generated `*_pb2.py`)
- Source: upstream `proto/`, `.tmp_proto/`

- [ ] **Step 1: Confirm the canonical proto source.** Diff the two upstream proto dirs:

Run (from `../flipperzero-mcp-upstream`): `for f in flipper property system; do diff -q proto/$f.proto .tmp_proto/$f.proto; done`
Decision: if files are identical, `proto/` is canonical. If they differ, regenerate `_pb2.py` from each set and pick the set whose generated `flipper_pb2.py` matches the committed one (`diff <(protoc ...) src/.../flipper_pb2.py`). Record the winner. `.tmp_proto/` is then discarded.

- [ ] **Step 2: Copy the canonical `.proto` files** into the new repo's `proto/`:

Run: `mkdir -p proto && cp ../flipperzero-mcp-upstream/proto/*.proto proto/`

- [ ] **Step 3: Record provenance** in `proto/PROTO_VERSION`

```
Source: https://github.com/flipperdevices/flipperzero-protobuf
Vendored via: github.com/busse/flipperzero-mcp (proto/ directory)
Commit/date: UNKNOWN-UPSTREAM — these .protos were copied from busse/flipperzero-mcp
             on 2026-05-29; upstream did not record the flipperzero-protobuf commit.
Regenerate with: scripts/gen_proto.sh  (protobuf runtime pinned to 6.33.2)
```

- [ ] **Step 4: Create `scripts/gen_proto.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
# Regenerate protobuf bindings. The protobuf runtime is pinned to 6.33.2 in
# pyproject; grpcio-tools provides a matching protoc. Keep them in lockstep —
# a newer protoc emits a runtime-version assertion that fails on import.
OUT="src/flipperzero_mcp/rpc/protobuf_gen"
mkdir -p "$OUT"
uv run python -m grpc_tools.protoc -Iproto --python_out="$OUT" proto/*.proto
touch "$OUT/__init__.py"
# Rewrite absolute imports the generated files use (`import flipper_pb2`) into
# package-relative imports so they resolve inside flipperzero_mcp.rpc.protobuf_gen.
uv run python - <<'PY'
import pathlib, re
out = pathlib.Path("src/flipperzero_mcp/rpc/protobuf_gen")
for f in out.glob("*_pb2.py"):
    text = f.read_text()
    text = re.sub(r'^import (\w+_pb2) as', r'from . import \1 as', text, flags=re.M)
    f.write_text(text)
PY
echo "Generated bindings in $OUT"
```

- [ ] **Step 5: Generate and verify import**

Run: `mkdir -p src/flipperzero_mcp/rpc && touch src/flipperzero_mcp/rpc/__init__.py && chmod +x scripts/gen_proto.sh && ./scripts/gen_proto.sh`
Then: `uv run python -c "from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, system_pb2, storage_pb2, application_pb2, property_pb2; print('ok')"`
Expected: prints `ok` with **no** `RuntimeVersionError` (this is the protobuf 6.33.2 pin paying off).

- [ ] **Step 6: Commit**

```bash
git add proto/ scripts/gen_proto.sh src/flipperzero_mcp/rpc/
git commit -m "Harvest protos and regenerate bindings (protobuf 6.33.2)"
```

---

### Task 6: Harvest transport layer

**Files:**
- Create: `src/flipperzero_mcp/transport/{__init__,base,usb,wifi,auto}.py`
- Test: `tests/unit/test_transport.py`
- Source: upstream `src/flipper_mcp/core/transport/`

- [ ] **Step 1: Copy four files** `base.py`, `usb.py`, `wifi.py`, `auto.py` from upstream `core/transport/` into `src/flipperzero_mcp/transport/`. **Do NOT copy `bluetooth.py`** (non-functional stub; its bare `print()` calls would corrupt the stdio JSON-RPC stream).

- [ ] **Step 2: Edit `usb.py` — add an `asyncio.Lock` and remove the shared-`timeout` mutation race.** In `__init__`, after `self.serial = None`, add `self._lock = asyncio.Lock()`. Replace the body of `receive()` with:

```python
    async def receive(self, timeout: Optional[float] = None) -> bytes:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("USB not connected")
        loop = asyncio.get_event_loop()
        async with self._lock:
            return await loop.run_in_executor(None, self._blocking_read, timeout)

    def _blocking_read(self, timeout: Optional[float]) -> bytes:
        assert self.serial is not None
        old_timeout = self.serial.timeout
        if timeout is not None:
            self.serial.timeout = timeout
        try:
            return self.serial.read(4096)
        finally:
            self.serial.timeout = old_timeout
```

Also wrap `send()`'s executor call in `async with self._lock:` so reads and writes don't interleave on the port.

- [ ] **Step 3: Replace `print(..., file=sys.stderr)` with logging** in `usb.py`, `wifi.py`, `auto.py`. Add `import logging` + `logger = logging.getLogger(__name__)` at the top of each, remove `import sys`, and convert each `print(MSG, file=sys.stderr)` to `logger.info(MSG)` (or `logger.warning` for the "No Flipper detected" fallbacks). Convert the bare `except Exception:` in `wifi._drain_socket_buffer` and `auto.is_connected`/`get_name` to `except (OSError, asyncio.TimeoutError):` and `except AttributeError:` respectively (no silent broad swallows — see CLAUDE.md).

- [ ] **Step 4: Create `src/flipperzero_mcp/transport/__init__.py`** (factory without bluetooth)

```python
"""Transport layer factory."""

from __future__ import annotations

from flipperzero_mcp.transport.auto import AutoTransport
from flipperzero_mcp.transport.base import FlipperTransport
from flipperzero_mcp.transport.usb import USBTransport
from flipperzero_mcp.transport.wifi import WiFiTransport

__all__ = ["AutoTransport", "FlipperTransport", "USBTransport", "WiFiTransport", "get_transport"]

_TRANSPORTS: dict[str, type[FlipperTransport]] = {
    "auto": AutoTransport,
    "usb": USBTransport,
    "wifi": WiFiTransport,
}


def get_transport(transport_type: str, config: dict) -> FlipperTransport:
    """Create a transport instance from a config dict (see FlipperConfig.as_transport_config)."""
    transport_type = transport_type.lower()
    if transport_type not in _TRANSPORTS:
        raise ValueError(f"Unknown transport type: {transport_type}. Available: {', '.join(_TRANSPORTS)}")
    section = config.get("transport", {}) or {}
    if transport_type == "auto":
        return AutoTransport(section)
    return _TRANSPORTS[transport_type](section.get(transport_type, {}) or {})
```

Update the relative imports inside the copied `usb.py`/`wifi.py`/`auto.py` from `from .base import` to `from flipperzero_mcp.transport.base import` (absolute imports — CLAUDE.md bans relative `..`/`.` package imports; the harvested files use `.base`).

- [ ] **Step 5: Write the test** `tests/unit/test_transport.py`

```python
import pytest

from flipperzero_mcp.transport import get_transport
from flipperzero_mcp.transport.auto import AutoTransport
from flipperzero_mcp.transport.base import FlipperTransport


class FakeInner(FlipperTransport):
    def __init__(self, config, *, succeed):
        super().__init__(config)
        self._succeed = succeed
        self.sent: list[bytes] = []

    async def connect(self):
        self.connected = self._succeed
        return self._succeed

    async def disconnect(self):
        self.connected = False

    async def send(self, data):
        self.sent.append(data)

    async def receive(self, timeout=None):
        return b""

    async def is_connected(self):
        return self.connected


def test_unknown_transport_raises():
    with pytest.raises(ValueError, match="Unknown transport"):
        get_transport("serial", {"transport": {}})


async def test_auto_prefers_usb(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.transport.auto.USBTransport", lambda c: FakeInner(c, succeed=True))
    monkeypatch.setattr("flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=True))
    auto = AutoTransport({"usb": {}, "wifi": {"host": "x"}})
    assert await auto.connect() is True
    assert auto.get_name() == "FakeInner"


async def test_auto_skips_wifi_when_unconfigured(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.transport.auto.USBTransport", lambda c: FakeInner(c, succeed=False))
    monkeypatch.setattr("flipperzero_mcp.transport.auto.WiFiTransport", lambda c: FakeInner(c, succeed=True))
    auto = AutoTransport({"usb": {}, "wifi": {}})  # no host -> wifi not configured
    assert await auto.connect() is False
```

- [ ] **Step 6: Run tests / lint / types**

Run: `uv run pytest tests/unit/test_transport.py -q && uv run ruff check src/flipperzero_mcp/transport/ && uv run ty check src/flipperzero_mcp/`
Expected: 3 passed; ruff and ty clean.

- [ ] **Step 7: Commit**

```bash
git add src/flipperzero_mcp/transport/ tests/unit/test_transport.py
git commit -m "Harvest transport layer (USB lock, logging, no bluetooth)"
```

---

### Task 7: Harvest protobuf RPC + framing property test

**Files:**
- Create: `src/flipperzero_mcp/rpc/protobuf_rpc.py`
- Test: `tests/property/test_framing.py`
- Source: upstream `core/protobuf_rpc.py`

- [ ] **Step 1: Copy `core/protobuf_rpc.py` to `src/flipperzero_mcp/rpc/protobuf_rpc.py`.** Update its protobuf import to `from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, system_pb2, property_pb2, storage_pb2, application_pb2` and its transport import to `from flipperzero_mcp.transport.base import FlipperTransport`.

- [ ] **Step 2: Fix the event-loop block.** At what is line 148 in the source (inside `drain_host_rx`), change `time.sleep(0.01)` to `await asyncio.sleep(0.01)`. Remove the now-unused `import time` if nothing else uses it (check with `rg "time\." src/flipperzero_mcp/rpc/protobuf_rpc.py`).

- [ ] **Step 3: Convert debug `print(..., file=sys.stderr)` to `logger.debug(...)`.** Add `import logging` + `logger = logging.getLogger(__name__)`; replace the `self.debug`-gated prints with `logger.debug(...)` (drop the `if self.debug:` guards — logging level handles it). Replace any remaining bare `except Exception:` that silently `pass` with a narrow exception type or a `logger.debug("...", exc_info=True)` so failures are observable.

- [ ] **Step 4: Write the framing property test** `tests/property/test_framing.py`

```python
from hypothesis import given
from hypothesis import strategies as st

from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


@given(st.integers(min_value=0, max_value=2**31 - 1))
def test_varint_roundtrip(n):
    encoded = ProtobufRPC._encode_varint(n)
    # decode the varint the same way _read_varint accumulates 7-bit groups
    value = 0
    shift = 0
    for byte in encoded:
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    assert value == n


@given(st.integers(min_value=0, max_value=127))
def test_small_varint_is_single_byte(n):
    assert len(ProtobufRPC._encode_varint(n)) == 1
```

- [ ] **Step 5: Run the property test / lint / types**

Run: `uv run pytest tests/property/test_framing.py -q && uv run ruff check src/flipperzero_mcp/rpc/protobuf_rpc.py && uv run ty check src/flipperzero_mcp/`
Expected: passed; clean. (If `_encode_varint` is an instance method rather than `@staticmethod`, call it via an instance; adjust the test accordingly — confirm the signature in the copied file.)

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/rpc/protobuf_rpc.py tests/property/test_framing.py
git commit -m "Harvest ProtobufRPC (async sleep fix, logging) + framing property test"
```

---

### Task 8: Slim FlipperClient over ProtobufRPC

**Files:**
- Create: `src/flipperzero_mcp/rpc/client.py`
- Test: `tests/unit/test_client.py`
- Source: upstream `core/flipper_client.py` (harvest the health/device-info logic ONLY; drop `rpc.py`/`FlipperRPC` entirely and the storage/app sub-clients not needed in phase 1)

- [ ] **Step 1: Write the failing test** `tests/unit/test_client.py`

```python
from flipperzero_mcp.rpc.client import FlipperClient


class FakeTransport:
    def __init__(self, connected=True):
        self._connected = connected

    def get_name(self):
        return "Fake"

    async def connect(self):
        return self._connected

    async def disconnect(self):
        self._connected = False

    async def is_connected(self):
        return self._connected


class FakeRPC:
    def __init__(self, transport):
        self._transport = transport

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Flipper", "firmware_version": "1.0.0"}

    async def storage_info(self, path):
        return (1000, 500)


async def test_health_connected_and_rpc_responsive(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    assert await client.connect() is True
    health = await client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    assert health["transport_connected"] is True
    assert health["rpc_responsive"] is True
    assert health["transport"]["type"] == "Fake"


async def test_health_reports_disconnected_transport(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport(connected=False))
    await client.connect()
    health = await client.get_connection_health(probe_rpc=True)
    assert health["connected"] is False


async def test_device_info_normalizes(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    info = await client.get_device_info()
    assert info["firmware"] == "1.0.0"


async def test_sd_card_available_true(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    client = FlipperClient(FakeTransport())
    await client.connect()
    assert await client.check_sd_card_available() is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_client.py -q`
Expected: FAIL with `ModuleNotFoundError: flipperzero_mcp.rpc.client`.

- [ ] **Step 3: Create `src/flipperzero_mcp/rpc/client.py`** (uses `ProtobufRPC` directly — note `ping` not `protobuf_ping`, and `storage_info` returns `tuple[int, int]`)

```python
"""High-level Flipper client over the protobuf RPC layer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC
from flipperzero_mcp.transport.base import FlipperTransport

logger = logging.getLogger(__name__)

_HEALTH_PROBE = b"mcp_health"


class FlipperClient:
    """Connect/health/device-info wrapper around a transport + ProtobufRPC."""

    def __init__(self, transport: FlipperTransport) -> None:
        self.transport = transport
        self.connected = False
        self.rpc: ProtobufRPC | None = None
        self.last_connection_error: str | None = None
        self._sd_card_available: bool | None = None

    async def connect(self) -> bool:
        try:
            ok = await self.transport.connect()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
            return False
        if not ok:
            return False
        self.rpc = ProtobufRPC(self.transport)
        self.connected = True
        self.last_connection_error = None
        self._sd_card_available = None
        return True

    async def disconnect(self) -> None:
        try:
            await self.transport.disconnect()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
        self.connected = False
        self.rpc = None

    async def get_connection_health(self, probe_rpc: bool = True) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat()
        transport_connected = False
        try:
            transport_connected = bool(await self.transport.is_connected())
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)

        rpc_responsive: bool | None = None
        if probe_rpc:
            rpc_responsive = False
            if transport_connected and self.rpc is not None:
                try:
                    echoed = await self.rpc.ping(_HEALTH_PROBE)
                    rpc_responsive = echoed == _HEALTH_PROBE
                except (OSError, RuntimeError) as exc:
                    self.last_connection_error = str(exc)

        connected = transport_connected and (rpc_responsive if probe_rpc else True)
        return {
            "timestamp": ts,
            "connected": bool(connected),
            "transport_connected": transport_connected,
            "rpc_responsive": rpc_responsive,
            "transport": {"type": self.transport.get_name()},
            "last_error": self.last_connection_error,
        }

    async def get_device_info(self) -> dict[str, Any]:
        if self.rpc is None:
            return {"name": "Flipper Zero", "hardware": "Unknown", "firmware": "Unknown"}
        try:
            info = await self.rpc.get_device_info()
        except (OSError, RuntimeError) as exc:
            self.last_connection_error = str(exc)
            info = {}
        return {
            "name": info.get("hardware_name") or info.get("name") or "Flipper Zero",
            "hardware": info.get("hardware_model") or info.get("hardware") or "Unknown",
            "firmware": info.get("firmware_version") or info.get("firmware") or "Unknown",
            **{k: v for k, v in info.items() if k not in {"hardware_name", "name", "hardware_model"}},
        }

    async def check_sd_card_available(self) -> bool:
        if self._sd_card_available is not None:
            return self._sd_card_available
        available = False
        if self.rpc is not None:
            try:
                info = await self.rpc.storage_info("/ext")
                available = bool(info and info[0] > 0)
            except (OSError, RuntimeError) as exc:
                self.last_connection_error = str(exc)
        self._sd_card_available = available
        return available
```

> **Note for the implementer:** confirm the exact dict keys `ProtobufRPC.get_device_info()` returns by reading the copied `protobuf_rpc.py` `_get_device_info_internal`; the `.get(...)` fallbacks above cover the common keys (`hardware_name`, `hardware_model`, `firmware_version`) but adjust if the real keys differ. `storage_info` returns `tuple[int, int]` = `(total, free)` per its signature.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_client.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/flipperzero_mcp/rpc/client.py tests/unit/test_client.py
git commit -m "Add slim FlipperClient over ProtobufRPC"
```

---

### Task 9: FastMCP server + lifespan

**Files:**
- Create: `src/flipperzero_mcp/server.py`
- Reference: `../gandi-mcp/src/gandi_mcp/server.py`

- [ ] **Step 1: Create `src/flipperzero_mcp/server.py`**

```python
"""FastMCP server creation and lifespan for the Flipper MCP server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.transport import get_transport

logger = logging.getLogger(__name__)


@dataclass
class ServerContext:
    """Lifespan context passed to all tools via ctx.lifespan_context."""

    config: FlipperConfig
    client: FlipperClient


def _build_lifespan(config: FlipperConfig):  # type: ignore[no-untyped-def]
    @lifespan  # ty: ignore[invalid-argument-type]
    async def server_lifespan(server: FastMCP) -> AsyncIterator[ServerContext]:
        transport = get_transport(config.transport, config.as_transport_config())
        client = FlipperClient(transport)
        if await client.connect():
            logger.info("Connected to Flipper via %s", transport.get_name())
        else:
            logger.warning(
                "Flipper not connected at startup (%s). Connection tools remain usable.",
                client.last_connection_error or "no device found",
            )
        try:
            yield ServerContext(config=config, client=client)
        finally:
            await client.disconnect()

    return server_lifespan


def create_server(config: FlipperConfig | None = None) -> FastMCP:
    """Create and configure the FastMCP server."""
    if config is None:
        config = FlipperConfig()
    server = FastMCP(
        name="flipperzero-mcp",
        instructions=(
            "Flipper Zero MCP server. Inspect device connection health and system "
            "information over USB or WiFi. Call flipper_connection_health before other "
            "tools if the device may have disconnected."
        ),
        lifespan=_build_lifespan(config),
    )
    from flipperzero_mcp.tools import register_all_tools

    register_all_tools(server)
    return server
```

- [ ] **Step 2: Verify it imports** (tools module comes in Task 13; stub it first so import works)

Run: `mkdir -p src/flipperzero_mcp/tools && printf 'def register_all_tools(mcp):\n    pass\n' > src/flipperzero_mcp/tools/__init__.py && uv run python -c "from flipperzero_mcp.server import create_server; create_server()"`
Expected: exits 0 (lifespan does not run on construction).

- [ ] **Step 3: Commit**

```bash
git add src/flipperzero_mcp/server.py src/flipperzero_mcp/tools/__init__.py
git commit -m "Add FastMCP server with lifespan-owned FlipperClient"
```

---

### Task 10: Tool helpers + reconnect guard

**Files:**
- Create: `src/flipperzero_mcp/tools/_common.py`
- Test: `tests/unit/test_common.py`
- Reference: `../gandi-mcp/src/gandi_mcp/tools/_common.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_common.py`

```python
import pytest

from flipperzero_mcp.errors import FlipperNotConnectedError
from flipperzero_mcp.tools import _common


class FakeCtx:
    def __init__(self, context):
        self.lifespan_context = context


class FakeContextObj:
    def __init__(self, client):
        self.client = client


class FakeClient:
    def __init__(self, *, up, reconnects_to):
        self._up = up
        self._reconnects_to = reconnects_to
        self.disconnect_calls = 0
        self.connect_calls = 0

        class _T:
            async def is_connected(_self):
                return up

        self.transport = _T()

    async def disconnect(self):
        self.disconnect_calls += 1

    async def connect(self):
        self.connect_calls += 1
        return self._reconnects_to


async def test_ensure_connected_passes_when_up():
    client = FakeClient(up=True, reconnects_to=True)
    ctx = FakeCtx(FakeContextObj(client))
    await _common.ensure_connected(ctx)
    assert client.connect_calls == 0


async def test_ensure_connected_reconnects_once_then_ok():
    client = FakeClient(up=False, reconnects_to=True)
    ctx = FakeCtx(FakeContextObj(client))
    await _common.ensure_connected(ctx)
    assert client.disconnect_calls == 1
    assert client.connect_calls == 1


async def test_ensure_connected_raises_when_reconnect_fails():
    client = FakeClient(up=False, reconnects_to=False)
    ctx = FakeCtx(FakeContextObj(client))
    with pytest.raises(FlipperNotConnectedError):
        await _common.ensure_connected(ctx)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_common.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'ensure_connected'`.

- [ ] **Step 3: Create `src/flipperzero_mcp/tools/_common.py`**

```python
"""Shared helpers for Flipper MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flipperzero_mcp.errors import FlipperNotConnectedError

if TYPE_CHECKING:
    from fastmcp import Context

    from flipperzero_mcp.rpc.client import FlipperClient
    from flipperzero_mcp.server import ServerContext


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return ctx.lifespan_context  # ty: ignore[invalid-return-type]


def get_client(ctx: Context) -> FlipperClient:
    """Return the FlipperClient owned by the lifespan."""
    return get_server_context(ctx).client


async def ensure_connected(ctx: Context) -> FlipperClient:
    """Guarantee a live transport, attempting one reconnect on a mid-session drop.

    Replaces upstream's central call_tool reconnect wrapper. Every hardware-touching
    tool calls this first; the connection tools do NOT (they must run while down).

    Raises:
        FlipperNotConnectedError: if the device is down and a single reconnect fails.
    """
    client = get_client(ctx)
    try:
        if await client.transport.is_connected():
            return client
    except (OSError, RuntimeError):
        pass
    await client.disconnect()
    if await client.connect():
        return client
    raise FlipperNotConnectedError(client.last_connection_error or "device unavailable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_common.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/flipperzero_mcp/tools/_common.py tests/unit/test_common.py
git commit -m "Add tool helpers and ensure_connected reconnect guard"
```

---

### Task 11: connection tools

**Files:**
- Create: `src/flipperzero_mcp/tools/connection.py`
- Test: `tests/unit/test_tool_connection.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_tool_connection.py`

```python
from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def __init__(self):
        self.connected = True

    def get_name(self):
        return "Fake"

    async def connect(self):
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False

    async def is_connected(self):
        return self.connected


class FakeRPC:
    def __init__(self, transport):
        pass

    async def ping(self, data=b"ping"):
        return data


async def _server(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.transport.get_transport", lambda t, c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    return create_server(FlipperConfig(_env_file=None))


async def test_health_tool_reports_connected(monkeypatch):
    server = await _server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipper_connection_health", {"probe_rpc": True})
        assert result.data["connected"] is True


async def test_reconnect_tool_returns_health(monkeypatch):
    server = await _server(monkeypatch)
    async with Client(server) as client:
        result = await client.call_tool("flipper_connection_reconnect", {})
        assert result.data["reconnect_ok"] is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_tool_connection.py -q`
Expected: FAIL (tool not registered — `register_all_tools` is still a stub).

- [ ] **Step 3: Create `src/flipperzero_mcp/tools/connection.py`**

```python
"""Connection health and reconnect tools (always callable, even when disconnected)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from flipperzero_mcp.tools._common import get_client


def register_connection_tools(mcp: FastMCP) -> None:
    """Register connection health/reconnect tools."""

    @mcp.tool(tags={"flipper", "connection"})
    async def flipper_connection_health(ctx: Context, probe_rpc: bool = True) -> dict[str, Any]:
        """Return authoritative Flipper connection health.

        Args:
            probe_rpc: If true, send a protobuf RPC ping to confirm RPC responsiveness.

        Returns:
            Health dict: connected, transport_connected, rpc_responsive, transport, last_error.
        """
        return await get_client(ctx).get_connection_health(probe_rpc=probe_rpc)

    @mcp.tool(tags={"flipper", "connection"})
    async def flipper_connection_reconnect(ctx: Context, probe_rpc: bool = True) -> dict[str, Any]:
        """Disconnect and reconnect to the Flipper, then return updated health.

        Args:
            probe_rpc: If true, ping RPC after reconnect to confirm responsiveness.

        Returns:
            Health dict plus reconnect_ok (bool).
        """
        client = get_client(ctx)
        await client.disconnect()
        reconnect_ok = await client.connect()
        health = await client.get_connection_health(probe_rpc=probe_rpc)
        health["reconnect_ok"] = reconnect_ok
        return health
```

- [ ] **Step 4: Wire into `register_all_tools`** — replace the stub `src/flipperzero_mcp/tools/__init__.py` body:

```python
"""MCP tool registration for the Flipper Zero."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register every Flipper tool on the server."""
    from flipperzero_mcp.tools.connection import register_connection_tools
    from flipperzero_mcp.tools.systeminfo import register_systeminfo_tools

    register_connection_tools(mcp)
    register_systeminfo_tools(mcp)
```

> The `systeminfo` import lands in Task 12. To keep this task's tests green on their own, temporarily comment the `systeminfo` import+call, then restore it in Task 12 Step 4.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_connection.py -q`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/tools/connection.py src/flipperzero_mcp/tools/__init__.py tests/unit/test_tool_connection.py
git commit -m "Add flipper connection health/reconnect tools"
```

---

### Task 12: systeminfo tool

**Files:**
- Create: `src/flipperzero_mcp/tools/systeminfo.py`
- Test: `tests/unit/test_tool_systeminfo.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_tool_systeminfo.py`

```python
from fastmcp import Client

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


class FakeTransport:
    def get_name(self):
        return "Fake"

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def is_connected(self):
        return True


class FakeRPC:
    def __init__(self, transport):
        pass

    async def ping(self, data=b"ping"):
        return data

    async def get_device_info(self):
        return {"hardware_name": "Flipper", "firmware_version": "1.2.3"}

    async def storage_info(self, path):
        return (1000, 500)


async def test_systeminfo_returns_structured(monkeypatch):
    monkeypatch.setattr("flipperzero_mcp.transport.get_transport", lambda t, c: FakeTransport())
    monkeypatch.setattr("flipperzero_mcp.rpc.client.ProtobufRPC", FakeRPC)
    server = create_server(FlipperConfig(_env_file=None))
    async with Client(server) as client:
        result = await client.call_tool("systeminfo_get", {})
        data = result.data
        assert data["connected"] is True
        assert data["device"]["firmware"] == "1.2.3"
        assert data["sd_card_available"] is True
        assert data["transport"] == "Fake"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_tool_systeminfo.py -q`
Expected: FAIL (`systeminfo_get` not registered).

- [ ] **Step 3: Create `src/flipperzero_mcp/tools/systeminfo.py`**

```python
"""System information tool for the Flipper Zero."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from flipperzero_mcp.errors import handle_client_error
from flipperzero_mcp.tools._common import ensure_connected


def register_systeminfo_tools(mcp: FastMCP) -> None:
    """Register the systeminfo tool."""

    @mcp.tool(tags={"flipper", "systeminfo"})
    async def systeminfo_get(ctx: Context) -> dict[str, Any]:
        """Get system information about the connected Flipper Zero.

        Returns:
            Dict with connection status, transport, device info (name/hardware/firmware),
            and SD-card availability.
        """
        try:
            client = await ensure_connected(ctx)
            health = await client.get_connection_health(probe_rpc=True)
            device = await client.get_device_info()
            sd = await client.check_sd_card_available()
        except Exception as e:  # noqa: BLE001 — mapped to ToolError below
            handle_client_error(e)
        return {
            "connected": health["connected"],
            "transport": health["transport"]["type"],
            "rpc_responsive": health["rpc_responsive"],
            "device": device,
            "sd_card_available": sd,
        }
```

- [ ] **Step 4: Restore the `systeminfo` registration** in `tools/__init__.py` (uncomment the import + call added in Task 11 Step 4).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_systeminfo.py tests/unit/test_tool_connection.py -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/flipperzero_mcp/tools/systeminfo.py src/flipperzero_mcp/tools/__init__.py tests/unit/test_tool_systeminfo.py
git commit -m "Add systeminfo_get tool"
```

---

### Task 13: Entry point

**Files:**
- Create: `src/flipperzero_mcp/__main__.py`
- Reference: `../gandi-mcp/src/gandi_mcp/__main__.py`

- [ ] **Step 1: Create `src/flipperzero_mcp/__main__.py`**

```python
"""Entry point for running flipperzero-mcp as a module."""

from __future__ import annotations

from flipperzero_mcp._logging import configure_logging
from flipperzero_mcp.server import create_server


def main() -> None:
    """Start the Flipper MCP server over stdio."""
    configure_logging()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the console script resolves**

Run: `uv run python -c "from flipperzero_mcp.__main__ import main; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/flipperzero_mcp/__main__.py
git commit -m "Add module entry point"
```

---

### Task 14: Integration tests (opt-in, real hardware)

**Files:**
- Create: `tests/integration/test_hardware.py`, `tests/integration/conftest.py`

- [ ] **Step 1: Create `tests/integration/conftest.py`** (skips unless a Flipper is reachable)

```python
import os

import pytest

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.rpc.client import FlipperClient
from flipperzero_mcp.transport import get_transport


@pytest.fixture
async def usb_client():
    cfg = FlipperConfig(_env_file=None, transport="usb")
    client = FlipperClient(get_transport("usb", cfg.as_transport_config()))
    if not await client.connect():
        pytest.skip("No USB Flipper connected")
    yield client
    await client.disconnect()


@pytest.fixture
async def wifi_client():
    host = os.environ.get("FLIPPER_WIFI_HOST")
    if not host:
        pytest.skip("FLIPPER_WIFI_HOST not set")
    cfg = FlipperConfig(_env_file=None, transport="wifi", wifi_host=host)
    client = FlipperClient(get_transport("wifi", cfg.as_transport_config()))
    if not await client.connect():
        pytest.skip("WiFi Flipper not reachable")
    yield client
    await client.disconnect()
```

- [ ] **Step 2: Create `tests/integration/test_hardware.py`**

```python
import pytest


@pytest.mark.integration
@pytest.mark.usb
async def test_usb_health_and_device_info(usb_client):
    health = await usb_client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    assert health["rpc_responsive"] is True
    info = await usb_client.get_device_info()
    assert info["firmware"] != "Unknown"


@pytest.mark.integration
@pytest.mark.wifi
async def test_wifi_health_and_device_info(wifi_client):
    health = await wifi_client.get_connection_health(probe_rpc=True)
    assert health["connected"] is True
    info = await wifi_client.get_device_info()
    assert info["firmware"] != "Unknown"
```

- [ ] **Step 3: Verify they are skipped (not failed) without hardware in CI mode**

Run: `uv run pytest -m "not integration" -q` (collects them, runs none) then `uv run pytest tests/integration -q` (skips both without hardware).
Expected: first run excludes them; second run shows 2 skipped.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/
git commit -m "Add opt-in USB/WiFi integration tests"
```

---

### Task 15: Firmware + docs + repo docs

**Files:**
- Create: `firmware/tcp_uart_bridge/` (sanitized copy), `firmware/tcp_uart_bridge/sdkconfig.defaults`, `docs/wifi_dev_board.md`, `docs/protobuf_rpc.md`, `README.md`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CLAUDE.md`
- Source: upstream `firmware/`, `docs/`

- [ ] **Step 1: Copy the firmware** then sanitize and drop stale files:

Run:
```bash
mkdir -p firmware && cp -R ../flipperzero-mcp-upstream/firmware/tcp_uart_bridge firmware/
rm -f firmware/tcp_uart_bridge/sdkconfig.old
rg -n -i "wifi.*(ssid|password)|CONFIG_.*PASSWORD|CONFIG_.*SSID" firmware/tcp_uart_bridge/sdkconfig
```
If the grep finds any credential value, scrub it: keep the keys but blank the values, save the result as `firmware/tcp_uart_bridge/sdkconfig.defaults`, and confirm `sdkconfig` is gitignored (Task 0 added it). Do NOT commit a populated `sdkconfig`.

- [ ] **Step 2: Copy domain docs** `cp ../flipperzero-mcp-upstream/docs/wifi_dev_board.md ../flipperzero-mcp-upstream/docs/protobuf_rpc.md docs/` and fix any `flipper_mcp`→`flipperzero_mcp` and `python -m flipper_mcp.cli.main`→`python -m flipperzero_mcp` references.

- [ ] **Step 3: Write `README.md`** — features, the stdio Claude Desktop config block (using `"command": "uv", "args": ["run", "flipperzero-mcp"]` or `python -m flipperzero_mcp`), the `FLIPPER_*` env table from `.env.example`, available tools (`flipper_connection_health`, `flipper_connection_reconnect`, `systeminfo_get`), and an attribution line pointing at `NOTICE`.

- [ ] **Step 4: Write `CHANGELOG.md`** (Keep a Changelog format, `0.1.0` unreleased: connection + systeminfo, USB + WiFi), `SECURITY.md` (how to report; note firmware `sdkconfig` is gitignored), `CONTRIBUTING.md` (uv workflow, `prek run`, tiered tests), and `CLAUDE.md` (inherits workspace CLAUDE.md; notes the harvest provenance, the stdio/stderr-logging constraint, and the protobuf 6.33.2 pin).

- [ ] **Step 5: Commit**

```bash
git add firmware/ docs/ README.md CHANGELOG.md SECURITY.md CONTRIBUTING.md CLAUDE.md
git commit -m "Harvest firmware (sanitized) and docs; add repo docs"
```

---

### Task 16: Full gate + hardware verification + PR

- [ ] **Step 1: Run the complete local gate**

Run:
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/flipperzero_mcp/
uv run bandit -r src/flipperzero_mcp/ -c pyproject.toml
uv run pytest -m "not integration" --cov=flipperzero_mcp --cov-report=term --cov-fail-under=80
uv run pip-audit
uv run pre-commit run --all-files
```
Expected: all clean; coverage ≥ 80%.

- [ ] **Step 2: Verify against real hardware (USB)** — connect the Flipper via USB:

Run: `uv run pytest tests/integration -m "usb" -q`
Expected: `test_usb_health_and_device_info` passes (not skipped).

- [ ] **Step 3: Verify against real hardware (WiFi)** — set the dev board host:

Run: `FLIPPER_WIFI_HOST=<board-ip> uv run pytest tests/integration -m "wifi" -q`
Expected: `test_wifi_health_and_device_info` passes.

- [ ] **Step 4: Smoke-test the live server in Claude Desktop / `fastmcp` inspector** — start `uv run flipperzero-mcp`, confirm `systeminfo_get` returns real device data and no output appears on stdout except JSON-RPC frames.

- [ ] **Step 5: Push and open the PR**

Run:
```bash
git push -u origin phase1
gh pr create --title "Phase 1: connection + systeminfo over USB/WiFi" \
  --body "Implements the Phase 1 tracer bullet per docs/superpowers/plans/2026-05-29-flipperzero-mcp-phase1.md: house-style FastMCP scaffold, harvested transport + protobuf RPC + firmware, and working connection/systeminfo tools verified on real hardware."
```

---

## Self-Review

**Spec coverage:**
- Delete plugin system → FastMCP decorators: Tasks 9, 11, 12, 13. ✓
- Lifespan-owned client + `ensure_connected` reconnect guard: Tasks 9, 10. ✓
- stderr logging guard: Task 2 + Task 13 (`configure_logging` before `run`). ✓
- pydantic-settings config: Task 4. ✓
- FlipperError → ToolError: Task 3, used in Task 12. ✓
- Harvest transport (USB lock, drop bluetooth, print→logging): Task 6. ✓
- Harvest protobuf RPC (`time.sleep`→`asyncio.sleep`): Task 7. ✓
- Delete rpc.py dead code (use ProtobufRPC directly): Task 8. ✓
- Protobuf regen + 6.33.2 pin + provenance + `.tmp_proto` diff: Tasks 0, 5. ✓
- Tiered tests + framing property test + ~80% gate: Tasks 7, 14, 1, 16. ✓
- Licensing NOTICE: Task 0. ✓
- sdkconfig credential sanitize: Task 15. ✓
- CI + pre-commit: Task 1. ✓

**Placeholder scan:** Harvested files (transport, protobuf_rpc) are specified as copy-with-named-edits rather than full paste — every edit names the exact change. Two implementer notes flag values to confirm against the copied source (device-info dict keys in Task 8; `_encode_varint` static-vs-instance in Task 7) — these are verification steps, not unfilled blanks.

**Type/name consistency:** `FlipperClient` methods (`connect`, `disconnect`, `get_connection_health`, `get_device_info`, `check_sd_card_available`, `.transport`, `.rpc`, `.last_connection_error`) are defined in Task 8 and used identically in Tasks 9–12. `ServerContext(config, client)` defined in Task 9, consumed in Task 10. `get_client`/`get_server_context`/`ensure_connected` defined in Task 10, used in Tasks 11–12. `register_connection_tools`/`register_systeminfo_tools` defined in Tasks 11/12, called in Task 11's `register_all_tools`. Consistent.
