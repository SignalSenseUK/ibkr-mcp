"""Pydantic models for order-monitoring responses (spec §6.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderStatusResponse(BaseModel):
    """Schema returned by ``get_order_status`` (spec §6.5)."""

    model_config = ConfigDict(populate_by_name=True)

    orderId: int
    status: str
    symbol: str
    secType: str
    action: str
    quantity: float
    orderType: str
    limitPrice: float | None = Field(default=None)
    stopPrice: float | None = Field(default=None)
    filledQuantity: float = 0.0
    avgFillPrice: float | None = Field(default=None)
    commission: float | None = Field(default=None)
    submittedAt: datetime | None = Field(default=None)
    filledAt: datetime | None = Field(default=None)


class LiveOrderItem(BaseModel):
    """A single line in the open-orders list."""

    model_config = ConfigDict(populate_by_name=True)

    orderId: int
    status: str
    symbol: str
    secType: str
    action: str
    quantity: float
    orderType: str
    limitPrice: float | None = Field(default=None)
    stopPrice: float | None = Field(default=None)
    filledQuantity: float = 0.0
    submittedAt: datetime | None = Field(default=None)


class LiveOrdersResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account: str
    timestamp: datetime
    orders: list[LiveOrderItem]
