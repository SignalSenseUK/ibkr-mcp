"""Pydantic models for position-level responses (spec §6.3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PositionItem(BaseModel):
    """A single line in the positions list.

    For options, the spec mandates that ``right``, ``strike``, ``expiry``, and
    ``multiplier`` are populated. They are left ``None`` for non-option
    instruments.
    """

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    secType: str
    exchange: str | None = Field(default=None)
    currency: str | None = Field(default=None)
    conId: int | None = Field(default=None)
    position: float
    avgCost: float | None = Field(default=None)
    marketPrice: float | None = Field(default=None)
    marketValue: float | None = Field(default=None)
    unrealizedPnL: float | None = Field(default=None)
    realizedPnL: float | None = Field(default=None)

    # Option-only fields. ``None`` for non-options.
    right: str | None = Field(default=None)
    strike: float | None = Field(default=None)
    expiry: str | None = Field(default=None)
    multiplier: int | None = Field(default=None)


class PositionsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account: str
    timestamp: datetime
    positions: list[PositionItem]


class PortfolioGreekItem(BaseModel):
    """One line in the per-position Greek breakdown (spec §6.8)."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    expiry: str
    strike: float
    right: str
    position: float
    delta: float | None = Field(default=None)
    gamma: float | None = Field(default=None)
    theta: float | None = Field(default=None)
    vega: float | None = Field(default=None)
    source: str = Field(default="model")


class PortfolioGreeksResponse(BaseModel):
    """Aggregate response shape for ``get_portfolio_greeks`` (spec §6.8)."""

    model_config = ConfigDict(populate_by_name=True)

    account: str
    timestamp: datetime
    totalDelta: float = 0.0
    totalGamma: float = 0.0
    totalTheta: float = 0.0
    totalVega: float = 0.0
    positions: list[PortfolioGreekItem]
