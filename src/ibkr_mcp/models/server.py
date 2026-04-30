"""Pydantic models for server-status responses (spec §6.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectionStatus = Literal["connected", "disconnected", "connecting"]


class ServerStatusResponse(BaseModel):
    """Schema returned by ``get_server_status`` (spec §6.2).

    Field names use camelCase to match the spec exactly; the JSON output is
    therefore identical to the example in the specification.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: ConnectionStatus = Field(description="Current IB Gateway connection state.")
    ibHost: str
    ibPort: int
    clientId: int
    accountId: str | None = Field(default=None)
    paperTrading: bool
    serverVersion: str
    transport: str
    uptimeSeconds: int = Field(ge=0)
    marketDataType: str
    registeredTools: int = Field(ge=0)
    timestamp: datetime
