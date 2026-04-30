"""Tests for ``ibkr_mcp.config``."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import structlog
from pydantic import ValidationError

from ibkr_mcp.config import (
    LogFormat,
    LogLevel,
    MarketDataType,
    Settings,
    TransportMode,
    setup_logging,
)


def _make_settings(env_file: Path | None = None, **overrides: object) -> Settings:
    """Build a Settings instance with an explicit ``.env`` path or no file at all."""
    return Settings(_env_file=env_file or "/dev/null", **overrides)  # type: ignore[arg-type, call-arg]


class TestDefaults:
    def test_default_port_is_paper(self) -> None:
        s = _make_settings()
        assert s.IB_PORT == 4002, (
            "IB_PORT default must be 4002 (paper) to match paper-trading default"
        )

    def test_default_paper_trading(self) -> None:
        assert _make_settings().IB_PAPER_TRADING is True

    def test_default_market_data_type(self) -> None:
        assert _make_settings().IB_MARKET_DATA_TYPE is MarketDataType.LIVE

    def test_default_transport(self) -> None:
        assert _make_settings().MCP_TRANSPORT is TransportMode.STREAMABLE_HTTP

    def test_default_log_format(self) -> None:
        assert _make_settings().LOG_FORMAT is LogFormat.JSON

    def test_default_log_level(self) -> None:
        assert _make_settings().LOG_LEVEL is LogLevel.INFO

    def test_optional_fields_default_none(self) -> None:
        s = _make_settings()
        assert s.IB_ACCOUNT is None
        assert s.IB_FLEX_TOKEN is None


class TestEnvOverrides:
    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IB_HOST", "10.0.0.5")
        monkeypatch.setenv("IB_PORT", "7497")
        monkeypatch.setenv("IB_PAPER_TRADING", "false")
        monkeypatch.setenv("IB_MARKET_DATA_TYPE", "DELAYED")
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.setenv("LOG_FORMAT", "console")
        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        s = _make_settings()

        assert s.IB_HOST == "10.0.0.5"
        assert s.IB_PORT == 7497
        assert s.IB_PAPER_TRADING is False
        assert s.IB_MARKET_DATA_TYPE is MarketDataType.DELAYED
        assert s.MCP_TRANSPORT is TransportMode.STDIO
        assert s.LOG_FORMAT is LogFormat.CONSOLE
        assert s.LOG_TOOL_CALLS is True

    def test_invalid_log_format_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_FORMAT", "yaml")
        with pytest.raises(ValidationError):
            _make_settings()

    def test_invalid_market_data_type_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IB_MARKET_DATA_TYPE", "BLAH")
        with pytest.raises(ValidationError):
            _make_settings()

    def test_invalid_port_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IB_PORT", "99999")
        with pytest.raises(ValidationError):
            _make_settings()


class TestEnvFileLoading:
    def test_dotenv_loaded(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "IB_HOST=192.168.1.10",
                    "IB_PORT=7496",
                    "IB_FLEX_TOKEN=secret-token",
                    "LOG_LEVEL=DEBUG",
                ]
            )
        )

        s = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        assert s.IB_HOST == "192.168.1.10"
        assert s.IB_PORT == 7496
        assert s.IB_FLEX_TOKEN == "secret-token"
        assert s.LOG_LEVEL is LogLevel.DEBUG

    def test_env_overrides_dotenv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("IB_HOST=from-file\n")
        monkeypatch.setenv("IB_HOST", "from-env")

        s = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        assert s.IB_HOST == "from-env"


class TestSetupLogging:
    def test_json_format_configures_renderer(self) -> None:
        settings = _make_settings(LOG_FORMAT=LogFormat.JSON, LOG_LEVEL=LogLevel.INFO)
        setup_logging(settings)
        # structlog should be configured (no exception); root level matches.
        assert logging.getLogger().level == logging.INFO

    def test_console_format(self) -> None:
        settings = _make_settings(LOG_FORMAT=LogFormat.CONSOLE, LOG_LEVEL=LogLevel.WARNING)
        setup_logging(settings)
        assert logging.getLogger().level == logging.WARNING

    def test_setup_logging_is_idempotent(self) -> None:
        settings = _make_settings(LOG_LEVEL=LogLevel.DEBUG)
        setup_logging(settings)
        setup_logging(settings)
        # Only one stderr handler should be attached after repeated calls.
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1

    def test_logger_is_usable_after_setup(self) -> None:
        settings = _make_settings()
        setup_logging(settings)
        logger = structlog.get_logger("test")
        # Should not raise.
        logger.info("hello", foo="bar")
