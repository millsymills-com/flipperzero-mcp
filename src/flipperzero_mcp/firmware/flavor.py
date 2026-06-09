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
    """Classified firmware facts derived from device_info.

    Attributes:
        flavor: The recognized firmware distribution, or ``UNKNOWN``.
        version: The firmware version string, if reported.
        origin_fork: Short fork name as reported by the device (e.g. ``Momentum``).
        origin_git: Upstream git URL the firmware was built from.
        target: Hardware target identifier (e.g. ``f7``), if reported.
    """

    flavor: FirmwareFlavor
    version: str | None
    origin_fork: str | None
    origin_git: str | None
    target: str | None


_GIT_MARKERS = (
    ("next-flip/momentum", FirmwareFlavor.MOMENTUM),
    ("darkflippers/unleashed", FirmwareFlavor.UNLEASHED),
    ("roguemaster/", FirmwareFlavor.ROGUEMASTER),
    ("flipperdevices/flipperzero-firmware", FirmwareFlavor.OFFICIAL),
)
_FORK_MARKERS = {
    "momentum": FirmwareFlavor.MOMENTUM,
    "unleashed": FirmwareFlavor.UNLEASHED,
    "roguemaster": FirmwareFlavor.ROGUEMASTER,
    "official": FirmwareFlavor.OFFICIAL,
}


def _flavor_from(origin_git: str | None, origin_fork: str | None) -> FirmwareFlavor:
    git = (origin_git or "").lower()
    for marker, flavor in _GIT_MARKERS:
        if marker in git:
            return flavor
    fork = (origin_fork or "").strip().lower()
    if fork in _FORK_MARKERS:
        return _FORK_MARKERS[fork]
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
