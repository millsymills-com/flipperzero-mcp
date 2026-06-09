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
