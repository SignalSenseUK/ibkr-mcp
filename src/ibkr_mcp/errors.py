"""Error codes and structured error responses.

Every tool returns either a JSON-serialised success model or a JSON-serialised
:class:`ErrorResponse`. This module is the single source of truth for the
``code`` field; spec §10 defines the canonical set.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    """Canonical error codes returned by tools (spec §10)."""

    IB_NOT_CONNECTED = "IB_NOT_CONNECTED"
    IB_CONNECTION_FAILED = "IB_CONNECTION_FAILED"
    IB_TIMEOUT = "IB_TIMEOUT"
    IB_INVALID_CONTRACT = "IB_INVALID_CONTRACT"
    IB_NO_MARKET_DATA = "IB_NO_MARKET_DATA"
    IB_FLEX_ERROR = "IB_FLEX_ERROR"
    IB_ACCOUNT_NOT_FOUND = "IB_ACCOUNT_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ErrorResponse(BaseModel):
    """Standard error envelope returned by every tool on failure."""

    error: str = Field(description="Human-readable error message.")
    code: ErrorCode = Field(description="Stable machine-readable error code.")


def make_error(code: ErrorCode, message: str) -> str:
    """Serialise an :class:`ErrorResponse` to JSON.

    All tools should return the result of this function (rather than raising)
    when an error condition is detected.
    """

    return ErrorResponse(error=message, code=code).model_dump_json()


# Substrings that, when seen in an exception message, hint at a specific code.
# Order matters: the first match wins. Kept as substrings (not regex) so the
# mapping table is trivially auditable.
_MESSAGE_HINTS: tuple[tuple[str, ErrorCode], ...] = (
    ("not connected", ErrorCode.IB_NOT_CONNECTED),
    ("no security definition", ErrorCode.IB_INVALID_CONTRACT),
    ("ambiguous contract", ErrorCode.IB_INVALID_CONTRACT),
    ("no market data permission", ErrorCode.IB_NO_MARKET_DATA),
    ("market data is not subscribed", ErrorCode.IB_NO_MARKET_DATA),
    ("requested market data is not subscribed", ErrorCode.IB_NO_MARKET_DATA),
    ("flex", ErrorCode.IB_FLEX_ERROR),
    ("account", ErrorCode.IB_ACCOUNT_NOT_FOUND),
)


def map_exception(exc: BaseException) -> ErrorCode:
    """Map a raised exception to the appropriate :class:`ErrorCode`.

    The mapping is deliberately conservative: anything we can't classify is
    treated as ``VALIDATION_ERROR`` (the catch-all bucket). Tool-call sites
    are still expected to surface the original message via :func:`make_error`.
    """

    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return ErrorCode.IB_TIMEOUT
    if isinstance(exc, ConnectionError):
        return ErrorCode.IB_NOT_CONNECTED
    if isinstance(exc, NotImplementedError):
        return ErrorCode.NOT_IMPLEMENTED

    # Pydantic ValidationError lives in pydantic; we match by class name to
    # avoid a hard import dependency in this module.
    if exc.__class__.__name__ == "ValidationError":
        return ErrorCode.VALIDATION_ERROR

    message = str(exc).lower()
    for needle, code in _MESSAGE_HINTS:
        if needle in message:
            return code

    if isinstance(exc, ValueError):
        return ErrorCode.VALIDATION_ERROR

    return ErrorCode.VALIDATION_ERROR
