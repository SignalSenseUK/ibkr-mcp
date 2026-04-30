"""``get_order_status`` and ``get_live_orders`` tools (spec §6.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.orders import (
    LiveOrderItem,
    LiveOrdersResponse,
    OrderStatusResponse,
)
from ibkr_mcp.server import AppContext

# Order types whose ``Order.lmtPrice`` carries a meaningful value.
_LIMIT_TYPES: frozenset[str] = frozenset({"LMT", "STP LMT", "TRAIL LIMIT", "REL"})
# Order types whose ``Order.auxPrice`` carries a meaningful stop trigger price.
_STOP_TYPES: frozenset[str] = frozenset({"STP", "STP LMT", "TRAIL", "TRAIL LIMIT"})


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _resolve_account(app_ctx: AppContext, requested: str | None) -> tuple[str | None, str | None]:
    """Same contract as ``tools.account._resolve_account`` — kept local to avoid
    cross-module coupling between order and account modules."""

    if requested is None:
        return app_ctx.account_id, None

    try:
        managed = [str(a) for a in app_ctx.manager.ib.managedAccounts() or []]
    except Exception:
        managed = []

    if requested not in managed:
        return None, (
            f"Account {requested!r} is not linked to this Gateway connection "
            f"(managed accounts: {managed})."
        )
    return requested, None


def _trade_account(trade: Any) -> str:
    """Best-effort extraction of the account id a trade belongs to."""
    order = getattr(trade, "order", None)
    return str(getattr(order, "account", "") or "") if order else ""


def _limit_price_for(order: Any) -> float | None:
    if str(getattr(order, "orderType", "") or "").upper() not in _LIMIT_TYPES:
        return None
    return _safe_float(getattr(order, "lmtPrice", None))


def _stop_price_for(order: Any) -> float | None:
    if str(getattr(order, "orderType", "") or "").upper() not in _STOP_TYPES:
        return None
    return _safe_float(getattr(order, "auxPrice", None))


def _commission_total(fills: list[Any]) -> float | None:
    """Sum commissions across a trade's fills.

    Returns ``None`` when no fill carries a commission report (e.g. for orders
    that haven't been filled yet); otherwise the summed total.
    """
    total: float = 0.0
    saw_commission = False
    for fill in fills or []:
        report = getattr(fill, "commissionReport", None)
        if report is None:
            continue
        commission = _safe_float(getattr(report, "commission", None))
        if commission is None:
            continue
        total += commission
        saw_commission = True
    return total if saw_commission else None


def _submitted_at(trade: Any) -> datetime | None:
    """First entry in ``trade.log`` is the order submission."""
    log = getattr(trade, "log", None) or []
    if not log:
        return None
    first = log[0]
    raw = getattr(first, "time", None)
    return raw if isinstance(raw, datetime) else None


def _filled_at(trade: Any, status: str) -> datetime | None:
    """Most recent log entry where ``status`` says the order is filled."""
    if status not in {"Filled", "PartiallyFilled"}:
        return None
    candidates: list[datetime] = []
    for entry in getattr(trade, "log", None) or []:
        entry_status = str(getattr(entry, "status", "") or "")
        if entry_status not in {"Filled", "PartiallyFilled"}:
            continue
        raw = getattr(entry, "time", None)
        if isinstance(raw, datetime):
            candidates.append(raw)
    return max(candidates) if candidates else None


def _trade_to_status(trade: Any) -> OrderStatusResponse:
    """Map an ``ib_async.Trade`` to the spec §6.5 ``OrderStatusResponse``."""

    contract = trade.contract
    order = trade.order
    order_status = trade.orderStatus
    order_type = str(getattr(order, "orderType", "") or "")
    status_value = str(getattr(order_status, "status", "") or "")

    return OrderStatusResponse(
        orderId=int(getattr(order, "orderId", 0) or 0),
        status=status_value,
        symbol=str(getattr(contract, "symbol", "") or ""),
        secType=str(getattr(contract, "secType", "") or ""),
        action=str(getattr(order, "action", "") or ""),
        quantity=_safe_float(getattr(order, "totalQuantity", 0.0)) or 0.0,
        orderType=order_type,
        limitPrice=_limit_price_for(order),
        stopPrice=_stop_price_for(order),
        filledQuantity=_safe_float(getattr(order_status, "filled", 0.0)) or 0.0,
        avgFillPrice=_safe_float(getattr(order_status, "avgFillPrice", None)),
        commission=_commission_total(list(getattr(trade, "fills", None) or [])),
        submittedAt=_submitted_at(trade),
        filledAt=_filled_at(trade, status_value),
    )


def _trade_to_live(trade: Any) -> LiveOrderItem:
    """Map an ``ib_async.Trade`` to the spec §6.5 ``LiveOrderItem``."""
    contract = trade.contract
    order = trade.order
    order_status = trade.orderStatus
    order_type = str(getattr(order, "orderType", "") or "")
    status_value = str(getattr(order_status, "status", "") or "")
    return LiveOrderItem(
        orderId=int(getattr(order, "orderId", 0) or 0),
        status=status_value,
        symbol=str(getattr(contract, "symbol", "") or ""),
        secType=str(getattr(contract, "secType", "") or ""),
        action=str(getattr(order, "action", "") or ""),
        quantity=_safe_float(getattr(order, "totalQuantity", 0.0)) or 0.0,
        orderType=order_type,
        limitPrice=_limit_price_for(order),
        stopPrice=_stop_price_for(order),
        filledQuantity=_safe_float(getattr(order_status, "filled", 0.0)) or 0.0,
        submittedAt=_submitted_at(trade),
    )


# ============================================================ get_order_status
@tool_error_handler
@tool_call_logger
async def get_order_status(
    ctx: Context,  # type: ignore[type-arg]
    orderId: int,
) -> str:
    """Get the current status of a specific order by its order ID. Returns fill status, quantities, prices, commission, and timestamps. Use this to check if an order has been filled, partially filled, or cancelled."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    if not app_ctx.manager.is_connected:
        return make_error(ErrorCode.IB_NOT_CONNECTED, "Not connected to IB Gateway.")

    ib = app_ctx.manager.ib
    # ``trades()`` is sync — no lock needed since it reads cached state.
    for trade in ib.trades() or []:
        order = getattr(trade, "order", None)
        if order is None:
            continue
        if int(getattr(order, "orderId", -1) or -1) == int(orderId):
            return _trade_to_status(trade).model_dump_json(exclude_none=True)

    return make_error(
        ErrorCode.VALIDATION_ERROR,
        f"Order {orderId} not found in this session.",
    )


# ============================================================ get_live_orders
@tool_error_handler
@tool_call_logger
async def get_live_orders(
    ctx: Context,  # type: ignore[type-arg]
    accountId: str | None = None,
) -> str:
    """List all currently open or pending orders for the account. Returns order details including status, symbol, action, quantity, order type, and limit/stop prices. Optionally filter by account ID."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    if not app_ctx.manager.is_connected:
        return make_error(ErrorCode.IB_NOT_CONNECTED, "Not connected to IB Gateway.")

    account, err = _resolve_account(app_ctx, accountId)
    if err is not None:
        return make_error(ErrorCode.IB_ACCOUNT_NOT_FOUND, err)
    if account is None:
        return make_error(
            ErrorCode.IB_ACCOUNT_NOT_FOUND,
            "No account is linked to this Gateway connection.",
        )

    ib = app_ctx.manager.ib
    # Refresh the open-orders cache, then read it.
    async with app_ctx.ib_lock:
        await ib.reqOpenOrdersAsync()

    orders: list[LiveOrderItem] = []
    for trade in ib.trades() or []:
        # Live orders are those still open. ``Trade.isActive()`` exists in
        # ib_async but we read the status directly to keep the FakeIB simple.
        order_status = getattr(trade, "orderStatus", None)
        status_value = str(getattr(order_status, "status", "") or "") if order_status else ""
        if status_value not in {
            "PendingSubmit",
            "Submitted",
            "ApiPending",
            "PreSubmitted",
            "PartiallyFilled",
        }:
            continue
        if accountId is not None and _trade_account(trade) and _trade_account(trade) != account:
            continue
        orders.append(_trade_to_live(trade))

    response = LiveOrdersResponse(
        account=account,
        timestamp=datetime.now(UTC),
        orders=orders,
    )
    return response.model_dump_json(exclude_none=True)


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach the order-monitoring tools to ``mcp``."""
    mcp.tool()(get_order_status)
    mcp.tool()(get_live_orders)
