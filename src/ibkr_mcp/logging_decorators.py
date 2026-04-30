"""Decorators applied to every tool function.

These decorators implement two cross-cutting concerns from the spec:

* **Error handling** (spec §10) — :func:`tool_error_handler` catches every
  exception raised by a tool and converts it to a structured JSON
  :class:`~ibkr_mcp.errors.ErrorResponse`.

* **Per-tool-call logging** (spec §12.3) — :func:`tool_call_logger` emits a
  ``tool_call`` event when ``LOG_TOOL_CALLS`` is true, with the tool name,
  redacted input, duration in milliseconds, and outcome.

The decorators are designed to stack in this order::

    @tool_error_handler
    @tool_call_logger
    async def my_tool(ctx, ...): ...

so the logger sees the post-error-handling string the tool returned (success
or error JSON) and can extract ``error_code`` from it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, cast

import structlog

from ibkr_mcp.config import Settings
from ibkr_mcp.errors import ErrorCode, make_error, map_exception

_log = structlog.get_logger("ibkr_mcp.tool")


def tool_error_handler[**P](fn: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """Catch every exception raised by ``fn`` and return a JSON error envelope."""

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            code = map_exception(exc)
            return make_error(code, str(exc) or exc.__class__.__name__)

    return wrapper


def _redact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop the MCP ``Context`` (and similar non-serialisable values) from logs."""

    redacted: dict[str, Any] = {}
    for key, value in kwargs.items():
        # FastMCP's Context object is not JSON-serialisable and not interesting in logs.
        if value.__class__.__name__ == "Context":
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            redacted[key] = repr(value)
        else:
            redacted[key] = value
    return redacted


def _outcome_from_result(result: str) -> tuple[str, ErrorCode | None]:
    """Inspect a tool's JSON return string to derive (outcome, error_code)."""

    try:
        parsed = json.loads(result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "success", None

    if isinstance(parsed, dict) and "error" in parsed and "code" in parsed:
        raw_code = parsed.get("code")
        try:
            code = ErrorCode(raw_code) if isinstance(raw_code, str) else None
        except ValueError:
            code = None
        return "error", code

    return "success", None


def tool_call_logger[**P](fn: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """Emit a structured ``tool_call`` event when ``LOG_TOOL_CALLS`` is true.

    The decorator inspects ``Settings()`` lazily on each call so test runs that
    flip the env var see the new value without needing to reimport the module.
    """

    tool_name = getattr(fn, "__name__", "<anonymous>")

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        if not Settings().LOG_TOOL_CALLS:
            return await fn(*args, **kwargs)

        start = time.perf_counter()
        result: str
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            _log.error(
                "tool_call",
                tool=tool_name,
                input=_redact_kwargs(dict(kwargs)),
                duration_ms=duration_ms,
                outcome="error",
                error_code="UNCAUGHT_EXCEPTION",
            )
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        outcome, error_code = _outcome_from_result(result)
        log_kwargs: dict[str, Any] = {
            "tool": tool_name,
            "input": _redact_kwargs(dict(kwargs)),
            "duration_ms": duration_ms,
            "outcome": outcome,
        }
        if error_code is not None:
            log_kwargs["error_code"] = error_code.value

        if outcome == "error":
            _log.warning("tool_call", **log_kwargs)
        else:
            _log.info("tool_call", **log_kwargs)
        return result

    return cast(Callable[P, Awaitable[str]], wrapper)
