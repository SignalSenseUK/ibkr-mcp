"""Pydantic models for Flex-query tool responses (spec §6.7)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlexQueryDefinition(BaseModel):
    """One entry in the configured Flex-query registry."""

    model_config = ConfigDict(populate_by_name=True)

    queryId: str
    queryName: str
    type: str | None = Field(default=None)


class FlexQueriesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    queries: list[FlexQueryDefinition]


class FlexQueryResult(BaseModel):
    """Successful parse of a Flex query response."""

    model_config = ConfigDict(populate_by_name=True)

    queryId: str
    queryName: str | None = Field(default=None)
    topic: str | None = Field(default=None)
    parsed: bool = True
    # Map topic name → list of records. When ``topic`` is supplied the dict
    # contains a single key.
    data: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class FlexQueryRawXml(BaseModel):
    """Fallback returned when ``FlexReport.extract`` raises."""

    model_config = ConfigDict(populate_by_name=True)

    queryId: str
    queryName: str | None = Field(default=None)
    topic: str | None = Field(default=None)
    parsed: bool = False
    xml: str
