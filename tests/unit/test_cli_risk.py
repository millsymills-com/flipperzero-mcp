"""Risk classifier for CLI commands (#39)."""

import pytest

from flipperzero_mcp.rpc.cli_risk import classify


def test_benign_command_is_unlisted():
    risk = classify("storage list /ext")
    assert risk.gated is False
    assert risk.category == "benign"
    assert risk.warning is None


def test_subghz_rx_is_benign():
    risk = classify("subghz rx 433920000")
    assert risk.gated is False
    assert risk.category == "benign"


@pytest.mark.parametrize(
    ("command", "category"),
    [
        ("subghz tx 0x00112233 433920000 200 10", "transmit"),
        ("ir tx 38000 100 200", "transmit"),
        ("rfid write EM4100 1234567890", "transmit"),
        ("ikey write DS1990 1234", "transmit"),
        ("factory reset", "destructive"),
        ("storage format /ext", "destructive"),
        ("power off", "destructive"),
        ("power reboot", "destructive"),
        ("update install /ext/update/upd.fuf", "destructive"),
    ],
)
def test_listed_families_are_gated(command, category):
    risk = classify(command)
    assert risk.gated is True
    assert risk.category == category
    assert risk.warning


def test_exact_prefix_match_is_gated():
    assert classify("power off").gated is True


def test_prefix_must_be_followed_by_space_or_end():
    # "power offer" must not match the "power off" prefix.
    assert classify("power offer").gated is False


def test_classification_ignores_leading_whitespace_and_case():
    risk = classify("   RFID WRITE EM4100 1234567890")
    assert risk.gated is True
    assert risk.category == "transmit"


def test_risk_is_frozen():
    risk = classify("device info")
    with pytest.raises(AttributeError):
        risk.gated = True  # type: ignore[misc]
