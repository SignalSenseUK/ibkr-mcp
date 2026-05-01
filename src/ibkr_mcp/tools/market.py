"""``get_market_data`` and ``get_historical_data`` tools (spec §6.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.market import (
    HistoricalBar,
    HistoricalDataResponse,
    MarketDataResponse,
    OptionChainDiscovery,
    OptionChainResponse,
    OptionChainStrike,
)
from ibkr_mcp.server import AppContext
from ibkr_mcp.utils.contracts import build_contract
from ibkr_mcp.utils.durations import parse_duration

# ib_async ``Ticker`` exposes Greeks under several attributes, in this order
# of preference (most stable → most volatile). Spec §2.7 of the implementation
# plan locks this priority.
_GREEKS_PRIORITY: tuple[str, ...] = (
    "modelGreeks",
    "lastGreeks",
    "bidGreeks",
    "askGreeks",
)


def _safe_float(value: Any) -> float | None:
    """Coerce IB's NaN/None/strings to Optional[float]."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # ib_async returns NaN for missing fields; treat as None.
    if result != result:  # NaN check
        return None
    return result


def _extract_greeks(ticker: Any) -> dict[str, float | None]:
    """Pick the highest-priority non-empty Greeks bundle from a Ticker."""
    for attr in _GREEKS_PRIORITY:
        bundle = getattr(ticker, attr, None)
        if bundle is None:
            continue
        delta = _safe_float(getattr(bundle, "delta", None))
        gamma = _safe_float(getattr(bundle, "gamma", None))
        theta = _safe_float(getattr(bundle, "theta", None))
        vega = _safe_float(getattr(bundle, "vega", None))
        iv = _safe_float(getattr(bundle, "impliedVol", None))
        if any(v is not None for v in (delta, gamma, theta, vega, iv)):
            return {
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "impliedVolatility": iv,
            }
    return {
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
        "impliedVolatility": None,
    }


# ============================================================ get_market_data
@tool_error_handler
@tool_call_logger
async def get_market_data(
    ctx: Context,  # type: ignore[type-arg]
    symbol: str,
    secType: str,
    exchange: str = "SMART",
    currency: str = "USD",
    expiry: str | None = None,
    strike: float | None = None,
    right: str | None = None,
) -> str:
    """Get a real-time snapshot quote for any instrument — stocks, options, futures, forex, bonds, or indices. Provide the symbol and security type. For options, also provide expiry, strike, and right (C/P). Returns bid, ask, last price, volume, and for options also includes Greeks (delta, gamma, theta, vega) and implied volatility."""

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
        qualified = await ib.qualifyContractsAsync(contract)
        # ``qualifyContractsAsync`` is typed loosely upstream — normalise.
        qualified_list: list[Any] = list(qualified) if isinstance(qualified, list) else [qualified]
        resolved: Any = next((q for q in qualified_list if q is not None), None)
        if resolved is None:
            return make_error(
                ErrorCode.IB_INVALID_CONTRACT,
                f"Could not qualify contract for {symbol!r} ({secType!r}).",
            )
        tickers = await ib.reqTickersAsync(resolved)

    if not tickers:
        return make_error(
            ErrorCode.IB_NO_MARKET_DATA,
            f"No market data returned for {symbol!r}.",
        )
    ticker = tickers[0]

    sec_upper = secType.upper()
    payload: dict[str, Any] = {
        "symbol": symbol,
        "secType": sec_upper,
        "exchange": exchange,
        "currency": currency,
        "lastPrice": _safe_float(getattr(ticker, "last", None)),
        "bid": _safe_float(getattr(ticker, "bid", None)),
        "ask": _safe_float(getattr(ticker, "ask", None)),
        "bidSize": _safe_float(getattr(ticker, "bidSize", None)),
        "askSize": _safe_float(getattr(ticker, "askSize", None)),
        "volume": _safe_float(getattr(ticker, "volume", None)),
        "high": _safe_float(getattr(ticker, "high", None)),
        "low": _safe_float(getattr(ticker, "low", None)),
        "open": _safe_float(getattr(ticker, "open", None)),
        "close": _safe_float(getattr(ticker, "close", None)),
        "timestamp": datetime.now(UTC),
    }

    if sec_upper in {"OPT", "FOP"}:
        payload["expiry"] = expiry
        payload["strike"] = strike
        payload["right"] = right.upper() if right else None
        payload["openInterest"] = _safe_float(getattr(ticker, "openInterest", None))
        payload.update(_extract_greeks(ticker))

    return MarketDataResponse.model_validate(payload).model_dump_json(exclude_none=True)


