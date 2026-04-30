"""In-memory ``ib_async.IB`` replacement used across the test suite.

The real ``ib_async.IB`` opens a TCP connection on instantiation paths that we
cannot reach in CI, so every unit test for tool logic talks to a ``FakeIB``
instead. Methods are populated as later milestones add tools that depend on
them; the surface stays minimal until the production code grows.

Public attributes (mutable, set per-test) drive the canned responses:

* ``connected``                 — value of ``isConnected()`` after ``connectAsync``
* ``connect_should_fail``       — make ``connectAsync`` raise
* ``managed_accounts``          — list returned by ``managedAccounts()``
* ``market_data_type_calls``    — list of ints captured from ``reqMarketDataType``
* ``account_summary``           — list returned by ``accountSummaryAsync``
* ``positions_data``            — list returned by ``reqPositionsAsync``/``positions``
* ``tickers``                   — list returned by ``reqTickersAsync``
* ``historical_bars``           — list returned by ``reqHistoricalDataAsync``
* ``contract_details``          — list returned by ``reqContractDetailsAsync``
* ``open_orders_data``          — list returned by ``reqOpenOrdersAsync``/``openOrders``
* ``trades_data``               — list returned by ``trades()``
* ``sec_def_opt_params_data``   — list returned by ``reqSecDefOptParamsAsync``
"""

from __future__ import annotations

from typing import Any


class FakeIB:
    """A scripted stand-in for :class:`ib_async.IB`.

    Tests should reach for the helper builders below (``make_*``) instead of
    constructing IB objects directly, so the test suite stays insulated from
    upstream type changes.
    """

    def __init__(self) -> None:
        # connection state
        self.connected: bool = False
        self.connect_should_fail: bool = False
        self.connect_error: BaseException = ConnectionRefusedError("FakeIB refused")
        self.connect_calls: list[dict[str, Any]] = []
        self.disconnect_calls: int = 0

        # account / metadata
        self.managed_accounts: list[str] = ["U1234567"]
        self.market_data_type_calls: list[int] = []
        self.market_data_type_should_fail: bool = False

        # data caches consumed by tools (populated as needed by tests)
        self.account_summary: list[Any] = []
        self.positions_data: list[Any] = []
        self.tickers: list[Any] = []
        self.historical_bars: list[Any] = []
        self.contract_details: list[Any] = []
        self.open_orders_data: list[Any] = []
        self.trades_data: list[Any] = []
        self.sec_def_opt_params_data: list[Any] = []

        # call recorders for assertions
        self.tickers_calls: list[tuple[Any, ...]] = []
        self.historical_calls: list[dict[str, Any]] = []
        self.contract_details_calls: list[Any] = []
        self.sec_def_opt_calls: list[dict[str, Any]] = []

    # --------------------------------------------------------------- connection
    async def connectAsync(
        self,
        host: str,
        port: int,
        clientId: int,
        **_: Any,
    ) -> None:
        self.connect_calls.append({"host": host, "port": port, "clientId": clientId})
        if self.connect_should_fail:
            raise self.connect_error
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def disconnectAsync(self) -> None:
        self.disconnect()

    def isConnected(self) -> bool:
        return self.connected

    # --------------------------------------------------------------- accounts
    def managedAccounts(self) -> list[str]:
        return list(self.managed_accounts)

    def reqMarketDataType(self, market_data_type: int) -> None:
        if self.market_data_type_should_fail:
            raise RuntimeError("reqMarketDataType failed")
        self.market_data_type_calls.append(market_data_type)

    # --------------------------------------------------------------- account / portfolio
    async def accountSummaryAsync(self, account: str = "") -> list[Any]:
        return list(self.account_summary)

    async def reqPositionsAsync(self) -> list[Any]:
        return list(self.positions_data)

    def positions(self, account: str = "") -> list[Any]:
        return list(self.positions_data)

    # --------------------------------------------------------------- market data
    async def reqTickersAsync(self, *contracts: Any) -> list[Any]:
        self.tickers_calls.append(contracts)
        return list(self.tickers)

    async def qualifyContractsAsync(self, *contracts: Any) -> list[Any]:
        return list(contracts)

    async def reqHistoricalDataAsync(
        self,
        contract: Any,
        endDateTime: str = "",
        durationStr: str = "",
        barSizeSetting: str = "",
        whatToShow: str = "TRADES",
        useRTH: bool = True,
        formatDate: int = 1,
        keepUpToDate: bool = False,
        chartOptions: list[Any] | None = None,
    ) -> list[Any]:
        self.historical_calls.append(
            {
                "contract": contract,
                "endDateTime": endDateTime,
                "durationStr": durationStr,
                "barSizeSetting": barSizeSetting,
                "whatToShow": whatToShow,
                "useRTH": useRTH,
            }
        )
        return list(self.historical_bars)

    # --------------------------------------------------------------- contract details
    async def reqContractDetailsAsync(self, contract: Any) -> list[Any]:
        self.contract_details_calls.append(contract)
        return list(self.contract_details)

    # --------------------------------------------------------------- orders
    async def reqOpenOrdersAsync(self) -> list[Any]:
        return list(self.open_orders_data)

    def openOrders(self) -> list[Any]:
        return list(self.open_orders_data)

    def trades(self) -> list[Any]:
        return list(self.trades_data)

    # --------------------------------------------------------------- options
    async def reqSecDefOptParamsAsync(
        self,
        underlyingSymbol: str,
        futFopExchange: str,
        underlyingSecType: str,
        underlyingConId: int,
    ) -> list[Any]:
        self.sec_def_opt_calls.append(
            {
                "underlyingSymbol": underlyingSymbol,
                "futFopExchange": futFopExchange,
                "underlyingSecType": underlyingSecType,
                "underlyingConId": underlyingConId,
            }
        )
        return list(self.sec_def_opt_params_data)


# ----------------------------------------------------------------- builders
def make_account_summary(
    account: str = "U1234567",
    *,
    net_liquidation: float = 150_000.0,
    total_cash: float = 50_000.0,
    gross_position_value: float = 100_000.0,
    unrealized_pnl: float = -1_200.5,
    realized_pnl: float = 3_400.0,
    available_funds: float = 45_000.0,
    buying_power: float = 90_000.0,
    maint_margin: float = 55_000.0,
    init_margin: float = 70_000.0,
    currency: str = "USD",
) -> list[Any]:
    """Build a list of ``AccountValue``-shaped dicts for ``accountSummaryAsync``."""

    pairs = {
        "NetLiquidation": net_liquidation,
        "TotalCashValue": total_cash,
        "GrossPositionValue": gross_position_value,
        "UnrealizedPnL": unrealized_pnl,
        "RealizedPnL": realized_pnl,
        "AvailableFunds": available_funds,
        "BuyingPower": buying_power,
        "MaintMarginReq": maint_margin,
        "InitMarginReq": init_margin,
    }
    return [
        _AccountValue(account=account, tag=tag, value=str(value), currency=currency)
        for tag, value in pairs.items()
    ]


class _AccountValue:
    """Stand-in for ``ib_async.AccountValue`` (only the fields tools read)."""

    def __init__(self, account: str, tag: str, value: str, currency: str) -> None:
        self.account = account
        self.tag = tag
        self.value = value
        self.currency = currency
