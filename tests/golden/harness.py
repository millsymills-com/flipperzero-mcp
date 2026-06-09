"""Capture/replay transports and the golden-fixture file format.

A fixture is a JSON file holding the ordered list of wire events (host->device
``tx`` and device->host ``rx``) that a real Flipper produced for one behavior,
plus the high-level ``expect`` result the behavior must still yield on replay.

The replay is *event-cursor* based: ``receive()`` only serves the next ``rx``
event once every ``tx`` event recorded before it has been sent. This gates
device output behind the matching request, so the time-based drain/read loops in
the RPC and CLI code reproduce the recorded exchange faithfully without hardware
and without depending on wall-clock timing.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from flipperzero_mcp.transport.base import FlipperTransport

SCHEMA_VERSION = 1

FIXTURES_DIR = Path(__file__).parent / "fixtures"

Direction = Literal["tx", "rx"]


@dataclass
class Event:
    """One wire event: a host->device send (``tx``) or device->host read (``rx``)."""

    dir: Direction
    data: bytes

    def to_json(self) -> dict[str, str]:
        return {"dir": self.dir, "b64": base64.b64encode(self.data).decode("ascii")}

    @classmethod
    def from_json(cls, obj: dict[str, str]) -> Event:
        direction = obj["dir"]
        if direction not in ("tx", "rx"):
            raise ValueError(f"invalid event direction: {direction!r}")
        return cls(dir=direction, data=base64.b64decode(obj["b64"]))


@dataclass
class Fixture:
    """A recorded behavior: wire events plus the expected high-level result."""

    name: str
    description: str
    meta: dict[str, Any]
    events: list[Event]
    expect: dict[str, Any]
    session_pre_started: bool = False
    schema_version: int = SCHEMA_VERSION

    @property
    def supports_cli_text_mode(self) -> bool:
        return bool(self.meta.get("supports_cli_text_mode", True))

    @property
    def transport_name(self) -> str:
        return "WiFi" if self.meta.get("transport") == "wifi" else "USB"

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "meta": self.meta,
            "session_pre_started": self.session_pre_started,
            "events": [e.to_json() for e in self.events],
            "expect": self.expect,
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> Fixture:
        version = obj.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"fixture {obj.get('name')!r} schema_version {version} != {SCHEMA_VERSION}; "
                "re-record with `make record-fixtures`"
            )
        for key in ("name", "description", "meta", "events", "expect"):
            if key not in obj:
                raise ValueError(f"fixture missing required key {key!r}")
        return cls(
            name=obj["name"],
            description=obj["description"],
            meta=obj["meta"],
            events=[Event.from_json(e) for e in obj["events"]],
            expect=obj["expect"],
            session_pre_started=bool(obj.get("session_pre_started", False)),
            schema_version=version,
        )

    def save(self, directory: Path = FIXTURES_DIR) -> Path:
        path = directory / f"{self.name}.json"
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, name: str, directory: Path = FIXTURES_DIR) -> Fixture:
        path = directory / f"{name}.json"
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


def load_all(directory: Path = FIXTURES_DIR) -> list[Fixture]:
    """Load every ``*.json`` fixture in the directory, sorted by name."""
    return [
        Fixture.from_json(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(directory.glob("*.json"))
    ]


class ReplayTransport(FlipperTransport):
    """Serve a recorded event list back to the real client/RPC code, offline.

    ``receive()`` returns the next ``rx`` event only when the cursor is not
    parked on an un-sent ``tx`` event; otherwise it returns ``b""`` (modeling an
    idle link), so the code's drain/read loops behave exactly as during capture.
    Sent bytes are recorded in :attr:`sent` for assertions; their payload is not
    matched against the recording, so a replay may legitimately send different
    request bytes (e.g. a different local file in a push integrity test).
    """

    def __init__(self, fixture: Fixture) -> None:
        super().__init__({})
        self._fixture = fixture
        self._events = fixture.events
        self._cursor = 0
        self.connected = True
        self.sent: list[bytes] = []

    @property
    def supports_cli_text_mode(self) -> bool:
        return self._fixture.supports_cli_text_mode

    def get_name(self) -> str:
        return self._fixture.transport_name

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        if self._cursor < len(self._events) and self._events[self._cursor].dir == "tx":
            self._cursor += 1

    async def receive(self, timeout: float | None = None) -> bytes:  # noqa: ARG002
        if self._cursor < len(self._events) and self._events[self._cursor].dir == "rx":
            data = self._events[self._cursor].data
            self._cursor += 1
            return data
        return b""

    async def is_connected(self) -> bool:
        return self.connected


class RecordingTransport(FlipperTransport):
    """Wrap a real transport and log every wire event for later replay.

    Used only by the integration-marked recorder against a physical Flipper.
    Delegates connect/disconnect/identity to the wrapped transport; every
    ``send`` and every non-empty ``receive`` chunk is appended to :attr:`events`
    exactly as it crossed the wire.
    """

    def __init__(self, inner: FlipperTransport) -> None:
        super().__init__(dict(inner.config))
        self._inner = inner
        self.events: list[Event] = []

    @property
    def supports_cli_text_mode(self) -> bool:
        return self._inner.supports_cli_text_mode

    def get_name(self) -> str:
        return self._inner.get_name()

    def clear(self) -> None:
        """Drop recorded events (e.g. to discard session-negotiation noise)."""
        self.events.clear()

    async def connect(self) -> bool:
        return await self._inner.connect()

    async def disconnect(self) -> None:
        await self._inner.disconnect()

    async def send(self, data: bytes) -> None:
        self.events.append(Event(dir="tx", data=bytes(data)))
        await self._inner.send(data)

    async def receive(self, timeout: float | None = None) -> bytes:
        chunk = await self._inner.receive(timeout=timeout)
        if chunk:
            self.events.append(Event(dir="rx", data=bytes(chunk)))
        return chunk

    async def is_connected(self) -> bool:
        return await self._inner.is_connected()

    def to_fixture(
        self,
        name: str,
        description: str,
        meta: dict[str, Any],
        expect: dict[str, Any],
        *,
        session_pre_started: bool = False,
    ) -> Fixture:
        return Fixture(
            name=name,
            description=description,
            meta={"supports_cli_text_mode": self.supports_cli_text_mode, **meta},
            events=list(self.events),
            expect=expect,
            session_pre_started=session_pre_started,
        )


__all__ = [
    "FIXTURES_DIR",
    "SCHEMA_VERSION",
    "Event",
    "Fixture",
    "RecordingTransport",
    "ReplayTransport",
    "load_all",
]
