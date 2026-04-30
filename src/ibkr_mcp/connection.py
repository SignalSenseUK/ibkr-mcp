"""IB Gateway / TWS connection management.

This module wraps :class:`ib_async.IB` with a small ``ConnectionManager`` that

* never raises on connection failure (the server must stay up — spec §5);
* applies ``IB_MARKET_DATA_TYPE`` to the connected client;
* resolves the active account id from ``IB_ACCOUNT`` or, if unset, from the
  first entry of ``ib.managedAccounts()``.

The manager is constructed by the FastMCP lifespan and stored on the typed
``AppContext`` so tools can read ``mgr.ib`` and ``mgr.account_id`` directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

import structlog
from ib_async import IB

from ibkr_mcp.config import MarketDataType, Settings

_log = structlog.get_logger("ibkr_mcp.connection")


# ib_async / TWS market-data-type integer codes. See:
# https://interactivebrokers.github.io/tws-api/market_data_type.html
_MDT_CODE: Final[dict[MarketDataType, int]] = {
    MarketDataType.LIVE: 1,
    MarketDataType.FROZEN: 2,
    MarketDataType.DELAYED: 3,
    MarketDataType.DELAYED_FROZEN: 4,
}


class ConnectionManager:
    """Wraps an ``ib_async.IB`` client with idempotent connect/disconnect."""

    def __init__(self, settings: Settings, ib: IB | None = None) -> None:
        self._settings = settings
        self._ib: IB = ib if ib is not None else IB()
        self._account_id: str | None = None

    # ------------------------------------------------------------------ props
    @property
    def ib(self) -> IB:
        """The underlying ``ib_async.IB`` client (always present)."""
        return self._ib

    @property
    def is_connected(self) -> bool:
        """Whether the client believes it is connected to the gateway."""
        try:
            return bool(self._ib.isConnected())
        except Exception:  # pragma: no cover — defensive
            return False

    @property
    def account_id(self) -> str | None:
        """Resolved account id, or ``None`` if connect has not (yet) succeeded."""
        return self._account_id

    # --------------------------------------------------------------- methods
    async def connect(self) -> bool:
        """Connect to IB Gateway / TWS.

        Returns ``True`` on success, ``False`` on any failure. Never raises;
        all errors are logged via ``structlog`` so the caller (the MCP
        lifespan) can keep the server alive even when the gateway is down.
        """

        host = self._settings.IB_HOST
        port = self._settings.IB_PORT
        client_id = self._settings.IB_CLIENT_ID

        try:
            await self._ib.connectAsync(host=host, port=port, clientId=client_id)
        except Exception as exc:
            _log.warning(
                "ib_connect_failed",
                host=host,
                port=port,
                client_id=client_id,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
            return False

        # Apply market-data-type for the lifetime of this connection. This is
        # done once here so individual tools never need to re-issue it.
        mdt_code = _MDT_CODE[self._settings.IB_MARKET_DATA_TYPE]
        try:
            self._ib.reqMarketDataType(mdt_code)
        except Exception as exc:
            _log.warning(
                "ib_reqMarketDataType_failed",
                market_data_type=self._settings.IB_MARKET_DATA_TYPE.value,
                error=str(exc),
            )

        # Resolve the account id.
        managed = list(_safe_iter(self._ib.managedAccounts()))
        requested = self._settings.IB_ACCOUNT
        if requested is not None:
            if requested not in managed:
                _log.error(
                    "ib_account_not_found",
                    requested=requested,
                    managed=managed,
                )
                # Disconnect — the configuration is wrong and serving tools
                # against the wrong account would be unsafe.
                await self.disconnect()
                self._account_id = None
                return False
            self._account_id = requested
        elif managed:
            self._account_id = managed[0]
        else:
            _log.warning("ib_no_managed_accounts")
            self._account_id = None

        _log.info(
            "ib_connected",
            host=host,
            port=port,
            client_id=client_id,
            account_id=self._account_id,
            market_data_type=self._settings.IB_MARKET_DATA_TYPE.value,
        )
        return True

    async def disconnect(self) -> None:
        """Disconnect from IB Gateway / TWS. Idempotent."""
        try:
            if self._ib.isConnected():
                self._ib.disconnect()
        except Exception as exc:
            _log.warning("ib_disconnect_failed", error=str(exc))


def _safe_iter(value: object) -> Iterable[str]:
    """Return ``value`` as an iterable of strings, tolerating non-list returns."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Iterable):
        return ()
    try:
        return [str(item) for item in value]
    except TypeError:
        return ()
