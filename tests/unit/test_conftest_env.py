"""Behavioral tests for shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

_ROOT_CONFTEST = Path(__file__).parents[1] / "conftest.py"
_SPEC = importlib.util.spec_from_file_location("root_tests_conftest", _ROOT_CONFTEST)
assert _SPEC is not None
_ROOT_CONFTEST_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_ROOT_CONFTEST_MODULE)
_isolate_flipper_env = _ROOT_CONFTEST_MODULE._isolate_flipper_env


@dataclass(frozen=True)
class _FakeNode:
    integration_marked: bool

    def get_closest_marker(self, name: str) -> object | None:
        if name == "integration" and self.integration_marked:
            return object()
        return None


@dataclass(frozen=True)
class _FakeRequest:
    node: _FakeNode


def test_isolate_flipper_env_strips_flipper_vars_for_unit_tests() -> None:
    with pytest.MonkeyPatch.context() as host_env:
        host_env.setenv("FLIPPER_WIFI_HOST", "192.0.2.42")

        with pytest.MonkeyPatch.context() as fixture_patch:
            request = cast(
                "pytest.FixtureRequest",
                _FakeRequest(node=_FakeNode(integration_marked=False)),
            )
            _isolate_flipper_env(request, fixture_patch)

            assert "FLIPPER_WIFI_HOST" not in os.environ

        assert os.environ["FLIPPER_WIFI_HOST"] == "192.0.2.42"


def test_isolate_flipper_env_preserves_flipper_vars_for_integration_tests() -> None:
    with pytest.MonkeyPatch.context() as host_env:
        host_env.setenv("FLIPPER_WIFI_HOST", "192.0.2.42")

        with pytest.MonkeyPatch.context() as fixture_patch:
            request = cast(
                "pytest.FixtureRequest",
                _FakeRequest(node=_FakeNode(integration_marked=True)),
            )
            _isolate_flipper_env(request, fixture_patch)

            assert os.environ["FLIPPER_WIFI_HOST"] == "192.0.2.42"
