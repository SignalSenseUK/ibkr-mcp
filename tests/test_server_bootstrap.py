"""Tests for the FastMCP lifespan and CLI bootstrap."""

from __future__ import annotations

import asyncio
import io
import sys
from collections.abc import Callable
from typing import cast
from unittest.mock import patch

import pytest

from ibkr_mcp import __main__ as cli
from ibkr_mcp.config import Settings, TransportMode
from ibkr_mcp.connection import ConnectionManager
from ibkr_mcp.server import AppContext, build_lifespan, build_mcp

from .fake_ib import FakeIB


class TestAppContext:
    def test_account_id_proxies_manager(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        from ib_async import IB

        mgr = ConnectionManager(settings=settings_factory(), ib=cast(IB, fake_ib))
        ctx = AppContext(
            settings=settings_factory(),
            manager=mgr,
            started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            server_version="0.0.0",
        )
        # Before connect, no account id.
        assert ctx.account_id is None


class TestLifespan:
    async def test_lifespan_yields_appcontext_on_connect_failure(
        self, settings_factory: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lifespan must yield even when the gateway connection fails."""

        fake = FakeIB()
        fake.connect_should_fail = True

        # Patch ConnectionManager to use our FakeIB.
        original_init = ConnectionManager.__init__

        def patched_init(
            self: ConnectionManager,
            settings: Settings,
            ib: object | None = None,
        ) -> None:
            from ib_async import IB

            original_init(self, settings=settings, ib=cast(IB, ib if ib is not None else fake))

        monkeypatch.setattr(ConnectionManager, "__init__", patched_init)

        settings = settings_factory()
        lifespan = build_lifespan(settings)

        # Build a sentinel FastMCP just for the type signature; we don't run it.
        from mcp.server.fastmcp import FastMCP

        app: FastMCP[AppContext] = FastMCP("test")

        async with lifespan(app) as ctx:
            assert isinstance(ctx, AppContext)
            assert ctx.account_id is None
            assert ctx.manager.is_connected is False
            assert isinstance(ctx.ib_lock, asyncio.Lock)
            assert ctx.server_version  # any non-empty version string

    async def test_lifespan_yields_appcontext_on_successful_connect(
        self, settings_factory: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeIB()
        fake.managed_accounts = ["U7777777"]

        original_init = ConnectionManager.__init__

        def patched_init(
            self: ConnectionManager,
            settings: Settings,
            ib: object | None = None,
        ) -> None:
            from ib_async import IB

            original_init(self, settings=settings, ib=cast(IB, ib if ib is not None else fake))

        monkeypatch.setattr(ConnectionManager, "__init__", patched_init)

        settings = settings_factory()
        lifespan = build_lifespan(settings)

        from mcp.server.fastmcp import FastMCP

        app: FastMCP[AppContext] = FastMCP("test")

        async with lifespan(app) as ctx:
            assert ctx.manager.is_connected is True
            assert ctx.account_id == "U7777777"

        # After exit, disconnect was issued.
        assert fake.disconnect_calls >= 1


class TestBuildMcp:
    def test_build_mcp_sets_http_host_port_and_path(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        settings = settings_factory(MCP_HTTP_HOST="127.0.0.1", MCP_HTTP_PORT=9000)
        mcp = build_mcp(settings)
        assert mcp.settings.host == "127.0.0.1"
        assert mcp.settings.port == 9000
        assert mcp.settings.streamable_http_path == "/mcp"

    def test_build_mcp_runs_with_zero_tools(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        mcp = build_mcp(settings_factory())
        # The server should still construct cleanly — no tools registered yet.
        assert mcp is not None


class TestBanner:
    def _capture(self, settings: Settings, *, connected: bool, account_id: str | None) -> str:
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            cli._print_banner(settings, connected=connected, account_id=account_id)
        return buf.getvalue()

    def test_banner_success(self, settings_factory: Callable[..., Settings]) -> None:
        text = self._capture(
            settings_factory(IB_HOST="127.0.0.1", IB_PORT=4002),
            connected=True,
            account_id="U1234567",
        )
        assert "IBKR MCP Server v" in text
        assert "Connected to IB Gateway at 127.0.0.1:4002" in text
        assert "Account: U1234567" in text
        assert "Paper: true" in text
        assert "Transport: streamable-http" in text

    def test_banner_warning_on_failure(self, settings_factory: Callable[..., Settings]) -> None:
        text = self._capture(
            settings_factory(IB_HOST="10.0.0.1", IB_PORT=4001),
            connected=False,
            account_id=None,
        )
        assert "WARNING: Failed to connect to IB Gateway at 10.0.0.1:4001" in text
        assert "Tools will return IB_NOT_CONNECTED errors" in text
        assert "Account: —" in text

    def test_banner_stdio_omits_host_port(self, settings_factory: Callable[..., Settings]) -> None:
        text = self._capture(
            settings_factory(MCP_TRANSPORT=TransportMode.STDIO),
            connected=True,
            account_id="U1234567",
        )
        assert "Transport: stdio" in text
        assert "(127.0.0.1" not in text  # no host:port suffix


class TestMainCli:
    def test_main_runs_stdio_with_probe(
        self, settings_factory: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``main`` should probe, print banner, then call ``mcp.run``."""

        fake = FakeIB()
        fake.managed_accounts = ["U1234567"]

        original_init = ConnectionManager.__init__

        def patched_init(
            self: ConnectionManager,
            settings: Settings,
            ib: object | None = None,
        ) -> None:
            from ib_async import IB

            original_init(self, settings=settings, ib=cast(IB, ib if ib is not None else fake))

        monkeypatch.setattr(ConnectionManager, "__init__", patched_init)

        # Stub out FastMCP.run so the CLI completes immediately.
        run_calls: list[str] = []

        def fake_run(self: object, transport: str = "stdio", mount_path: str | None = None) -> None:
            run_calls.append(transport)

        from mcp.server.fastmcp import FastMCP

        monkeypatch.setattr(FastMCP, "run", fake_run)

        # Force stdio so we don't try to bind a port.
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--transport", "stdio"])

        assert excinfo.value.code == 0
        assert run_calls == ["stdio"]
