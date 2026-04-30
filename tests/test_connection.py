"""Tests for ``ibkr_mcp.connection``."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from ibkr_mcp.config import MarketDataType, Settings
from ibkr_mcp.connection import ConnectionManager

from .fake_ib import FakeIB


def _mgr(fake_ib: FakeIB, settings: Settings) -> ConnectionManager:
    # FakeIB is a structural stand-in for ib_async.IB; cast to satisfy mypy.
    from ib_async import IB  # local import to keep top-of-file clean

    return ConnectionManager(settings=settings, ib=cast(IB, fake_ib))


class TestConnectSuccess:
    async def test_connect_returns_true(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory())
        ok = await mgr.connect()
        assert ok is True
        assert mgr.is_connected is True

    async def test_connect_passes_host_port_client_id(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(
            fake_ib,
            settings_factory(IB_HOST="10.0.0.1", IB_PORT=7497, IB_CLIENT_ID=42),
        )
        await mgr.connect()
        assert fake_ib.connect_calls == [{"host": "10.0.0.1", "port": 7497, "clientId": 42}]

    async def test_account_resolved_from_managed_accounts_when_unset(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U7777777", "U8888888"]
        mgr = _mgr(fake_ib, settings_factory())  # IB_ACCOUNT unset
        await mgr.connect()
        assert mgr.account_id == "U7777777"

    async def test_account_resolved_from_explicit_setting(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1111111", "U2222222"]
        mgr = _mgr(fake_ib, settings_factory(IB_ACCOUNT="U2222222"))
        await mgr.connect()
        assert mgr.account_id == "U2222222"


class TestMarketDataType:
    @pytest.mark.parametrize(
        ("mdt", "expected_code"),
        [
            (MarketDataType.LIVE, 1),
            (MarketDataType.FROZEN, 2),
            (MarketDataType.DELAYED, 3),
            (MarketDataType.DELAYED_FROZEN, 4),
        ],
    )
    async def test_each_market_data_type_maps_to_correct_int(
        self,
        fake_ib: FakeIB,
        settings_factory: Callable[..., Settings],
        mdt: MarketDataType,
        expected_code: int,
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory(IB_MARKET_DATA_TYPE=mdt))
        await mgr.connect()
        assert fake_ib.market_data_type_calls == [expected_code]

    async def test_failure_does_not_abort_connect(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.market_data_type_should_fail = True
        mgr = _mgr(fake_ib, settings_factory())
        ok = await mgr.connect()
        assert ok is True
        assert mgr.is_connected is True


class TestConnectFailures:
    async def test_connect_async_raises_returns_false(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.connect_should_fail = True
        mgr = _mgr(fake_ib, settings_factory())
        ok = await mgr.connect()
        assert ok is False
        assert mgr.is_connected is False
        assert mgr.account_id is None

    async def test_connect_never_propagates_exception(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.connect_should_fail = True
        fake_ib.connect_error = OSError("network unreachable")
        mgr = _mgr(fake_ib, settings_factory())
        # Must not raise.
        await mgr.connect()

    async def test_account_not_in_managed_disconnects(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = ["U1234567"]
        mgr = _mgr(fake_ib, settings_factory(IB_ACCOUNT="U9999999"))
        ok = await mgr.connect()
        assert ok is False
        assert mgr.account_id is None
        # The manager must drop the bad-config connection.
        assert fake_ib.disconnect_calls >= 1
        assert mgr.is_connected is False

    async def test_no_managed_accounts_keeps_connection_but_account_is_none(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        fake_ib.managed_accounts = []
        mgr = _mgr(fake_ib, settings_factory())
        ok = await mgr.connect()
        assert ok is True
        assert mgr.account_id is None


class TestDisconnect:
    async def test_disconnect_when_connected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory())
        await mgr.connect()
        await mgr.disconnect()
        assert fake_ib.disconnect_calls == 1
        assert mgr.is_connected is False

    async def test_disconnect_is_idempotent_when_never_connected(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory())
        # No exception, no spurious call against the fake.
        await mgr.disconnect()
        assert fake_ib.disconnect_calls == 0


class TestProperties:
    async def test_ib_property_exposes_underlying_client(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory())
        assert mgr.ib is fake_ib  # same identity, no proxy

    async def test_account_id_none_before_connect(
        self, fake_ib: FakeIB, settings_factory: Callable[..., Settings]
    ) -> None:
        mgr = _mgr(fake_ib, settings_factory())
        assert mgr.account_id is None
