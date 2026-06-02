"""USB Serial transport for Flipper Zero."""

import asyncio
import logging
from pathlib import Path

import serial
import serial.tools.list_ports

from flipperzero_mcp.transport.base import FlipperTransport

logger = logging.getLogger(__name__)

# Flipper Zero USB VID:PID
FLIPPER_VID = 0x0483  # STMicroelectronics
FLIPPER_PID = 0x5740  # Virtual COM Port


class USBTransport(FlipperTransport):
    """
    USB Serial transport implementation.

    Connects to Flipper Zero via USB serial port.
    """

    def __init__(self, config: dict):
        """
        Initialize USB transport.

        Args:
            config: USB configuration with 'port' and 'baudrate'
        """
        super().__init__(config)
        # IMPORTANT: dict.get(default=...) eagerly evaluates the default, which would
        # auto-detect even when an explicit port was provided. Keep this lazy.
        configured_port = config.get("port")
        self.port = configured_port or self._auto_detect_port()
        self.baudrate = config.get("baudrate", 115200)
        self.timeout = config.get("timeout", 1.0)
        self.serial: serial.Serial | None = None

    def _auto_detect_port(self) -> str:
        """
        Auto-detect Flipper Zero USB port.

        Supports both macOS (tty.usbmodem*) and Linux (ttyACM*, ttyUSB*).

        Returns:
            Port path or default
        """
        import platform

        system = platform.system()

        # Look for Flipper Zero USB device
        ports = serial.tools.list_ports.comports()
        detected_ports = []

        for port in ports:
            device = port.device

            # Flipper Zero VID:PID match (most reliable), description match, or
            # macOS-specific usbmodem pattern containing "flip".
            is_flipper = (
                (port.vid == FLIPPER_VID and port.pid == FLIPPER_PID)
                or "Flipper" in str(port.description)
                or (
                    system == "Darwin" and "usbmodem" in device.lower() and "flip" in device.lower()
                )
            )

            if is_flipper:
                # On macOS, prefer cu.* for initiating outgoing serial connections.
                # (tty.* is typically for incoming/call-in.)
                if system == "Darwin" and device.startswith("/dev/tty."):
                    cu_device = device.replace("/dev/tty.", "/dev/cu.")
                    if Path(cu_device).exists():
                        device = cu_device

                detected_ports.append((device, port))

        # Return the first detected port
        if detected_ports:
            device, port = detected_ports[0]
            logger.info(f"   Detected Flipper Zero at {device}")
            return device

        # Platform-specific fallback
        if system == "Darwin":
            # macOS: try common usbmodem pattern
            fallback = "/dev/tty.usbmodemflip_1"
            logger.warning(f"   ⚠️  No Flipper Zero detected, using fallback: {fallback}")
            return fallback
        else:
            # Linux: try common ACM port
            fallback = "/dev/ttyACM0"
            logger.warning(f"   ⚠️  No Flipper Zero detected, using fallback: {fallback}")
            return fallback

    async def connect(self) -> bool:
        """
        Connect to Flipper Zero via USB.

        Returns:
            True if connection successful
        """
        try:
            # Open serial port
            self.serial = serial.Serial(
                port=self.port, baudrate=self.baudrate, timeout=self.timeout
            )

            # Wait for connection to stabilize
            await asyncio.sleep(0.5)

            self.connected = True
            return True

        except (serial.SerialException, OSError) as e:
            logger.warning(f"USB connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Close USB connection."""
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False

    async def send(self, data: bytes) -> None:
        """
        Send data over USB.

        Args:
            data: Bytes to send
        """
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("USB not connected")

        # Run serial write in executor to avoid blocking. Frame-level
        # serialization is provided by the client's shared I/O lock; this
        # transport intentionally holds no lock of its own.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.serial.write, data)

    async def receive(self, timeout: float | None = None) -> bytes:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("USB not connected")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._blocking_read, timeout)

    def _blocking_read(self, timeout: float | None) -> bytes:
        assert self.serial is not None
        old_timeout = self.serial.timeout
        if timeout is not None:
            self.serial.timeout = timeout
        try:
            return self.serial.read(4096)
        finally:
            self.serial.timeout = old_timeout

    async def is_connected(self) -> bool:
        """
        Check if USB is connected.

        Returns:
            True if connected
        """
        return self.connected and self.serial is not None and self.serial.is_open
