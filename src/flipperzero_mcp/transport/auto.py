"""Auto transport: prefer USB, fall back to WiFi when configured.

This transport is designed to support a *single* MCP client configuration.

Selection policy:
- Try USB first
- If USB fails and WiFi is configured (host is set), try WiFi
"""

from __future__ import annotations

import logging

from flipperzero_mcp.transport.base import FlipperTransport
from flipperzero_mcp.transport.usb import USBTransport
from flipperzero_mcp.transport.wifi import WiFiTransport

logger = logging.getLogger(__name__)


class AutoTransport(FlipperTransport):
    """
    Transport that selects between USB and WiFi at runtime.

    The constructor expects to receive the *full* transport section:

    {
      "type": "auto",
      "usb": {...},
      "wifi": {...}
    }
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self._transport_config = config or {}
        self._active: FlipperTransport | None = None

    def _usb_config(self) -> dict:
        return dict(self._transport_config.get("usb", {}) or {})

    def _wifi_config(self) -> dict:
        return dict(self._transport_config.get("wifi", {}) or {})

    def _wifi_is_configured(self) -> bool:
        """
        WiFi is considered configured only if a host is explicitly set.
        """
        wifi = self._wifi_config()
        host = wifi.get("host")
        return bool(host and str(host).strip())

    async def connect(self) -> bool:
        # Prefer USB first.
        usb = USBTransport(self._usb_config())
        if await usb.connect():
            self._active = usb
            self.connected = True
            self.clear_receive_buffer()
            logger.info("   Auto transport selected: USB")
            return True

        # USB failed; only try WiFi if it is explicitly configured.
        if self._wifi_is_configured():
            wifi_cfg = self._wifi_config()
            wifi = WiFiTransport(wifi_cfg)
            if await wifi.connect():
                self._active = wifi
                self.connected = True
                self.clear_receive_buffer()
                host = wifi_cfg.get("host")
                port = wifi_cfg.get("port")
                if host and port:
                    logger.info(f"   Auto transport selected: WiFi ({host}:{port})")
                else:
                    logger.info("   Auto transport selected: WiFi")
                return True

        self._active = None
        self.connected = False
        return False

    async def disconnect(self) -> None:
        try:
            if self._active:
                await self._active.disconnect()
        finally:
            self._active = None
            self.connected = False
            self.clear_receive_buffer()

    async def send(self, data: bytes) -> None:
        if not self._active:
            raise RuntimeError("Auto transport has no active connection")
        await self._active.send(data)

    async def receive(self, timeout: float | None = None) -> bytes:
        if not self._active:
            raise RuntimeError("Auto transport has no active connection")
        return await self._active.receive(timeout=timeout)

    async def is_connected(self) -> bool:
        if not self._active:
            return False
        try:
            return bool(await self._active.is_connected())
        except (OSError, RuntimeError):
            logger.debug("active transport is_connected() raised", exc_info=True)
            return False

    def get_name(self) -> str:
        # Report the underlying transport when available (used in health reporting).
        if self._active:
            try:
                return self._active.get_name()
            except AttributeError:
                return "Auto"
        return "Auto"
