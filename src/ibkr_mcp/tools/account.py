"""``get_account_info`` and ``get_positions`` tools (spec §6.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.account import AccountInfoResponse
from ibkr_mcp.models.positions import (
    PortfolioGreekItem,
    PortfolioGreeksResponse,
    PositionItem,
    PositionsResponse,
)
from ibkr_mcp.server import AppContext
from ibkr_mcp.utils.black_scholes import fallback_greeks

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


# --------------------------------------------------------------- get_portfolio_greeks
_GREEKS_PRIORITY: tuple[str, ...] = (
    "modelGreeks",
    "lastGreeks",
    "bidGreeks",
    "askGreeks",
)


def _greeks_from_ticker(ticker: Any) -> tuple[dict[str, float] | None, float | None]:
    """Pull (greeks, last_iv) from a ticker following the spec §2.7 priority.

    Returns ``(None, last_iv_if_available)`` when no priority bundle has any
    Greeks — callers can then attempt the BS fallback using the last IV.
    """
    last_iv: float | None = None
    for attr in _GREEKS_PRIORITY:
        bundle = getattr(ticker, attr, None)
        if bundle is None:
            continue
        delta = _safe_float(getattr(bundle, "delta", None))
        gamma = _safe_float(getattr(bundle, "gamma", None))
        theta = _safe_float(getattr(bundle, "theta", None))
        vega = _safe_float(getattr(bundle, "vega", None))
        iv = _safe_float(getattr(bundle, "impliedVol", None))
        if last_iv is None and iv is not None:
            last_iv = iv
        if any(v is not None for v in (delta, gamma, theta, vega)):
            return (
                {
                    "delta": delta or 0.0,
                    "gamma": gamma or 0.0,
                    "theta": theta or 0.0,
                    "vega": vega or 0.0,
                },
                iv if iv is not None else last_iv,
            )
    return None, last_iv


def _underlying_spot(ticker: Any) -> float | None:
    """Best-effort underlying spot extracted from a ticker bundle."""
    for attr in ("modelGreeks", "lastGreeks"):
        bundle = getattr(ticker, attr, None)
        if bundle is None:
            continue
        spot = _safe_float(getattr(bundle, "undPrice", None))
        if spot is not None:
            return spot
    return None


@tool_error_handler
@tool_call_logger
async def get_portfolio_greeks(
    ctx: Context,  # type: ignore[type-arg]
    accountId: str | None = None,
) -> str:
    """Get aggregated Greeks (delta, gamma, theta, vega) across all option positions in the portfolio. Also returns per-position Greek breakdowns. Useful for understanding overall portfolio risk exposure from options."""

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

    # Pull option positions for the requested account.
    portfolio_items: list[Any] = []
    try:
        portfolio_items = list(ib.portfolio() or [])
    except Exception:
        portfolio_items = []

    option_items: list[Any] = []
    for item in portfolio_items:
        contract = getattr(item, "contract", None)
        if contract is None:
            continue
        if str(getattr(contract, "secType", "") or "") not in {"OPT", "FOP"}:
            continue
        if getattr(item, "account", account) != account:
            continue
        option_items.append(item)

    breakdown: list[PortfolioGreekItem] = []
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    now = datetime.now(UTC)

    if option_items:
        contracts = [item.contract for item in option_items]
        async with app_ctx.ib_lock:
            tickers = await ib.reqTickersAsync(*contracts)

        # Map contracts back to tickers via input order.
        for item, ticker in zip(option_items, tickers or [], strict=False):
            contract = item.contract
            position = _safe_float(getattr(item, "position", 0.0)) or 0.0
            multiplier = _safe_int(getattr(contract, "multiplier", None)) or 100

            greeks, last_iv = _greeks_from_ticker(ticker)
            source = "model"
            if greeks is None:
                # Try BS fallback when last IV is known.
                spot = _underlying_spot(ticker) or _safe_float(getattr(item, "marketPrice", None))
                bs = fallback_greeks(
                    right=str(getattr(contract, "right", "") or ""),
                    spot=spot,
                    strike=_safe_float(getattr(contract, "strike", None)),
                    expiry_yyyymmdd=str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")
                    or None,
                    iv=last_iv,
                    valuation_date=now,
                )
                if bs is None:
                    breakdown.append(
                        PortfolioGreekItem(
                            symbol=str(getattr(contract, "symbol", "") or ""),
                            expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "") or ""),
                            strike=_safe_float(getattr(contract, "strike", None)) or 0.0,
                            right=str(getattr(contract, "right", "") or ""),
                            position=position,
                            source="missing",
                        )
                    )
                    continue
                greeks = bs
                source = "fallback"

            # Aggregate position-weighted Greeks. Multiplier is per spec
            # convention (100 for equity options).
            weight = position * float(multiplier)
            position_delta = greeks["delta"] * weight
            position_gamma = greeks["gamma"] * weight
            position_theta = greeks["theta"] * weight
            position_vega = greeks["vega"] * weight

            totals["delta"] += position_delta
            totals["gamma"] += position_gamma
            totals["theta"] += position_theta
            totals["vega"] += position_vega

            breakdown.append(
                PortfolioGreekItem(
                    symbol=str(getattr(contract, "symbol", "") or ""),
                    expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "") or ""),
                    strike=_safe_float(getattr(contract, "strike", None)) or 0.0,
                    right=str(getattr(contract, "right", "") or ""),
                    position=position,
                    delta=position_delta,
                    gamma=position_gamma,
                    theta=position_theta,
                    vega=position_vega,
                    source=source,
                )
            )

    response = PortfolioGreeksResponse(
        account=account,
        timestamp=now,
        totalDelta=totals["delta"],
        totalGamma=totals["gamma"],
        totalTheta=totals["theta"],
        totalVega=totals["vega"],
        positions=breakdown,
    )
    return response.model_dump_json(exclude_none=True)


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach :func:`get_account_info` and :func:`get_positions` to ``mcp``."""
    mcp.tool()(get_account_info)
    mcp.tool()(get_positions)
    mcp.tool()(get_portfolio_greeks)
