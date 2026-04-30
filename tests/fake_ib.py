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
* ``portfolio_data``            — list returned by ``portfolio()`` (rich fields)
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
        self.portfolio_data: list[Any] = []
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

    def portfolio(self, account: str = "") -> list[Any]:
        items = self.portfolio_data
        if account:
            return [item for item in items if getattr(item, "account", account) == account]
        return list(items)

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


class FakeContract:
    """Minimal stand-in for ``ib_async.Contract`` populated as tests need it."""

    def __init__(
        self,
        *,
        secType: str = "STK",
        symbol: str = "",
        exchange: str | None = "SMART",
        currency: str | None = "USD",
        conId: int | None = None,
        right: str | None = None,
        strike: float | None = None,
        lastTradeDateOrContractMonth: str | None = None,
        multiplier: str | None = None,
    ) -> None:
        self.secType = secType
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.conId = conId
        self.right = right
        self.strike = strike
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.multiplier = multiplier


class FakePortfolioItem:
    """Stand-in for ``ib_async.PortfolioItem``."""

    def __init__(
        self,
        *,
        contract: FakeContract,
        position: float,
        marketPrice: float | None = None,
        marketValue: float | None = None,
        averageCost: float | None = None,
        unrealizedPNL: float | None = None,
        realizedPNL: float | None = None,
        account: str = "U1234567",
    ) -> None:
        self.contract = contract
        self.position = position
        self.marketPrice = marketPrice
        self.marketValue = marketValue
        self.averageCost = averageCost
        self.unrealizedPNL = unrealizedPNL
        self.realizedPNL = realizedPNL
        self.account = account


class FakePosition:
    """Stand-in for ``ib_async.Position`` (basic positions, no market data)."""

    def __init__(
        self,
        *,
        account: str,
        contract: FakeContract,
        position: float,
        avgCost: float | None = None,
    ) -> None:
        self.account = account
        self.contract = contract
        self.position = position
        self.avgCost = avgCost


def make_stock_position(
    *,
    account: str = "U1234567",
    symbol: str = "AAPL",
    quantity: float = 100,
    avg_cost: float = 145.20,
    market_price: float = 150.50,
    con_id: int = 265598,
) -> FakePortfolioItem:
    """Build a stock-position ``PortfolioItem`` for ``portfolio()`` tests."""
    return FakePortfolioItem(
        contract=FakeContract(
            secType="STK",
            symbol=symbol,
            exchange="SMART",
            currency="USD",
            conId=con_id,
        ),
        position=quantity,
        marketPrice=market_price,
        marketValue=market_price * quantity,
        averageCost=avg_cost,
        unrealizedPNL=(market_price - avg_cost) * quantity,
        realizedPNL=0.0,
        account=account,
    )


class FakeGreeks:
    """Stand-in for ``ib_async.OptionComputation`` used in Ticker.*Greeks."""

    def __init__(
        self,
        *,
        delta: float | None = None,
        gamma: float | None = None,
        theta: float | None = None,
        vega: float | None = None,
        impliedVol: float | None = None,
    ) -> None:
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.impliedVol = impliedVol


class FakeTicker:
    """Stand-in for ``ib_async.Ticker`` populated lazily by tests."""

    def __init__(self, **fields: Any) -> None:
        # Defaults reflect ib_async, which uses NaN for "no data".
        defaults: dict[str, Any] = {
            "contract": None,
            "last": None,
            "bid": None,
            "ask": None,
            "bidSize": None,
            "askSize": None,
            "volume": None,
            "high": None,
            "low": None,
            "open": None,
            "close": None,
            "openInterest": None,
            "modelGreeks": None,
            "lastGreeks": None,
            "bidGreeks": None,
            "askGreeks": None,
        }
        defaults.update(fields)
        for key, value in defaults.items():
            setattr(self, key, value)


class FakeHistoricalBar:
    """Stand-in for ``ib_async.BarData``."""

    def __init__(
        self,
        *,
        date: Any,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        average: float | None = None,
        barCount: int | None = None,
    ) -> None:
        self.date = date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.average = average
        self.barCount = barCount


