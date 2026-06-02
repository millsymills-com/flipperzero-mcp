"""WiFi transport for Flipper Zero (ESP32 WiFi Dev Board)."""

import asyncio
import logging

from flipperzero_mcp.transport.base import FlipperTransport

logger = logging.getLogger(__name__)


class WiFiTransport(FlipperTransport):
    """
    WiFi transport implementation for ESP32 WiFi Dev Board.

    Connects to Flipper Zero via network socket.
    """

    def __init__(self, config: dict):
        """
        Initialize WiFi transport.

        Args:
            config: WiFi configuration with 'host' and 'port'
        """
        super().__init__(config)
        self.host = config.get("host", "192.168.1.1")
        self.port = config.get("port", 8080)
        # Connection/read tuning
        self.connect_timeout = float(config.get("connect_timeout", 3.0))
        self.read_chunk_size = int(config.get("read_chunk_size", 4096))
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    @property
    def supports_cli_text_mode(self) -> bool:
        """The WiFi bridge speaks nanopb RPC over TCP; it has no CLI text shell."""
        return False

    async def connect(self) -> bool:
        """
        Connect to Flipper Zero via WiFi.

        Returns:
            True if connection successful
        """
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.connect_timeout,
            )
            self.connected = True
            # Best-effort: clear any previously buffered bytes for framed protocols.
            self.clear_receive_buffer()
            await self._drain_socket_buffer(max_seconds=0.2)
            return True
        except (TimeoutError, OSError) as e:
            logger.warning(f"WiFi connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Close WiFi connection."""
        try:
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
        finally:
            self.reader = None
            self.writer = None
        self.connected = False

    async def send(self, data: bytes) -> None:
        """
        Send data over WiFi.

        Args:
            data: Bytes to send
        """
        if not self.writer:
            raise RuntimeError("WiFi not connected")

        self.writer.write(data)
        await self.writer.drain()

    async def receive(self, timeout: float | None = None) -> bytes:
        """
        Receive data from WiFi.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Received bytes
        """
        if not self.reader:
            raise RuntimeError("WiFi not connected")

        try:
            if timeout is not None:
                # If timeout is 0.0, we want an immediate "no data" response.
                if timeout <= 0:
                    return b""
                data = await asyncio.wait_for(
                    self.reader.read(self.read_chunk_size),
                    timeout=timeout,
                )
            else:
                data = await self.reader.read(self.read_chunk_size)
            return data
        except TimeoutError:
            return b""
        except (ConnectionResetError, BrokenPipeError):
            logger.debug(
                "WiFi connection dropped during receive (%s:%s)",
                self.host,
                self.port,
                exc_info=True,
            )
            self.connected = False
            return b""

    async def _drain_socket_buffer(self, max_seconds: float = 0.2) -> None:
        """
        Best-effort drain of any already-received bytes buffered in the TCP reader.

        This helps ensure framed protocols (nanopb-delimited protobuf) start reading
        cleanly after connect/reconnect.
        """
        if not self.reader:
            return
        try:
            deadline = asyncio.get_event_loop().time() + max_seconds
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(
                        self.reader.read(self.read_chunk_size), timeout=0.01
                    )
                except TimeoutError:
                    chunk = b""
                if not chunk:
                    # Nothing immediately buffered.
                    await asyncio.sleep(0)
                    break
        except (TimeoutError, OSError):
            # Drain is best-effort only.
            return

    async def is_connected(self) -> bool:
        """
        Check if WiFi is connected.

        Returns:
            True if connected
        """
        return self.connected and self.writer is not None and not self.writer.is_closing()
