"""Pydantic model for ``get_contract_details`` (spec §6.6)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContractDetailsResponse(BaseModel):
    """Schema returned by ``get_contract_details``.

    Equity-style contracts populate the upper block; option contracts also
    populate ``strike``/``right``/``expiry``/``multiplier``/``lastTradeDate``.
    """

    model_config = ConfigDict(populate_by_name=True)

    conId: int
    symbol: str
    secType: str
    exchange: str
    primaryExchange: str | None = Field(default=None)
    currency: str
    localSymbol: str | None = Field(default=None)
    tradingHours: str | None = Field(default=None)
    liquidHours: str | None = Field(default=None)
    longName: str | None = Field(default=None)
    category: str | None = Field(default=None)
    subcategory: str | None = Field(default=None)
    industry: str | None = Field(default=None)

    # Option-only fields.
    strike: float | None = Field(default=None)
    right: str | None = Field(default=None)
    expiry: str | None = Field(default=None)
    multiplier: str | None = Field(default=None)
    lastTradeDate: str | None = Field(default=None)
