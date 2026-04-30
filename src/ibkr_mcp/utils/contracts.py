"""Helpers that turn tool inputs into ``ib_async.Contract`` instances.

Tools never instantiate ``ib_async.Contract`` subclasses directly; they call
:func:`build_contract`, which is the single place where we map user-facing
``secType`` strings to library types and validate the input combination.
"""

from __future__ import annotations

from typing import Final

from ib_async import Bond, Contract, Forex, Future, Index, Option, Stock

# All security types that the spec advertises in ``get_market_data`` (§6.4).
SUPPORTED_SEC_TYPES: Final[frozenset[str]] = frozenset({"STK", "OPT", "FUT", "CASH", "BOND", "IND"})


def build_contract(
    symbol: str,
    secType: str,
    exchange: str = "SMART",
    currency: str = "USD",
    expiry: str | None = None,
    strike: float | None = None,
    right: str | None = None,
    multiplier: str | None = None,
) -> Contract:
    """Construct an ``ib_async.Contract`` from tool-level parameters.

    Raises:
        ValueError: when ``secType`` is unsupported or option/future-specific
            fields are missing for those types.
    """

    if not symbol:
        raise ValueError("symbol is required")

    sec = secType.upper() if secType else ""
    if sec not in SUPPORTED_SEC_TYPES:
        raise ValueError(
            f"Unsupported secType {secType!r}. Expected one of: {sorted(SUPPORTED_SEC_TYPES)}."
        )

    if sec == "STK":
        return Stock(symbol=symbol, exchange=exchange, currency=currency)

    if sec == "OPT":
        if expiry is None or strike is None or right is None:
            raise ValueError("OPT contracts require expiry, strike, and right.")
        right_upper = right.upper()
        if right_upper not in {"C", "P"}:
            raise ValueError(f"Option right must be 'C' or 'P', got {right!r}.")
        return Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=strike,
            right=right_upper,
            exchange=exchange,
            currency=currency,
            multiplier=multiplier or "",
        )

    if sec == "FUT":
        if expiry is None:
            raise ValueError("FUT contracts require expiry.")
        return Future(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            exchange=exchange,
            currency=currency,
            multiplier=multiplier or "",
        )

    if sec == "CASH":
        # ib_async ``Forex`` accepts either a six-letter pair or symbol+currency.
        pair = f"{symbol}{currency}" if currency else symbol
        return Forex(pair=pair, exchange=exchange or "IDEALPRO")

    if sec == "BOND":
        # ``Bond.__init__`` injects ``secType="BOND"`` itself, so we only pass
        # the contract identifying fields. ``Bond`` lacks type stubs in
        # ib_async — cast the call rather than spread ``Any`` through the API.
        bond: Contract = Bond(symbol=symbol, exchange=exchange, currency=currency)  # type: ignore[no-untyped-call]
        return bond

    # IND
    return Index(symbol=symbol, exchange=exchange, currency=currency)
