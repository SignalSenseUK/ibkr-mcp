"""Tests for ``ibkr_mcp.tools.flex``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from ib_async import IB
from mcp.server.fastmcp import Context

from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.errors import ErrorCode
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.flex import get_flex_query, list_flex_queries

from .fake_ib import FakeIB


# --------------------------------------------------------------------------- helpers
class _DynamicObject:
    """Minimal stand-in for ``ib_async.flexreport.DynamicObject``."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _FakeReport:
    """Stand-in for ``ib_async.FlexReport``.

    The real class hits the network in ``__init__``; tests inject this via
    ``monkeypatch`` so no HTTP traffic occurs.
    """

    def __init__(
        self,
        *,
        topics_data: dict[str, list[_DynamicObject]] | None = None,
        raw_xml: bytes = b"<FlexQueryResponse/>",
        extract_should_fail: bool = False,
    ) -> None:
        self._topics = topics_data or {}
        self.data = raw_xml
        self._extract_should_fail = extract_should_fail

    def topics(self) -> set[str]:
        return set(self._topics)

    def extract(self, topic: str, parseNumbers: bool = True) -> list[Any]:
        if self._extract_should_fail:
            raise RuntimeError("Simulated extract failure")
        return list(self._topics.get(topic, []))


def _make_ctx(
    fake_ib: FakeIB,
    settings: Settings,
) -> Context:  # type: ignore[type-arg]
    # Connection state is irrelevant for flex tools — they bypass the gateway.
    fake_ib.connected = False
    mgr = ConnectionManager(settings=settings, ib=cast(IB, fake_ib))
    app_ctx = AppContext(
        settings=settings,
        manager=mgr,
        started_at=datetime.now(UTC),
        server_version="0.1.0",
        ib_lock=asyncio.Lock(),
    )
    mcp = build_mcp(settings)
    request_context: Any = MagicMock()
    request_context.lifespan_context = app_ctx
    request_context.request_id = "test"
    return Context(request_context=request_context, fastmcp=mcp)


