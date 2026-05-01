"""Tests for ``get_portfolio_greeks`` (spec §6.8)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

from ib_async import IB
from mcp.server.fastmcp import Context

from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.errors import ErrorCode
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.account import get_portfolio_greeks

from .fake_ib import (
    FakeGreeks,
    FakeIB,
    FakeTicker,
    make_option_position,
    make_stock_position,
)


def _make_ctx(
    fake_ib: FakeIB,
    settings: Settings,
    *,
    connected: bool = True,
) -> Context:  # type: ignore[type-arg]
    fake_ib.connected = connected
    mgr = ConnectionManager(settings=settings, ib=cast(IB, fake_ib))
    mgr._account_id = "U1234567"
    app_ctx = AppContext(
        settings=settings,
        manager=mgr,
        started_at=datetime.now(UTC),
        server_version="0.1.0",
        ib_lock=asyncio.Lock(),
    )
    mcp = build_mcp(settings)
    request_context: Any = MagicMock()
    request_context.lifespan_context = app_ctx
    request_context.request_id = "test"
    return Context(request_context=request_context, fastmcp=mcp)


class TestGetPortfolioGreeks:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_portfolio_greeks(ctx))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_no_options_yields_zero_totals(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # Stock-only portfolio.
        fake_ib.portfolio_data = [make_stock_position()]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_portfolio_greeks(ctx))

        assert payload["account"] == "U1234567"
        assert payload["positions"] == []
        # exclude_none=True drops null totals; the spec defaults are 0.0 so
        # they must be retained because Pydantic emits 0.0 (not None).
        assert payload["totalDelta"] == 0.0
        assert payload["totalGamma"] == 0.0
        assert payload["totalTheta"] == 0.0
        assert payload["totalVega"] == 0.0

    async def test_aggregates_three_positions_with_mixed_sources(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # 3 option positions: 2 with model Greeks, 1 with no Greeks but valid IV.
        opt_a = make_option_position(
            account="U1234567",
            symbol="AAPL",
            quantity=10,
            strike=150.0,
            right="C",
            expiry="20991231",  # far in the future so BS doesn't choke
            multiplier="100",
        )
        opt_b = make_option_position(
            account="U1234567",
            symbol="AAPL",
            quantity=-5,
            strike=160.0,
            right="P",
            expiry="20991231",
            multiplier="100",
        )
        opt_c = make_option_position(
            account="U1234567",
            symbol="MSFT",
            quantity=2,
            strike=380.0,
            right="C",
            expiry="20991231",
            multiplier="100",
        )

        fake_ib.portfolio_data = [opt_a, opt_b, opt_c, make_stock_position()]

        # Tickers in same input order: opt_a, opt_b, opt_c.
        fake_ib.tickers = [
            FakeTicker(
                modelGreeks=FakeGreeks(
                    delta=0.45, gamma=0.02, theta=-0.08, vega=0.15, impliedVol=0.28
                ),
            ),
            FakeTicker(
                modelGreeks=FakeGreeks(
                    delta=-0.30, gamma=0.025, theta=-0.10, vega=0.20, impliedVol=0.30
                ),
            ),
            FakeTicker(
                # No Greeks bundle; only an IV in lastGreeks (no dxx) so the
                # tool falls back to Black-Scholes.
                modelGreeks=None,
                lastGreeks=FakeGreeks(impliedVol=0.32),
            ),
        ]

        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_portfolio_greeks(ctx))

        assert len(payload["positions"]) == 3
        # First 2 are model, third is fallback.
        sources = [p["source"] for p in payload["positions"]]
        assert sources[0] == "model"
        assert sources[1] == "model"
        assert sources[2] == "fallback"

        # Verify weighting: opt_a delta = 0.45 * 10 * 100 = 450
        assert payload["positions"][0]["delta"] == 450.0
        # opt_b delta = -0.30 * -5 * 100 = 150
        assert payload["positions"][1]["delta"] == 150.0

        # totalDelta sums position-weighted contributions.
        total = (
            payload["positions"][0]["delta"]
            + payload["positions"][1]["delta"]
            + payload["positions"][2]["delta"]
        )
        assert payload["totalDelta"] == total

    async def test_missing_greeks_and_no_iv_marks_position_missing(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        opt = make_option_position(
            account="U1234567",
            symbol="AAPL",
            quantity=10,
            strike=150.0,
            right="C",
            expiry="20991231",
        )
        fake_ib.portfolio_data = [opt]
        # No Greeks, no IV — tool can't compute, must mark as missing.
        fake_ib.tickers = [FakeTicker(modelGreeks=None, lastGreeks=None)]

        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_portfolio_greeks(ctx))

        assert len(payload["positions"]) == 1
        assert payload["positions"][0]["source"] == "missing"
        # No contribution to totals.
        assert payload["totalDelta"] == 0.0

    async def test_filters_other_accounts(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567", "U7777777"]
        opt_us = make_option_position(account="U1234567")
        opt_other = make_option_position(account="U7777777")
        fake_ib.portfolio_data = [opt_us, opt_other]
        fake_ib.tickers = [
            FakeTicker(modelGreeks=FakeGreeks(delta=0.5)),
        ]

        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_portfolio_greeks(ctx, accountId="U1234567"))

        assert len(payload["positions"]) == 1
        assert payload["account"] == "U1234567"

    async def test_unknown_account(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567"]
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_portfolio_greeks(ctx, accountId="U9999999"))
        assert payload["code"] == ErrorCode.IB_ACCOUNT_NOT_FOUND.value


class TestRegistration:
    def test_register_attaches_tool(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_portfolio_greeks" in names
