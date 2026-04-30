"""Tests for ``ibkr_mcp.tools.server``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from ib_async import IB
from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.config import MarketDataType, Settings, TransportMode
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.server import get_server_status

from .fake_ib import FakeIB


def _make_app_ctx(
    fake_ib: FakeIB,
    settings: Settings,
    *,
    started_at: datetime | None = None,
    server_version: str = "0.1.0",
) -> AppContext:
    mgr = ConnectionManager(settings=settings, ib=cast(IB, fake_ib))
    return AppContext(
        settings=settings,
        manager=mgr,
        started_at=started_at or datetime.now(UTC),
        server_version=server_version,
        ib_lock=asyncio.Lock(),
    )


def _make_ctx(app_ctx: AppContext, mcp: FastMCP[AppContext]) -> Context:  # type: ignore[type-arg]
    """Build a minimal MCP ``Context`` whose lifespan_context is ``app_ctx``."""
    request_context: Any = MagicMock()
    request_context.lifespan_context = app_ctx
    request_context.request_id = "test-request"
    return Context(request_context=request_context, fastmcp=mcp)


class TestGetServerStatus:
    async def test_returns_connected_when_gateway_up(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        # Force the connection state to "connected" without going through connectAsync.
        fake_ib.connected = True

        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory())
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        assert payload["status"] == "connected"

    async def test_returns_disconnected_when_gateway_down(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        fake_ib.connected = False

        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory())
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        assert payload["status"] == "disconnected"

    async def test_response_contains_all_spec_fields(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        fake_ib.connected = True

        settings = settings_factory(
            IB_HOST="10.0.0.5",
            IB_PORT=7497,
            IB_CLIENT_ID=42,
            IB_PAPER_TRADING=False,
            IB_MARKET_DATA_TYPE=MarketDataType.DELAYED,
            MCP_TRANSPORT=TransportMode.STDIO,
        )

        mcp = build_mcp(settings)
        app_ctx = _make_app_ctx(fake_ib, settings, server_version="9.9.9")
        # Pre-populate the manager's account id so the response includes one.
        app_ctx.manager._account_id = "U0001234"
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        assert payload["ibHost"] == "10.0.0.5"
        assert payload["ibPort"] == 7497
        assert payload["clientId"] == 42
        assert payload["accountId"] == "U0001234"
        assert payload["paperTrading"] is False
        assert payload["serverVersion"] == "9.9.9"
        assert payload["transport"] == "stdio"
        assert payload["marketDataType"] == "DELAYED"
        assert payload["uptimeSeconds"] >= 0
        assert payload["registeredTools"] >= 1  # get_server_status is registered
        assert "timestamp" in payload

    async def test_uptime_reflects_started_at(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        fake_ib.connected = True
        started = datetime.now(UTC) - timedelta(seconds=125)
        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory(), started_at=started)
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        # Allow a couple of seconds of slack for test-runtime drift.
        assert 124 <= payload["uptimeSeconds"] <= 130

    async def test_account_id_none_serialises_to_null(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        fake_ib.connected = False

        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory())
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        assert payload["accountId"] is None

    async def test_registered_tools_counts_at_least_self(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        # build_mcp wires register_all_tools, so get_server_status is attached.
        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory())
        ctx = _make_ctx(app_ctx, mcp)

        payload = json.loads(await get_server_status(ctx))

        assert payload["registeredTools"] >= 1

    async def test_tool_returns_error_envelope_on_unexpected_failure(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If an unexpected error occurs, the tool MUST return JSON, not raise."""

        mcp = build_mcp(settings_factory())
        app_ctx = _make_app_ctx(fake_ib, settings_factory())
        ctx = _make_ctx(app_ctx, mcp)

        # Force a failure by removing the lifespan_context attribute.
        ctx.request_context.lifespan_context = None  # type: ignore[union-attr]

        result = await get_server_status(ctx)
        payload = json.loads(result)

        assert "error" in payload
        assert "code" in payload


class TestRegistration:
    def test_register_attaches_tool_to_mcp(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_server_status" in names
