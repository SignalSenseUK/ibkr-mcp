"""Shared pytest fixtures for the ``ibkr_mcp`` test suite."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from ibkr_mcp.config import Settings

from .fake_ib import FakeIB


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every IB_*/MCP_*/LOG_* env var so tests are deterministic."""
    for key in list(os.environ):
        if key.startswith(("IB_", "MCP_", "LOG_")):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def fake_ib() -> FakeIB:
    """A fresh :class:`FakeIB` per test."""
    return FakeIB()


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Factory that builds a :class:`Settings` with overrides and no `.env`."""

    def _factory(**overrides: Any) -> Settings:
        return Settings(_env_file="/dev/null", **overrides)  # type: ignore[arg-type, call-arg]

    return _factory


@pytest.fixture
def settings(settings_factory: Callable[..., Settings]) -> Settings:
    """Default Settings instance for tests that don't need overrides."""
    return settings_factory()


@pytest.fixture
def event_loop_policy() -> Iterator[None]:  # pragma: no cover - asyncio compat shim
    """Placeholder to keep pytest-asyncio happy across versions."""
    yield
