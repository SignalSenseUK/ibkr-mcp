"""``get_server_status`` tool.

Reports the live connection state, uptime, and resolved metadata of the
running MCP server. The tool is intentionally cheap and side-effect-free so
clients can call it on every reconnect to verify the server is healthy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mcp.server.fastmcp import Context, FastMCP

from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
from ibkr_mcp.models.server import ConnectionStatus, ServerStatusResponse
from ibkr_mcp.server import AppContext


def _connection_status(app_ctx: AppContext) -> ConnectionStatus:
    """Derive the spec §6.2 status value from the live ``ConnectionManager``."""
    if app_ctx.manager.is_connected:
        return "connected"
    return "disconnected"


@tool_error_handler
@tool_call_logger
async def get_server_status(ctx: Context) -> str:  # type: ignore[type-arg]
    """Check the health and connection status of the IBKR MCP server. Call this before making data requests to verify the server is connected to IB Gateway. Returns connection state, uptime, account ID, and server version."""

    app_ctx: AppContext = ctx.request_context.lifespan_context
    settings = app_ctx.settings

    now = datetime.now(UTC)
    uptime = max(0, int((now - app_ctx.started_at).total_seconds()))
    registered_tools = len(ctx.fastmcp._tool_manager._tools)

    response = ServerStatusResponse(
        status=_connection_status(app_ctx),
        ibHost=settings.IB_HOST,
        ibPort=settings.IB_PORT,
        clientId=settings.IB_CLIENT_ID,
        accountId=app_ctx.account_id,
        paperTrading=settings.IB_PAPER_TRADING,
        serverVersion=app_ctx.server_version,
        transport=settings.MCP_TRANSPORT.value,
        uptimeSeconds=uptime,
        marketDataType=settings.IB_MARKET_DATA_TYPE.value,
        registeredTools=registered_tools,
        timestamp=now,
    )
    return response.model_dump_json()


def register(mcp: FastMCP[AppContext]) -> None:
    """Attach :func:`get_server_status` to ``mcp``."""
    mcp.tool()(get_server_status)
