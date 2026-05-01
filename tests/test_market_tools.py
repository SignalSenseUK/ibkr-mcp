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
from ibkr_mcp.tools.market import (
    get_historical_data,
    get_market_data,
    get_option_chain,
)

from .fake_ib import (
    FakeContract,
    FakeGreeks,
    FakeHistoricalBar,
    FakeIB,
    FakeOptionChain,
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


# ============================================================ get_option_chain
class TestGetOptionChain:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_option_chain(ctx, symbol="AAPL"))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_discovery_mode_no_per_contract_calls(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
    ) -> None:
        # Underlying qualification returns a contract with conId 265598.
        underlying = FakeContract(
            secType="STK",
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
            conId=265598,
        )

        async def qualify(*contracts: Any) -> list[Any]:
            return [underlying]

        fake_ib.qualifyContractsAsync = qualify  # type: ignore[method-assign]

        fake_ib.sec_def_opt_params_data = [
            FakeOptionChain(
                exchange="SMART",
                multiplier="100",
                expirations=["20260620", "20260516"],
                strikes=[140.0, 145.0, 150.0, 155.0, 160.0],
            ),
            FakeOptionChain(
                exchange="CBOE",
                multiplier="100",
                expirations=["20260516"],
                strikes=[150.0, 155.0],
            ),
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_option_chain(ctx, symbol="AAPL"))

        assert payload["underlying"] == "AAPL"
        assert "expirations" in payload
        # Aggregated and deduplicated.
        assert payload["expirations"] == ["20260516", "20260620"]
        assert payload["strikes"] == [140.0, 145.0, 150.0, 155.0, 160.0]
        assert set(payload["exchanges"]) == {"SMART", "CBOE"}
        assert payload["multiplier"] == 100
        # Per-contract data MUST NOT be fetched in discovery mode (spec §6.8).
        assert fake_ib.tickers_calls == []

    async def test_no_chain_data_returns_no_market_data(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.sec_def_opt_params_data = []
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_option_chain(ctx, symbol="ZZZZ"))
        assert payload["code"] == ErrorCode.IB_NO_MARKET_DATA.value

    async def test_full_chain_with_expiry_emits_per_strike(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        underlying = FakeContract(secType="STK", symbol="AAPL", conId=265598)

        async def qualify(*contracts: Any) -> list[Any]:
            return [underlying]

        fake_ib.qualifyContractsAsync = qualify  # type: ignore[method-assign]

        fake_ib.sec_def_opt_params_data = [
            FakeOptionChain(
                exchange="SMART",
                multiplier="100",
                expirations=["20260516"],
                strikes=[150.0, 155.0],
            )
        ]

        # 2 strikes x 2 rights = 4 tickers, in input order (strike asc, then C, P).
        fake_ib.tickers = [
            FakeTicker(
                contract=FakeContract(conId=4123456),
                last=3.50,
                bid=3.48,
                ask=3.52,
                volume=12345,
                openInterest=67890,
                modelGreeks=FakeGreeks(
                    delta=0.45, gamma=0.02, theta=-0.08, vega=0.15, impliedVol=0.28
                ),
            ),
            FakeTicker(
                contract=FakeContract(conId=4123457),
                last=2.10,
                modelGreeks=FakeGreeks(delta=-0.40),
            ),
            FakeTicker(
                contract=FakeContract(conId=4123458),
                last=1.50,
                modelGreeks=FakeGreeks(delta=0.30),
            ),
            FakeTicker(
                contract=FakeContract(conId=4123459),
                last=4.00,
                modelGreeks=FakeGreeks(delta=-0.55),
            ),
        ]

        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_option_chain(ctx, symbol="AAPL", expiry="20260516"))

        assert payload["underlying"] == "AAPL"
        assert payload["expiry"] == "20260516"
        assert payload["multiplier"] == 100
        assert len(payload["chains"]) == 4
        # Order: (150, C), (150, P), (155, C), (155, P).
        assert (payload["chains"][0]["strike"], payload["chains"][0]["right"]) == (150.0, "C")
        assert (payload["chains"][1]["strike"], payload["chains"][1]["right"]) == (150.0, "P")
        assert (payload["chains"][2]["strike"], payload["chains"][2]["right"]) == (155.0, "C")
        assert (payload["chains"][3]["strike"], payload["chains"][3]["right"]) == (155.0, "P")
        # First strike pulls Greeks via modelGreeks priority.
        first = payload["chains"][0]
        assert first["delta"] == 0.45
        assert first["impliedVolatility"] == 0.28
        assert first["openInterest"] == 67890
        assert first["conId"] == 4123456

    async def test_full_chain_filters_right(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        async def qualify(*contracts: Any) -> list[Any]:
            return [FakeContract(secType="STK", symbol="AAPL", conId=1)]

        fake_ib.qualifyContractsAsync = qualify  # type: ignore[method-assign]

        fake_ib.sec_def_opt_params_data = [
            FakeOptionChain(
                exchange="SMART",
                multiplier="100",
                expirations=["20260516"],
                strikes=[150.0, 155.0],
            )
        ]
        # Only 2 contracts requested (C only).
        fake_ib.tickers = [
            FakeTicker(contract=FakeContract(conId=1), last=3.50),
            FakeTicker(contract=FakeContract(conId=2), last=1.50),
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_option_chain(ctx, symbol="AAPL", expiry="20260516", right="C")
        )

        assert all(row["right"] == "C" for row in payload["chains"])
        assert len(payload["chains"]) == 2

    async def test_invalid_right_returns_validation_error(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        async def qualify(*contracts: Any) -> list[Any]:
            return [FakeContract(secType="STK", symbol="AAPL", conId=1)]

        fake_ib.qualifyContractsAsync = qualify  # type: ignore[method-assign]
        fake_ib.sec_def_opt_params_data = [
            FakeOptionChain(
                exchange="SMART",
                multiplier="100",
                expirations=["20260516"],
                strikes=[150.0],
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_option_chain(ctx, symbol="AAPL", expiry="20260516", right="X")
        )
        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value

    async def test_unknown_expiry_returns_invalid_contract(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        async def qualify(*contracts: Any) -> list[Any]:
            return [FakeContract(secType="STK", symbol="AAPL", conId=1)]

        fake_ib.qualifyContractsAsync = qualify  # type: ignore[method-assign]
        fake_ib.sec_def_opt_params_data = [
            FakeOptionChain(
                exchange="SMART",
                multiplier="100",
                expirations=["20260516"],
                strikes=[150.0],
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_option_chain(ctx, symbol="AAPL", expiry="20990101"))
        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value


class TestRegistration:
    def test_register_attaches_all_tools(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_market_data" in names
        assert "get_historical_data" in names
        assert "get_option_chain" in names
