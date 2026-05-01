"""Pydantic models for ``get_alerts`` (spec §6.8).

The tool itself is stubbed pending feasibility validation against ``ib_async``
(see spec §6.8 — IB's TWS API does not expose user-defined alerts cleanly),
but the schemas live here so any future implementation can wire up directly.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlertCondition(BaseModel):
    """One predicate within an :class:`Alert`."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    field: str = Field(description="e.g. 'LAST', 'BID', 'ASK', 'VOLUME'.")
    operator: str = Field(description="e.g. '>=', '<=', '=='.")
    value: float


class Alert(BaseModel):
    """A single alert configured on an IBKR account."""

    model_config = ConfigDict(populate_by_name=True)

    alertId: int
    name: str
    active: bool = True
    conditions: list[AlertCondition] = Field(default_factory=list)
    createdAt: datetime | None = Field(default=None)


class AlertsResponse(BaseModel):
    """``get_alerts`` envelope."""

    model_config = ConfigDict(populate_by_name=True)

    alerts: list[Alert]
