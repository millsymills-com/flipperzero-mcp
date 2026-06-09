"""Configuration for the Flipper MCP server using pydantic-settings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator
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
    enable_tx_tools: bool = False
    enable_write_tools: bool = False
    enable_firmware_flash: bool = False
    debug: bool = False

    @property
    def wifi_configured(self) -> bool:
        """WiFi is usable only when a host is explicitly set."""
        return bool(self.wifi_host and self.wifi_host.strip())

    @model_validator(mode="after")
    def _require_wifi_host_for_wifi_transport(self) -> FlipperConfig:
        if self.transport == "wifi" and not self.wifi_configured:
            raise ValueError("transport='wifi' requires wifi_host (FLIPPER_WIFI_HOST) to be set")
        return self

    def as_transport_config(self) -> dict[str, Any]:
        """Build the nested dict shape expected by transport.get_transport()."""
        usb: dict[str, Any] = {"baudrate": self.usb_baudrate}
        if self.usb_port:
            usb["port"] = self.usb_port
        wifi: dict[str, Any] = {"port": self.wifi_port}
        if self.wifi_host:
            wifi["host"] = self.wifi_host
        return {"transport": {"type": self.transport, "usb": usb, "wifi": wifi}}
