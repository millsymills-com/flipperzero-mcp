"""Advisory risk classification for raw Flipper CLI command lines.

This is an ordered-prefix denylist and therefore FAILS OPEN: anything unlisted
(a future subcommand, an app that transmits via ``loader open``, reordered
arguments) is treated as benign. It is defense-in-depth, not the security
boundary. The real control is the operator env flag ``FLIPPER_ENABLE_TX_TOOLS``
checked alongside the per-call acceptance flag in ``flipper_cli_exec``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal["benign", "transmit", "destructive"]

# Ordered (prefix, category) rules; first match wins. Prefixes are matched
# against the normalized (lowercased, whitespace-collapsed) command line, either
# exactly or followed by a space.
DENYLIST: tuple[tuple[str, Category], ...] = (
    ("subghz tx", "transmit"),
    ("ir tx", "transmit"),
    ("rfid write", "transmit"),
    ("ikey write", "transmit"),
    ("factory reset", "destructive"),
    ("storage format", "destructive"),
    ("update install", "destructive"),
    ("power off", "destructive"),
    ("power reboot", "destructive"),
)

_WARNINGS: dict[Category, str] = {
    "transmit": (
        "This command makes the Flipper TRANSMIT on a radio/RF interface. "
        "Transmitting outside permitted frequencies/power is illegal in most "
        "regions and is your responsibility. Re-call with "
        "i_accept_responsibility=true (and FLIPPER_ENABLE_TX_TOOLS=true on the "
        "server) to proceed."
    ),
    "destructive": (
        "This command is destructive (data loss, reset, or reboot). Re-call with "
        "i_accept_responsibility=true (and FLIPPER_ENABLE_TX_TOOLS=true on the "
        "server) to proceed."
    ),
}


@dataclass(frozen=True)
class Risk:
    """Advisory classification of a single CLI command line."""

    category: Category
    gated: bool
    warning: str | None


def _normalize(command: str) -> str:
    return " ".join(command.strip().lower().split())


def classify(command: str) -> Risk:
    """Classify a raw CLI command line by risk.

    Args:
        command: The raw command line as it would be sent to the Flipper CLI.

    Returns:
        A Risk with the matched category, whether the command is gated (requires
        both server and per-call opt-in), and a human-readable warning. Unlisted
        commands are benign and ungated (the denylist fails open).
    """
    normalized = _normalize(command)
    for prefix, category in DENYLIST:
        if normalized == prefix or normalized.startswith(prefix + " "):
            return Risk(category=category, gated=True, warning=_WARNINGS[category])
    return Risk(category="benign", gated=False, warning=None)
