"""Flipper Zero Protobuf RPC implementation.

This module implements the Flipper Zero RPC protocol using Protocol Buffers
based on the official protobuf schemas from:
https://github.com/flipperdevices/flipperzero-protobuf

Uses generated protobuf code from proto/ directory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flipperzero_mcp.transport.base import FlipperTransport

logger = logging.getLogger(__name__)

# When CLI->RPC negotiation fails, skip re-running the multi-second probe/switch
# sequence on every subsequent RPC for this long. Bounds both log spam and per-call
# latency while a Flipper sits in CLI mode, yet stays short enough that recovery
# (e.g. the device entering RPC mode) is picked up promptly.
_NEGOTIATION_COOLDOWN_SECONDS = 5.0

# Import generated protobuf classes
try:
    from flipperzero_mcp.rpc.protobuf_gen import (
        application_pb2,
        flipper_pb2,
        property_pb2,
        storage_pb2,
        system_pb2,
    )

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False
    if TYPE_CHECKING:
        # For type checking only
        from flipperzero_mcp.rpc.protobuf_gen import (
            application_pb2,
            flipper_pb2,
            property_pb2,
            storage_pb2,
            system_pb2,
        )
    else:
        flipper_pb2 = None
        system_pb2 = None
        property_pb2 = None
        storage_pb2 = None
        application_pb2 = None


class ProtobufRPC:
    """
    Flipper Zero Protobuf RPC client.

    Implements the RPC protocol using protobuf messages as defined in
    the flipperzero-protobuf repository.
    """

    def __init__(self, transport: FlipperTransport, *, io_lock: asyncio.Lock | None = None):
        """Initialize Protobuf RPC client.

        Args:
            transport: Transport layer for communication.
            io_lock: Shared client-level I/O lock that serializes every CLI and
                RPC round-trip on the link. When omitted a fresh per-instance
                lock is created so direct callers still get safe serialization.
        """
        if not PROTOBUF_AVAILABLE:
            raise ImportError(
                "Protobuf generated code not available. "
                "Run 'protoc' to generate Python code from .proto files."
            )

        self.transport = transport
        self.command_id = 0
        self._rpc_session_started = False
        self._last_negotiation_failure: float | None = None
        self._io_lock = io_lock if io_lock is not None else asyncio.Lock()

    def _get_next_command_id(self) -> int:
        """Get next command ID for RPC calls."""
        self.command_id = (self.command_id + 1) % 0xFFFFFFFF
        return self.command_id

    @staticmethod
    def _encode_varint(n: int) -> bytes:
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
        return bytes(out)

    async def _read_varint(self, timeout: float = 2.5) -> int | None:
        """
        Read a protobuf varint from the transport.

        Flipper firmware uses nanopb's PB_ENCODE_DELIMITED / PB_DECODE_DELIMITED,
        meaning each message is encoded as: [varint length][protobuf bytes].
        """
        try:
            value = 0
            shift = 0
            # Varint for message sizes should be small; cap at 5 bytes (32-bit).
            for _ in range(5):
                b = await self.transport.receive_exact(1, timeout=timeout)
                if not b:
                    return None
                byte = b[0]
                value |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    return value
                shift += 7
            return None
        except Exception:
            logger.debug("_read_varint failed", exc_info=True)
            return None

    async def _receive_main_message(self, timeout: float = 2.5) -> Any | None:
        """Receive one nanopb-delimited Main message: [varint length][payload].

        Returns a flipper_pb2.Main on success, or None on timeout/decode failure.
        """
        try:
            payload_len = await self._read_varint(timeout=timeout)
            if payload_len is None or payload_len <= 0 or payload_len > 1_000_000:
                return None

            payload = await self.transport.receive_exact(payload_len, timeout=timeout)
            if not payload or len(payload) != payload_len:
                return None

            logger.debug("[protobuf] rx delimited len=%d", payload_len)

            msg = flipper_pb2.Main()
            msg.ParseFromString(payload)
            return msg
        except Exception:
            logger.debug("_receive_main_message failed", exc_info=True)
            return None

    async def _drain_host_rx(self, max_seconds: float = 0.6) -> None:
        """Drain pending device->host bytes until idle for the given budget.

        Unlocked helper: callers must already hold the shared I/O lock. Used to
        clear CLI banner/prompt/echo so it is not misread as RPC framing.
        """
        try:
            end = time.monotonic() + max_seconds
            while time.monotonic() < end:
                chunk = await self.transport.receive(timeout=0.05)
                if not chunk:
                    await asyncio.sleep(0.01)
                    continue
        except Exception:
            logger.debug("_drain_host_rx failed", exc_info=True)

    async def send_stop_session(self) -> None:
        """Send a nanopb-delimited StopSession frame to leave RPC mode.

        Unlocked helper: callers must already hold the shared I/O lock. Drives
        the device from RPC back into CLI mode and drains residual output.
        """
        main_request = flipper_pb2.Main()
        main_request.stop_session.CopyFrom(flipper_pb2.StopSession())
        payload = main_request.SerializeToString()
        await self.transport.send(self._encode_varint(len(payload)) + payload)
        await self._drain_host_rx(max_seconds=0.4)
        self._rpc_session_started = False

    async def _ensure_rpc_session_started(self) -> None:
        """
        Ensure the device is in RPC session mode.

        On firmware 1.4.3, the USB CDC port starts in CLI mode. The CLI command
        `start_rpc_session` switches the same port into nanopb-delimited RPC mode.

        Important detail: send the command terminated by CR-only ('\\r'), not CRLF,
        otherwise the trailing '\\n' can be consumed as the first byte of the first
        delimited message length and cause an immediate ERROR_DECODE + session close.
        """
        if self._rpc_session_started:
            return

        if (
            self._last_negotiation_failure is not None
            and time.monotonic() - self._last_negotiation_failure < _NEGOTIATION_COOLDOWN_SECONDS
        ):
            return

        async def drain_host_rx(max_seconds: float = 0.6) -> None:
            """
            Drain any pending device->host bytes (CLI banner/prompt/echo).

            If we don't drain this before the first RPC call, we may misinterpret
            CLI output bytes as the first RPC response varint length prefix.
            """
            try:
                end = time.monotonic() + max_seconds
                while time.monotonic() < end:
                    chunk = await self.transport.receive(timeout=0.05)
                    if not chunk:
                        # Keep draining until the deadline to avoid stopping in the middle
                        # of a multi-chunk CLI banner/echo.
                        await asyncio.sleep(0.01)
                        continue
            except Exception:
                logger.debug("drain_host_rx failed", exc_info=True)

        # Best-effort: clear any buffered host-side bytes.
        try:
            self.transport.clear_receive_buffer()
        except Exception:
            logger.debug("clear_receive_buffer failed", exc_info=True)

        # Give the device a moment to finish emitting the CLI banner/prompt after opening the port.
        await asyncio.sleep(0.3)

        async def probe_rpc(timeout: float = 0.4) -> bool:
            """
            Best-effort probe: send a protobuf ping request and see if we get a valid
            nanopb-delimited PB.Main ping response back.

            This is safer than trying to infer mode from idle output, because the CLI can
            be silent until the first keystroke.
            """
            try:
                # Clear any pending bytes so we only look at the probe response.
                try:
                    self.transport.clear_receive_buffer()
                except Exception:
                    logger.debug("clear_receive_buffer failed", exc_info=True)
                await drain_host_rx(max_seconds=0.2)

                probe = flipper_pb2.Main()
                probe.command_id = 1
                probe.has_next = False
                probe.system_ping_request.CopyFrom(system_pb2.PingRequest(data=b"mcp"))
                payload = probe.SerializeToString()
                await self.transport.send(self._encode_varint(len(payload)) + payload)

                # Robustly read one nanopb-delimited message.
                msg = await self._receive_main_message(timeout=timeout)
                return (
                    bool(msg)
                    and msg.HasField("system_ping_response")
                    and msg.system_ping_response.data == b"mcp"
                )
            except Exception:
                # If we probed while in CLI mode, the device may have emitted text output;
                # drain it so it doesn't interfere with subsequent session negotiation.
                logger.debug("probe_rpc failed", exc_info=True)
                await drain_host_rx(max_seconds=0.5)
                return False

        force_start = os.environ.get("FLIPPER_FORCE_START_RPC_SESSION", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # WiFi Dev Board transport already speaks nanopb-delimited protobuf over TCP (no CLI mode).
        # Attempting to send `start_rpc_session` bytes would corrupt the session.
        try:
            transport_name = ""
            if hasattr(self.transport, "get_name"):
                transport_name = str(self.transport.get_name() or "")
            is_wifi_transport = "wifi" in transport_name.lower() or hasattr(self.transport, "host")
        except Exception:
            logger.debug("transport name detection failed", exc_info=True)
            is_wifi_transport = False

        # For WiFi transport, there is no CLI->RPC mode switch. Treat the session as started
        # and avoid sending any probe pings here (those can race with the caller's real ping
        # and cause false negatives in health checks).
        if is_wifi_transport:
            self._rpc_session_started = True
            return

        if not force_start:
            # WiFi can have slightly higher latency; probe longer before deciding it's not RPC.
            probe_timeout = 1.2 if is_wifi_transport else 0.4
            if await probe_rpc(timeout=probe_timeout):
                self._rpc_session_started = True
                return

            # On WiFi transport, do NOT attempt CLI session switching.
            if is_wifi_transport:
                self._rpc_session_started = False
                return

        # Switch to RPC mode via CLI command (CR-only) and verify by probing.
        # Important: do NOT assume the mode switch succeeded; if it didn't, subsequent
        # protobuf reads will interpret CLI output as varint framing and fail hard.
        async def start_session_attempt() -> bool:
            try:
                # Cancel any partially typed CLI input that could prevent the command
                # from being recognized (the CLI may remain open across host reconnects).
                await self.transport.send(b"\x03\r")
                await self.transport.send(b"start_rpc_session\r")
            except Exception:
                logger.debug("start_rpc_session send failed", exc_info=True)

            await drain_host_rx(max_seconds=0.4)
            try:
                self.transport.clear_receive_buffer()
            except Exception:
                logger.debug("clear_receive_buffer failed", exc_info=True)
            # Give the device a moment to switch modes before probing.
            await asyncio.sleep(0.2)

            return await probe_rpc(timeout=1.2)

        # One or two attempts is usually enough; keep it bounded to avoid long hangs.
        ok = await start_session_attempt()
        if not ok:
            ok = await start_session_attempt()
        if not ok:
            ok = await start_session_attempt()

        self._rpc_session_started = bool(ok)
        if not ok:
            self._last_negotiation_failure = time.monotonic()
            logger.warning(
                "start_rpc_session negotiation failed after 3 attempts; is the Flipper in "
                "CLI mode? Later RPC calls retry negotiation at most once every %.0fs.",
                _NEGOTIATION_COOLDOWN_SECONDS,
            )

    async def _send_rpc_message(
        self,
        main_message: Any,  # flipper_pb2.Main
    ) -> Any | None:  # Optional[flipper_pb2.Main]
        """
        Send a protobuf RPC message and receive response.

        Flipper Zero RPC protocol:
        1. Send: [4 bytes: message_length][protobuf Main message]
        2. Receive: [4 bytes: response_length][protobuf Main message]

        Args:
            main_message: Main protobuf message to send

        Returns:
            Main response message or None
        """
        try:
            await self._ensure_rpc_session_started()

            # Serialize Main message
            message_data = main_message.SerializeToString()

            # Nanopb-delimited framing: [varint length][payload]
            message = self._encode_varint(len(message_data)) + message_data

            # Send message
            await self.transport.send(message)

            # Receive one response Main message
            return await self._receive_main_message(timeout=2.5)

        except Exception:
            logger.debug("_send_rpc_message failed", exc_info=True)
            return None

    async def ping(self, data: bytes = b"ping") -> bytes | None:
        """
        Send a protobuf ping request.

        Returns the echoed bytes (if any) or None on failure.
        """
        async with self._io_lock:
            try:
                main_request = flipper_pb2.Main()
                main_request.command_id = self._get_next_command_id()
                main_request.has_next = False
                ping_req = system_pb2.PingRequest()
                ping_req.data = data
                main_request.system_ping_request.CopyFrom(ping_req)

                resp = await self._send_rpc_message(main_request)
                if (
                    resp
                    and resp.command_status == flipper_pb2.CommandStatus.OK
                    and resp.HasField("system_ping_response")
                ):
                    return resp.system_ping_response.data
            except Exception:
                logger.debug("ping failed", exc_info=True)
            return None

    async def system_protobuf_version(self) -> dict[str, int] | None:
        """Return the firmware protobuf RPC version."""
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._system_protobuf_version_internal(), timeout=3.0)
            except Exception:
                logger.debug("system_protobuf_version timed out or failed", exc_info=True)
                return None

    async def _system_protobuf_version_internal(self) -> dict[str, int] | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False
            main_request.system_protobuf_version_request.CopyFrom(
                system_pb2.ProtobufVersionRequest()
            )

            resp = await self._send_rpc_message(main_request)
            if (
                resp
                and resp.command_status == flipper_pb2.CommandStatus.OK
                and resp.HasField("system_protobuf_version_response")
            ):
                version = resp.system_protobuf_version_response
                return {"major": int(version.major), "minor": int(version.minor)}
        except Exception:
            logger.debug("_system_protobuf_version_internal failed", exc_info=True)
        return None

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

    async def system_datetime(self) -> dict[str, int] | None:
        """Return the device date/time fields reported by firmware."""
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._system_datetime_internal(), timeout=3.0)
            except Exception:
                logger.debug("system_datetime timed out or failed", exc_info=True)
                return None

    async def _system_datetime_internal(self) -> dict[str, int] | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False
            main_request.system_get_datetime_request.CopyFrom(system_pb2.GetDateTimeRequest())

            resp = await self._send_rpc_message(main_request)
            if (
                resp
                and resp.command_status == flipper_pb2.CommandStatus.OK
                and resp.HasField("system_get_datetime_response")
            ):
                dt = resp.system_get_datetime_response.datetime
                return {
                    "year": int(dt.year),
                    "month": int(dt.month),
                    "day": int(dt.day),
                    "hour": int(dt.hour),
                    "minute": int(dt.minute),
                    "second": int(dt.second),
                    "weekday": int(dt.weekday),
                }
        except Exception:
            logger.debug("_system_datetime_internal failed", exc_info=True)
        return None

    async def system_power_info(self) -> dict[str, str] | None:
        """Return power/battery key-value pairs, or None if the RPC read failed."""
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._system_power_info_internal(), timeout=6.0)
            except Exception:
                logger.debug("system_power_info timed out or failed", exc_info=True)
                return None

    async def _system_power_info_internal(self) -> dict[str, str] | None:
        info: dict[str, str] = {}
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False
            main_request.system_power_info_request.CopyFrom(system_pb2.PowerInfoRequest())

            main_response = await self._send_rpc_message(main_request)
            if not main_response or main_response.command_status != flipper_pb2.CommandStatus.OK:
                return None

            def collect(resp: Any) -> None:
                if resp.HasField("system_power_info_response"):
                    power = resp.system_power_info_response
                    if power.key and power.value:
                        info[power.key] = power.value

            collect(main_response)
            max_iterations = 100
            iteration = 0
            while main_response.has_next and iteration < max_iterations:
                iteration += 1
                next_response = await self._receive_main_message(timeout=2.5)
                if not next_response:
                    break
                main_response = next_response
                if main_response.command_status != flipper_pb2.CommandStatus.OK:
                    break
                collect(main_response)
        except Exception:
            logger.debug("_system_power_info_internal failed", exc_info=True)
            return None
        return info

    async def app_start(self, name: str, args: str = "") -> bool:
        """
        Start an application via protobuf RPC (PB_App.StartRequest).

        Note: On some firmwares, starting certain apps (e.g. BadUSB) may change USB mode
        and disrupt the current transport (especially USB CDC). Callers should be prepared
        for the connection to drop even if the start succeeded.
        """
        async with self._io_lock:
            try:
                main_request = flipper_pb2.Main()
                main_request.command_id = self._get_next_command_id()
                main_request.has_next = False

                req = application_pb2.StartRequest()
                req.name = name
                req.args = args or ""
                main_request.app_start_request.CopyFrom(req)

                resp = await self._send_rpc_message(main_request)
                return bool(resp and resp.command_status == flipper_pb2.CommandStatus.OK)
            except Exception:
                logger.debug("app_start failed", exc_info=True)
                return False

    async def get_device_info(self) -> dict[str, Any]:
        """
        Get device information using system.get_device_info RPC.

        DeviceInfo returns multiple key-value pairs, so we need to
        collect all responses until has_next is false.

        Returns:
            Dictionary of device information key-value pairs
        """
        info = {}

        # Add overall timeout to prevent hanging
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._get_device_info_internal(), timeout=6.0)
            except (TimeoutError, Exception):
                logger.debug("get_device_info timed out or failed", exc_info=True)
                return info

    async def _get_device_info_internal(self) -> dict[str, Any]:  # noqa: PLR0912
        """Internal implementation of get_device_info.

        Branch count exceeds the lint threshold because the streamed has_next
        collection loop and the property.get fallback are part of one protocol
        exchange; splitting them would obscure the wire sequence.
        """
        info = {}

        try:
            # Build Main message with DeviceInfoRequest
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False
            main_request.system_device_info_request.CopyFrom(system_pb2.DeviceInfoRequest())

            # Send request and get response
            main_response = await self._send_rpc_message(main_request)

            if main_response and main_response.command_status == flipper_pb2.CommandStatus.OK:
                # Check if we have a DeviceInfoResponse
                if main_response.HasField("system_device_info_response"):
                    device_info = main_response.system_device_info_response
                    if device_info.key and device_info.value:
                        info[device_info.key] = device_info.value

                # Handle has_next flag - collect all key-value pairs
                # Note: DeviceInfo can return multiple responses
                # Limit to prevent infinite loops
                max_iterations = 100
                iteration = 0
                while main_response.has_next and iteration < max_iterations:
                    iteration += 1
                    try:
                        next_response = await self._receive_main_message(timeout=2.5)
                        if not next_response:
                            break
                        main_response = next_response

                        if main_response.HasField("system_device_info_response"):
                            device_info = main_response.system_device_info_response
                            if device_info.key and device_info.value:
                                info[device_info.key] = device_info.value

                        if main_response.command_status != flipper_pb2.CommandStatus.OK:
                            break
                    except Exception:
                        # Timeout or error reading next response - stop collecting
                        logger.debug("get_device_info: reading next frame failed", exc_info=True)
                        break

        except Exception:
            logger.debug("_get_device_info_internal failed", exc_info=True)

        # If we didn't get info from DeviceInfo, try property.get for common keys
        if not info:
            property_keys = [
                "firmware_version",
                "hardware_model",
                "hardware_version",
                "serial_number",
                "firmware_build_date",
                "firmware_git_hash",
            ]

            for key in property_keys:
                try:
                    value = await self._get_property_internal(key)
                    if value:
                        info[key] = value
                except Exception:
                    logger.debug("get_device_info: property.get(%s) failed", key, exc_info=True)

        return info

    async def get_property(self, key: str) -> str | None:
        """
        Get a property value using property.get RPC.

        Args:
            key: Property key

        Returns:
            Property value or None
        """
        # Add overall timeout to prevent hanging
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._get_property_internal(key), timeout=2.0)
            except (TimeoutError, Exception):
                logger.debug("get_property(%s) timed out or failed", key, exc_info=True)
                return None

    async def _get_property_internal(self, key: str) -> str | None:
        """Internal implementation of get_property."""
        try:
            # Build Main message with Property.GetRequest
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            # Set property_get_request
            get_request = property_pb2.GetRequest()
            get_request.key = key
            main_request.property_get_request.CopyFrom(get_request)

            # Send request and get response
            main_response = await self._send_rpc_message(main_request)

            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("property_get_response")
            ):
                return main_response.property_get_response.value

        except Exception:
            logger.debug("_get_property_internal failed", exc_info=True)

        return None

    async def storage_list(
        self, path: str, include_md5: bool = False, filter_max_size: int = 0
    ) -> list[str]:
        """
        List entries in a directory via protobuf storage_list_request.

        Returns a list of names (files/dirs). If the device streams results using has_next,
        we collect all frames.
        """
        names: list[str] = []
        async with self._io_lock:
            try:
                return await asyncio.wait_for(
                    self._storage_list_internal(
                        path, include_md5=include_md5, filter_max_size=filter_max_size
                    ),
                    timeout=3.0,
                )
            except Exception:
                logger.debug("storage_list(%s) timed out or failed", path, exc_info=True)
                return names

    async def storage_list_detailed(
        self, path: str, include_md5: bool = False, filter_max_size: int = 0
    ) -> list[dict[str, Any]]:
        """
        List entries in a directory via protobuf storage_list_request (detailed).

        Returns a list of dicts with:
        - name: entry name
        - type: "FILE" | "DIR"
        - size: uint32 size (0 for dirs on most firmwares)
        - md5sum: optional md5 (only when include_md5=True and device provides it)
        """
        entries: list[dict[str, Any]] = []
        async with self._io_lock:
            try:
                return await asyncio.wait_for(
                    self._storage_list_detailed_internal(
                        path, include_md5=include_md5, filter_max_size=filter_max_size
                    ),
                    timeout=3.0,
                )
            except Exception:
                logger.debug("storage_list_detailed(%s) timed out or failed", path, exc_info=True)
                return entries

    async def _storage_list_internal(
        self, path: str, include_md5: bool = False, filter_max_size: int = 0
    ) -> list[str]:
        names: list[str] = []
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.ListRequest()
            req.path = path
            req.include_md5 = include_md5
            if filter_max_size:
                req.filter_max_size = int(filter_max_size)
            main_request.storage_list_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if not main_response or main_response.command_status != flipper_pb2.CommandStatus.OK:
                return names

            def collect(resp: Any) -> None:
                if resp.HasField("storage_list_response"):
                    names.extend(f.name for f in resp.storage_list_response.file if f.name)

            collect(main_response)

            max_iterations = 100
            iteration = 0
            while main_response.has_next and iteration < max_iterations:
                iteration += 1
                next_response = await self._receive_main_message(timeout=2.5)
                if not next_response:
                    break
                main_response = next_response
                if main_response.command_status != flipper_pb2.CommandStatus.OK:
                    break
                collect(main_response)

        except Exception:
            logger.debug("_storage_list_internal failed", exc_info=True)
        return names

    async def _storage_list_detailed_internal(
        self, path: str, include_md5: bool = False, filter_max_size: int = 0
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.ListRequest()
            req.path = path
            req.include_md5 = include_md5
            if filter_max_size:
                req.filter_max_size = int(filter_max_size)
            main_request.storage_list_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if not main_response or main_response.command_status != flipper_pb2.CommandStatus.OK:
                return entries

            def collect(resp: Any) -> None:
                if resp.HasField("storage_list_response"):
                    for f in resp.storage_list_response.file:
                        if not f.name:
                            continue
                        ftype = "DIR" if f.type == storage_pb2.File.DIR else "FILE"
                        item: dict[str, Any] = {"name": f.name, "type": ftype, "size": int(f.size)}
                        if include_md5 and getattr(f, "md5sum", ""):
                            item["md5sum"] = f.md5sum
                        entries.append(item)

            collect(main_response)

            max_iterations = 100
            iteration = 0
            while main_response.has_next and iteration < max_iterations:
                iteration += 1
                next_response = await self._receive_main_message(timeout=2.5)
                if not next_response:
                    break
                main_response = next_response
                if main_response.command_status != flipper_pb2.CommandStatus.OK:
                    break
                collect(main_response)
        except Exception:
            logger.debug("_storage_list_detailed_internal failed", exc_info=True)
        return entries

    async def storage_read(self, path: str) -> bytes:
        """
        Read a file via protobuf storage_read_request.

        Note: Some firmwares may stream large files or require chunking; this is a best-effort
        read for small files where `ReadResponse.file.data` is populated.
        """
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_read_internal(path), timeout=3.0)
            except Exception:
                logger.debug("storage_read(%s) timed out or failed", path, exc_info=True)
                return b""

    async def _storage_read_internal(self, path: str) -> bytes:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.ReadRequest()
            req.path = path
            main_request.storage_read_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("storage_read_response")
            ):
                return bytes(main_response.storage_read_response.file.data)
        except Exception:
            logger.debug("_storage_read_internal failed", exc_info=True)
        return b""

    async def storage_info(self, path: str) -> tuple[int, int] | None:
        """
        Query storage info for a path (e.g. /ext for SD card).

        Returns (total_space, free_space) or None on failure.
        """
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_info_internal(path), timeout=3.0)
            except Exception:
                return None

    async def storage_stat(self, path: str) -> dict[str, Any] | None:
        """Return file metadata for a device path via storage_stat_request."""
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_stat_internal(path), timeout=3.0)
            except Exception:
                logger.debug("storage_stat(%s) timed out or failed", path, exc_info=True)
                return None

    async def storage_timestamp(self, path: str) -> int | None:
        """Return a device file timestamp via storage_timestamp_request."""
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_timestamp_internal(path), timeout=3.0)
            except Exception:
                logger.debug("storage_timestamp(%s) timed out or failed", path, exc_info=True)
                return None

    async def _storage_info_internal(self, path: str) -> tuple[int, int] | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.InfoRequest()
            req.path = path
            main_request.storage_info_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("storage_info_response")
            ):
                r = main_response.storage_info_response
                return int(r.total_space), int(r.free_space)
        except Exception:
            logger.debug("_storage_info_internal failed", exc_info=True)
        return None

    async def _storage_stat_internal(self, path: str) -> dict[str, Any] | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.StatRequest()
            req.path = path
            main_request.storage_stat_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("storage_stat_response")
            ):
                f = main_response.storage_stat_response.file
                ftype = "DIR" if f.type == storage_pb2.File.DIR else "FILE"
                result: dict[str, Any] = {"name": f.name, "type": ftype, "size": int(f.size)}
                if getattr(f, "md5sum", ""):
                    result["md5sum"] = f.md5sum
                return result
        except Exception:
            logger.debug("_storage_stat_internal failed", exc_info=True)
        return None

    async def _storage_timestamp_internal(self, path: str) -> int | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.TimestampRequest()
            req.path = path
            main_request.storage_timestamp_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("storage_timestamp_response")
            ):
                return int(main_response.storage_timestamp_response.timestamp)
        except Exception:
            logger.debug("_storage_timestamp_internal failed", exc_info=True)
        return None

    async def storage_mkdir(self, path: str) -> bool:
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_mkdir_internal(path), timeout=3.0)
            except Exception:
                logger.debug("storage_mkdir(%s) timed out or failed", path, exc_info=True)
                return False

    async def _storage_mkdir_internal(self, path: str) -> bool:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.MkdirRequest()
            req.path = path
            main_request.storage_mkdir_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            return bool(
                main_response and main_response.command_status == flipper_pb2.CommandStatus.OK
            )
        except Exception:
            logger.debug("_storage_mkdir_internal failed", exc_info=True)
            return False

    async def storage_delete(self, path: str, recursive: bool = False) -> bool:
        async with self._io_lock:
            try:
                return await asyncio.wait_for(
                    self._storage_delete_internal(path, recursive=recursive), timeout=3.0
                )
            except Exception:
                logger.debug("storage_delete(%s) timed out or failed", path, exc_info=True)
                return False

    async def _storage_delete_internal(self, path: str, recursive: bool = False) -> bool:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.DeleteRequest()
            req.path = path
            req.recursive = recursive
            main_request.storage_delete_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            return bool(
                main_response and main_response.command_status == flipper_pb2.CommandStatus.OK
            )
        except Exception:
            logger.debug("_storage_delete_internal failed", exc_info=True)
            return False

    async def storage_rename(self, old_path: str, new_path: str) -> bool:
        async with self._io_lock:
            try:
                return await asyncio.wait_for(
                    self._storage_rename_internal(old_path, new_path), timeout=3.0
                )
            except Exception:
                logger.debug(
                    "storage_rename(%s, %s) timed out or failed",
                    old_path,
                    new_path,
                    exc_info=True,
                )
                return False

    async def _storage_rename_internal(self, old_path: str, new_path: str) -> bool:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.RenameRequest()
            req.old_path = old_path
            req.new_path = new_path
            main_request.storage_rename_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            return bool(
                main_response and main_response.command_status == flipper_pb2.CommandStatus.OK
            )
        except Exception:
            logger.debug("_storage_rename_internal failed", exc_info=True)
            return False

    async def storage_md5sum(self, path: str) -> str | None:
        """Compute the device-side MD5 of a file via storage_md5sum_request.

        Args:
            path: Absolute path on the device (e.g. ``/ext/foo.bin``).

        Returns:
            The lowercase hex MD5 digest, or None on failure or empty digest.
        """
        async with self._io_lock:
            try:
                return await asyncio.wait_for(self._storage_md5sum_internal(path), timeout=10.0)
            except Exception:
                logger.debug("storage_md5sum(%s) timed out or failed", path, exc_info=True)
                return None

    async def _storage_md5sum_internal(self, path: str) -> str | None:
        try:
            main_request = flipper_pb2.Main()
            main_request.command_id = self._get_next_command_id()
            main_request.has_next = False

            req = storage_pb2.Md5sumRequest()
            req.path = path
            main_request.storage_md5sum_request.CopyFrom(req)

            main_response = await self._send_rpc_message(main_request)
            if (
                main_response
                and main_response.command_status == flipper_pb2.CommandStatus.OK
                and main_response.HasField("storage_md5sum_response")
            ):
                return main_response.storage_md5sum_response.md5sum or None
        except Exception:
            logger.debug("_storage_md5sum_internal failed", exc_info=True)
        return None

    _WRITE_CHUNK_SIZE = 1024  # Bytes per RPC write frame; conservative for the Flipper serial link.

    async def storage_write(self, path: str, content: bytes) -> bool:
        async with self._io_lock:
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
                await self.transport.send(framed)
                if is_last:
                    response = await self._receive_main_message(timeout=2.5)
                    return bool(
                        response and response.command_status == flipper_pb2.CommandStatus.OK
                    )
            return False
        except Exception:
            logger.debug("_storage_write_internal failed", exc_info=True)
            return False

    @staticmethod
    def _chunk(content: bytes, size: int) -> list[bytes]:
        if not content:
            return [b""]
        return [content[i : i + size] for i in range(0, len(content), size)]
