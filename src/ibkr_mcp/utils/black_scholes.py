"""Pure-Python Black-Scholes Greeks for European options.

Used by ``get_portfolio_greeks`` as a fallback when ``ib_async`` does not
return ``modelGreeks`` for a position. We deliberately do not depend on
``scipy`` — spec §1.2 mandates a minimal dependency tree — so the normal
CDF/PDF are computed via :func:`math.erf` and :func:`math.exp`.
"""

from __future__ import annotations

import math

# Number of trading days per year used for theta scaling (industry default).
_DAYS_PER_YEAR: int = 365

_MIN_TIME_TO_EXPIRY = 1.0 / (24.0 * 365.0)  # 1 hour, in years


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function of the standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Probability density function of the standard normal."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> tuple[float, float]:
    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * iv * iv) * time_to_expiry_years
    ) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    return d1, d2


def black_scholes_greeks(
    *,
    right: str,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
) -> dict[str, float]:
    """Compute Black-Scholes Greeks for a European option.

    Parameters
    ----------
    right
        ``"C"`` for call, ``"P"`` for put. Case-insensitive.
    spot
        Underlying spot price.
    strike
        Option strike.
    time_to_expiry_years
        Time to expiration in **years** (e.g. 30 days = 30/365).
    iv
        Implied volatility as a decimal (e.g. 0.28 for 28%).
    risk_free_rate
        Annualised risk-free rate as a decimal. Defaults to 0.
    dividend_yield
        Annualised continuous dividend yield. Defaults to 0.

    Returns
    -------
    dict
        ``{"delta", "gamma", "theta", "vega"}`` keyed greeks (theta is per
        calendar day; vega is per 1.00 of vol movement, i.e. per 100%).

    Raises
    ------
    ValueError
        If inputs are non-positive or ``right`` is not in ``{"C","P"}``.
    """
    right_upper = right.upper()
    if right_upper not in {"C", "P"}:
        raise ValueError(f"`right` must be 'C' or 'P', got {right!r}.")
    if spot <= 0 or strike <= 0:
        raise ValueError("Spot and strike must be positive.")
    if iv <= 0:
        raise ValueError("Implied volatility must be positive.")
    if time_to_expiry_years <= 0:
        # Fall back to a tiny non-zero value so we don't divide by zero;
        # the resulting Greeks degenerate gracefully.
        time_to_expiry_years = _MIN_TIME_TO_EXPIRY

    d1, d2 = _d1_d2(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        iv=iv,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    pdf_d1 = _norm_pdf(d1)

    if right_upper == "C":
        delta = math.exp(-dividend_yield * time_to_expiry_years) * _norm_cdf(d1)
    else:
        delta = math.exp(-dividend_yield * time_to_expiry_years) * (_norm_cdf(d1) - 1.0)

    gamma = (
        math.exp(-dividend_yield * time_to_expiry_years)
        * pdf_d1
        / (spot * iv * math.sqrt(time_to_expiry_years))
    )

    # Vega is conventionally quoted per 1% vol; here we return the raw
    # Black-Scholes vega (per 1.00 of vol). Callers can scale.
    vega = (
        spot
        * math.exp(-dividend_yield * time_to_expiry_years)
        * pdf_d1
        * math.sqrt(time_to_expiry_years)
    )

    common_theta = (
        -spot
        * math.exp(-dividend_yield * time_to_expiry_years)
        * pdf_d1
        * iv
        / (2.0 * math.sqrt(time_to_expiry_years))
    )
    if right_upper == "C":
        theta_year = (
            common_theta
            - risk_free_rate
            * strike
            * math.exp(-risk_free_rate * time_to_expiry_years)
            * _norm_cdf(d2)
            + dividend_yield
            * spot
            * math.exp(-dividend_yield * time_to_expiry_years)
            * _norm_cdf(d1)
        )
    else:
        theta_year = (
            common_theta
            + risk_free_rate
            * strike
            * math.exp(-risk_free_rate * time_to_expiry_years)
            * _norm_cdf(-d2)
            - dividend_yield
            * spot
            * math.exp(-dividend_yield * time_to_expiry_years)
            * _norm_cdf(-d1)
        )

    # Convert annual theta to per-day; this mirrors how IB reports theta.
    theta = theta_year / _DAYS_PER_YEAR

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def fallback_greeks(
    *,
    right: str,
    spot: float | None,
    strike: float | None,
    expiry_yyyymmdd: str | None,
    iv: float | None,
    valuation_date: object,
    risk_free_rate: float = 0.0,
) -> dict[str, float] | None:
    """Compute fallback Greeks when the gateway omits ``modelGreeks``.

    Returns ``None`` when any required input is missing — callers should
    treat that as "Greeks unavailable" and skip the position.
    """
    from datetime import date, datetime

    if spot is None or strike is None or iv is None or not expiry_yyyymmdd:
        return None
    if iv <= 0 or spot <= 0 or strike <= 0:
        return None

    try:
        exp_dt = datetime.strptime(expiry_yyyymmdd, "%Y%m%d").date()
    except ValueError:
        return None

    if isinstance(valuation_date, datetime):
        ref_date = valuation_date.date()
    elif isinstance(valuation_date, date):
        ref_date = valuation_date
    else:
        return None

    days = (exp_dt - ref_date).days
    if days < 0:
        return None
    time_to_expiry_years = max(days, 0) / _DAYS_PER_YEAR

    try:
        return black_scholes_greeks(
            right=right,
            spot=spot,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            iv=iv,
            risk_free_rate=risk_free_rate,
        )
    except ValueError:
        return None
