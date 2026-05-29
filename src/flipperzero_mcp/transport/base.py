"""Transport layer abstraction for Flipper Zero communication."""

import asyncio
import time
from abc import ABC, abstractmethod


class FlipperTransport(ABC):
    """
    Abstract base class for Flipper Zero transport implementations.

    Provides a common interface for different connection methods:
    - USB Serial
    - WiFi (ESP32)
    """

    def __init__(self, config: dict):
        """
        Initialize transport with configuration.

        Args:
            config: Transport-specific configuration
        """
        self.config = config
        self.connected = False
        # Buffer for deterministic framed reads (e.g. protobuf length-prefix protocol)
        self._rx_buffer = bytearray()

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to Flipper Zero.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to Flipper Zero."""
        pass

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """
        Send data to Flipper Zero.

        Args:
            data: Raw bytes to send
        """
        pass

    @abstractmethod
    async def receive(self, timeout: float | None = None) -> bytes:
        """
        Receive data from Flipper Zero.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Received bytes
        """
        pass

    async def receive_exact(self, n: int, timeout: float | None = None) -> bytes:
        """
        Receive exactly N bytes, buffering any extra data for subsequent reads.

        This is required for protocols that use explicit framing (e.g. 4-byte length
        prefix + payload). Underlying transports may return arbitrary chunk sizes.

        Args:
            n: Number of bytes to read
            timeout: Optional overall timeout in seconds

        Returns:
            Exactly N bytes, or b"" if timeout/EOF occurs before N bytes are available.
        """
        if n <= 0:
            return b""

        deadline: float | None = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        while len(self._rx_buffer) < n:
            remaining: float | None
            if deadline is None:
                remaining = None
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

            chunk = await self.receive(timeout=remaining)
            if not chunk:
                # Avoid tight loop if transport returns empty on timeout.
                if deadline is None:
                    await asyncio.sleep(0)
                continue
            self._rx_buffer.extend(chunk)

        if len(self._rx_buffer) < n:
            return b""

        out = bytes(self._rx_buffer[:n])
        del self._rx_buffer[:n]
        return out

    def clear_receive_buffer(self) -> None:
        """Clear any buffered received bytes."""
        self._rx_buffer.clear()

    @abstractmethod
    async def is_connected(self) -> bool:
        """
        Check if transport is connected.

        Returns:
            True if connected, False otherwise
        """
        pass

    def get_name(self) -> str:
        """
        Get transport name for logging.

        Returns:
            Transport name (e.g., "USB", "WiFi")
        """
        return self.__class__.__name__.replace("Transport", "")
