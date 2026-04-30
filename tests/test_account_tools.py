"""Tests for ``ibkr_mcp.tools.account``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from ib_async import IB
from mcp.server.fastmcp import Context

from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.errors import ErrorCode
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.account import get_account_info, get_positions

from .fake_ib import (
    FakeIB,
    FakePosition,
    make_account_summary,
    make_option_position,
    make_stock_position,
)


def _make_ctx(
    fake_ib: FakeIB,
    settings: Settings,
    *,
    account_id: str | None = "U1234567",
    connected: bool = True,
) -> Context:  # type: ignore[type-arg]
    fake_ib.connected = connected
    mgr = ConnectionManager(settings=settings, ib=cast(IB, fake_ib))
    mgr._account_id = account_id
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


# ============================================================ get_account_info
class TestGetAccountInfo:
    async def test_returns_summary(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.account_summary = make_account_summary(
            account="U1234567",
            net_liquidation=150_000.0,
            total_cash=50_000.0,
            buying_power=90_000.0,
        )
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_account_info(ctx))

        assert payload["accountId"] == "U1234567"
        assert payload["netLiquidation"] == 150_000.0
        assert payload["totalCashValue"] == 50_000.0
        assert payload["buyingPower"] == 90_000.0
        assert "timestamp" in payload

    async def test_disconnected_returns_ib_not_connected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)

        payload = json.loads(await get_account_info(ctx))

        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_unknown_account_returns_account_not_found(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567"]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_account_info(ctx, accountId="U9999999"))

        assert payload["code"] == ErrorCode.IB_ACCOUNT_NOT_FOUND.value

    async def test_account_filter_keeps_only_target(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # Mix two accounts in the response — the tool must filter to the target.
        fake_ib.account_summary = [
            *make_account_summary(account="U1234567", net_liquidation=150_000.0),
            *make_account_summary(account="U7777777", net_liquidation=999_999.0),
        ]
        fake_ib.managed_accounts = ["U1234567", "U7777777"]
        ctx = _make_ctx(fake_ib, settings_factory(), account_id="U1234567")

        payload = json.loads(await get_account_info(ctx))

        assert payload["accountId"] == "U1234567"
        assert payload["netLiquidation"] == 150_000.0

    async def test_missing_tags_serialise_as_null(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # Only NetLiquidation is returned by the gateway.
        from .fake_ib import _AccountValue

        fake_ib.account_summary = [
            _AccountValue(account="U1234567", tag="NetLiquidation", value="100000", currency="USD")
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_account_info(ctx))

        assert payload["netLiquidation"] == 100_000.0
        assert payload.get("buyingPower") is None
        assert payload.get("maintMarginReq") is None

    async def test_no_account_linked_returns_account_not_found(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), account_id=None)

        payload = json.loads(await get_account_info(ctx))

        assert payload["code"] == ErrorCode.IB_ACCOUNT_NOT_FOUND.value


# ============================================================ get_positions
class TestGetPositions:
    async def test_disconnected_returns_ib_not_connected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)

        payload = json.loads(await get_positions(ctx))

        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_returns_stock_position_with_market_data(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.portfolio_data = [
            make_stock_position(
                account="U1234567",
                symbol="AAPL",
                quantity=100,
                avg_cost=145.20,
                market_price=150.50,
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_positions(ctx))

        assert payload["account"] == "U1234567"
        assert len(payload["positions"]) == 1
        pos = payload["positions"][0]
        assert pos["symbol"] == "AAPL"
        assert pos["secType"] == "STK"
        assert pos["position"] == 100.0
        assert pos["marketPrice"] == 150.50
        assert pos["unrealizedPnL"] == pytest.approx(530.0)
        # Stock positions must NOT include option fields populated.
        assert pos.get("right") is None
        assert pos.get("strike") is None
        assert pos.get("expiry") is None
        assert pos.get("multiplier") is None

    async def test_option_position_includes_all_option_fields(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        """Spec §6.3 mandates options carry right/strike/expiry/multiplier."""
        fake_ib.portfolio_data = [
            make_option_position(
                account="U1234567",
                symbol="AAPL",
                quantity=-5,
                strike=150.0,
                right="C",
                expiry="20260516",
                multiplier="100",
                avg_cost=320.0,
                market_price=3.50,
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_positions(ctx))

        opt = payload["positions"][0]
        assert opt["secType"] == "OPT"
        assert opt["right"] == "C"
        assert opt["strike"] == 150.0
        assert opt["expiry"] == "20260516"
        assert opt["multiplier"] == 100
        assert opt["position"] == -5.0
        assert opt["marketPrice"] == 3.50

    async def test_account_filter_excludes_other_accounts(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.portfolio_data = [
            make_stock_position(account="U1234567", symbol="AAPL", quantity=100),
            make_stock_position(account="U7777777", symbol="MSFT", quantity=50),
        ]
        fake_ib.managed_accounts = ["U1234567", "U7777777"]
        ctx = _make_ctx(fake_ib, settings_factory(), account_id="U1234567")

        payload = json.loads(await get_positions(ctx))

        symbols = {p["symbol"] for p in payload["positions"]}
        assert symbols == {"AAPL"}

    async def test_unknown_account_returns_account_not_found(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567"]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_positions(ctx, accountId="U9999999"))

        assert payload["code"] == ErrorCode.IB_ACCOUNT_NOT_FOUND.value

    async def test_falls_back_to_req_positions_when_portfolio_empty(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        from .fake_ib import FakeContract

        fake_ib.portfolio_data = []
        fake_ib.positions_data = [
            FakePosition(
                account="U1234567",
                contract=FakeContract(
                    secType="STK",
                    symbol="GOOG",
                    exchange="SMART",
                    currency="USD",
                    conId=99,
                ),
                position=10,
                avgCost=2700.0,
            ),
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_positions(ctx))

        assert len(payload["positions"]) == 1
        pos = payload["positions"][0]
        assert pos["symbol"] == "GOOG"
        assert pos["avgCost"] == 2700.0
        # Fallback path doesn't have market data — fields default to None.
        assert pos.get("marketPrice") is None

    async def test_empty_portfolio_returns_empty_list(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_positions(ctx))

        assert payload["positions"] == []
        assert payload["account"] == "U1234567"


class TestRegistration:
    def test_register_attaches_both_tools(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_account_info" in names
        assert "get_positions" in names
