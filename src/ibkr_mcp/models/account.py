"""Pydantic models for account-level responses (spec §6.3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountInfoResponse(BaseModel):
    """Schema returned by ``get_account_info`` (spec §6.3).

    All numeric fields are nullable because IB only returns the tags the
    account is authorised to expose. Tools never raise on missing data.
    """

    model_config = ConfigDict(populate_by_name=True)

    accountId: str
    netLiquidation: float | None = Field(default=None)
    totalCashValue: float | None = Field(default=None)
    grossPositionValue: float | None = Field(default=None)
    unrealizedPnL: float | None = Field(default=None)
    realizedPnL: float | None = Field(default=None)
    availableFunds: float | None = Field(default=None)
    buyingPower: float | None = Field(default=None)
    maintMarginReq: float | None = Field(default=None)
    initMarginReq: float | None = Field(default=None)
    timestamp: datetime
