"""Tests for ``ibkr_mcp.logging_decorators``."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from ibkr_mcp.config import Settings, setup_logging
from ibkr_mcp.errors import ErrorCode, make_error
from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler


@pytest.fixture
def captured_logs() -> list[dict[str, object]]:
    """Capture structlog events emitted by the decorators."""

    captured: list[dict[str, object]] = []

    def _capture(_logger: object, _name: str, event_dict: dict[str, object]) -> str:
        captured.append(event_dict)
        return json.dumps(event_dict)

    structlog.configure(
        processors=[_capture],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    return captured


class TestToolErrorHandler:
    async def test_passes_through_success(self) -> None:
        @tool_error_handler
        async def ok() -> str:
            return '{"ok": true}'

        assert await ok() == '{"ok": true}'

    async def test_value_error_becomes_validation_error(self) -> None:
        @tool_error_handler
        async def boom() -> str:
            raise ValueError("nope")

        result = json.loads(await boom())
        assert result == {"error": "nope", "code": ErrorCode.VALIDATION_ERROR.value}

    async def test_connection_error_becomes_not_connected(self) -> None:
        @tool_error_handler
        async def boom() -> str:
            raise ConnectionError("gateway down")

        result = json.loads(await boom())
        assert result["code"] == ErrorCode.IB_NOT_CONNECTED.value
        assert "gateway down" in result["error"]

    async def test_timeout_error_becomes_ib_timeout(self) -> None:
        @tool_error_handler
        async def boom() -> str:
            raise TimeoutError("too slow")

        result = json.loads(await boom())
        assert result["code"] == ErrorCode.IB_TIMEOUT.value

    async def test_empty_message_uses_class_name(self) -> None:
        @tool_error_handler
        async def boom() -> str:
            raise RuntimeError()

        result = json.loads(await boom())
        assert result["error"] == "RuntimeError"


class TestToolCallLogger:
    async def test_no_log_when_disabled(
        self, captured_logs: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_TOOL_CALLS", "false")

        @tool_call_logger
        async def silent() -> str:
            return '{"ok": true}'

        await silent()
        assert captured_logs == []

    async def test_logs_success(
        self, captured_logs: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        @tool_call_logger
        async def my_tool(symbol: str = "AAPL") -> str:
            return '{"ok": true}'

        await my_tool(symbol="AAPL")

        assert len(captured_logs) == 1
        evt = captured_logs[0]
        assert evt["event"] == "tool_call"
        assert evt["tool"] == "my_tool"
        assert evt["outcome"] == "success"
        assert evt["input"] == {"symbol": "AAPL"}
        assert isinstance(evt["duration_ms"], int)
        assert "error_code" not in evt

    async def test_logs_error_outcome(
        self, captured_logs: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        @tool_call_logger
        async def fails() -> str:
            return make_error(ErrorCode.IB_INVALID_CONTRACT, "nope")

        await fails()

        assert len(captured_logs) == 1
        evt = captured_logs[0]
        assert evt["outcome"] == "error"
        assert evt["error_code"] == "IB_INVALID_CONTRACT"

    async def test_uncaught_exception_still_logged(
        self, captured_logs: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        @tool_call_logger
        async def boom() -> str:
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError):
            await boom()

        assert len(captured_logs) == 1
        evt = captured_logs[0]
        assert evt["outcome"] == "error"
        assert evt["error_code"] == "UNCAUGHT_EXCEPTION"


class TestStackedDecorators:
    async def test_error_handler_outside_logger(
        self, captured_logs: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When stacked, the logger sees the error JSON the handler produced."""

        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        @tool_error_handler
        @tool_call_logger
        async def stacked() -> str:
            raise ValueError("bad input")

        result = json.loads(await stacked())
        assert result["code"] == ErrorCode.VALIDATION_ERROR.value
        # The inner logger fires on the uncaught exception path.
        assert any(evt.get("outcome") == "error" for evt in captured_logs)

    async def test_setup_logging_then_decorator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity: once setup_logging has been called, decorators still work."""

        setup_logging(Settings())  # type: ignore[call-arg]
        monkeypatch.setenv("LOG_TOOL_CALLS", "true")

        @tool_error_handler
        @tool_call_logger
        async def ok() -> str:
            return '{"ok": true}'

        assert await ok() == '{"ok": true}'
