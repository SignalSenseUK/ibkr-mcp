"""Live integration smoke tests (skipped in CI).

These tests require a running IB Gateway or TWS on the host configured in
``.env`` (or environment variables) and a paper trading account. They are
marked with ``@pytest.mark.integration`` and are excluded by default via
``pyproject.toml`` (``-m "not integration"``). Run them locally with::

    uv run pytest tests/test_integration.py -m integration -v
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import pytest

from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.server import AppContext, build_mcp
from ibkr_mcp.tools.account import get_account_info
from ibkr_mcp.tools.server import get_server_status

pytestmark = pytest.mark.integration

# Skip the entire module unless an explicit opt-in env var is set, so that an
# accidental ``pytest -m integration`` doesn't try to talk to a gateway that
# isn't running.
_RUN = os.environ.get("IBKR_MCP_INTEGRATION", "0") == "1"
if not _RUN:
    pytest.skip(
        "Set IBKR_MCP_INTEGRATION=1 with a paper IB Gateway running to enable.",
        allow_module_level=True,
    )


async def _live_app_ctx() -> AppContext:
    settings = Settings()  # reads .env / environment
    manager = ConnectionManager(settings=settings)
    await manager.connect()
    return AppContext(
        settings=settings,
        manager=manager,
        started_at=datetime.now(UTC),
        server_version="0.1.0",
        ib_lock=asyncio.Lock(),
    )


class _RequestCtxStub:
    def __init__(self, ctx: AppContext) -> None:
        self.lifespan_context = ctx
        self.request_id = "integration"


class _CtxStub:
    """Minimal Context stand-in carrying ``request_context``."""

    def __init__(self, ctx: AppContext, mcp: object) -> None:
        self.request_context = _RequestCtxStub(ctx)
        self.fastmcp = mcp


async def test_get_server_status_against_live_gateway() -> None:
    settings = Settings()
    mcp = build_mcp(settings)
    app_ctx = await _live_app_ctx()
    try:
        ctx = _CtxStub(app_ctx, mcp)
        payload = json.loads(await get_server_status(ctx))
        assert "status" in payload
        # Either healthy (connected) or warning (lifespan kept the server up).
        assert payload["status"] in {"healthy", "degraded", "warning"}
    finally:
        await app_ctx.manager.disconnect()


async def test_get_account_info_against_live_gateway() -> None:
    settings = Settings()
    mcp = build_mcp(settings)
    app_ctx = await _live_app_ctx()
    try:
        ctx = _CtxStub(app_ctx, mcp)
        payload = json.loads(await get_account_info(ctx))
        # Either a successful summary (with accountId) or a structured error
        # — both shapes prove the tool round-trips JSON correctly.
        assert "accountId" in payload or "code" in payload
    finally:
        await app_ctx.manager.disconnect()
