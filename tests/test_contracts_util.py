"""Tests for ``ibkr_mcp.utils.contracts``."""

from __future__ import annotations

import pytest
from ib_async import Bond, Forex, Future, Index, Option, Stock

from ibkr_mcp.utils.contracts import build_contract


class TestStock:
    def test_basic(self) -> None:
        c = build_contract("AAPL", "STK")
        assert isinstance(c, Stock)
        assert c.symbol == "AAPL"
        assert c.exchange == "SMART"
        assert c.currency == "USD"

    def test_overrides(self) -> None:
        c = build_contract("VOD", "STK", exchange="LSE", currency="GBP")
        assert isinstance(c, Stock)
        assert c.exchange == "LSE"
        assert c.currency == "GBP"


class TestOption:
    def test_call(self) -> None:
        c = build_contract("AAPL", "OPT", expiry="20260516", strike=150.0, right="C")
        assert isinstance(c, Option)
        assert c.symbol == "AAPL"
        assert c.lastTradeDateOrContractMonth == "20260516"
        assert c.strike == 150.0
        assert c.right == "C"

    def test_put_lowercase_right_normalised(self) -> None:
        c = build_contract("AAPL", "OPT", expiry="20260516", strike=150.0, right="p")
        assert isinstance(c, Option)
        assert c.right == "P"

    def test_with_multiplier(self) -> None:
        c = build_contract(
            "AAPL",
            "OPT",
            expiry="20260516",
            strike=150.0,
            right="C",
            multiplier="100",
        )
        assert isinstance(c, Option)
        assert c.multiplier == "100"

    @pytest.mark.parametrize(
        ("expiry", "strike", "right"),
        [
            (None, 150.0, "C"),
            ("20260516", None, "C"),
            ("20260516", 150.0, None),
        ],
    )
    def test_missing_required_raises(
        self, expiry: str | None, strike: float | None, right: str | None
    ) -> None:
        with pytest.raises(ValueError):
            build_contract("AAPL", "OPT", expiry=expiry, strike=strike, right=right)

    def test_invalid_right_raises(self) -> None:
        with pytest.raises(ValueError):
            build_contract("AAPL", "OPT", expiry="20260516", strike=150.0, right="X")


class TestFuture:
    def test_basic(self) -> None:
        c = build_contract("ES", "FUT", expiry="202609", exchange="CME")
        assert isinstance(c, Future)
        assert c.symbol == "ES"
        assert c.lastTradeDateOrContractMonth == "202609"
        assert c.exchange == "CME"

    def test_missing_expiry_raises(self) -> None:
        with pytest.raises(ValueError):
            build_contract("ES", "FUT", exchange="CME")


class TestCash:
    def test_forex_pair(self) -> None:
        c = build_contract("EUR", "CASH", exchange="IDEALPRO", currency="USD")
        assert isinstance(c, Forex)
        assert c.pair() == "EURUSD"

    def test_default_exchange(self) -> None:
        c = build_contract("EUR", "CASH", currency="USD")
        assert isinstance(c, Forex)


class TestBond:
    def test_basic(self) -> None:
        c = build_contract("US-T", "BOND", exchange="SMART", currency="USD")
        assert isinstance(c, Bond)
        assert c.symbol == "US-T"


class TestIndex:
    def test_basic(self) -> None:
        c = build_contract("SPX", "IND", exchange="CBOE", currency="USD")
        assert isinstance(c, Index)
        assert c.symbol == "SPX"
        assert c.exchange == "CBOE"


class TestInvalid:
    def test_unsupported_sec_type(self) -> None:
        with pytest.raises(ValueError):
            build_contract("AAPL", "WARRANT")

    def test_empty_symbol(self) -> None:
        with pytest.raises(ValueError):
            build_contract("", "STK")

    def test_lowercase_sec_type_normalised(self) -> None:
        c = build_contract("AAPL", "stk")
        assert isinstance(c, Stock)
