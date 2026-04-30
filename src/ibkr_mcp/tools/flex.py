"""Flex-query tools (spec §6.7).

These tools talk to IB's Flex Web Service over HTTPS via ``ib_async.FlexReport``;
they do **not** require an active TWS/Gateway connection and never acquire
``app_ctx.ib_lock``. They are registered only when ``settings.IB_FLEX_TOKEN``
is set (see :func:`register_if_enabled`).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ib_async import FlexReport
from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.config import Settings
from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.flex import (
    FlexQueriesResponse,
    FlexQueryDefinition,
    FlexQueryRawXml,
    FlexQueryResult,
)
from ibkr_mcp.server import AppContext


def _parse_registry(raw: str | None) -> list[FlexQueryDefinition]:
    """Parse ``settings.IB_FLEX_QUERIES`` (JSON) into typed definitions.

    Tolerates ``None`` and malformed JSON (returns ``[]``).
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[FlexQueryDefinition] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(FlexQueryDefinition.model_validate(entry))
        except Exception:
            # Defensive: user-supplied JSON may have unexpected shapes.
            continue
    return out


def _resolve_query(
    *,
    queryId: str | None,
    queryName: str | None,
    registry: list[FlexQueryDefinition],
) -> tuple[str | None, str | None, str | None]:
    """Validate ``queryId`` xor ``queryName`` and resolve aliases.

    Returns ``(resolved_id, resolved_name, error_message)``.
    """
    if queryId and queryName:
        return None, None, "Provide queryId xor queryName, not both."
    if not queryId and not queryName:
        return None, None, "Either queryId or queryName is required."

    if queryId:
        match = next((q for q in registry if q.queryId == queryId), None)
        return queryId, (match.queryName if match else None), None

    # queryName only.
    assert queryName is not None
    match = next((q for q in registry if q.queryName == queryName), None)
    if match is None:
        return (
            None,
            None,
            f"queryName {queryName!r} is not configured in IB_FLEX_QUERIES.",
        )
    return match.queryId, match.queryName, None


def _download_blocking(token: str, query_id: str) -> Any:
    """Synchronous FlexReport download — wrapped via ``asyncio.to_thread``.

    Returns ``Any`` because ``FlexReport`` lacks type stubs in ib_async; tools
    interact with the result via ``getattr`` and duck-typing.
    """
    return FlexReport(token=token, queryId=query_id)  # type: ignore[no-untyped-call]


def _records_from_extract(items: list[Any]) -> list[dict[str, Any]]:
    """Turn ``FlexReport.extract`` results (DynamicObjects) into plain dicts."""
    out: list[dict[str, Any]] = []
    for item in items:
        attrs = getattr(item, "__dict__", None)
        if isinstance(attrs, dict):
            out.append(dict(attrs))
        else:
            out.append({"value": str(item)})
    return out


# ============================================================ list_flex_queries
@tool_error_handler
@tool_call_logger
async def list_flex_queries(ctx: Context) -> str:  # type: ignore[type-arg]
    """List all available Flex Query definitions configured in your IBKR Account Management portal. Returns query IDs and names that can be passed to get_flex_query to execute."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    registry = _parse_registry(app_ctx.settings.IB_FLEX_QUERIES)
    return FlexQueriesResponse(queries=registry).model_dump_json(exclude_none=True)


# ============================================================ get_flex_query
@tool_error_handler
@tool_call_logger
async def get_flex_query(
    ctx: Context,  # type: ignore[type-arg]
    queryId: str | None = None,
    queryName: str | None = None,
    topic: str | None = None,
) -> str:
    """Execute a Flex Query by ID or name and return the parsed results as structured JSON. Flex Queries provide access to historical account data, trade reports, and statements configured in your IBKR Account Management portal. Requires IB_FLEX_TOKEN to be configured."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    settings = app_ctx.settings
    if not settings.IB_FLEX_TOKEN:
        return make_error(
            ErrorCode.IB_FLEX_ERROR,
            "IB_FLEX_TOKEN is not configured on the server.",
        )

    registry = _parse_registry(settings.IB_FLEX_QUERIES)
    resolved_id, resolved_name, err = _resolve_query(
        queryId=queryId, queryName=queryName, registry=registry
    )
    if err is not None:
        return make_error(ErrorCode.VALIDATION_ERROR, err)
    assert resolved_id is not None  # for type checker

    try:
        report = await asyncio.to_thread(_download_blocking, settings.IB_FLEX_TOKEN, resolved_id)
    except Exception as exc:
        # FlexError + transport errors all map to IB_FLEX_ERROR.
        return make_error(
            ErrorCode.IB_FLEX_ERROR,
            f"Flex query download failed: {exc}",
        )

    raw_xml = getattr(report, "data", b"") or b""
    if isinstance(raw_xml, bytes):
        raw_xml_str = raw_xml.decode("utf-8", errors="replace")
    else:
        raw_xml_str = str(raw_xml)

    try:
        if topic:
            extracted = report.extract(topic)
            data = {topic: _records_from_extract(extracted)}
        else:
            topics = list(report.topics())
            data = {t: _records_from_extract(report.extract(t)) for t in topics}
    except Exception:
        # Fall back to raw XML on parse failure (spec §6.7).
        return FlexQueryRawXml(
            queryId=resolved_id,
            queryName=resolved_name,
            topic=topic,
            xml=raw_xml_str,
        ).model_dump_json(exclude_none=True)

    return FlexQueryResult(
        queryId=resolved_id,
        queryName=resolved_name,
        topic=topic,
        data=data,
    ).model_dump_json(exclude_none=True)


def register_if_enabled(mcp: FastMCP[AppContext], settings: Settings) -> bool:
    """Attach the flex-query tools to ``mcp`` iff a token is configured.

    Returns ``True`` when the tools were registered.
    """
    if not settings.IB_FLEX_TOKEN:
        return False
    mcp.tool()(list_flex_queries)
    mcp.tool()(get_flex_query)
    return True
