# Multi-firmware Support + Firmware-Flash Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support official Flipper firmware (release / release-candidate / development) alongside Momentum, including a USB firmware-flash tool, and validate the server on real official hardware.

**Architecture:** A pure firmware classifier reads `device_info` and is surfaced by `flipperzero_system_info`. A firmware-flash path fixes chunked `storage_write`, adds `system_update`/`system_reboot` RPCs, an installer that pushes an update bundle and reboots into the updater, and a gated `flipperzero_firmware_install` tool. Bundles come from a verified auto-downloader (official `directory.json` / Momentum GitHub releases) or a local `.tgz`. Golden tests run against both Momentum and official fixtures.

**Tech Stack:** Python 3.13, `uv`, FastMCP, protobuf (`6.33.x`), pytest (`asyncio_mode=auto`), VCR cassettes, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-06-09-multi-firmware-support-design.md`

**Branch:** `multi-firmware-support` (already created).

---

## Phase 1 — Chunked `storage_write` (fixes latent `fs_push` large-file bug)

### Task 1: Chunk large payloads in `storage_write`

**Files:**
- Modify: `src/flipperzero_mcp/rpc/protobuf_rpc.py` (the `storage_write` / `_storage_write_internal` pair, ~lines 1078-1108)
- Test: `tests/unit/test_storage_write_chunked.py` (create)

Context: the transport exposes `send(bytes)`, `receive_exact(n, timeout)`, `receive(timeout)`. A frame is `_encode_varint(len(payload)) + payload`. `_receive_main_message()` reads exactly one response frame. Intermediate write frames set `has_next=True` and get **no** response; only the final frame (`has_next=False`) is answered. All chunks share one `command_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_storage_write_chunked.py
"""Unit tests for chunked storage_write framing."""

import pytest

from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class RecordingTransport:
    """Captures sent frames and replies with one canned WriteResponse (OK)."""

    def __init__(self):
        self.sent: list[bytes] = []
        ok = flipper_pb2.Main()
        ok.command_status = flipper_pb2.CommandStatus.OK
        ok.empty.CopyFrom(flipper_pb2.Empty())
        payload = ok.SerializeToString()
        self._reply = ProtobufRPC._encode_varint(len(payload)) + payload
        self._reply_pos = 0

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive_exact(self, n: int, timeout: float | None = None) -> bytes:
        chunk = self._reply[self._reply_pos : self._reply_pos + n]
        self._reply_pos += n
        return chunk

    async def is_connected(self) -> bool:
        return True


def _decode_frames(sent: list[bytes]) -> list[flipper_pb2.Main]:
    frames = []
    for raw in sent:
        # Strip the leading varint length prefix, then parse the Main payload.
        idx, shift, length = 0, 0, 0
        while True:
            byte = raw[idx]
            length |= (byte & 0x7F) << shift
            idx += 1
            if not (byte & 0x80):
                break
            shift += 7
        msg = flipper_pb2.Main()
        msg.ParseFromString(raw[idx : idx + length])
        frames.append(msg)
    return frames


@pytest.mark.asyncio
async def test_large_write_is_chunked_with_has_next():
    rpc = ProtobufRPC(RecordingTransport())
    rpc._rpc_session_started = True  # skip CLI negotiation
    content = b"A" * 3000  # > one 1024-byte chunk

    ok = await rpc.storage_write("/ext/big.bin", content)

    assert ok is True
    frames = _decode_frames(rpc.transport.sent)
    assert len(frames) == 3  # 1024 + 1024 + 952
    assert all(f.command_id == frames[0].command_id for f in frames)
    assert [f.has_next for f in frames] == [True, True, False]
    rebuilt = b"".join(f.storage_write_request.file.data for f in frames)
    assert rebuilt == content
    assert all(f.storage_write_request.path == "/ext/big.bin" for f in frames)