# ============================================================ get_historical_data
@tool_error_handler
@tool_call_logger
async def get_historical_data(
    ctx: Context,  # type: ignore[type-arg]
    symbol: str,
    secType: str,
    duration: str,
    barSize: str,
    exchange: str = "SMART",
    currency: str = "USD",
    endDateTime: str = "",
    expiry: str | None = None,
    strike: float | None = None,
    right: str | None = None,
) -> str:
    """Retrieve historical OHLCV price bars for any instrument. Specify duration (how far back) and bar size (candle interval). Accepts both IB-native duration strings (e.g. '30 D', '1 Y') and ISO 8601 durations (e.g. 'P30D', 'P1Y', 'PT1H'). Bar sizes follow IB format: '1 min', '5 mins', '1 hour', '1 day', '1 week'."""

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

    try:
        ib_duration = parse_duration(duration)
    except ValueError as exc:
        return make_error(ErrorCode.VALIDATION_ERROR, str(exc))

    ib = app_ctx.manager.ib
    async with app_ctx.ib_lock:
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime=endDateTime,
            durationStr=ib_duration,
            barSizeSetting=barSize,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

    serialised: list[HistoricalBar] = []
    for bar in bars or []:
        date_value = getattr(bar, "date", "")
        date_str = (
            date_value.strftime("%Y%m%d %H:%M:%S")
            if hasattr(date_value, "strftime")
            else str(date_value)
        )
        serialised.append(
            HistoricalBar(
                date=date_str,
                open=_safe_float(getattr(bar, "open", None)),
                high=_safe_float(getattr(bar, "high", None)),
                low=_safe_float(getattr(bar, "low", None)),
                close=_safe_float(getattr(bar, "close", None)),
                volume=_safe_float(getattr(bar, "volume", None)),
                wap=_safe_float(getattr(bar, "average", None)),
                count=int(getattr(bar, "barCount", 0) or 0) or None,
            )
        )

    response = HistoricalDataResponse(
        symbol=symbol,
        secType=secType.upper(),
        barSize=barSize,
        bars=serialised,
    )
    return response.model_dump_json(exclude_none=True)


