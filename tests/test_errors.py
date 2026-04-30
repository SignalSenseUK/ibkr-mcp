"""Tests for ``ibkr_mcp.errors``."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from ibkr_mcp.errors import ErrorCode, ErrorResponse, make_error, map_exception


class TestErrorCode:
    def test_all_spec_codes_present(self) -> None:
        # spec §10 enumerates 8 codes; we add NOT_IMPLEMENTED for the alerts placeholder.
        expected = {
            "IB_NOT_CONNECTED",
            "IB_CONNECTION_FAILED",
            "IB_TIMEOUT",
            "IB_INVALID_CONTRACT",
            "IB_NO_MARKET_DATA",
            "IB_FLEX_ERROR",
            "IB_ACCOUNT_NOT_FOUND",
            "VALIDATION_ERROR",
            "NOT_IMPLEMENTED",
        }
        assert {c.value for c in ErrorCode} == expected


class TestMakeError:
    def test_make_error_shape(self) -> None:
        payload = json.loads(make_error(ErrorCode.IB_NOT_CONNECTED, "down"))
        assert payload == {"error": "down", "code": "IB_NOT_CONNECTED"}

    def test_make_error_round_trips(self) -> None:
        encoded = make_error(ErrorCode.IB_TIMEOUT, "slow")
        decoded = ErrorResponse.model_validate_json(encoded)
        assert decoded.code is ErrorCode.IB_TIMEOUT
        assert decoded.error == "slow"

    def test_invalid_code_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ErrorResponse.model_validate({"error": "x", "code": "NOT_A_REAL_CODE"})


class TestMapException:
    def test_timeout_error(self) -> None:
        # ``asyncio.TimeoutError`` is an alias of the builtin ``TimeoutError`` on 3.11+
        # but we still test the bare builtin to lock the contract.
        assert map_exception(TimeoutError()) is ErrorCode.IB_TIMEOUT

    def test_builtin_timeout_error(self) -> None:
        assert map_exception(TimeoutError("slow")) is ErrorCode.IB_TIMEOUT

    def test_connection_error(self) -> None:
        assert map_exception(ConnectionError("nope")) is ErrorCode.IB_NOT_CONNECTED

    def test_not_implemented(self) -> None:
        assert map_exception(NotImplementedError("soon")) is ErrorCode.NOT_IMPLEMENTED

    def test_value_error_falls_through(self) -> None:
        assert map_exception(ValueError("bad")) is ErrorCode.VALIDATION_ERROR

    def test_pydantic_validation_error(self) -> None:
        class M(BaseModel):
            x: int

        try:
            M(x="bad")  # type: ignore[arg-type]
        except ValidationError as exc:
            assert map_exception(exc) is ErrorCode.VALIDATION_ERROR
        else:  # pragma: no cover
            pytest.fail("ValidationError should have been raised")

    def test_message_hint_invalid_contract(self) -> None:
        exc = RuntimeError("No security definition has been found for the request")
        assert map_exception(exc) is ErrorCode.IB_INVALID_CONTRACT

    def test_message_hint_no_market_data(self) -> None:
        exc = RuntimeError("Requested market data is not subscribed")
        assert map_exception(exc) is ErrorCode.IB_NO_MARKET_DATA

    def test_message_hint_flex(self) -> None:
        exc = RuntimeError("Flex query token expired")
        assert map_exception(exc) is ErrorCode.IB_FLEX_ERROR

    def test_message_hint_account(self) -> None:
        exc = RuntimeError("Account U999 not linked to this connection")
        assert map_exception(exc) is ErrorCode.IB_ACCOUNT_NOT_FOUND

    def test_unknown_exception_is_validation(self) -> None:
        assert map_exception(Exception("something else")) is ErrorCode.VALIDATION_ERROR