# --------------------------------------------------------------------------- registration
class TestRegistration:
    def test_flex_tools_skipped_when_no_token(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        mcp = build_mcp(settings_factory(IB_FLEX_TOKEN=None))
        names = list(mcp._tool_manager._tools)
        assert "list_flex_queries" not in names
        assert "get_flex_query" not in names

    def test_flex_tools_registered_when_token_set(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        mcp = build_mcp(settings_factory(IB_FLEX_TOKEN="abc123"))
        names = list(mcp._tool_manager._tools)
        assert "list_flex_queries" in names
        assert "get_flex_query" in names


# --------------------------------------------------------------------------- list
class TestListFlexQueries:
    async def test_returns_empty_list_when_unconfigured(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc", IB_FLEX_QUERIES=None))

        payload = json.loads(await list_flex_queries(ctx))

        assert payload == {"queries": []}

    async def test_returns_configured_queries(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        registry = json.dumps(
            [
                {"queryId": "12345", "queryName": "Daily P&L", "type": "Statement"},
                {"queryId": "67890", "queryName": "Trades"},
            ]
        )
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc", IB_FLEX_QUERIES=registry))

        payload = json.loads(await list_flex_queries(ctx))

        assert len(payload["queries"]) == 2
        assert payload["queries"][0]["queryId"] == "12345"
        assert payload["queries"][0]["queryName"] == "Daily P&L"
        assert payload["queries"][0]["type"] == "Statement"
        assert payload["queries"][1]["queryId"] == "67890"

    async def test_works_when_disconnected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        # Spec: flex tools must function with no gateway connection.
        fake_ib.connected = False
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc"))
        payload = json.loads(await list_flex_queries(ctx))
        assert "queries" in payload

    async def test_malformed_registry_returns_empty(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(
            fake_ib,
            settings_factory(IB_FLEX_TOKEN="abc", IB_FLEX_QUERIES="not valid json"),
        )

        payload = json.loads(await list_flex_queries(ctx))

        assert payload == {"queries": []}


# --------------------------------------------------------------------------- get
class TestGetFlexQuery:
    async def test_missing_token_returns_flex_error(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN=None))
        payload = json.loads(await get_flex_query(ctx, queryId="12345"))
        assert payload["code"] == ErrorCode.IB_FLEX_ERROR.value

    async def test_xor_missing_both_arguments(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc"))
        payload = json.loads(await get_flex_query(ctx))
        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value

    async def test_xor_both_arguments(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc"))
        payload = json.loads(await get_flex_query(ctx, queryId="12345", queryName="Trades"))
        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value

    async def test_unknown_query_name_validation(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="abc"))
        payload = json.loads(await get_flex_query(ctx, queryName="Unknown"))
        assert payload["code"] == ErrorCode.VALIDATION_ERROR.value

    async def test_query_name_resolves_via_registry(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        registry = json.dumps([{"queryId": "12345", "queryName": "Daily P&L", "type": "Statement"}])
        captured: dict[str, str] = {}

        def fake_download(token: str, query_id: str) -> _FakeReport:
            captured["token"] = token
            captured["queryId"] = query_id
            return _FakeReport(
                topics_data={
                    "Trade": [_DynamicObject(symbol="AAPL", quantity=10)],
                }
            )

        monkeypatch.setattr("ibkr_mcp.tools.flex._download_blocking", fake_download)
        ctx = _make_ctx(
            fake_ib,
            settings_factory(IB_FLEX_TOKEN="tok", IB_FLEX_QUERIES=registry),
        )

        payload = json.loads(await get_flex_query(ctx, queryName="Daily P&L", topic="Trade"))

        assert captured == {"token": "tok", "queryId": "12345"}
        assert payload["queryId"] == "12345"
        assert payload["queryName"] == "Daily P&L"
        assert payload["topic"] == "Trade"
        assert payload["parsed"] is True
        assert payload["data"]["Trade"][0]["symbol"] == "AAPL"
        assert payload["data"]["Trade"][0]["quantity"] == 10

    async def test_topic_filter_extracts_only_requested_topic(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_download(token: str, query_id: str) -> _FakeReport:
            return _FakeReport(
                topics_data={
                    "Trade": [_DynamicObject(symbol="AAPL")],
                    "Order": [_DynamicObject(orderId=1)],
                }
            )

        monkeypatch.setattr("ibkr_mcp.tools.flex._download_blocking", fake_download)
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="tok"))

        payload = json.loads(await get_flex_query(ctx, queryId="12345", topic="Trade"))

        assert list(payload["data"].keys()) == ["Trade"]
        assert payload["data"]["Trade"][0]["symbol"] == "AAPL"

    async def test_no_topic_returns_all_topics(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_download(token: str, query_id: str) -> _FakeReport:
            return _FakeReport(
                topics_data={
                    "Trade": [_DynamicObject(symbol="AAPL")],
                    "Order": [_DynamicObject(orderId=1)],
                }
            )

        monkeypatch.setattr("ibkr_mcp.tools.flex._download_blocking", fake_download)
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="tok"))

        payload = json.loads(await get_flex_query(ctx, queryId="12345"))

        assert set(payload["data"].keys()) == {"Trade", "Order"}

    async def test_bad_token_returns_flex_error(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_download(token: str, query_id: str) -> _FakeReport:
            raise RuntimeError("1019: Invalid token")

        monkeypatch.setattr("ibkr_mcp.tools.flex._download_blocking", fake_download)
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="bad"))

        payload = json.loads(await get_flex_query(ctx, queryId="12345"))

        assert payload["code"] == ErrorCode.IB_FLEX_ERROR.value
        assert "Invalid token" in payload["error"]

    async def test_extract_failure_returns_raw_xml(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_download(token: str, query_id: str) -> _FakeReport:
            return _FakeReport(
                raw_xml=b"<FlexQueryResponse><Trades/></FlexQueryResponse>",
                extract_should_fail=True,
            )

        monkeypatch.setattr("ibkr_mcp.tools.flex._download_blocking", fake_download)
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="tok"))

        payload = json.loads(await get_flex_query(ctx, queryId="12345", topic="Trade"))

        assert payload["parsed"] is False
        assert payload["xml"].startswith("<FlexQueryResponse>")
        assert payload["queryId"] == "12345"
        assert payload["topic"] == "Trade"

    async def test_works_when_disconnected(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Spec: flex tools must function with no gateway connection.
        fake_ib.connected = False
        monkeypatch.setattr(
            "ibkr_mcp.tools.flex._download_blocking",
            lambda token, query_id: _FakeReport(topics_data={"Trade": []}),
        )
        ctx = _make_ctx(fake_ib, settings_factory(IB_FLEX_TOKEN="tok"))

        payload = json.loads(await get_flex_query(ctx, queryId="12345"))

        assert payload["parsed"] is True
