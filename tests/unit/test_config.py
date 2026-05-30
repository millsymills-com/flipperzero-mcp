import pytest
from pydantic import ValidationError

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


def test_wifi_transport_without_host_rejected():
    with pytest.raises(ValidationError, match="wifi_host"):
        FlipperConfig(_env_file=None, transport="wifi")


def test_wifi_transport_with_host_accepted():
    cfg = FlipperConfig(_env_file=None, transport="wifi", wifi_host="10.0.0.2")
    assert cfg.transport == "wifi"


def test_auto_transport_without_wifi_host_allowed():
    cfg = FlipperConfig(_env_file=None, transport="auto")
    assert cfg.wifi_configured is False
