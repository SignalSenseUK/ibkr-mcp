"""Tests for ``get_alerts`` placeholder and ``models.alerts`` schemas (spec §6.8)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

from ib_async import IB
from mcp.server.fastmcp import Context

from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.errors import ErrorCode
from ibkr_mcp.models.alerts import Alert, AlertCondition, AlertsResponse
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.orders import get_alerts

from .fake_ib import FakeIB


def _make_ctx(
    fake_ib: FakeIB,
    settings: Settings,
) -> Context:  # type: ignore[type-arg]
    fake_ib.connected = True
    mgr = ConnectionManager(settings=settings, ib=cast(IB, fake_ib))
    mgr._account_id = "U1234567"
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


class TestGetAlerts:
    async def test_returns_not_implemented(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_alerts(ctx))
        assert payload["code"] == ErrorCode.NOT_IMPLEMENTED.value
        assert "feasibility validation" in payload["error"]

    async def test_returns_not_implemented_with_account_id(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        ctx = _make_ctx(fake_ib, settings_factory())
        payload = json.loads(await get_alerts(ctx, accountId="U1234567"))
        assert payload["code"] == ErrorCode.NOT_IMPLEMENTED.value


class TestAlertSchemas:
    def test_validates_spec_sample_payload(self) -> None:
        # Sample shape lifted from spec §6.8.
        sample = {
            "alerts": [
                {
                    "alertId": 42,
                    "name": "AAPL > 160",
                    "active": True,
                    "conditions": [
                        {
                            "symbol": "AAPL",
                            "field": "LAST",
                            "operator": ">=",
                            "value": 160.0,
                        }
                    ],
                    "createdAt": "2026-04-28T10:00:00Z",
                }
            ]
        }

        response = AlertsResponse.model_validate(sample)

        assert len(response.alerts) == 1
        assert response.alerts[0].alertId == 42
        assert response.alerts[0].active is True
        assert isinstance(response.alerts[0].conditions[0], AlertCondition)
        assert response.alerts[0].conditions[0].operator == ">="

    def test_alert_minimal_payload(self) -> None:
        a = Alert(alertId=1, name="test")
        assert a.active is True
        assert a.conditions == []


class TestRegistration:
    def test_register_attaches_tool(self, settings_factory: Callable[..., Settings]) -> None:
        mcp = build_mcp(settings_factory())
        names = list(mcp._tool_manager._tools)
        assert "get_alerts" in names
