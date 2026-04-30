"""Configuration management and structured logging setup.

Settings are loaded from environment variables (and an optional ``.env`` file).
This module is the single source of truth for all runtime configuration; no
other module should read from ``os.environ`` directly.
"""

from __future__ import annotations

import logging
import sys
from enum import StrEnum

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketDataType(StrEnum):
    """IB market-data subscription types accepted by ``ib.reqMarketDataType``."""

    LIVE = "LIVE"
    FROZEN = "FROZEN"
    DELAYED = "DELAYED"
    DELAYED_FROZEN = "DELAYED_FROZEN"


class TransportMode(StrEnum):
    """MCP transport modes supported by this server."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"


class LogFormat(StrEnum):
    """Output format for ``structlog``."""

    JSON = "json"
    CONSOLE = "console"


class LogLevel(StrEnum):
    """Standard logging levels accepted by Python's ``logging`` module."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Defaults match ``spec.md`` §3.1 with one corrected value: ``IB_PORT`` defaults
    to ``4002`` (paper) so it is consistent with ``IB_PAPER_TRADING=true``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- IB Gateway / TWS connection -----------------------------------------
    IB_HOST: str = Field(default="127.0.0.1")
    IB_PORT: int = Field(default=4002, ge=1, le=65535)
    IB_CLIENT_ID: int = Field(default=1, ge=0)
    IB_ACCOUNT: str | None = Field(default=None)
    IB_PAPER_TRADING: bool = Field(default=True)
    IB_FLEX_TOKEN: str | None = Field(default=None)
    IB_MARKET_DATA_TYPE: MarketDataType = Field(default=MarketDataType.LIVE)

    # --- MCP transport --------------------------------------------------------
    MCP_TRANSPORT: TransportMode = Field(default=TransportMode.STREAMABLE_HTTP)
    MCP_HTTP_HOST: str = Field(default="127.0.0.1")
    MCP_HTTP_PORT: int = Field(default=8400, ge=1, le=65535)

    # --- Logging --------------------------------------------------------------
    LOG_LEVEL: LogLevel = Field(default=LogLevel.INFO)
    LOG_FORMAT: LogFormat = Field(default=LogFormat.JSON)
    LOG_TOOL_CALLS: bool = Field(default=False)


def setup_logging(settings: Settings) -> None:
    """Configure ``structlog`` according to ``settings``.

    Idempotent: callers may invoke this multiple times safely (e.g. in tests).
    Output is written to stderr so MCP stdio transport is unaffected.
    """

    log_level = getattr(logging, settings.LOG_LEVEL.value)

    # Reset root logger handlers so re-configuration takes effect.
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(log_level)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    final_processor: structlog.types.Processor
    if settings.LOG_FORMAT is LogFormat.JSON:
        final_processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, final_processor],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
