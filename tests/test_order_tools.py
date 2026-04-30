"""Tests for ``ibkr_mcp.tools.orders``."""

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
from ibkr_mcp.tools.orders import get_live_orders, get_order_status

from .fake_ib import (
    FakeCommissionReport,
    FakeContract,
    FakeFill,
    FakeIB,
    FakeOrder,
    FakeOrderStatus,
    FakeTrade,
    FakeTradeLogEntry,
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


def _stk(symbol: str = "AAPL") -> FakeContract:
    return FakeContract(secType="STK", symbol=symbol, exchange="SMART", currency="USD")


# ============================================================ get_order_status
class TestGetOrderStatus:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_order_status(ctx, orderId=1001))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_filled_order_with_two_fills_aggregates_commission(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        submitted_at = datetime(2026, 4, 29, 15, 25, 0, tzinfo=UTC)
        filled_at = datetime(2026, 4, 29, 15, 25, 1, tzinfo=UTC)

        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("AAPL"),
                order=FakeOrder(orderId=1001, action="BUY", totalQuantity=10, orderType="MKT"),
                orderStatus=FakeOrderStatus(status="Filled", filled=10, avgFillPrice=150.52),
                fills=[
                    FakeFill(commissionReport=FakeCommissionReport(commission=0.50)),
                    FakeFill(commissionReport=FakeCommissionReport(commission=0.50)),
                ],
                log=[
                    FakeTradeLogEntry(time=submitted_at, status="Submitted"),
                    FakeTradeLogEntry(time=filled_at, status="Filled"),
                ],
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_order_status(ctx, orderId=1001))

        assert payload["orderId"] == 1001
        assert payload["status"] == "Filled"
        assert payload["symbol"] == "AAPL"
        assert payload["action"] == "BUY"
        assert payload["quantity"] == 10
        assert payload["filledQuantity"] == 10
        assert payload["avgFillPrice"] == 150.52
        assert payload["commission"] == 1.00  # 0.50 + 0.50
        # Timestamps round-trip through Pydantic's datetime serialiser.
        assert payload["submittedAt"].startswith("2026-04-29T15:25:00")
        assert payload["filledAt"].startswith("2026-04-29T15:25:01")

    async def test_limit_order_includes_limit_price(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("MSFT"),
                order=FakeOrder(
                    orderId=2002,
                    action="BUY",
                    totalQuantity=5,
                    orderType="LMT",
                    lmtPrice=380.0,
                ),
                orderStatus=FakeOrderStatus(status="Submitted"),
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_order_status(ctx, orderId=2002))

        assert payload["orderType"] == "LMT"
        assert payload["limitPrice"] == 380.0
        assert payload.get("stopPrice") is None

    async def test_stop_order_includes_stop_price(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("MSFT"),
                order=FakeOrder(
                    orderId=3003,
                    action="SELL",
                    totalQuantity=5,
                    orderType="STP",
                    auxPrice=350.0,
                ),
                orderStatus=FakeOrderStatus(status="Submitted"),
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_order_status(ctx, orderId=3003))

        assert payload["orderType"] == "STP"
        assert payload["stopPrice"] == 350.0
        assert payload.get("limitPrice") is None

    async def test_unknown_order_id(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = []
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_order_status(ctx, orderId=9999))

        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "9999" in payload["error"]

    async def test_no_fills_yields_null_commission(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("AAPL"),
                order=FakeOrder(orderId=4004, action="BUY", totalQuantity=10),
                orderStatus=FakeOrderStatus(status="Submitted"),
                fills=[],
            )
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_order_status(ctx, orderId=4004))

        assert payload.get("commission") is None
        assert payload.get("filledAt") is None


# ============================================================ get_live_orders
class TestGetLiveOrders:
    async def test_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(), connected=False)
        payload = json.loads(await get_live_orders(ctx))
        assert payload["code"] == ErrorCode.IB_NOT_CONNECTED.value

    async def test_lists_open_orders_only(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("MSFT"),
                order=FakeOrder(
                    orderId=1002,
                    action="BUY",
                    totalQuantity=5,
                    orderType="LMT",
                    lmtPrice=380.0,
                ),
                orderStatus=FakeOrderStatus(status="Submitted"),
                log=[
                    FakeTradeLogEntry(
                        time=datetime(2026, 4, 29, 14, 0, 0, tzinfo=UTC),
                        status="Submitted",
                    )
                ],
            ),
            # Filled and Cancelled orders must be excluded.
            FakeTrade(
                contract=_stk("AAPL"),
                order=FakeOrder(orderId=999, action="BUY", totalQuantity=1),
                orderStatus=FakeOrderStatus(status="Filled"),
            ),
            FakeTrade(
                contract=_stk("GOOG"),
                order=FakeOrder(orderId=998, action="SELL", totalQuantity=1),
                orderStatus=FakeOrderStatus(status="Cancelled"),
            ),
        ]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_live_orders(ctx))

        ids = [o["orderId"] for o in payload["orders"]]
        assert ids == [1002]
        only = payload["orders"][0]
        assert only["status"] == "Submitted"
        assert only["limitPrice"] == 380.0
        assert only["submittedAt"].startswith("2026-04-29T14:00:00")

    async def test_empty_when_no_open_orders(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.trades_data = []
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_live_orders(ctx))

        assert payload["orders"] == []
        assert payload["account"] == "U1234567"

    async def test_account_filter_excludes_other_accounts(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567", "U7777777"]
        fake_ib.trades_data = [
            FakeTrade(
                contract=_stk("AAPL"),
                order=FakeOrder(orderId=1, action="BUY", totalQuantity=1, account="U1234567"),
                orderStatus=FakeOrderStatus(status="Submitted"),
            ),
            FakeTrade(
                contract=_stk("MSFT"),
                order=FakeOrder(orderId=2, action="BUY", totalQuantity=1, account="U7777777"),
                orderStatus=FakeOrderStatus(status="Submitted"),
            ),
        ]
        ctx = _make_ctx(fake_ib, settings_factory(), account_id="U1234567")

        payload = json.loads(await get_live_orders(ctx, accountId="U1234567"))

        ids = [o["orderId"] for o in payload["orders"]]
        assert ids == [1]

    async def test_unknown_account(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567"]
        ctx = _make_ctx(fake_ib, settings_factory())

        payload = json.loads(await get_live_orders(ctx, accountId="U9999999"))

        assert payload["code"] == ErrorCode.IB_ACCOUNT_NOT_FOUND.value

    async def test_refresh_calls_req_open_orders_async(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # Track invocations of reqOpenOrdersAsync.
        original = fake_ib.reqOpenOrdersAsync
        calls = {"count": 0}

        async def counting_refresh() -> list[Any]:
            calls["count"] += 1
            return await original()

        fake_ib.reqOpenOrdersAsync = counting_refresh  # type: ignore[method-assign]

        ctx = _make_ctx(fake_ib, settings_factory())
        await get_live_orders(ctx)

        assert calls["count"] == 1


class TestRegistration:
    def test_register_attaches_both_tools(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_order_status" in names
        assert "get_live_orders" in names