@pytest.mark.asyncio
async def test_small_write_is_single_frame():
    rpc = ProtobufRPC(RecordingTransport())
    rpc._rpc_session_started = True
    ok = await rpc.storage_write("/ext/small.bin", b"hi")
    assert ok is True
    frames = _decode_frames(rpc.transport.sent)
    assert len(frames) == 1
    assert frames[0].has_next is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_write_chunked.py -v`
Expected: FAIL — large write produces 1 frame (current single-shot), `len(frames) == 3` assertion fails.

- [ ] **Step 3: Implement chunking**

Replace the existing `storage_write` / `_storage_write_internal` pair with:

```python
    _WRITE_CHUNK_SIZE = 1024  # RPC frame payload slice; validated on hardware in Phase 6.

    async def storage_write(self, path: str, content: bytes) -> bool:
        async with self._io_lock:
            # Timeout scales with payload: ~1s per 64 KiB, floor 3s.
            timeout = max(3.0, len(content) / 65536.0)
            try:
                return await asyncio.wait_for(
                    self._storage_write_internal(path, content), timeout=timeout
                )
            except Exception:
                logger.debug("storage_write(%s) timed out or failed", path, exc_info=True)
                return False

    async def _storage_write_internal(self, path: str, content: bytes) -> bool:
        try:
            await self._ensure_rpc_session_started()
            command_id = self._get_next_command_id()
            chunks = self._chunk(content, self._WRITE_CHUNK_SIZE)
            for index, chunk in enumerate(chunks):
                is_last = index == len(chunks) - 1
                main_request = flipper_pb2.Main()
                main_request.command_id = command_id
                main_request.has_next = not is_last
                req = storage_pb2.WriteRequest()
                req.path = path
                req.file.data = chunk
                main_request.storage_write_request.CopyFrom(req)
                payload = main_request.SerializeToString()
                framed = self._encode_varint(len(payload)) + payload
                if is_last:
                    await self.transport.send(framed)
                    response = await self._receive_main_message()
                    return bool(
                        response
                        and response.command_status == flipper_pb2.CommandStatus.OK
                    )
                await self.transport.send(framed)
            return False
        except Exception:
            logger.debug("_storage_write_internal failed", exc_info=True)
            return False

    @staticmethod
    def _chunk(content: bytes, size: int) -> list[bytes]:
        if not content:
            return [b""]
        return [content[i : i + size] for i in range(0, len(content), size)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_storage_write_chunked.py tests/unit/test_tool_fs.py -v`
Expected: PASS (both new tests + existing fs tests unaffected — same signature).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_storage_write_chunked.py
uv run ruff check src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_storage_write_chunked.py
uv run ty check
git add src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_storage_write_chunked.py
git commit -m "fix(rpc): chunk large storage_write payloads with has_next framing"
```

---

## Phase 2 — Firmware classifier + `system_info` block

### Task 2: Pure firmware classifier

**Files:**
- Create: `src/flipperzero_mcp/firmware/__init__.py`
- Create: `src/flipperzero_mcp/firmware/flavor.py`
- Test: `tests/unit/test_firmware_flavor.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_firmware_flavor.py
"""Unit tests for the firmware classifier."""

import pytest

from flipperzero_mcp.firmware.flavor import FirmwareFlavor, classify


@pytest.mark.parametrize(
    ("device_info", "expected_flavor", "expected_target"),
    [
        (
            {
                "firmware_origin_fork": "Momentum",
                "firmware_origin_git": "https://github.com/Next-Flip/Momentum-Firmware",
                "firmware_version": "mntm-012",
                "hardware_target": "7",
            },
            FirmwareFlavor.MOMENTUM,
            "f7",
        ),
        (
            {
                "firmware_origin_fork": "Official",
                "firmware_origin_git": "https://github.com/flipperdevices/flipperzero-firmware",
                "firmware_version": "1.4.3",
                "hardware_target": "7",
            },
            FirmwareFlavor.OFFICIAL,
            "f7",
        ),
        (
            {"firmware_origin_git": "https://github.com/DarkFlippers/unleashed-firmware"},
            FirmwareFlavor.UNLEASHED,
            None,
        ),
        (
            {"firmware_origin_git": "https://github.com/RogueMaster/flipperzero-firmware-wPlugins"},
            FirmwareFlavor.ROGUEMASTER,
            None,
        ),
        ({}, FirmwareFlavor.UNKNOWN, None),
    ],
)
def test_classify(device_info, expected_flavor, expected_target):
    info = classify(device_info)
    assert info.flavor is expected_flavor
    assert info.target == expected_target


def test_classify_falls_back_to_fork_field_when_git_missing():
    info = classify({"firmware_origin_fork": "Momentum"})
    assert info.flavor is FirmwareFlavor.MOMENTUM


def test_classify_reports_version():
    info = classify({"firmware_version": "1.4.3"})
    assert info.version == "1.4.3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_firmware_flavor.py -v`
Expected: FAIL — `ModuleNotFoundError: flipperzero_mcp.firmware`.

- [ ] **Step 3: Implement the classifier**

```python
# src/flipperzero_mcp/firmware/__init__.py
"""Firmware classification and flashing support."""
```

```python
# src/flipperzero_mcp/firmware/flavor.py
"""Pure classifier mapping a device_info dict to a firmware descriptor."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FirmwareFlavor(enum.Enum):
    """Recognized Flipper Zero firmware distributions."""

    OFFICIAL = "official"
    MOMENTUM = "momentum"
    UNLEASHED = "unleashed"
    ROGUEMASTER = "roguemaster"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FirmwareInfo:
    """Classified firmware facts derived from device_info."""

    flavor: FirmwareFlavor
    version: str | None
    origin_fork: str | None
    origin_git: str | None
    target: str | None


_GIT_MARKERS = (
    ("next-flip/momentum", FirmwareFlavor.MOMENTUM),
    ("darkflippers/unleashed", FirmwareFlavor.UNLEASHED),
    ("roguemaster", FirmwareFlavor.ROGUEMASTER),
    ("flipperdevices/flipperzero-firmware", FirmwareFlavor.OFFICIAL),
)
_FORK_MARKERS = (
    ("momentum", FirmwareFlavor.MOMENTUM),
    ("unleashed", FirmwareFlavor.UNLEASHED),
    ("roguemaster", FirmwareFlavor.ROGUEMASTER),
    ("official", FirmwareFlavor.OFFICIAL),
)


def _flavor_from(origin_git: str | None, origin_fork: str | None) -> FirmwareFlavor:
    git = (origin_git or "").lower()
    for marker, flavor in _GIT_MARKERS:
        if marker in git:
            return flavor
    fork = (origin_fork or "").lower()
    for marker, flavor in _FORK_MARKERS:
        if marker in fork:
            return flavor
    return FirmwareFlavor.UNKNOWN


def _target_from(hardware_target: str | None) -> str | None:
    if not hardware_target:
        return None
    return f"f{hardware_target.strip()}"


def classify(device_info: dict[str, str]) -> FirmwareInfo:
    """Classify the connected firmware from a device_info key/value dict.

    Args:
        device_info: The flat dict returned by ProtobufRPC.get_device_info.

    Returns:
        FirmwareInfo with flavor, version, origin fields, and hardware target
        (e.g. ``f7``). Unknown firmwares classify as ``FirmwareFlavor.UNKNOWN``.
    """
    origin_fork = device_info.get("firmware_origin_fork")
    origin_git = device_info.get("firmware_origin_git")
    return FirmwareInfo(
        flavor=_flavor_from(origin_git, origin_fork),
        version=device_info.get("firmware_version"),
        origin_fork=origin_fork,
        origin_git=origin_git,
        target=_target_from(device_info.get("hardware_target")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_firmware_flavor.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/flipperzero_mcp/firmware/ tests/unit/test_firmware_flavor.py
uv run ruff check src/flipperzero_mcp/firmware/ tests/unit/test_firmware_flavor.py
uv run ty check
git add src/flipperzero_mcp/firmware/ tests/unit/test_firmware_flavor.py
git commit -m "feat(firmware): add pure firmware-flavor classifier"
```

### Task 3: Surface `firmware` block in `flipperzero_system_info`

**Files:**
- Modify: `src/flipperzero_mcp/tools/systeminfo.py` (the `flipperzero_system_info` return dict)
- Test: `tests/unit/test_tool_systeminfo.py` (add a case)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_tool_systeminfo.py
@pytest.mark.asyncio
async def test_system_info_includes_firmware_block():
    # Mirror this file's existing server/FakeRPC construction; the FakeRPC's
    # get_device_info returns Momentum-shaped device_info.
    async with Client(_server_with_momentum_device()) as client:
        result = await client.call_tool("flipperzero_system_info", {})
    fw = result.data["firmware"]
    assert fw["flavor"] == "momentum"
    assert fw["target"] == "f7"
    assert fw["version"] == "mntm-012"
```

Add a helper near the top of the test module if one does not already exist:

```python
def _server_with_momentum_device():
    from flipperzero_mcp.config import FlipperConfig
    from flipperzero_mcp.server import create_server

    class _FakeTransport:
        def get_name(self): return "Fake"
        async def connect(self): return True
        async def disconnect(self): return None
        async def is_connected(self): return True

    class _FakeRPC:
        def __init__(self, _t, *, io_lock=None): ...
        async def get_connection_health(self, probe_rpc=True):
            return {"connected": True, "transport": {"type": "usb"}, "rpc_responsive": True}
        async def get_device_info(self):
            return {
                "hardware_name": "Lun10n",
                "hardware_target": "7",
                "firmware_version": "mntm-012",
                "firmware_origin_fork": "Momentum",
                "firmware_origin_git": "https://github.com/Next-Flip/Momentum-Firmware",
            }
        async def check_sd_card_available(self): return True

    # Follow the existing monkeypatch/build idiom in this file to inject the
    # fake client into create_server(FlipperConfig(_env_file=None)).
    return create_server(FlipperConfig(_env_file=None))
```

> If `test_tool_systeminfo.py` already has a server/fake builder, reuse it and just assert the new `firmware` block instead of adding `_server_with_momentum_device`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tool_systeminfo.py::test_system_info_includes_firmware_block -v`
Expected: FAIL — `KeyError: 'firmware'`.

- [ ] **Step 3: Add the firmware block**

In `systeminfo.py`, import the classifier and add the block. Change the import line and the return dict of `flipperzero_system_info`:

```python
from flipperzero_mcp.firmware.flavor import classify
```

```python
        device = await client.get_device_info()
        firmware = classify(device)
        sd = await client.check_sd_card_available()
    except Exception as e:
        _classify_client_error(e)
    return {
        "connected": health["connected"],
        "transport": health["transport"]["type"],
        "rpc_responsive": health["rpc_responsive"],
        "device": device,
        "firmware": {
            "flavor": firmware.flavor.value,
            "version": firmware.version,
            "origin_fork": firmware.origin_fork,
            "origin_git": firmware.origin_git,
            "target": firmware.target,
        },
        "sd_card_available": sd,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_systeminfo.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/flipperzero_mcp/tools/systeminfo.py tests/unit/test_tool_systeminfo.py
uv run ruff check src/flipperzero_mcp/tools/systeminfo.py tests/unit/test_tool_systeminfo.py
uv run ty check
git add src/flipperzero_mcp/tools/systeminfo.py tests/unit/test_tool_systeminfo.py
git commit -m "feat(systeminfo): surface classified firmware block"
```

---

## Phase 3 — Update/reboot RPCs + installer

### Task 4: `system_update` and `system_reboot` RPCs

**Files:**
- Modify: `src/flipperzero_mcp/rpc/protobuf_rpc.py` (add two methods near the other `system_*` methods, e.g. after `system_protobuf_version`)
- Test: `tests/unit/test_system_update_rpc.py` (create)

Context proto facts: `system_pb2.UpdateRequest(update_manifest=str)`; response on `main_response.system_update_response.code` (enum `UpdateResponse.UpdateResultCode`, `OK == 0`). `system_pb2.RebootRequest` with `RebootRequest.RebootMode.UPDATE`. Oneof fields on Main: `system_update_request`, `system_update_response`, `system_reboot_request`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_system_update_rpc.py
"""Unit tests for system_update / system_reboot RPCs."""

import pytest

from flipperzero_mcp.rpc.protobuf_gen import flipper_pb2, system_pb2
from flipperzero_mcp.rpc.protobuf_rpc import ProtobufRPC


class UpdateTransport:
    def __init__(self, code):
        self.sent: list[bytes] = []
        reply = flipper_pb2.Main()
        reply.command_status = flipper_pb2.CommandStatus.OK
        reply.system_update_response.code = code
        payload = reply.SerializeToString()
        self._reply = ProtobufRPC._encode_varint(len(payload)) + payload
        self._pos = 0

    async def send(self, data): self.sent.append(data)
    async def receive_exact(self, n, timeout=None):
        out = self._reply[self._pos : self._pos + n]
        self._pos += n
        return out
    async def is_connected(self): return True


@pytest.mark.asyncio
async def test_system_update_returns_ok_code():
    rpc = ProtobufRPC(UpdateTransport(system_pb2.UpdateResponse.OK))
    rpc._rpc_session_started = True
    code = await rpc.system_update("/ext/update/x/update.fuf")
    assert code == system_pb2.UpdateResponse.OK


@pytest.mark.asyncio
async def test_system_update_returns_target_mismatch_code():
    rpc = ProtobufRPC(UpdateTransport(system_pb2.UpdateResponse.TargetMismatch))
    rpc._rpc_session_started = True
    code = await rpc.system_update("/ext/update/x/update.fuf")
    assert code == system_pb2.UpdateResponse.TargetMismatch


@pytest.mark.asyncio
async def test_system_reboot_update_sends_frame_without_awaiting_response():
    class RebootTransport:
        def __init__(self): self.sent = []
        async def send(self, data): self.sent.append(data)
        async def is_connected(self): return True

    rpc = ProtobufRPC(RebootTransport())
    rpc._rpc_session_started = True
    await rpc.system_reboot_update()
    assert len(rpc.transport.sent) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_system_update_rpc.py -v`
Expected: FAIL — `AttributeError: 'ProtobufRPC' object has no attribute 'system_update'`.

- [ ] **Step 3: Implement the RPCs**

```python
    async def system_update(self, manifest_path: str) -> int:
        """Validate an update bundle manifest on the device.

        Args:
            manifest_path: Absolute device path to ``update.fuf``.

        Returns:
            The ``UpdateResponse.UpdateResultCode`` integer (``0`` == OK).
        """
        async with self._io_lock:
            try:
                main_request = flipper_pb2.Main()
                main_request.command_id = self._get_next_command_id()
                main_request.has_next = False
                req = system_pb2.UpdateRequest()
                req.update_manifest = manifest_path
                main_request.system_update_request.CopyFrom(req)
                response = await self._send_rpc_message(main_request)
                if response and response.HasField("system_update_response"):
                    return int(response.system_update_response.code)
                return int(system_pb2.UpdateResponse.UnspecifiedError)
            except Exception:
                logger.debug("system_update failed", exc_info=True)
                return int(system_pb2.UpdateResponse.UnspecifiedError)

    async def system_reboot_update(self) -> None:
        """Reboot the device into UPDATE mode (fire-and-forget; no response)."""
        async with self._io_lock:
            await self._ensure_rpc_session_started()
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False
            req = system_pb2.RebootRequest()
            req.mode = system_pb2.RebootRequest.UPDATE
            main_request.system_reboot_request.CopyFrom(req)
            payload = main_request.SerializeToString()
            await self.transport.send(self._encode_varint(len(payload)) + payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_system_update_rpc.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_system_update_rpc.py
uv run ruff check src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_system_update_rpc.py
uv run ty check
git add src/flipperzero_mcp/rpc/protobuf_rpc.py tests/unit/test_system_update_rpc.py
git commit -m "feat(rpc): add system_update and system_reboot_update RPCs"
```

### Task 5: Update-result-code mapping

**Files:**
- Create: `src/flipperzero_mcp/firmware/codes.py`
- Test: `tests/unit/test_firmware_codes.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_firmware_codes.py
from flipperzero_mcp.firmware.codes import update_code_message
from flipperzero_mcp.rpc.protobuf_gen import system_pb2


def test_ok_is_none():
    assert update_code_message(system_pb2.UpdateResponse.OK) is None


def test_target_mismatch_message():
    msg = update_code_message(system_pb2.UpdateResponse.TargetMismatch)
    assert "target" in msg.lower()


def test_unknown_code_falls_back():
    assert "code 99" in update_code_message(99).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_firmware_codes.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the mapping**

```python
# src/flipperzero_mcp/firmware/codes.py
"""Human-readable messages for SystemUpdate result codes."""

from __future__ import annotations

from flipperzero_mcp.rpc.protobuf_gen import system_pb2

_MESSAGES = {
    system_pb2.UpdateResponse.ManifestPathInvalid: "update manifest path is invalid",
    system_pb2.UpdateResponse.ManifestFolderNotFound: "update folder not found on device",
    system_pb2.UpdateResponse.ManifestInvalid: "update manifest is invalid or corrupt",
    system_pb2.UpdateResponse.StageMissing: "an update stage file is missing from the bundle",
    system_pb2.UpdateResponse.StageIntegrityError: "an update stage failed its integrity check",
    system_pb2.UpdateResponse.ManifestPointerError: "update manifest pointer error",
    system_pb2.UpdateResponse.TargetMismatch: "bundle hardware target does not match the device",
    system_pb2.UpdateResponse.OutdatedManifestVersion: "update manifest version is outdated",
    system_pb2.UpdateResponse.IntFull: "device internal storage is full",
    system_pb2.UpdateResponse.UnspecifiedError: "unspecified update error",
}


def update_code_message(code: int) -> str | None:
    """Return an actionable message for a non-OK update code, or None for OK.

    Args:
        code: An ``UpdateResponse.UpdateResultCode`` integer.

    Returns:
        None when ``code`` is OK; otherwise a human-readable explanation.
    """
    if code == system_pb2.UpdateResponse.OK:
        return None
    return _MESSAGES.get(code, f"update failed (code {code})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_firmware_codes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/firmware/codes.py tests/unit/test_firmware_codes.py
uv run ruff check src/flipperzero_mcp/firmware/codes.py tests/unit/test_firmware_codes.py
uv run ty check
git add src/flipperzero_mcp/firmware/codes.py tests/unit/test_firmware_codes.py
git commit -m "feat(firmware): map SystemUpdate result codes to messages"
```

### Task 6: Installer orchestration

**Files:**
- Create: `src/flipperzero_mcp/firmware/installer.py`
- Test: `tests/unit/test_firmware_installer.py` (create)

Interface the installer depends on (duck-typed RPC): `get_device_info()`, `storage_mkdir(path)`, `storage_write(path, content)`, `storage_md5sum(path)`, `system_update(manifest)`, `system_reboot_update()`. A `LocalBundle` (from Task 7) has `.manifest_name: str`, `.files: list[tuple[str, bytes]]` (relative posix path → bytes), `.target: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_firmware_installer.py
"""Unit tests for the firmware installer orchestration."""

import hashlib

import pytest

from flipperzero_mcp.firmware.installer import FlashError, install_bundle
from flipperzero_mcp.rpc.protobuf_gen import system_pb2


class FakeBundle:
    manifest_name = "update.fuf"
    target = "f7"
    files = [("update.fuf", b"manifest"), ("firmware.dfu", b"DFU" * 100)]


class FakeRPC:
    def __init__(self, *, update_code=system_pb2.UpdateResponse.OK, target="7"):
        self._update_code = update_code
        self._target = target
        self.store: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.rebooted = False

    async def get_device_info(self):
        return {"hardware_target": self._target, "hardware_name": "Lun10n"}

    async def storage_mkdir(self, path):
        self.calls.append(f"mkdir:{path}")
        return True

    async def storage_write(self, path, content):
        self.store[path] = bytes(content)
        self.calls.append(f"write:{path}")
        return True

    async def storage_md5sum(self, path):
        return hashlib.md5(self.store[path]).hexdigest()

    async def system_update(self, manifest):
        self.calls.append(f"update:{manifest}")
        return self._update_code

    async def system_reboot_update(self):
        self.rebooted = True


@pytest.mark.asyncio
async def test_install_pushes_files_then_updates_then_reboots():
    rpc = FakeRPC()
    await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert "mkdir:/ext/update/upd-test" in rpc.calls
    assert "write:/ext/update/upd-test/firmware.dfu" in rpc.calls
    assert "update:/ext/update/upd-test/update.fuf" in rpc.calls
    assert rpc.rebooted is True


@pytest.mark.asyncio
async def test_install_aborts_on_target_mismatch():
    rpc = FakeRPC(target="18")  # device f18, bundle f7
    with pytest.raises(FlashError, match="target"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False


@pytest.mark.asyncio
async def test_install_aborts_on_non_ok_update_code():
    rpc = FakeRPC(update_code=system_pb2.UpdateResponse.ManifestInvalid)
    with pytest.raises(FlashError, match="manifest"):
        await install_bundle(rpc, FakeBundle(), pkg_name="upd-test")
    assert rpc.rebooted is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_firmware_installer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the installer**

```python
# src/flipperzero_mcp/firmware/installer.py
"""Push an update bundle to the device and trigger the on-device updater."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Protocol

from flipperzero_mcp.firmware.codes import update_code_message

if TYPE_CHECKING:
    from flipperzero_mcp.firmware.bundles import LocalBundle

logger = logging.getLogger(__name__)

_UPDATE_ROOT = "/ext/update"


class FlashError(RuntimeError):
    """Raised when a firmware flash cannot proceed safely."""


class _RPCLike(Protocol):
    async def get_device_info(self) -> dict[str, str]: ...
    async def storage_mkdir(self, path: str) -> bool: ...
    async def storage_write(self, path: str, content: bytes) -> bool: ...
    async def storage_md5sum(self, path: str) -> str | None: ...
    async def system_update(self, manifest: str) -> int: ...
    async def system_reboot_update(self) -> None: ...


async def install_bundle(rpc: _RPCLike, bundle: LocalBundle, *, pkg_name: str) -> None:
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
        if device_md5 != hashlib.md5(data).hexdigest():
            raise FlashError(f"md5 mismatch after writing {dest}")

    manifest = f"{pkg_dir}/{bundle.manifest_name}"
    code = await rpc.system_update(manifest)
    message = update_code_message(code)
    if message is not None:
        raise FlashError(f"device rejected update: {message}")

    await rpc.system_reboot_update()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_firmware_installer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/firmware/installer.py tests/unit/test_firmware_installer.py
uv run ruff check src/flipperzero_mcp/firmware/installer.py tests/unit/test_firmware_installer.py
uv run ty check
git add src/flipperzero_mcp/firmware/installer.py tests/unit/test_firmware_installer.py
git commit -m "feat(firmware): add bundle installer orchestration"
```

---

## Phase 4 — Bundle acquisition

### Task 7: Local bundle extraction + `LocalBundle`

**Files:**
- Create: `src/flipperzero_mcp/firmware/bundles.py`
- Test: `tests/unit/test_firmware_bundles_local.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_firmware_bundles_local.py
"""Unit tests for local bundle extraction."""

import io
import tarfile

import pytest

from flipperzero_mcp.firmware.bundles import BundleError, load_local_bundle


def _make_tgz(tmp_path, files):
    path = tmp_path / "flipper-z-f7-update-test.tgz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_load_local_bundle_reads_files_and_target(tmp_path):
    tgz = _make_tgz(tmp_path, {"upd/update.fuf": b"manifest", "upd/firmware.dfu": b"DFU"})
    bundle = load_local_bundle(str(tgz))
    assert bundle.manifest_name == "update.fuf"
    assert bundle.target == "f7"
    names = {rel for rel, _ in bundle.files}
    assert names == {"update.fuf", "firmware.dfu"}


def test_load_local_bundle_rejects_missing_manifest(tmp_path):
    tgz = _make_tgz(tmp_path, {"upd/firmware.dfu": b"DFU"})
    with pytest.raises(BundleError, match="update.fuf"):
        load_local_bundle(str(tgz))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_firmware_bundles_local.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement local bundle loading**

```python
# src/flipperzero_mcp/firmware/bundles.py
"""Resolve firmware update bundles from local files or upstream downloads."""

from __future__ import annotations

import logging
import re
import tarfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MANIFEST = "update.fuf"
_TARGET_RE = re.compile(r"flipper-z-(f\w+)-update", re.IGNORECASE)


class BundleError(RuntimeError):
    """Raised when a bundle cannot be resolved or is malformed."""


@dataclass(frozen=True)
class LocalBundle:
    """An extracted update bundle ready to push to the device."""

    manifest_name: str
    target: str
    files: list[tuple[str, bytes]]


def _target_from_name(name: str) -> str:
    match = _TARGET_RE.search(name)
    if not match:
        raise BundleError(f"cannot determine hardware target from bundle name {name!r}")
    return match.group(1).lower()


def _extract_members(tgz_path: str) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    with tarfile.open(tgz_path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        if not members:
            raise BundleError("bundle archive is empty")
        # Strip the single top-level directory the bundle is wrapped in.
        prefix = members[0].name.split("/", 1)[0] + "/"
        for member in members:
            rel = member.name[len(prefix) :] if member.name.startswith(prefix) else member.name
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            files.append((rel, extracted.read()))
    return files


def load_local_bundle(tgz_path: str) -> LocalBundle:
    """Load and validate a local update ``.tgz`` bundle.

    Args:
        tgz_path: Host path to a ``flipper-z-<target>-update-*.tgz`` file.

    Returns:
        A LocalBundle with the manifest name, hardware target, and member files.

    Raises:
        BundleError: If the target is unknown, the archive is empty, or it has
            no ``update.fuf`` manifest.
    """
    target = _target_from_name(tgz_path)
    files = _extract_members(tgz_path)
    if not any(rel == _MANIFEST for rel, _ in files):
        raise BundleError(f"bundle has no {_MANIFEST} manifest")
    return LocalBundle(manifest_name=_MANIFEST, target=target, files=files)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_firmware_bundles_local.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_local.py
uv run ruff check src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_local.py
uv run ty check
git add src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_local.py
git commit -m "feat(firmware): load and validate local update bundles"
```

### Task 8: Verified auto-download (official + Momentum)

**Files:**
- Modify: `src/flipperzero_mcp/firmware/bundles.py` (add `download_bundle`)
- Modify: `pyproject.toml` (add `httpx` to deps if absent; add `pytest-httpx` to dev deps)
- Test: `tests/unit/test_firmware_bundles_download.py` (create)

Check first whether `httpx` is already a dependency (`rg httpx pyproject.toml`). FastMCP pulls it transitively, but add it explicitly if it is not a direct dep. Use `pytest-httpx` to stub responses (no VCR needed for synthetic bundles; cassettes are reserved for real recorded shapes in Phase 6 if desired).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_firmware_bundles_download.py
"""Unit tests for verified bundle downloads."""

import hashlib
import io
import json
import tarfile

import pytest

from flipperzero_mcp.firmware.bundles import BundleError, download_bundle
from flipperzero_mcp.firmware.flavor import FirmwareFlavor


def _tgz_bytes():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in {"upd/update.fuf": b"manifest", "upd/firmware.dfu": b"DFU"}.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_official_download_verifies_sha256(httpx_mock, tmp_path):
    tgz = _tgz_bytes()
    sha = hashlib.sha256(tgz).hexdigest()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/flipper-z-f7-update-1.4.3.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": sha,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(
        url="https://up.example/flipper-z-f7-update-1.4.3.tgz", content=tgz
    )
    bundle = await download_bundle(
        FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
    )
    assert bundle.target == "f7"


@pytest.mark.asyncio
async def test_official_download_aborts_on_sha256_mismatch(httpx_mock):
    tgz = _tgz_bytes()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/x.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(url="https://up.example/x.tgz", content=tgz)
    with pytest.raises(BundleError, match="sha256"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_firmware_bundles_download.py -v`
Expected: FAIL — `download_bundle` missing (and/or `pytest-httpx` not installed).

If `pytest-httpx` is missing: `uv add --dev pytest-httpx` then re-run.

- [ ] **Step 3: Implement the downloader**

Append to `bundles.py` (and add `import hashlib`, `import json`, `import os`, `import tempfile`, `import httpx`, and `from flipperzero_mcp.firmware.flavor import FirmwareFlavor` at the top):

```python
_OFFICIAL_DIRECTORY = "https://update.flipperzero.one/firmware/directory.json"
_MOMENTUM_RELEASES = "https://api.github.com/repos/Next-Flip/Momentum-Firmware/releases"


def _select_official_file(directory: dict, channel: str, version: str, target: str) -> dict:
    channels = {c["id"]: c for c in directory.get("channels", [])}
    if channel not in channels:
        raise BundleError(f"unknown official channel {channel!r}")
    versions = channels[channel].get("versions", [])
    if not versions:
        raise BundleError(f"no versions in official channel {channel!r}")
    picked = versions[0] if version == "latest" else next(
        (v for v in versions if v.get("version") == version), None
    )
    if picked is None:
        raise BundleError(f"official version {version!r} not found in {channel!r}")
    for entry in picked.get("files", []):
        if entry.get("target") == target and entry.get("type") == "update_tgz":
            return entry
    raise BundleError(f"no update_tgz for target {target} in official {channel}/{version}")


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    return response.content


def _verify_sha256(data: bytes, expected: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise BundleError(f"sha256 mismatch: expected {expected}, got {actual}")


def _bundle_from_tgz_bytes(data: bytes) -> LocalBundle:
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return load_local_bundle(tmp_path)
    finally:
        os.unlink(tmp_path)


async def _download_official(channel: str, version: str, target: str) -> LocalBundle:
    async with httpx.AsyncClient() as client:
        directory = json.loads(await _fetch(client, _OFFICIAL_DIRECTORY))
        entry = _select_official_file(directory, channel, version, target)
        data = await _fetch(client, entry["url"])
    _verify_sha256(data, entry["sha256"])
    return _bundle_from_tgz_bytes(data)


async def _download_momentum(version: str, target: str) -> LocalBundle:
    suffix = f"-update-" if version == "latest" else f"-update-{version}"
    async with httpx.AsyncClient() as client:
        releases = json.loads(await _fetch(client, _MOMENTUM_RELEASES))
        if not releases:
            raise BundleError("no Momentum releases found")
        release = releases[0] if version == "latest" else next(
            (r for r in releases if r.get("tag_name") == version), None
        )
        if release is None:
            raise BundleError(f"Momentum release {version!r} not found")
        asset = next(
            (
                a
                for a in release.get("assets", [])
                if a["name"].startswith(f"flipper-z-{target}") and a["name"].endswith("update-" + release["tag_name"] + ".tgz")
            ),
            None,
        )
        if asset is None:
            raise BundleError(f"no {target} update .tgz asset in Momentum {release['tag_name']}")
        data = await _fetch(client, asset["browser_download_url"])
    digest = asset.get("digest", "")
    if digest.startswith("sha256:"):
        _verify_sha256(data, digest.split(":", 1)[1])
    else:
        raise BundleError("Momentum asset is missing a sha256 digest")
    return _bundle_from_tgz_bytes(data)


async def download_bundle(
    flavor: FirmwareFlavor, *, channel: str, version: str, target: str
) -> LocalBundle:
    """Download and verify an update bundle for ``flavor``.

    Args:
        flavor: OFFICIAL or MOMENTUM (others are local-path only).
        channel: Official channel id (ignored for Momentum).
        version: ``latest`` or an exact version/tag.
        target: Hardware target such as ``f7``.

    Returns:
        A verified LocalBundle.

    Raises:
        BundleError: On unsupported flavor, missing file, or sha256 mismatch.
    """
    if flavor is FirmwareFlavor.OFFICIAL:
        return await _download_official(channel, version, target)
    if flavor is FirmwareFlavor.MOMENTUM:
        return await _download_momentum(version, target)
    raise BundleError(f"auto-download unsupported for {flavor.value}; supply a local .tgz path")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_firmware_bundles_download.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_download.py
uv run ruff check src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_download.py
uv run ty check
git add pyproject.toml uv.lock src/flipperzero_mcp/firmware/bundles.py tests/unit/test_firmware_bundles_download.py
git commit -m "feat(firmware): verified auto-download for official and Momentum bundles"
```

---

## Phase 5 — `flipperzero_firmware_install` tool + gating

### Task 9: `enable_firmware_flash` config flag + gate helper

**Files:**
- Modify: `src/flipperzero_mcp/config.py` (add field)
- Modify: `src/flipperzero_mcp/tools/_common.py` (add `require_firmware_flash`)
- Test: `tests/unit/test_config.py` (add a case), `tests/unit/test_common.py` (add a case)

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_config.py
def test_firmware_flash_disabled_by_default():
    assert FlipperConfig(_env_file=None).enable_firmware_flash is False


def test_firmware_flash_enabled_via_env(monkeypatch):
    monkeypatch.setenv("FLIPPER_ENABLE_FIRMWARE_FLASH", "true")
    assert FlipperConfig(_env_file=None).enable_firmware_flash is True
```

```python
# add to tests/unit/test_common.py  (mirror this file's existing ctx-building idiom)
import pytest
from fastmcp.exceptions import ToolError

from flipperzero_mcp.tools._common import require_firmware_flash


def test_require_firmware_flash_raises_when_disabled(make_ctx):
    # make_ctx is this module's existing helper that builds a Context with a
    # config; pass enable_firmware_flash=False.
    with pytest.raises(ToolError, match="FLIPPER_ENABLE_FIRMWARE_FLASH"):
        require_firmware_flash(make_ctx(enable_firmware_flash=False))
```

> If `test_common.py` has no `make_ctx` helper, build the Context the same way the existing `require_write_tools` test in that file does.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py::test_firmware_flash_disabled_by_default tests/unit/test_common.py -v`
Expected: FAIL — attribute / function missing.

- [ ] **Step 3: Implement the flag and gate**

In `config.py`, add after `enable_write_tools`:

```python
    enable_firmware_flash: bool = False
```

In `_common.py`, add:

```python
def require_firmware_flash(ctx: Context) -> None:
    """Gate the firmware-flash tool behind its dedicated opt-in.

    Args:
        ctx: FastMCP request context carrying the server config.

    Raises:
        ToolError: If write tools or firmware flashing are not both enabled.
    """
    require_write_tools(ctx)
    if not get_server_context(ctx).config.enable_firmware_flash:
        raise ToolError(
            "Firmware flashing is disabled. Set FLIPPER_ENABLE_FIRMWARE_FLASH=true "
            "(in addition to FLIPPER_ENABLE_WRITE_TOOLS) to allow flashing firmware."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py tests/unit/test_common.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/config.py src/flipperzero_mcp/tools/_common.py tests/unit/test_config.py tests/unit/test_common.py
uv run ruff check src/flipperzero_mcp/config.py src/flipperzero_mcp/tools/_common.py tests/unit/test_config.py tests/unit/test_common.py
uv run ty check
git add src/flipperzero_mcp/config.py src/flipperzero_mcp/tools/_common.py tests/unit/test_config.py tests/unit/test_common.py
git commit -m "feat(config): add enable_firmware_flash flag and gate helper"
```

### Task 10: `flipperzero_firmware_install` tool

**Files:**
- Create: `src/flipperzero_mcp/tools/firmware.py`
- Modify: `src/flipperzero_mcp/server.py` (register the new tool group — mirror how `register_systeminfo_tools` is wired)
- Test: `tests/unit/test_tool_firmware.py` (create)

The tool: resolve the bundle (local path or download), confirm the token matches the connected device name, run `install_bundle`, poll for reconnect, return before/after. Reconnect polling uses the client's reconnect path; the unit test injects a fake client/RPC so no real hardware is needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tool_firmware.py
"""Unit tests for the firmware_install tool gating and confirm token."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flipperzero_mcp.config import FlipperConfig
from flipperzero_mcp.server import create_server


@pytest.mark.asyncio
async def test_firmware_install_blocked_without_flag():
    # write tools on, firmware flash OFF
    server = create_server(FlipperConfig(_env_file=None, enable_write_tools=True))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="FLIPPER_ENABLE_FIRMWARE_FLASH"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"path": "/tmp/x.tgz"}, "confirm": "Lun10n"},
            )


