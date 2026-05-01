# Tool Usage Reference

Every tool returns a JSON-serialised string. Successful responses are Pydantic-validated payloads with optional fields omitted (`exclude_none=True`). Failures are always shaped like:

```json
{
  "error": "human-readable message",
  "code": "ONE_OF_THE_ERROR_CODES"
}
```

See [`docs/architecture.md` §7](architecture.md#7-error-model) for the full list of error codes and the exception → code mapping. See [`docs/troubleshooting.md`](troubleshooting.md) for what each error means in practice.

> **Sec types accepted by all symbol-resolving tools:** `STK`, `OPT`, `FUT`, `CASH`, `BOND`, `IND`. For `OPT`, you must pass `expiry` (YYYYMMDD), `strike`, and `right` (`C` / `P`). For `FUT`, you must pass `expiry`. For `CASH` (forex), `symbol` is the base currency.

---

## Table of contents

- [6.1 `get_server_status`](#61-get_server_status)
- [6.2 `get_account_info`](#62-get_account_info)
- [6.3 `get_positions`](#63-get_positions)
- [6.4 `get_market_data`](#64-get_market_data)
- [6.5 `get_historical_data`](#65-get_historical_data)
- [6.6 `get_order_status`](#66-get_order_status)
- [6.7 `get_live_orders`](#67-get_live_orders)
- [6.8 `get_contract_details`](#68-get_contract_details)
- [6.9 `get_option_chain`](#69-get_option_chain)
- [6.10 `get_portfolio_greeks`](#610-get_portfolio_greeks)
- [6.11 `list_flex_queries`](#611-list_flex_queries)
- [6.12 `get_flex_query`](#612-get_flex_query)
- [6.13 `get_alerts` (NOT_IMPLEMENTED)](#613-get_alerts-not-implemented)
- [Cross-cutting input formats](#cross-cutting-input-formats)

---

## 6.1 `get_server_status`

Health check. **Use this before issuing data calls** to verify the server is connected to IB Gateway.

**Input:** `{}`

**Output (connected):**

```json
{
  "status": "connected",
  "ibHost": "127.0.0.1",
  "ibPort": 4002,
  "clientId": 1,
  "accountId": "U1234567",
  "paperTrading": true,
  "serverVersion": "0.1.0",
  "transport": "streamable-http",
  "uptimeSeconds": 3600,
  "marketDataType": "LIVE",
  "registeredTools": 11,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

`status` ∈ `{"connected", "disconnected"}`. The tool **does not return errors** — it always succeeds, even when disconnected.

---

## 6.2 `get_account_info`

Account-level summary: net liquidation, cash, P&L, margin requirements.

**Input:**

```json
{ "accountId": "U1234567" }   // optional — defaults to the connected account
```

**Output:**

```json
{
  "accountId": "U1234567",
  "netLiquidation": 150000.00,
  "totalCashValue": 50000.00,
  "grossPositionValue": 100000.00,
  "unrealizedPnL": -1200.50,
  "realizedPnL": 3400.00,
  "availableFunds": 45000.00,
  "buyingPower": 90000.00,
  "maintMarginReq": 55000.00,
  "initMarginReq": 70000.00,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

**Errors:** `IB_NOT_CONNECTED`, `IB_ACCOUNT_NOT_FOUND` (when a non-managed `accountId` is requested).

---

## 6.3 `get_positions`

All open positions. Options carry `right`, `strike`, `expiry`, `multiplier`.

**Input:**

```json
{ "accountId": "U1234567" }   // optional
```

**Output:**

```json
{
  "account": "U1234567",
  "timestamp": "2026-04-29T15:30:00Z",
  "positions": [
    {
      "symbol": "AAPL",
      "secType": "STK",
      "exchange": "SMART",
      "currency": "USD",
      "conId": 265598,
      "position": 100,
      "avgCost": 145.20,
      "marketPrice": 150.50,
      "marketValue": 15050.00,
      "unrealizedPnL": 530.00,
      "realizedPnL": 0.0
    },
    {
      "symbol": "AAPL",
      "secType": "OPT",
      "right": "C",
      "strike": 150.0,
      "expiry": "20260516",
      "multiplier": 100,
      "position": -5,
      "avgCost": 3.20,
      "marketPrice": 3.50,
      "marketValue": -1750.00,
      "unrealizedPnL": -150.00,
      "realizedPnL": 0.0
    }
  ]
}
```

**Source preference:** the tool reads from `ib.portfolio()` first (richer fields). When that's empty (e.g. before account updates have arrived) it falls back to `ib.reqPositionsAsync()`.

**Errors:** `IB_NOT_CONNECTED`, `IB_ACCOUNT_NOT_FOUND`.

---

## 6.4 `get_market_data`

Single-shot snapshot quote. For options, the response includes Greeks via the priority `modelGreeks → lastGreeks → bidGreeks → askGreeks` (see [architecture §6.3](architecture.md#63-greeks-priority)).

**Input (equity):**

```json
{ "symbol": "AAPL", "secType": "STK" }
```

**Input (option):**

```json
{
  "symbol": "AAPL",
  "secType": "OPT",
  "expiry": "20260516",
  "strike": 150.0,
  "right": "C"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `symbol` | yes | Ticker symbol |
| `secType` | yes | `STK` / `OPT` / `FUT` / `CASH` / `BOND` / `IND` |
| `exchange` | no | default `SMART` |
| `currency` | no | default `USD` |
| `expiry`, `strike`, `right` | conditional | required for OPT |

**Output (equity):**

```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "lastPrice": 150.50,
  "bid": 150.48,
  "ask": 150.52,
  "bidSize": 400,
  "askSize": 300,
  "volume": 45000000,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

**Output (option):** as above plus `expiry`, `strike`, `right`, `openInterest`, `delta`, `gamma`, `theta`, `vega`, `impliedVolatility`.

**Snapshot semantics:** the tool calls `ib.reqTickersAsync(contract)` once and returns. It **never** opens a streaming subscription — there are no leaks across calls.

**Errors:** `IB_NOT_CONNECTED`, `IB_INVALID_CONTRACT` (qualification returned empty), `IB_NO_MARKET_DATA` (no permission / no subscription / data type unavailable).

> **Common gotcha:** if `IB_MARKET_DATA_TYPE=LIVE` but you don't have a live subscription, the gateway returns no data. Try `IB_MARKET_DATA_TYPE=DELAYED` for development.

---

## 6.5 `get_historical_data`

OHLCV bars. Accepts both IB-native duration strings and ISO 8601.

**Input:**

```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "duration": "P30D",
  "barSize": "1 day",
  "endDateTime": "20260429 15:30:00"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `symbol`, `secType` | yes | as above |
| `duration` | yes | `30 D` (IB-native) or `P30D` (ISO 8601) |
| `barSize` | yes | `1 secs`, `5 secs`, `1 min`, `5 mins`, `1 hour`, `1 day`, `1 week`, … |
| `endDateTime` | no | end point for the bars; defaults to "now" |
| `expiry`, `strike`, `right` | conditional | for OPT/FUT |

### ISO 8601 duration translation

| ISO 8601 | IB native |
|----------|-----------|
| `PT3600S` | `3600 S` |
| `PT1H` | `3600 S` |
| `P30D` | `30 D` |
| `P2W` | `2 W` |
| `P6M` | `6 M` |
| `P1Y` | `1 Y` |

IB-native strings are passed through unchanged.

**Output:**

```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "barSize": "1 day",
  "bars": [
    {
      "date": "20260331",
      "open": 149.00,
      "high": 151.50,
      "low": 148.20,
      "close": 150.80,
      "volume": 52000000,
      "wap": 150.10,
      "count": 50000
    }
  ]
}
```

**Errors:** `IB_NOT_CONNECTED`, `IB_INVALID_CONTRACT`, `VALIDATION_ERROR` (unparseable `duration`).

> **`whatToShow` is fixed at `TRADES` and `useRTH=True`.** If you need `MIDPOINT`, `BID`, `ASK`, `BID_ASK`, etc., open an issue — those are easy to expose via additional parameters but were intentionally kept off the v0.1 surface.

---

## 6.6 `get_order_status`

Status of a specific order by `orderId`, including aggregated commission and submission/fill timestamps.

**Input:**

```json
{ "orderId": 1001 }
```

**Output:**

```json
{
  "orderId": 1001,
  "status": "Filled",
  "symbol": "AAPL",
  "secType": "STK",
  "action": "BUY",
  "quantity": 10,
  "orderType": "MKT",
  "filledQuantity": 10,
  "avgFillPrice": 150.52,
  "commission": 1.00,
  "submittedAt": "2026-04-29T15:25:00Z",
  "filledAt": "2026-04-29T15:25:01Z"
}
```

- `commission` is the **sum** of `trade.fills[*].commissionReport.commission`.
- `limitPrice` and `stopPrice` are populated only when `orderType` actually uses them (`LMT`, `STP LMT`, `TRAIL LIMIT`, `REL` for limit; `STP`, `STP LMT`, `TRAIL`, `TRAIL LIMIT` for stop).
- `submittedAt` is the timestamp of the **first** entry in `trade.log`. `filledAt` is the latest entry whose status is `Filled` or `PartiallyFilled`.

**Errors:** `IB_NOT_CONNECTED`, `VALIDATION_ERROR` (unknown `orderId` in this session).

> **Read-only.** This tool does not place, modify, or cancel orders. By design, the server is incapable of doing so.

---

## 6.7 `get_live_orders`

All currently open / pending orders. Calls `ib.reqOpenOrdersAsync()` to refresh the cache before reading.

**Input:**

```json
{ "accountId": "U1234567" }   // optional
```

**Output:**

```json
{
  "account": "U1234567",
  "timestamp": "2026-04-29T15:30:00Z",
  "orders": [
    {
      "orderId": 1002,
      "status": "Submitted",
      "symbol": "MSFT",
      "secType": "STK",
      "action": "BUY",
      "quantity": 5,
      "orderType": "LMT",
      "limitPrice": 380.0,
      "submittedAt": "2026-04-29T14:00:00Z"
    }
  ]
}
```

Filtered to active statuses: `PendingSubmit`, `Submitted`, `ApiPending`, `PreSubmitted`, `PartiallyFilled`. `Filled` and `Cancelled` orders are excluded.

**Errors:** `IB_NOT_CONNECTED`, `IB_ACCOUNT_NOT_FOUND`.

---

## 6.8 `get_contract_details`

Resolves a symbol → conId, primary exchange, trading hours, long name, industry classification. For options, also returns `strike`, `right`, `expiry`, `multiplier`, `lastTradeDate`.

**Input:**

```json
{ "symbol": "AAPL", "secType": "STK" }
```

**Output (stock):**

```json
{
  "conId": 265598,
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "primaryExchange": "NASDAQ",
  "currency": "USD",
  "localSymbol": "AAPL",
  "tradingHours": "20260429:0930-20260429:1600",
  "liquidHours": "20260429:0930-20260429:1600",
  "longName": "APPLE INC",
  "category": "Technology",
  "subcategory": "Computers",
  "industry": "Consumer Electronics"
}
```

**Errors:** `IB_NOT_CONNECTED`, `IB_INVALID_CONTRACT` (empty result list).

> **Tip.** Use this tool to **validate inputs** before calling other tools. If `get_contract_details` returns `IB_INVALID_CONTRACT`, no other tool will resolve the same contract either.

---

## 6.9 `get_option_chain`

Two modes, controlled by whether `expiry` is supplied.

### Discovery mode (no `expiry`)

Returns expirations and strikes only. **Does not** issue per-contract requests — this is enforced to prevent rate-limit storms (spec §6.8).

**Input:**

```json
{ "symbol": "AAPL", "exchange": "SMART" }
```

**Output:**

```json
{
  "underlying": "AAPL",
  "exchanges": ["AMEX", "CBOE", "ISE", "PHLX", "SMART"],
  "expirations": ["20260516", "20260620", "20270115"],
  "strikes": [120, 125, 130, 135, 140, 145, 150, 155, 160, 165, 170],
  "multiplier": 100
}
```

### Full-chain mode (with `expiry`)

For the supplied `expiry`, builds a contract per `(strike, right)` and fires a single batched `reqTickersAsync(*contracts)`. Returns per-strike data with Greeks.

**Input:**

```json
{ "symbol": "AAPL", "expiry": "20260516", "right": "C" }
```

`right` is optional — omit to get both calls and puts.

**Output:**

```json
{
  "underlying": "AAPL",
  "expiry": "20260516",
  "multiplier": 100,
  "chains": [
    {
      "strike": 150.0,
      "right": "C",
      "conId": 4123456,
      "lastPrice": 3.50,
      "bid": 3.48,
      "ask": 3.52,
      "volume": 12345,
      "openInterest": 67890,
      "impliedVolatility": 0.28,
      "delta": 0.45,
      "gamma": 0.02,
      "theta": -0.08,
      "vega": 0.15
    }
  ]
}
```

**Errors:** `IB_NOT_CONNECTED`, `IB_INVALID_CONTRACT` (unknown underlying or unknown expiry), `IB_NO_MARKET_DATA` (no chain returned), `VALIDATION_ERROR` (`right` not in `{C, P}`).

> **Performance.** Full-chain mode can fan out to dozens of contracts; expect proportionally longer latency. Discovery mode is fast.

---

## 6.10 `get_portfolio_greeks`

Aggregated Greeks across **option positions only**, plus per-position breakdown.

**Input:**

```json
{ "accountId": "U1234567" }   // optional
```

**Output:**

```json
{
  "account": "U1234567",
  "timestamp": "2026-04-29T15:30:00Z",
  "totalDelta": 450.0,
  "totalGamma": 2.0,
  "totalTheta": -80.0,
  "totalVega": 150.0,
  "positions": [
    {
      "symbol": "AAPL",
      "expiry": "20260516",
      "strike": 150.0,
      "right": "C",
      "position": 10,
      "delta": 450.0,
      "gamma": 20.0,
      "theta": -80.0,
      "vega": 150.0,
      "source": "model"
    }
  ]
}
```

`source` ∈ `{"model", "fallback", "missing"}`:

| Source | Meaning |
|--------|---------|
| `model` | Greeks came from the gateway via the priority cascade. |
| `fallback` | Gateway returned no usable Greeks; we computed them via Black-Scholes using the last-known IV. |
| `missing` | Neither model Greeks nor an IV were available — position contributes nothing to totals. |

Each position's contribution is `(per-contract Greek) × position_size × multiplier`. `totalDelta`, etc. sum these.

**Errors:** `IB_NOT_CONNECTED`, `IB_ACCOUNT_NOT_FOUND`.

> **Read more.** [`utils/black_scholes.py`](../src/ibkr_mcp/utils/black_scholes.py) implements the BS Greeks via `math.erf` (no SciPy). Theta is per **calendar day**; vega is per **1.00 of vol** (not per 1%).

---

## 6.11 `list_flex_queries`

> **Conditional registration.** Available only when `IB_FLEX_TOKEN` is set.

Lists Flex query definitions. **Note**: IB's Flex Web Service does not expose query enumeration over the wire, so this tool reads from an optional registry you supply via the `IB_FLEX_QUERIES` env var.

**Input:** `{}`

**Output:**

```json
{
  "queries": [
    { "queryId": "12345", "queryName": "Daily P&L", "type": "Statement" },
    { "queryId": "67890", "queryName": "Trades" }
  ]
}
```

When `IB_FLEX_QUERIES` is unset or malformed, returns `{"queries": []}` (no errors).

`IB_FLEX_QUERIES` is JSON: a list of `{queryId, queryName, type?}` objects.

---

## 6.12 `get_flex_query`

> **Conditional registration.** Available only when `IB_FLEX_TOKEN` is set.

Executes a Flex query against IB's Flex Web Service over HTTPS (independent of the gateway connection — works even when `get_server_status` reports `disconnected`).

**Input:**

```json
{
  "queryId": "12345",
  "topic": "Trade"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `queryId` | conditional | Flex query ID (xor with `queryName`) |
| `queryName` | conditional | Resolved via `IB_FLEX_QUERIES` |
| `topic` | no | XML section to extract (e.g. `Trade`, `Order`, `OpenPosition`); omit for all sections |

**Output (parsed):**

```json
{
  "queryId": "12345",
  "queryName": "Daily P&L",
  "topic": "Trade",
  "parsed": true,
  "data": {
    "Trade": [
      { "symbol": "AAPL", "quantity": 10, "price": 150.50 }
    ]
  }
}
```

**Output (parse failure):** the tool returns the raw XML so consumers can fall back to their own parser.

```json
{
  "queryId": "12345",
  "topic": "Trade",
  "parsed": false,
  "xml": "<FlexQueryResponse>…</FlexQueryResponse>"
}
```

**Errors:**

- `IB_FLEX_ERROR` — token missing, invalid token, IB Flex server error, transport failure.
- `VALIDATION_ERROR` — both `queryId` and `queryName` supplied, or neither, or unknown `queryName`.

> **Latency.** `FlexReport` polls the IB server until the query is ready; expect a few seconds per call. `get_flex_query` wraps the blocking call in `asyncio.to_thread` so the FastMCP event loop is never blocked.

---

## 6.13 `get_alerts` (NOT_IMPLEMENTED)

This tool is **registered but always returns `NOT_IMPLEMENTED`**:

```json
{
  "code": "NOT_IMPLEMENTED",
  "error": "get_alerts requires feasibility validation against ib_async; see spec §6.8."
}
```

**Why:** IB's TWS API does not expose user-defined price/condition alerts cleanly; `ib_async` primarily handles `PriceCondition` objects on orders, not standalone alerts. The schemas in [`models/alerts.py`](../src/ibkr_mcp/models/alerts.py) are defined so a future implementation can wire up directly without breaking changes.

---

## Cross-cutting input formats

### Symbols

- Use IB's symbol (e.g. `AAPL`, `BRK B`, `BABA`). Some symbols differ from common ticker conventions; if a call returns `IB_INVALID_CONTRACT`, try `get_contract_details` first.
- Forex (`secType="CASH"`): `symbol` is the base currency (e.g. `EUR`), `currency` is the quote currency (e.g. `USD`). Default `exchange` for forex is `IDEALPRO`.

### Expiries

- All expiries are IB-format `YYYYMMDD` strings (no dashes).
- For `get_option_chain` full-chain mode, `expiry` must be a value present in the discovery payload.

### Strikes

- Strikes are floats. Match what IB returns from `reqSecDefOptParamsAsync` exactly (e.g. `150.0`, not `150`).

### Greeks priority (options)

For any tool that surfaces Greeks (`get_market_data`, `get_option_chain`, `get_portfolio_greeks`):

```
modelGreeks → lastGreeks → bidGreeks → askGreeks
```

The first bundle with any non-null value wins. See [architecture §6.3](architecture.md#63-greeks-priority).
