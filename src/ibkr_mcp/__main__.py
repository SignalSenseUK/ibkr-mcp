"""CLI entry point: ``python -m ibkr_mcp`` / ``ibkr-mcp``.

Parses ``--transport``, configures structured logging, prints the spec §11
startup banner to stderr, and runs the FastMCP server.
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from ibkr_mcp import __version__
from ibkr_mcp.config import Settings, TransportMode, setup_logging
from ibkr_mcp.server import build_mcp


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ibkr-mcp",
        description="Read-only Interactive Brokers MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=[t.value for t in TransportMode],
        default=None,
        help="MCP transport mode (overrides MCP_TRANSPORT).",
    )
    parser.add_argument("--version", action="version", version=f"ibkr-mcp {__version__}")
    return parser.parse_args(argv)


def _print_banner(settings: Settings, connected: bool, account_id: str | None) -> None:
    """Emit the spec §11 startup banner to stderr."""

    transport = settings.MCP_TRANSPORT.value
    transport_detail = (
        f"{transport} ({settings.MCP_HTTP_HOST}:{settings.MCP_HTTP_PORT})"
        if settings.MCP_TRANSPORT is TransportMode.STREAMABLE_HTTP
        else transport
    )

    print(f"IBKR MCP Server v{__version__}", file=sys.stderr)
    if connected:
        print(
            f"Connected to IB Gateway at {settings.IB_HOST}:{settings.IB_PORT} "
            f"(client_id={settings.IB_CLIENT_ID})",
            file=sys.stderr,
        )
    else:
        print(
            f"WARNING: Failed to connect to IB Gateway at {settings.IB_HOST}:{settings.IB_PORT}",
            file=sys.stderr,
        )
        print(
            "Tools will return IB_NOT_CONNECTED errors until connection is established.",
            file=sys.stderr,
        )

    account_display = account_id if account_id else "—"
    paper_display = "true" if settings.IB_PAPER_TRADING else "false"
    print(f"Account: {account_display} | Paper: {paper_display}", file=sys.stderr)
    print(f"Transport: {transport_detail}", file=sys.stderr)


def main(argv: list[str] | None = None) -> NoReturn:
    """Program entry point."""

    args = _parse_args(argv)

    settings = Settings()
    if args.transport is not None:
        settings = settings.model_copy(update={"MCP_TRANSPORT": TransportMode(args.transport)})

    setup_logging(settings)

    mcp = build_mcp(settings)

    # FastMCP's run() takes the transport name; HTTP host/port were set on the
    # FastMCP constructor in build_mcp. We invoke it from inside an async
    # context only for HTTP — the stdio path is sync-safe.
    transport_value = settings.MCP_TRANSPORT.value

    # The banner is printed before the server starts serving. We deliberately
    # print "connecting" state by inspecting whether connect succeeded inside
    # the lifespan; since the lifespan runs inside mcp.run, we only know the
    # outcome after-the-fact for the banner. To avoid blocking on the gateway
    # at CLI boot time, we attempt a probe connection here once and use its
    # outcome for the banner, then disconnect — the lifespan will reconnect.
    import asyncio

    from ibkr_mcp.connection import ConnectionManager

    async def _probe() -> tuple[bool, str | None]:
        probe_mgr = ConnectionManager(settings=settings)
        ok = await probe_mgr.connect()
        account = probe_mgr.account_id
        await probe_mgr.disconnect()
        return ok, account

    connected, account_id = asyncio.run(_probe())
    _print_banner(settings, connected=connected, account_id=account_id)

    mcp.run(transport=transport_value)  # type: ignore[arg-type]
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
