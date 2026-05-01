"""Unit tests for the pure-Python Black-Scholes helper."""

from __future__ import annotations

from datetime import date

import pytest

from ibkr_mcp.utils.black_scholes import black_scholes_greeks, fallback_greeks


class TestBlackScholesGreeks:
    def test_atm_call_reference_values(self) -> None:
        """ATM call: S=100, K=100, T=0.5, sigma=0.2, r=0.05, q=0.

        Closed-form reference, computed analytically from
            d1 = (r + 0.5 sigma^2) sqrt(T) / sigma  (since ln(S/K)=0)
                = (0.05 + 0.02) * 0.5 / 0.1414... = 0.2475
            delta_C = N(d1) ≈ 0.5977
            gamma   = phi(d1) / (S sigma sqrt(T)) ≈ 0.02711
            vega    = S phi(d1) sqrt(T) ≈ 27.108  (per 1.00 vol)
        """
        g = black_scholes_greeks(
            right="C",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=0.5,
            iv=0.20,
            risk_free_rate=0.05,
        )
        assert g["delta"] == pytest.approx(0.59773, abs=1e-4)
        assert g["gamma"] == pytest.approx(0.02736, abs=1e-4)
        # Per 1.00 of vol movement; per 1% would be ~0.27359.
        assert g["vega"] == pytest.approx(27.359, abs=1e-2)

    def test_put_delta_sign(self) -> None:
        g = black_scholes_greeks(
            right="P",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=0.5,
            iv=0.20,
            risk_free_rate=0.05,
        )
        # Put delta must be negative for a long put.
        assert g["delta"] < 0
        # Put-call parity for delta (q=0): delta_P = delta_C - 1 ≈ -0.40227.
        assert g["delta"] == pytest.approx(0.59773 - 1.0, abs=1e-4)

    def test_call_theta_negative(self) -> None:
        g = black_scholes_greeks(
            right="C",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=0.5,
            iv=0.20,
        )
        assert g["theta"] < 0

    def test_invalid_right(self) -> None:
        with pytest.raises(ValueError):
            black_scholes_greeks(
                right="X",
                spot=100.0,
                strike=100.0,
                time_to_expiry_years=0.5,
                iv=0.2,
            )

    def test_invalid_iv(self) -> None:
        with pytest.raises(ValueError):
            black_scholes_greeks(
                right="C",
                spot=100.0,
                strike=100.0,
                time_to_expiry_years=0.5,
                iv=0.0,
            )

    def test_zero_time_to_expiry_does_not_div_zero(self) -> None:
        g = black_scholes_greeks(
            right="C",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=0.0,
            iv=0.2,
        )
        # All values are finite numbers (not NaN/inf).
        for v in g.values():
            assert isinstance(v, float)


class TestFallbackGreeks:
    def test_returns_none_when_inputs_missing(self) -> None:
        assert (
            fallback_greeks(
                right="C",
                spot=None,
                strike=100.0,
                expiry_yyyymmdd="20260516",
                iv=0.25,
                valuation_date=date(2026, 4, 30),
            )
            is None
        )
        assert (
            fallback_greeks(
                right="C",
                spot=100.0,
                strike=100.0,
                expiry_yyyymmdd="20260516",
                iv=None,
                valuation_date=date(2026, 4, 30),
            )
            is None
        )
        assert (
            fallback_greeks(
                right="C",
                spot=100.0,
                strike=100.0,
                expiry_yyyymmdd=None,
                iv=0.25,
                valuation_date=date(2026, 4, 30),
            )
            is None
        )

    def test_expiry_in_past_returns_none(self) -> None:
        assert (
            fallback_greeks(
                right="C",
                spot=100.0,
                strike=100.0,
                expiry_yyyymmdd="20200101",
                iv=0.25,
                valuation_date=date(2026, 4, 30),
            )
            is None
        )

    def test_malformed_expiry_returns_none(self) -> None:
        assert (
            fallback_greeks(
                right="C",
                spot=100.0,
                strike=100.0,
                expiry_yyyymmdd="not-a-date",
                iv=0.25,
                valuation_date=date(2026, 4, 30),
            )
            is None
        )

    def test_happy_path(self) -> None:
        g = fallback_greeks(
            right="C",
            spot=150.0,
            strike=150.0,
            expiry_yyyymmdd="20260516",
            iv=0.28,
            valuation_date=date(2026, 4, 30),
            risk_free_rate=0.0,
        )
        assert g is not None
        assert 0.0 < g["delta"] < 1.0
        assert g["gamma"] > 0
        assert g["theta"] < 0
        assert g["vega"] > 0
