"""Tests for ``ibkr_mcp.utils.durations``."""

from __future__ import annotations

import pytest

from ibkr_mcp.utils.durations import parse_duration


class TestSpecTable:
    """Every row of the translation table from spec §6.4."""

    @pytest.mark.parametrize(
        ("iso", "ib_native"),
        [
            ("PT3600S", "3600 S"),
            ("P30D", "30 D"),
            ("P2W", "2 W"),
            ("P6M", "6 M"),
            ("P1Y", "1 Y"),
            ("PT1H", "3600 S"),
        ],
    )
    def test_iso_translates(self, iso: str, ib_native: str) -> None:
        assert parse_duration(iso) == ib_native


class TestPassThrough:
    @pytest.mark.parametrize(
        "ib_native",
        [
            "30 D",
            "1 Y",
            "3600 S",
            "2 W",
            "6 M",
            "1 W",
        ],
    )
    def test_ib_native_unchanged(self, ib_native: str) -> None:
        assert parse_duration(ib_native) == ib_native

    def test_extra_whitespace_normalised(self) -> None:
        assert parse_duration("  30   D  ") == "30 D"


class TestExtraIsoCombos:
    def test_minutes_only_converts_to_seconds(self) -> None:
        assert parse_duration("PT5M") == "300 S"

    def test_hours_and_minutes_sum_to_seconds(self) -> None:
        assert parse_duration("PT1H30M") == "5400 S"

    def test_seconds_only(self) -> None:
        assert parse_duration("PT45S") == "45 S"


class TestInvalidInput:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            " ",
            "garbage",
            "P",
            "PT",
            "30D",  # missing space, not IB-native
            "P-1D",  # negative
            "P1.5D",  # fractional
            "P1Y6M",  # multi-component date
            "P1D2W",  # multi-component date
            "P1DT5S",  # mixed date and time
        ],
    )
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_duration(bad)

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_duration(None)  # type: ignore[arg-type]