# ============================================================ get_option_chain
def _safe_int(value: Any, default: int = 100) -> int:
    """Coerce IB's str/int multiplier representation to an ``int``."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


@tool_error_handler
@tool_call_logger
async def get_option_chain(
    ctx: Context,  # type: ignore[type-arg]
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    expiry: str | None = None,
    right: str | None = None,
) -> str:
    """Fetch the option chain for an underlying symbol. Without an expiry date, returns available expirations and strikes (discovery mode). With an expiry date, returns full per-contract data including bid, ask, volume, open interest, and Greeks for each strike."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    if not app_ctx.manager.is_connected:
        return make_error(ErrorCode.IB_NOT_CONNECTED, "Not connected to IB Gateway.")

    ib = app_ctx.manager.ib

    # 1) Resolve the underlying so we have a conId for ``reqSecDefOptParamsAsync``.
    try:
        underlying = build_contract(
            symbol=symbol,
            secType="STK",
            exchange=exchange,
            currency=currency,
        )
    except ValueError as exc:
        return make_error(ErrorCode.IB_INVALID_CONTRACT, str(exc))

    async with app_ctx.ib_lock:
        qualified = await ib.qualifyContractsAsync(underlying)
        qualified_list: list[Any] = list(qualified) if isinstance(qualified, list) else [qualified]
        resolved: Any = next((q for q in qualified_list if q is not None), None)
        if resolved is None:
            return make_error(
                ErrorCode.IB_INVALID_CONTRACT,
                f"Could not qualify underlying {symbol!r}.",
            )
        params = await ib.reqSecDefOptParamsAsync(
            underlyingSymbol=symbol,
            futFopExchange="",
            underlyingSecType="STK",
            underlyingConId=int(getattr(resolved, "conId", 0) or 0),
        )

    if not params:
        return make_error(
            ErrorCode.IB_NO_MARKET_DATA,
            f"No option chain available for {symbol!r}.",
        )

    # Aggregate exchanges/expirations/strikes across the returned chains.
    exchanges = sorted(
        {str(getattr(p, "exchange", "")) for p in params if getattr(p, "exchange", None)}
    )
    expirations: set[str] = set()
    strikes: set[float] = set()
    multiplier_default = 100
    for chain in params:
        for exp in getattr(chain, "expirations", None) or []:
            expirations.add(str(exp))
        for strike in getattr(chain, "strikes", None) or []:
            try:
                strikes.add(float(strike))
            except (TypeError, ValueError):
                continue
        multiplier_default = _safe_int(getattr(chain, "multiplier", None), multiplier_default)

    # ---------- Discovery mode (no expiry): NEVER fetch per-contract data. -----
    if not expiry:
        return OptionChainDiscovery(
            underlying=symbol,
            exchanges=exchanges,
            expirations=sorted(expirations),
            strikes=sorted(strikes),
            multiplier=multiplier_default,
        ).model_dump_json(exclude_none=True)

    # ---------- Full chain mode (with expiry): fetch per-strike snapshots. ----
    if expiry not in expirations:
        return make_error(
            ErrorCode.IB_INVALID_CONTRACT,
            f"Expiry {expiry!r} is not in the available chain for {symbol!r}.",
        )

    rights: tuple[str, ...]
    if right is None:
        rights = ("C", "P")
    elif right.upper() in {"C", "P"}:
        rights = (right.upper(),)
    else:
        return make_error(
            ErrorCode.VALIDATION_ERROR,
            f"`right` must be one of 'C', 'P', or omitted; got {right!r}.",
        )

    sorted_strikes = sorted(strikes)

    # Build a Contract per (strike, right). build_contract enforces required
    # fields and raises on bad combos.
    contracts: list[Any] = []
    descriptors: list[tuple[float, str]] = []
    for strike in sorted_strikes:
        for r in rights:
            try:
                c = build_contract(
                    symbol=symbol,
                    secType="OPT",
                    exchange=exchange,
                    currency=currency,
                    expiry=expiry,
                    strike=strike,
                    right=r,
                )
            except ValueError as exc:
                return make_error(ErrorCode.IB_INVALID_CONTRACT, str(exc))
            contracts.append(c)
            descriptors.append((strike, r))

    async with app_ctx.ib_lock:
        # Single batched snapshot — never streaming. ib_async returns one
        # ticker per contract in input order.
        tickers = await ib.reqTickersAsync(*contracts)

    chains: list[OptionChainStrike] = []
    for (strike, r), ticker in zip(descriptors, tickers or [], strict=False):
        contract_obj = getattr(ticker, "contract", None)
        greeks = _extract_greeks(ticker)
        chains.append(
            OptionChainStrike(
                strike=strike,
                right=r,
                conId=int(getattr(contract_obj, "conId", 0) or 0) or None,
                lastPrice=_safe_float(getattr(ticker, "last", None)),
                bid=_safe_float(getattr(ticker, "bid", None)),
                ask=_safe_float(getattr(ticker, "ask", None)),
                volume=_safe_float(getattr(ticker, "volume", None)),
                openInterest=_safe_float(getattr(ticker, "openInterest", None)),
                impliedVolatility=greeks["impliedVolatility"],
                delta=greeks["delta"],
                gamma=greeks["gamma"],
                theta=greeks["theta"],
                vega=greeks["vega"],
            )
        )

    return OptionChainResponse(
        underlying=symbol,
        expiry=expiry,
        multiplier=multiplier_default,
        chains=chains,
    ).model_dump_json(exclude_none=True)


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach the market-data tools to ``mcp``."""
    mcp.tool()(get_market_data)
    mcp.tool()(get_historical_data)
    mcp.tool()(get_option_chain)
