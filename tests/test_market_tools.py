"""Tests for ``ibkr_mcp.tools.market``."""

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
from ibkr_mcp.tools.market import get_historical_data, get_market_data

from .fake_ib import (
    FakeGreeks,
    FakeHistoricalBar,
    FakeIB,
    FakeTicker,
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


# ============================================================ get_market_data
class TestGetMarketData:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_market_data(ctx, symbol="AAPL", secType="STK"))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_equity_snapshot(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.tickers = [
            FakeTicker(
                last=150.50,
                bid=150.48,
                ask=150.52,
                bidSize=400,
                askSize=300,
                volume=45_000_000,
                high=152.0,
                low=149.0,
                open=149.5,
                close=149.8,
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_market_data(ctx, symbol="AAPL", secType="STK"))

        assert payload["symbol"] == "AAPL"
        assert payload["secType"] == "STK"
        assert payload["lastPrice"] == 150.50
        assert payload["bid"] == 150.48
        assert payload["ask"] == 150.52
        assert payload["bidSize"] == 400
        assert payload["volume"] == 45_000_000
        # No option fields for an equity request.
        assert payload.get("delta") is None
        assert payload.get("impliedVolatility") is None

    async def test_option_includes_greeks_via_model_priority(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.tickers = [
            FakeTicker(
                last=3.50,
                bid=3.48,
                ask=3.52,
                volume=1234,
                openInterest=5678,
                modelGreeks=FakeGreeks(
                    delta=0.45,
                    gamma=0.02,
                    theta=-0.08,
                    vega=0.15,
                    impliedVol=0.28,
                ),
                # Lower-priority bundles deliberately differ — the tool MUST pick model.
                lastGreeks=FakeGreeks(delta=0.99),
                bidGreeks=FakeGreeks(delta=-1.0),
                askGreeks=FakeGreeks(delta=2.0),
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_market_data(
                ctx,
                symbol="AAPL",
                secType="OPT",
                expiry="20260516",
                strike=150.0,
                right="C",
            )
        )

        assert payload["secType"] == "OPT"
        assert payload["expiry"] == "20260516"
        assert payload["strike"] == 150.0
        assert payload["right"] == "C"
        assert payload["delta"] == 0.45  # picked from modelGreeks, not lastGreeks
        assert payload["gamma"] == 0.02
        assert payload["theta"] == -0.08
        assert payload["vega"] == 0.15
        assert payload["impliedVolatility"] == 0.28
        assert payload["openInterest"] == 5678

    async def test_option_falls_back_to_last_greeks(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.tickers = [
            FakeTicker(
                last=3.50,
                modelGreeks=None,
                lastGreeks=FakeGreeks(delta=0.55, gamma=0.03),
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_market_data(
                ctx,
                symbol="AAPL",
                secType="OPT",
                expiry="20260516",
                strike=150.0,
                right="C",
            )
        )

        assert payload["delta"] == 0.55

    async def test_invalid_contract_returns_validation(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())

        # OPT requires expiry+strike+right; missing all three.
        payload = json.loads(await get_market_data(ctx, symbol="AAPL", secType="OPT"))
        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value

    async def test_qualify_returns_empty(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: __import__("pytest").MonkeyPatch,
    ) -> None:
        async def empty_qualify(*_args: Any, **_kwargs: Any) -> list[Any]:
            return []

        monkeypatch.setattr(fake_ib, "qualifyContractsAsync", empty_qualify)
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_market_data(ctx, symbol="ZZZZZZ", secType="STK"))

        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value

    async def test_no_market_data_when_tickers_empty(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.tickers = []
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_market_data(ctx, symbol="AAPL", secType="STK"))

        assert payload["code"] == ErrorCode.IB_NO_MARKET_DATA.value


# ============================================================ get_historical_data
class TestGetHistoricalData:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(
            await get_historical_data(
                ctx, symbol="AAPL", secType="STK", duration="P30D", barSize="1 day"
            )
        )
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_iso_duration_translated(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.historical_bars = [
            FakeHistoricalBar(
                date="20260331",
                open=149.0,
                high=151.5,
                low=148.2,
                close=150.8,
                volume=52_000_000,
                average=150.10,
                barCount=50_000,
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_historical_data(
                ctx, symbol="AAPL", secType="STK", duration="P30D", barSize="1 day"
            )
        )

        assert fake_ib.historical_calls[-1]["durationStr"] == "30 D"
        assert payload["barSize"] == "1 day"
        assert len(payload["bars"]) == 1
        bar = payload["bars"][0]
        assert bar["open"] == 149.0
        assert bar["close"] == 150.8
        assert bar["volume"] == 52_000_000
        assert bar["wap"] == 150.10
        assert bar["count"] == 50_000

    async def test_ib_native_duration_passthrough(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        await get_historical_data(
            ctx, symbol="AAPL", secType="STK", duration="30 D", barSize="1 day"
        )
        assert fake_ib.historical_calls[-1]["durationStr"] == "30 D"

    async def test_invalid_duration_returns_validation_error(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(
            await get_historical_data(
                ctx, symbol="AAPL", secType="STK", duration="garbage", barSize="1 day"
            )
        )
        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value

    async def test_invalid_contract(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(
            await get_historical_data(
                ctx,
                symbol="AAPL",
                secType="OPT",
                duration="P30D",
                barSize="1 day",
                # missing strike/right/expiry
            )
        )
        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value

    async def test_datetime_date_serialised(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.historical_bars = [
            FakeHistoricalBar(
                date=datetime(2026, 3, 31, 9, 30, 0),
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=100,
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_historical_data(
                ctx, symbol="AAPL", secType="STK", duration="P1D", barSize="1 hour"
            )
        )

        assert payload["bars"][0]["date"] == "20260331 09:30:00"


class TestRegistration:
    def test_register_attaches_both_tools(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_market_data" in names
        assert "get_historical_data" in names