@pytest.mark.asyncio
async def test_firmware_install_rejects_wrong_confirm_token():
    server = create_server(
        FlipperConfig(_env_file=None, enable_write_tools=True, enable_firmware_flash=True)
    )
    # Inject a fake client whose device name is Lun10n (mirror the injection
    # idiom used in tests/unit/test_tool_systeminfo.py).
    async with Client(server) as client:
        with pytest.raises(ToolError, match="confirm"):
            await client.call_tool(
                "flipperzero_firmware_install",
                {"source": {"path": "/tmp/x.tgz"}, "confirm": "WRONG"},
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tool_firmware.py -v`
Expected: FAIL — tool not registered.

- [ ] **Step 3: Implement the tool**

```python
# src/flipperzero_mcp/tools/firmware.py
"""Firmware-flash tool for the Flipper Zero (gated, destructive)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from flipperzero_mcp.errors import _classify_client_error
from flipperzero_mcp.firmware.bundles import BundleError, download_bundle, load_local_bundle
from flipperzero_mcp.firmware.flavor import FirmwareFlavor, classify
from flipperzero_mcp.firmware.installer import FlashError, install_bundle
from flipperzero_mcp.tools._common import ensure_connected, get_rpc, require_firmware_flash

_PKG_NAME = "mcp-update"
_RECONNECT_BUDGET_S = 300.0


async def _resolve(source: dict[str, Any], target: str) -> Any:
    if "path" in source:
        return load_local_bundle(source["path"])
    flavor = FirmwareFlavor(source["flavor"])
    return await download_bundle(
        flavor,
        channel=source.get("channel", "release"),
        version=source.get("version", "latest"),
        target=target,
    )


def register_firmware_tools(mcp: FastMCP) -> None:
    """Register the firmware-flash tool."""

    @mcp.tool(
        tags={"flipper", "firmware"},
        annotations=ToolAnnotations(
            readOnlyHint=False, idempotentHint=False, destructiveHint=True, openWorldHint=True
        ),
    )
    async def flipperzero_firmware_install(
        ctx: Context, source: dict[str, Any], confirm: str
    ) -> dict[str, Any]:
        """Flash firmware onto the connected Flipper Zero over USB.

        Args:
            ctx: FastMCP request context.
            source: Either ``{"path": "<local .tgz>"}`` or
                ``{"flavor": "official"|"momentum", "channel": ..., "version": ...}``.
            confirm: Must equal the connected device's name (a safety interlock).

        Returns:
            Dict with ``before`` and ``after`` firmware blocks and the bundle target.

        Raises:
            ToolError: If flashing is disabled, the confirm token is wrong, the
                bundle is invalid, or the device rejects the update.
        """
        require_firmware_flash(ctx)
        try:
            client = await ensure_connected(ctx)
            rpc = await get_rpc(ctx)
            before = classify(await client.get_device_info())
        except Exception as e:
            _classify_client_error(e)

        device_name = (await client.get_device_info()).get("hardware_name")
        if confirm != device_name:
            raise ToolError(
                f"confirm token {confirm!r} does not match connected device {device_name!r}"
            )

        try:
            bundle = await _resolve(source, before.target or "f7")
            await install_bundle(rpc, bundle, pkg_name=_PKG_NAME)
        except (BundleError, FlashError) as e:
            raise ToolError(str(e)) from e

        after = await _reconnect_and_classify(client)
        return {
            "before": {"flavor": before.flavor.value, "version": before.version},
            "after": {"flavor": after.flavor.value, "version": after.version},
            "target": bundle.target,
        }


async def _reconnect_and_classify(client: Any) -> Any:
    """Poll for the device to come back after the update reboot."""
    deadline = _RECONNECT_BUDGET_S
    waited = 0.0
    while waited < deadline:
        await asyncio.sleep(5.0)
        waited += 5.0
        await client.disconnect()
        if await client.connect():
            try:
                return classify(await client.get_device_info())
            except Exception:  # noqa: BLE001 - device still settling; keep polling
                continue
    raise ToolError(
        "device did not reconnect after the update; it may still be applying or "
        "may have dropped to DFU — recover with qFlipper if it does not return"
    )
```

Register in `server.py` alongside the other `register_*_tools` calls:

```python
from flipperzero_mcp.tools.firmware import register_firmware_tools
# ... within create_server, next to register_systeminfo_tools(mcp):
register_firmware_tools(mcp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tool_firmware.py -v`
Expected: PASS.

- [ ] **Step 5: Full unit suite, lint, type-check, commit**

```bash
uv run pytest -m "not integration" -q
uv run ruff format src/flipperzero_mcp/tools/firmware.py src/flipperzero_mcp/server.py tests/unit/test_tool_firmware.py
uv run ruff check src/flipperzero_mcp/tools/firmware.py src/flipperzero_mcp/server.py tests/unit/test_tool_firmware.py
uv run ty check
git add src/flipperzero_mcp/tools/firmware.py src/flipperzero_mcp/server.py tests/unit/test_tool_firmware.py
git commit -m "feat(tools): add gated flipperzero_firmware_install tool"
```

---

## Phase 6 — Real-hardware validation + dual golden fixtures

> These steps touch the physical test device (`Lun10n`) and are LOCAL ONLY. They are destructive (reflash). The connected device is a designated test unit.

### Task 11: Validate flash + chunk size on hardware

**Files:**
- Modify (if needed): `src/flipperzero_mcp/rpc/protobuf_rpc.py` (`_WRITE_CHUNK_SIZE` only, if 1024 proves unreliable)

- [ ] **Step 1: Confirm starting firmware**

Run (with the server env set for USB):
`uv run python -c "import asyncio; from flipperzero_mcp.rpc.client import FlipperClient; ..."`
— or use the MCP `flipperzero_system_info` tool via your client. Record the `firmware` block (expected `momentum` / `mntm-012`).

- [ ] **Step 2: Flash official `release` with both flags + confirm**

Set `FLIPPER_ENABLE_WRITE_TOOLS=true FLIPPER_ENABLE_FIRMWARE_FLASH=true`. Call `flipperzero_firmware_install` with `{"source": {"flavor": "official", "channel": "release", "version": "latest"}, "confirm": "Lun10n"}`. Watch the device screen for the updater. Expected: returns `after.flavor == "official"`.

- [ ] **Step 3: If large writes stall**, lower `_WRITE_CHUNK_SIZE` (try 512) and re-run Task 1's tests + retry. Commit only if changed:

```bash
git commit -am "fix(rpc): tune storage write chunk size for hardware reliability"
```

- [ ] **Step 4: Flash back to Momentum**

Call `flipperzero_firmware_install` with `{"source": {"flavor": "momentum", "version": "latest"}, "confirm": "Lun10n"}`. Expected: `after.flavor == "momentum"`. Leave the device on the firmware the fixtures need for Task 12 (flash official again if you want official to be the captured baseline, then re-capture).

### Task 12: Capture official golden fixtures + parametrize

**Files:**
- Create: `tests/golden/fixtures/official/` fixtures (mirror the existing Momentum fixture filenames under `tests/golden/fixtures/`)
- Modify: `tests/golden/test_golden_fixtures.py` (parametrize over `{momentum, official}`)
- Modify: `tests/golden/harness.py` / `tests/golden/record.py` if fixture path layout changes

- [ ] **Step 1: Read the current golden harness**

Run: `sed -n '1,80p' tests/golden/harness.py tests/golden/test_golden_fixtures.py`
Understand how fixtures are located and asserted.

- [ ] **Step 2: Move Momentum fixtures into a `momentum/` subdir**

Reorganize `tests/golden/fixtures/*.json` → `tests/golden/fixtures/momentum/*.json`; update the harness fixture root to iterate `momentum` and `official` subdirs. Keep filenames identical across both.

- [ ] **Step 3: Record official fixtures on hardware**

With the device on official firmware, run the existing recorder (e.g. `make refresh-cassettes` equivalent for golden, or `uv run python -m tests.golden.record`) targeting the `official/` subdir. Confirm `device_info` shows `firmware_origin_fork: Official`.

- [ ] **Step 4: Parametrize the golden test**

```python
# in tests/golden/test_golden_fixtures.py
@pytest.mark.parametrize("firmware", ["momentum", "official"])
def test_golden_fixture(firmware, fixture_name):
    # load from tests/golden/fixtures/<firmware>/<fixture_name>.json
    ...
```

- [ ] **Step 5: Run golden tests + commit**

```bash
uv run pytest tests/golden/ -v
git add tests/golden/
git commit -m "test(golden): add official firmware fixtures and parametrize over flavors"
```

### Task 13: Integration test — real flash round-trip

**Files:**
- Modify: `tests/integration/test_hardware.py` (add a flash round-trip test)

- [ ] **Step 1: Write the integration test**

```python
# add to tests/integration/test_hardware.py
@pytest.mark.integration
@pytest.mark.usb
@pytest.mark.asyncio
async def test_flash_roundtrip_official_then_momentum(firmware_flash_client):
    # firmware_flash_client: a fixture (add to tests/integration/conftest.py)
    # building a real USB client with both flags enabled.
    before = await firmware_flash_client.call_tool("flipperzero_system_info", {})
    name = before.data["device"]["hardware_name"]

    res1 = await firmware_flash_client.call_tool(
        "flipperzero_firmware_install",
        {"source": {"flavor": "official", "channel": "release", "version": "latest"},
         "confirm": name},
    )
    assert res1.data["after"]["flavor"] == "official"

    res2 = await firmware_flash_client.call_tool(
        "flipperzero_firmware_install",
        {"source": {"flavor": "momentum", "version": "latest"}, "confirm": name},
    )
    assert res2.data["after"]["flavor"] == "momentum"
```

- [ ] **Step 2: Run it locally (only with the device attached)**

Run: `uv run pytest -m "integration and usb" tests/integration/test_hardware.py::test_flash_roundtrip_official_then_momentum -v`
Expected: PASS (takes several minutes per flash).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_hardware.py tests/integration/conftest.py
git commit -m "test(integration): real firmware flash round-trip"
```

---

## Phase 7 — Prompts + docs

### Task 14: Update `/flipper-install` and `/flipper-doctor` prompts

**Files:**
- Modify: `src/flipperzero_mcp/prompts.py` (the install SDK-selection step ~lines 82-87; the doctor preflight ~lines 60-61)
- Test: `tests/unit/test_prompts.py` (assert new wording)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_prompts.py
def test_install_prompt_branches_on_firmware_flavor():
    text = _render_install_prompt()  # use this module's existing render helper
    assert "flipperzero_system_info" in text
    assert "firmware.flavor" in text or "firmware flavor" in text
    assert "ufbt update --channel" in text
    assert "Momentum" in text


def test_doctor_prompt_reports_flavor():
    text = _render_doctor_prompt()
    assert "flavor" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompts.py -k "flavor" -v`
Expected: FAIL.

- [ ] **Step 3: Update the prompt text**

In the `/flipper-install` SDK step, replace the generic "Pick the ufbt SDK matching the device firmware channel/version" with flavor-aware guidance:

```
"3. Read firmware.flavor from `flipperzero_system_info`. "
"For official firmware, run `ufbt update --channel=<release|rc|dev>` matching the "
"device version. For Momentum, point ufbt at the Momentum SDK index per its docs. "
"If firmware.flavor is unknown/unsupported or the repo targets a different "
"channel, STOP and report — never produce an incompatible `.fap`.\n"
```

In `/flipper-doctor`, extend the device step to surface `firmware.flavor` alongside channel/version.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/flipperzero_mcp/prompts.py tests/unit/test_prompts.py
uv run ruff check src/flipperzero_mcp/prompts.py tests/unit/test_prompts.py
uv run ty check
git add src/flipperzero_mcp/prompts.py tests/unit/test_prompts.py
git commit -m "feat(prompts): make install/doctor firmware-flavor aware"
```

### Task 15: README, CLAUDE.md, CLI reference

**Files:**
- Modify: `README.md` (Firmware section ~line 150; Tools table; env-flag list)
- Modify: `CLAUDE.md` (project specifics)
- Modify: `src/flipperzero_mcp/resources/reference_cli.md` (note Momentum-only commands)

- [ ] **Step 1: Update the README Firmware section**

Replace the Momentum-only baseline with: both Official (`release`/`release-candidate`/`development`, tested on `1.4.x`) and Momentum (`mntm-012`) are supported; document `flipperzero_firmware_install`, the two env flags (`FLIPPER_ENABLE_WRITE_TOOLS` + `FLIPPER_ENABLE_FIRMWARE_FLASH`), the verification posture (per-file sha256 for official, GitHub asset digest for Momentum — integrity, not signed provenance), USB-only flashing, and **DFU + qFlipper recovery** if a flash fails. Add `flipperzero_firmware_install` to the Tools table with its destructive/gated note.

- [ ] **Step 2: Update CLAUDE.md**

Add a bullet under "Project specifics": the `firmware/` module (classifier + bundles + installer), the `FLIPPER_ENABLE_FIRMWARE_FLASH` gate, dual golden fixtures (`tests/golden/fixtures/{momentum,official}/`), and the chunked-write requirement for large pushes.

- [ ] **Step 3: Update the CLI reference**

In `reference_cli.md`, add a short note that the command list was captured on Momentum and that a few commands (e.g. Momentum management/extra apps) are Momentum-only; official firmware exposes the OFW subset.

- [ ] **Step 4: Self-audit + commit**

```bash
cd ~/Desktop/Projects/consistency-check && uv run consistency-check audit --repo flipperzero-mcp; cd -
git add README.md CLAUDE.md src/flipperzero_mcp/resources/reference_cli.md
git commit -m "docs: document multi-firmware support, flash tool, and recovery"
```

### Task 16: Final verification

- [ ] **Step 1: Full non-integration suite + lint + types**

Run:
```bash
uv run pytest -m "not integration" -q
uv run ruff check .
uv run ty check
```
Expected: all pass, zero warnings.

- [ ] **Step 2: Open the PR**

```bash
git push -u origin multi-firmware-support
gh pr create --base phase1 --title "Multi-firmware support + firmware-flash tooling" \
  --body "Implements docs/superpowers/specs/2026-06-09-multi-firmware-support-design.md"
```

---

## Self-review notes

- **Spec coverage:** chunked write (Task 1) ✔; classifier + system_info (Tasks 2-3) ✔; update/reboot RPCs + code map (Tasks 4-5) ✔; installer (Task 6) ✔; local + verified-download bundles (Tasks 7-8) ✔; flag + gate (Task 9) ✔; tool with confirm token (Task 10) ✔; hardware validation + dual fixtures + integration (Tasks 11-13) ✔; prompts (Task 14) ✔; README/CLAUDE/CLI docs incl. DFU recovery + supply-chain posture (Task 15) ✔.
- **Type consistency:** `LocalBundle{manifest_name, target, files}`, `FirmwareInfo{flavor, version, origin_fork, origin_git, target}`, `install_bundle(rpc, bundle, *, pkg_name)`, `download_bundle(flavor, *, channel, version, target)`, `system_update -> int`, `system_reboot_update() -> None` are used consistently across tasks.
- **Hardware/idiom caveats:** Tasks 3, 9-10, 12-14 say "mirror the existing idiom in <file>" where the exact fake/ctx/render helper is established by that file — read it before writing, rather than inventing a parallel pattern.
