"""Tests for ``ibkr_mcp.tools.contracts``."""

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
from ibkr_mcp.tools.contracts import get_contract_details

from .fake_ib import FakeContract, FakeContractDetails, FakeIB


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


class TestGetContractDetails:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_contract_details(ctx, symbol="AAPL", secType="STK"))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_stock_details(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        contract = FakeContract(
            secType="STK",
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
            conId=265598,
        )
        contract.primaryExchange = "NASDAQ"
        contract.localSymbol = "AAPL"
        fake_ib.contract_details = [
            FakeContractDetails(
                contract=contract,
                longName="APPLE INC",
                industry="Consumer Electronics",
                category="Technology",
                subcategory="Computers",
                tradingHours="20260429:0930-20260429:1600",
                liquidHours="20260429:0930-20260429:1600",
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_contract_details(ctx, symbol="AAPL", secType="STK"))

        assert payload["conId"] == 265598
        assert payload["symbol"] == "AAPL"
        assert payload["secType"] == "STK"
        assert payload["primaryExchange"] == "NASDAQ"
        assert payload["currency"] == "USD"
        assert payload["localSymbol"] == "AAPL"
        assert payload["longName"] == "APPLE INC"
        assert payload["category"] == "Technology"
        assert payload["subcategory"] == "Computers"
        assert payload["industry"] == "Consumer Electronics"
        assert payload["tradingHours"] == "20260429:0930-20260429:1600"
        assert payload["liquidHours"] == "20260429:0930-20260429:1600"
        # Equity payload must NOT carry option-only fields when empty.
        assert "strike" not in payload
        assert "right" not in payload
        assert "expiry" not in payload

    async def test_option_details_include_strike_right_expiry_multiplier(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        contract = FakeContract(
            secType="OPT",
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
            conId=4123456,
            right="C",
            strike=150.0,
            lastTradeDateOrContractMonth="20260516",
            multiplier="100",
        )
        fake_ib.contract_details = [
            FakeContractDetails(
                contract=contract,
                longName="APPLE INC",
                tradingHours="20260516:0930-20260516:1600",
                liquidHours="20260516:0930-20260516:1600",
                realExpirationDate="20260516",
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(
            await get_contract_details(
                ctx,
                symbol="AAPL",
                secType="OPT",
                expiry="20260516",
                strike=150.0,
                right="C",
            )
        )

        assert payload["secType"] == "OPT"
        assert payload["strike"] == 150.0
        assert payload["right"] == "C"
        assert payload["expiry"] == "20260516"
        assert payload["multiplier"] == "100"
        assert payload["lastTradeDate"] == "20260516"

    async def test_invalid_contract_validation_error(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        # OPT requires expiry/strike/right — all missing.
        payload = json.loads(await get_contract_details(ctx, symbol="AAPL", secType="OPT"))
        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value

    async def test_empty_results_returns_invalid_contract(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.contract_details = []
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_contract_details(ctx, symbol="ZZZZZZ", secType="STK"))

        assert payload["code"] == ErrorCode.IB_INVALID_CONTRACT.value

    async def test_call_uses_built_contract(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        contract = FakeContract(
            secType="STK", symbol="AAPL", exchange="SMART", currency="USD", conId=1
        )
        fake_ib.contract_details = [FakeContractDetails(contract=contract)]
        ctx = _make_ctx(fake_ib, settings_factory())

        await get_contract_details(ctx, symbol="MSFT", secType="STK")

        assert len(fake_ib.contract_details_calls) == 1
        called = fake_ib.contract_details_calls[0]
        assert called.symbol == "MSFT"
        assert called.secType == "STK"


class TestRegistration:
    def test_register_attaches_tool(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_contract_details" in names
