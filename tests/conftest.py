"""Shared pytest fixtures for the Flipper MCP test suite."""

from __future__ import annotations

import os

import pytest

_FLIPPER_PREFIX = "FLIPPER_"


def _isolate_flipper_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``FLIPPER_*`` env vars unless the test is integration-marked."""
    if request.node.get_closest_marker("integration") is not None:
        return
    for key in [k for k in os.environ if k.startswith(_FLIPPER_PREFIX)]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def isolate_flipper_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``FLIPPER_*`` env vars so the host environment can't change test outcomes.

    Integration tests opt out: they read ``FLIPPER_WIFI_HOST`` and friends from the
    real environment to reach a physical device.
    """
    _isolate_flipper_env(request, monkeypatch)
