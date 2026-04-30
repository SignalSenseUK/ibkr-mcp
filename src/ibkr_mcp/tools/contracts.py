"""``get_contract_details`` tool (spec §6.6)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.contracts import ContractDetailsResponse
from ibkr_mcp.server import AppContext
from ibkr_mcp.utils.contracts import build_contract


def _str_or_none(value: Any) -> str | None:
    """Normalise IB's empty-string sentinels to ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _details_to_response(
    details: Any,
    *,
    requested_sec_type: str,
    requested_exchange: str,
) -> ContractDetailsResponse:
    """Map an ``ib_async.ContractDetails`` instance to the spec §6.6 schema."""

    contract = details.contract
    sec_type_upper = _str_or_none(getattr(contract, "secType", None)) or requested_sec_type.upper()

    payload: dict[str, Any] = {
        "conId": int(getattr(contract, "conId", 0) or 0),
        "symbol": str(getattr(contract, "symbol", "") or ""),
        "secType": sec_type_upper,
        "exchange": (_str_or_none(getattr(contract, "exchange", None)) or requested_exchange),
        "primaryExchange": _str_or_none(getattr(contract, "primaryExchange", None)),
        "currency": str(getattr(contract, "currency", "") or ""),
        "localSymbol": _str_or_none(getattr(contract, "localSymbol", None)),
        "tradingHours": _str_or_none(getattr(details, "tradingHours", None)),
        "liquidHours": _str_or_none(getattr(details, "liquidHours", None)),
        "longName": _str_or_none(getattr(details, "longName", None)),
        "category": _str_or_none(getattr(details, "category", None)),
        "subcategory": _str_or_none(getattr(details, "subcategory", None)),
        "industry": _str_or_none(getattr(details, "industry", None)),
    }

    if sec_type_upper in {"OPT", "FOP"}:
        strike_raw = getattr(contract, "strike", None)
        try:
            strike = float(strike_raw) if strike_raw is not None else None
        except (TypeError, ValueError):
            strike = None
        # Prefer the contract's expiry; fall back to ContractDetails.realExpirationDate.
        expiry = _str_or_none(getattr(contract, "lastTradeDateOrContractMonth", None))
        last_trade = _str_or_none(getattr(details, "realExpirationDate", None)) or expiry
        payload.update(
            {
                "strike": strike,
                "right": _str_or_none(getattr(contract, "right", None)),
                "expiry": expiry,
                "multiplier": _str_or_none(getattr(contract, "multiplier", None)),
                "lastTradeDate": last_trade,
            }
        )

    return ContractDetailsResponse.model_validate(payload)


# ============================================================ get_contract_details
@tool_error_handler
@tool_call_logger
async def get_contract_details(
    ctx: Context,  # type: ignore[type-arg]
    symbol: str,
    secType: str,
    exchange: str = "SMART",
    currency: str = "USD",
    expiry: str | None = None,
    strike: float | None = None,
    right: str | None = None,
) -> str:
    """Look up full contract details for any instrument — resolves a symbol to its contract ID, primary exchange, trading hours, long name, industry classification, and other metadata. Essential for validating contract parameters before use in other tools. For options, also returns strike, expiry, multiplier, and last trade date."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    if not app_ctx.manager.is_connected:
        return make_error(ErrorCode.IB_NOT_CONNECTED, "Not connected to IB Gateway.")

    try:
        contract = build_contract(
            symbol=symbol,
            secType=secType,
            exchange=exchange,
            currency=currency,
            expiry=expiry,
            strike=strike,
            right=right,
        )
    except ValueError as exc:
        return make_error(ErrorCode.IB_INVALID_CONTRACT, str(exc))

    ib = app_ctx.manager.ib
    async with app_ctx.ib_lock:
        details_list = await ib.reqContractDetailsAsync(contract)

    if not details_list:
        return make_error(
            ErrorCode.IB_INVALID_CONTRACT,
            f"No contract details returned for {symbol!r} ({secType!r}).",
        )

    response = _details_to_response(
        details_list[0],
        requested_sec_type=secType,
        requested_exchange=exchange,
    )
    return response.model_dump_json(exclude_none=True)


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach the contract-details tool to ``mcp``."""
    mcp.tool()(get_contract_details)
