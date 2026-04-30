"""FastMCP server, typed lifespan, and ``AppContext``.

The lifespan deliberately swallows connection failures — per spec §5 the
server must stay up so tools can return ``IB_NOT_CONNECTED`` rather than the
client receiving a broken pipe. Every tool reads its dependencies off
``AppContext`` (yielded by the lifespan) so there is exactly one place where
connection state, settings, locks, and metadata live.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from ibkr_mcp import __version__
from ibkr_mcp.config import Settings
from ibkr_mcp.connection import ConnectionManager

_log = structlog.get_logger("ibkr_mcp.server")


@dataclass
class AppContext:
    """Per-process state shared across every tool invocation.

    Tools should read attributes off this dataclass — they should not import
    ``Settings()`` directly or hold references to the underlying ``IB`` client.
    """

    settings: Settings
    manager: ConnectionManager
    started_at: datetime
    server_version: str
    ib_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def account_id(self) -> str | None:
        """Resolved IB account id, or ``None`` when the gateway is unreachable."""
        return self.manager.account_id


# Tool registration callbacks (populated by future milestones via
# ``register_all_tools``). Each callback receives the FastMCP instance and an
# ``AppContext`` factory so it can attach decorated tools that read live state.
ToolRegistrar = Callable[[FastMCP[AppContext], Callable[[], AppContext]], None]


def register_all_tools(
    mcp: FastMCP[AppContext],
    app_ctx_factory: Callable[[], AppContext],
    settings: Settings,
) -> None:
    """Register every tool module against ``mcp``.

    Subsequent milestones append calls into this function so the registration
    order is explicit and central.
    """

    del app_ctx_factory  # tools read AppContext from ctx.request_context

    # Imports are local so individual tool modules don't trigger circular
    # imports of this module at package import time.
    from ibkr_mcp.tools import account as account_tools
    from ibkr_mcp.tools import contracts as contract_tools
    from ibkr_mcp.tools import flex as flex_tools
    from ibkr_mcp.tools import market as market_tools
    from ibkr_mcp.tools import orders as order_tools
    from ibkr_mcp.tools import server as server_tool

    server_tool.register(mcp)
    account_tools.register(mcp)
    market_tools.register(mcp)
    order_tools.register(mcp)
    contract_tools.register(mcp)
    # Flex query tools are only registered when a token is configured.
    flex_tools.register_if_enabled(mcp, settings)


def build_lifespan(
    settings: Settings,
) -> Callable[[FastMCP[AppContext]], Any]:
    """Construct the FastMCP lifespan callable bound to a given ``Settings``.

    A factory is used (rather than a free function) so tests can build a
    lifespan around their own ``Settings`` and ``ConnectionManager`` instance
    without going through environment variables.
    """

    @asynccontextmanager
    async def lifespan(_app: FastMCP[AppContext]) -> AsyncIterator[AppContext]:
        manager = ConnectionManager(settings=settings)
        # Per spec §5: the server MUST NOT exit on connection failure. We
        # invoke connect() inside try/except even though ConnectionManager
        # already swallows exceptions internally — defence in depth.
        try:
            await manager.connect()
        except Exception as exc:  # pragma: no cover — defensive backstop
            _log.warning("lifespan_connect_unexpected_exception", error=str(exc))

        ctx = AppContext(
            settings=settings,
            manager=manager,
            started_at=datetime.now(UTC),
            server_version=__version__,
        )
        try:
            yield ctx
        finally:
            await manager.disconnect()

    return lifespan


def build_mcp(settings: Settings | None = None) -> FastMCP[AppContext]:
    """Construct a configured ``FastMCP`` instance.

    Tools are registered as ``register_all_tools`` is extended in later
    milestones; for Milestone 2 the server boots with zero tools.
    """

    settings = settings or Settings()
    mcp: FastMCP[AppContext] = FastMCP(
        "IBKR",
        instructions="Read-only Interactive Brokers data access via MCP.",
        lifespan=build_lifespan(settings),
        host=settings.MCP_HTTP_HOST,
        port=settings.MCP_HTTP_PORT,
        streamable_http_path="/mcp",
        log_level=settings.LOG_LEVEL.value,
    )

    def _app_ctx_factory() -> AppContext:
        # Resolved per-call from the active request's lifespan context. Tools
        # that need the AppContext should pull it off ``Context.request_context``
        # directly — this factory exists for tests and future tool registries.
        raise RuntimeError(
            "AppContext is only available inside a tool invocation; "
            "read it from ctx.request_context.lifespan_context."
        )

    register_all_tools(mcp, _app_ctx_factory, settings)
    return mcp
