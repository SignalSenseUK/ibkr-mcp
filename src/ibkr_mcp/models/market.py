"""Pydantic models for market-data responses (spec §6.4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MarketDataResponse(BaseModel):
    """Snapshot quote returned by ``get_market_data``.

    The shape is identical for every security type — Greeks and option-only
    fields default to ``None`` for non-options. Two example payloads from
    spec §6.4 (equity and option) both validate against this single model.
    """

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    secType: str
    exchange: str | None = Field(default=None)
    currency: str | None = Field(default=None)

    # Common quote fields
    lastPrice: float | None = Field(default=None)
    bid: float | None = Field(default=None)
    ask: float | None = Field(default=None)
    bidSize: float | None = Field(default=None)
    askSize: float | None = Field(default=None)
    volume: float | None = Field(default=None)
    high: float | None = Field(default=None)
    low: float | None = Field(default=None)
    open: float | None = Field(default=None)
    close: float | None = Field(default=None)

    # Option-only fields
    expiry: str | None = Field(default=None)
    strike: float | None = Field(default=None)
    right: str | None = Field(default=None)
    impliedVolatility: float | None = Field(default=None)
    delta: float | None = Field(default=None)
    gamma: float | None = Field(default=None)
    theta: float | None = Field(default=None)
    vega: float | None = Field(default=None)
    openInterest: float | None = Field(default=None)

    timestamp: datetime


class HistoricalBar(BaseModel):
    """A single OHLCV bar returned by ``get_historical_data``."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    open: float | None = Field(default=None)
    high: float | None = Field(default=None)
    low: float | None = Field(default=None)
    close: float | None = Field(default=None)
    volume: float | None = Field(default=None)
    wap: float | None = Field(default=None)
    count: int | None = Field(default=None)


class HistoricalDataResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    secType: str
    barSize: str
    bars: list[HistoricalBar]


class OptionChainDiscovery(BaseModel):
    """``get_option_chain`` discovery payload (spec §6.8 — no ``expiry``)."""

    model_config = ConfigDict(populate_by_name=True)

    underlying: str
    exchanges: list[str]
    expirations: list[str]
    strikes: list[float]
    multiplier: int


class OptionChainStrike(BaseModel):
    """Per-contract data for a single strike in an expanded option chain."""

    model_config = ConfigDict(populate_by_name=True)

    strike: float
    right: str
    conId: int | None = Field(default=None)
    lastPrice: float | None = Field(default=None)
    bid: float | None = Field(default=None)
    ask: float | None = Field(default=None)
    volume: float | None = Field(default=None)
    openInterest: float | None = Field(default=None)
    impliedVolatility: float | None = Field(default=None)
    delta: float | None = Field(default=None)
    gamma: float | None = Field(default=None)
    theta: float | None = Field(default=None)
    vega: float | None = Field(default=None)


class OptionChainResponse(BaseModel):
    """``get_option_chain`` full-chain payload (spec §6.8 — with ``expiry``)."""

    model_config = ConfigDict(populate_by_name=True)

    underlying: str
    expiry: str
    multiplier: int
    chains: list[OptionChainStrike]