class FakeOrder:
    """Stand-in for ``ib_async.Order``."""

    def __init__(
        self,
        *,
        orderId: int,
        action: str = "BUY",
        totalQuantity: float = 0,
        orderType: str = "MKT",
        lmtPrice: float = 0.0,
        auxPrice: float = 0.0,
        account: str = "U1234567",
    ) -> None:
        self.orderId = orderId
        self.action = action
        self.totalQuantity = totalQuantity
        self.orderType = orderType
        self.lmtPrice = lmtPrice
        self.auxPrice = auxPrice
        self.account = account


class FakeOrderStatus:
    """Stand-in for ``ib_async.OrderStatus``."""

    def __init__(
        self,
        *,
        status: str = "Submitted",
        filled: float = 0.0,
        avgFillPrice: float = 0.0,
    ) -> None:
        self.status = status
        self.filled = filled
        self.avgFillPrice = avgFillPrice


class FakeCommissionReport:
    """Stand-in for ``ib_async.CommissionReport``."""

    def __init__(self, *, commission: float = 0.0, currency: str = "USD") -> None:
        self.commission = commission
        self.currency = currency


class FakeFill:
    """Stand-in for ``ib_async.Fill``."""

    def __init__(self, *, commissionReport: FakeCommissionReport | None = None) -> None:
        self.commissionReport = commissionReport


class FakeTradeLogEntry:
    """Stand-in for ``ib_async.TradeLogEntry``."""

    def __init__(self, *, time: Any, status: str = "", message: str = "") -> None:
        self.time = time
        self.status = status
        self.message = message


class FakeTrade:
    """Stand-in for ``ib_async.Trade``."""

    def __init__(
        self,
        *,
        contract: FakeContract,
        order: FakeOrder,
        orderStatus: FakeOrderStatus | None = None,
        fills: list[FakeFill] | None = None,
        log: list[FakeTradeLogEntry] | None = None,
    ) -> None:
        self.contract = contract
        self.order = order
        self.orderStatus = orderStatus or FakeOrderStatus()
        self.fills = list(fills or [])
        self.log = list(log or [])


class FakeContractDetails:
    """Stand-in for ``ib_async.ContractDetails``."""

    def __init__(
        self,
        *,
        contract: FakeContract,
        marketName: str | None = None,
        validExchanges: str | None = None,
        longName: str | None = None,
        industry: str | None = None,
        category: str | None = None,
        subcategory: str | None = None,
        tradingHours: str | None = None,
        liquidHours: str | None = None,
        timeZoneId: str | None = None,
        realExpirationDate: str | None = None,
    ) -> None:
        self.contract = contract
        self.marketName = marketName
        self.validExchanges = validExchanges
        self.longName = longName
        self.industry = industry
        self.category = category
        self.subcategory = subcategory
        self.tradingHours = tradingHours
        self.liquidHours = liquidHours
        self.timeZoneId = timeZoneId
        self.realExpirationDate = realExpirationDate


def make_option_position(
    *,
    account: str = "U1234567",
    symbol: str = "AAPL",
    quantity: float = -5,
    strike: float = 150.0,
    right: str = "C",
    expiry: str = "20260516",
    multiplier: str = "100",
    avg_cost: float = 320.0,
    market_price: float = 3.50,
    con_id: int = 4123456,
) -> FakePortfolioItem:
    """Build an option-position ``PortfolioItem``."""
    contract = FakeContract(
        secType="OPT",
        symbol=symbol,
        exchange="SMART",
        currency="USD",
        conId=con_id,
        right=right,
        strike=strike,
        lastTradeDateOrContractMonth=expiry,
        multiplier=multiplier,
    )
    # IB reports option market_value as price * quantity * multiplier.
    mult = int(multiplier)
    market_value = market_price * quantity * mult
    return FakePortfolioItem(
        contract=contract,
        position=quantity,
        marketPrice=market_price,
        marketValue=market_value,
        averageCost=avg_cost,
        unrealizedPNL=(market_price * mult - avg_cost) * quantity,
        realizedPNL=0.0,
        account=account,
    )
