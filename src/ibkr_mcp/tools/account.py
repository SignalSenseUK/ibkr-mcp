"""``get_account_info`` and ``get_positions`` tools (spec §6.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.account import AccountInfoResponse
from ibkr_mcp.models.positions import PositionItem, PositionsResponse
from ibkr_mcp.server import AppContext

# Map IB ``AccountValue.tag`` to the response field. Only these tags are
# extracted; everything else returned by ``accountSummaryAsync`` is ignored.
_ACCOUNT_TAG_FIELD: dict[str, str] = {
    "NetLiquidation": "netLiquidation",
    "TotalCashValue": "totalCashValue",
    "GrossPositionValue": "grossPositionValue",
    "UnrealizedPnL": "unrealizedPnL",
    "RealizedPnL": "realizedPnL",
    "AvailableFunds": "availableFunds",
    "BuyingPower": "buyingPower",
    "MaintMarginReq": "maintMarginReq",
    "InitMarginReq": "initMarginReq",
}


def _resolve_account(app_ctx: AppContext, requested: str | None) -> tuple[str | None, str | None]:
    """Resolve the effective account id, returning ``(account, error_message)``.

    On success the second element is ``None``. On failure (the requested
    account isn't linked to this gateway connection) the first element is
    ``None`` and the second carries a human-readable message.
    """

    if requested is None:
        return app_ctx.account_id, None

    managed: list[str]
    try:
        raw = app_ctx.manager.ib.managedAccounts()
        managed = [str(a) for a in raw] if raw else []
    except Exception:
        managed = []

    if requested not in managed:
        return None, (
            f"Account {requested!r} is not linked to this Gateway connection "
            f"(managed accounts: {managed})."
        )
    return requested, None


def _safe_float(value: Any) -> float | None:
    """Best-effort numeric coercion that tolerates IB's stringly-typed values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- get_account_info
@tool_error_handler
@tool_call_logger
async def get_account_info(
    ctx: Context,  # type: ignore[type-arg]
    accountId: str | None = None,
) -> str:
    """Retrieve account summary including net liquidation value, buying power, available funds, margin requirements, and P&L. Use this to understand the current financial state of the IBKR account."""

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

    async with app_ctx.ib_lock:
        rows = await app_ctx.manager.ib.accountSummaryAsync(account)

    payload: dict[str, Any] = {"accountId": account, "timestamp": datetime.now(UTC)}
    for row in rows or []:
        # Only consider rows for our target account (accountSummaryAsync may
        # return rows for other linked accounts when called with "" / "All").
        row_account = getattr(row, "account", account) or account
        if row_account != account:
            continue
        tag = getattr(row, "tag", None)
        field = _ACCOUNT_TAG_FIELD.get(tag) if isinstance(tag, str) else None
        if field is None:
            continue
        payload[field] = _safe_float(getattr(row, "value", None))

    return AccountInfoResponse.model_validate(payload).model_dump_json(exclude_none=True)


# --------------------------------------------------------------- get_positions
def _is_option(sec_type: str) -> bool:
    return sec_type in {"OPT", "FOP"}


def _portfolio_item_to_position(item: Any) -> PositionItem:
    contract = item.contract
    sec_type = str(getattr(contract, "secType", "") or "")
    base: dict[str, Any] = {
        "symbol": str(getattr(contract, "symbol", "") or ""),
        "secType": sec_type,
        "exchange": getattr(contract, "exchange", None) or None,
        "currency": getattr(contract, "currency", None) or None,
        "conId": _safe_int(getattr(contract, "conId", None)),
        "position": _safe_float(getattr(item, "position", 0.0)) or 0.0,
        "avgCost": _safe_float(getattr(item, "averageCost", None)),
        "marketPrice": _safe_float(getattr(item, "marketPrice", None)),
        "marketValue": _safe_float(getattr(item, "marketValue", None)),
        "unrealizedPnL": _safe_float(getattr(item, "unrealizedPNL", None)),
        "realizedPnL": _safe_float(getattr(item, "realizedPNL", None)),
    }
    if _is_option(sec_type):
        base["right"] = getattr(contract, "right", None) or None
        base["strike"] = _safe_float(getattr(contract, "strike", None))
        base["expiry"] = getattr(contract, "lastTradeDateOrContractMonth", None) or None
        base["multiplier"] = _safe_int(getattr(contract, "multiplier", None))
    return PositionItem.model_validate(base)


def _basic_position_to_position(item: Any) -> PositionItem:
    contract = item.contract
    sec_type = str(getattr(contract, "secType", "") or "")
    base: dict[str, Any] = {
        "symbol": str(getattr(contract, "symbol", "") or ""),
        "secType": sec_type,
        "exchange": getattr(contract, "exchange", None) or None,
        "currency": getattr(contract, "currency", None) or None,
        "conId": _safe_int(getattr(contract, "conId", None)),
        "position": _safe_float(getattr(item, "position", 0.0)) or 0.0,
        "avgCost": _safe_float(getattr(item, "avgCost", None)),
    }
    if _is_option(sec_type):
        base["right"] = getattr(contract, "right", None) or None
        base["strike"] = _safe_float(getattr(contract, "strike", None))
        base["expiry"] = getattr(contract, "lastTradeDateOrContractMonth", None) or None
        base["multiplier"] = _safe_int(getattr(contract, "multiplier", None))
    return PositionItem.model_validate(base)


@tool_error_handler
@tool_call_logger
async def get_positions(
    ctx: Context,  # type: ignore[type-arg]
    accountId: str | None = None,
) -> str:
    """Get all open positions in the portfolio with contract details, quantity, average cost, market price, and unrealized P&L. Optionally filter by account ID. Includes full contract details for options (strike, expiry, right, multiplier)."""

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
    items: list[PositionItem] = []

    # Prefer ib.portfolio() — it carries marketPrice / unrealizedPnL. Fall
    # back to reqPositionsAsync() if portfolio() is empty (e.g. before account
    # updates have arrived).
    portfolio_items: list[Any] = []
    try:
        portfolio_items = list(ib.portfolio() or [])
    except Exception:
        portfolio_items = []

    if portfolio_items:
        for item in portfolio_items:
            if getattr(item, "account", account) != account:
                continue
            items.append(_portfolio_item_to_position(item))
    else:
        async with app_ctx.ib_lock:
            positions = await ib.reqPositionsAsync()
        for pos in positions or []:
            if getattr(pos, "account", account) != account:
                continue
            items.append(_basic_position_to_position(pos))

    response = PositionsResponse(
        account=account,
        timestamp=datetime.now(UTC),
        positions=items,
    )
    return response.model_dump_json(exclude_none=True)


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach :func:`get_account_info` and :func:`get_positions` to ``mcp``."""
    mcp.tool()(get_account_info)
    mcp.tool()(get_positions)
