---
title: "IBKR MCP Server — Specification"
domain: infra
type: spec
created: 2026-04-29
updated: 2026-04-29 22:51:00
sources:
  - https://github.com/kelvingao/ibkr-mcp (evaluated, rejected)
  - https://github.com/xiao81/IBKR-MCP-Server (evaluated, rejected)
tags: [infra, spec, mcp, ibkr]
status: draft
---

# IBKR MCP Server — Specification

## 1. Purpose

A read-only MCP (Model Context Protocol) server that exposes Interactive Brokers account and market data to AI assistants and other MCP clients. The server connects to a locally running IB Gateway or TWS instance and provides structured access to account information, positions, market data, option chains, Greeks, order status, alerts, historical data, and flex queries.

**This server is strictly read-only.** It cannot place, modify, or cancel orders, and it cannot create, activate, or delete alerts. It is designed for portfolio monitoring, research, and analysis — not trade execution.

---

## 2. Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | **Python** | ib_async is the most mature async IBKR client library; broad ecosystem |
| IBKR client library | **ib_async** | Async-native, actively maintained, full TWS API coverage |
| MCP framework | **mcp[cli]** (FastMCP) | Standard Python MCP SDK; stdio transport; lifespan management |
| Data models | **Pydantic v2** | Type-safe input/output schemas; automatic JSON serialisation |
| Config | **Environment variables** | Simple, container-friendly, no config files required |
| Transport | **stdio** | MCP stdio protocol; can be spawned as subprocess or piped |
| Persistence | **None** | All data comes live from IB Gateway; no local database or cache |

---

## 3. Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IB_HOST` | Yes | `127.0.0.1` | IB Gateway / TWS host |
| `IB_PORT` | Yes | `4001` | IB Gateway port (4001 live, 4002 paper; 7497 TWS live, 7496 TWS paper) |
| `IB_CLIENT_ID` | Yes | `1` | TWS client ID; must be unique per connection to the same Gateway |
| `IB_ACCOUNT` | No | — | Specific account ID; if omitted, uses first linked account |
| `IB_PAPER_TRADING` | No | `true` | Informational flag; logged on startup for visibility |
| `IB_FLEX_TOKEN` | No | — | Required for flex query tools; if omitted, flex tools are not registered |
| `IB_MARKET_DATA_TYPE` | No | `LIVE` | One of: `LIVE`, `FROZEN`, `DELAYED`, `DELAYED_FROZEN` |

---

## 4. Connection Lifecycle

```
MCP server starts (stdin/stdout)
  │
  ▼
Connect to IB Gateway (ib_async)
  │
  ├── Success → Register tools → Yield context → Serve requests
  └── Failure → Register tools anyway (tools return error on call) → Log warning → Serve requests
  │
  ▼
On shutdown signal → Disconnect from IB Gateway → Exit
```

- The server MUST NOT exit on connection failure. Tools return structured errors instead.
- Reconnection is handled by ib_async automatically (it retries on socket drop).
- The lifespan context yields a shared `IB` instance for all tools.

---

## 5. Tool Definitions

### 5.1 Account & Portfolio

#### `get_account_info`

Retrieves account summary: net liquidation, buying power, available funds, margin requirements, P&L.

**Input:**
```json
{}
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
  "initMarginReq": 70000.00
}
```

---

#### `get_positions`

Returns all open positions with contract details, quantity, average cost, market price, and unrealized P&L.

**Input:**
```json
{
  "accountId": "U1234567"
}
```

`accountId` is optional; defaults to the connected account.

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
      "exchange": "SMART",
      "currency": "USD",
      "conId": 4123456,
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

Options positions MUST include `right`, `strike`, `expiry`, and `multiplier` fields.

---

#### `get_portfolio_greeks`

Aggregated Greeks across all option positions in the portfolio.

**Input:**
```json
{}
```

**Output:**
```json
{
  "account": "U1234567",
  "timestamp": "2026-04-29T15:30:00Z",
  "totalDelta": 45.2,
  "totalGamma": 3.1,
  "totalTheta": -120.5,
  "totalVega": 850.0,
  "positions": [
    {
      "symbol": "AAPL",
      "expiry": "20260516",
      "strike": 150.0,
      "right": "C",
      "position": 10,
      "delta": 4.5,
      "gamma": 0.3,
      "theta": -8.0,
      "vega": 45.0
    }
  ]
}
```

Calculated as position size × per-contract Greeks. If TWS does not provide model Greeks, compute from last known IV using Black-Scholes as fallback.

---

### 5.2 Market Data

#### `get_market_data`

Snapshot quote for a given instrument. Supports stocks, options, futures, forex, bonds, and indices.

**Input:**
```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "currency": "USD"
}
```

For options, include additional contract fields:
```json
{
  "symbol": "AAPL",
  "secType": "OPT",
  "exchange": "SMART",
  "currency": "USD",
  "expiry": "20260516",
  "strike": 150.0,
  "right": "C"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `symbol` | Yes | Ticker symbol |
| `secType` | Yes | Security type: `STK`, `OPT`, `FUT`, `CASH`, `BOND`, `IND` |
| `exchange` | No | Exchange (default: `SMART`) |
| `currency` | No | Currency (default: `USD`) |
| `expiry` | Conditional | Option/future expiry in YYYYMMDD format |
| `strike` | Conditional | Option strike price |
| `right` | Conditional | `C` for call, `P` for put |

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
  "high": 152.00,
  "low": 149.00,
  "open": 149.50,
  "close": 149.80,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

**Output (option) — includes Greeks:**
```json
{
  "symbol": "AAPL",
  "secType": "OPT",
  "expiry": "20260516",
  "strike": 150.0,
  "right": "C",
  "lastPrice": 3.50,
  "bid": 3.48,
  "ask": 3.52,
  "volume": 1234,
  "openInterest": 5678,
  "impliedVolatility": 0.28,
  "delta": 0.45,
  "gamma": 0.02,
  "theta": -0.08,
  "vega": 0.15,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

Uses `IB_MARKET_DATA_TYPE` to request delayed data when live subscriptions are unavailable.

---

#### `get_option_chain`

Fetches option chain for a given underlying. Returns available expirations, strikes, and optionally per-contract snapshot data with Greeks.

**Input:**
```json
{
  "symbol": "AAPL",
  "exchange": "SMART",
  "expiry": "20260516",
  "right": "C"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `symbol` | Yes | Underlying symbol |
| `exchange` | No | Exchange (default: `SMART`) |
| `expiry` | No | If omitted, returns list of available expirations and strikes only (no per-contract data) |
| `right` | No | `C`, `P`, or omit for both |

**Output (without expiry — discovery mode):**
```json
{
  "underlying": "AAPL",
  "exchanges": ["SMART", "AMEX", "PHLX", "CBOE", "ISE"],
  "expirations": ["20260516", "20260523", "20260620", "20260918", "20270115"],
  "strikes": [120, 125, 130, 135, 140, 145, 150, 155, 160, 165, 170, 175, 180],
  "multiplier": 100
}
```

**Output (with expiry — full chain):**
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
    },
    {
      "strike": 150.0,
      "right": "P",
      "conId": 4123457,
      "lastPrice": 2.80,
      "bid": 2.78,
      "ask": 2.82,
      "volume": 8900,
      "openInterest": 45670,
      "impliedVolatility": 0.27,
      "delta": -0.55,
      "gamma": 0.02,
      "theta": -0.06,
      "vega": 0.15
    }
  ]
}
```

This is the most data-intensive tool. When `expiry` is omitted, the server MUST return only the discovery payload (expirations + strikes) and NOT fetch per-contract data for the entire chain. This avoids hitting TWS rate limits with hundreds of concurrent snapshot requests.

---

#### `get_historical_data`

Historical OHLCV bars for a contract.

**Input:**
```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "currency": "USD",
  "duration": "30 D",
  "barSize": "1 day",
  "endDateTime": "20260429 15:30:00"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `symbol` | Yes | Ticker symbol |
| `secType` | Yes | Security type |
| `exchange` | No | Exchange (default: `SMART`) |
| `currency` | No | Currency (default: `USD`) |
| `duration` | Yes | ib_async duration string (e.g., `30 D`, `1 Y`, `3600 S`) |
| `barSize` | Yes | ib_async bar size string (e.g., `1 min`, `5 mins`, `1 hour`, `1 day`, `1 week`) |
| `endDateTime` | No | End point for data; defaults to now |

For options, include `expiry`, `strike`, `right` as with `get_market_data`.

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

---

### 5.3 Orders & Alerts

#### `get_order_status`

Returns the status of a specific order by ID.

**Input:**
```json
{
  "orderId": 1001
}
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
  "limitPrice": null,
  "stopPrice": null,
  "filledQuantity": 10,
  "avgFillPrice": 150.52,
  "commission": 1.00,
  "submittedAt": "2026-04-29T15:25:00Z",
  "filledAt": "2026-04-29T15:25:01Z"
}
```

Status values: `PendingSubmit`, `Submitted`, `ApiPending`, `PreSubmitted`, `Filled`, `PartiallyFilled`, `Cancelled`, `ApiCancelled`, `Inactive`.

---

#### `get_live_orders`

Returns all open/pending orders for the account.

**Input:**
```json
{
  "accountId": "U1234567"
}
```

`accountId` is optional; defaults to the connected account.

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
      "limitPrice": 380.00,
      "stopPrice": null,
      "filledQuantity": 0,
      "submittedAt": "2026-04-29T14:00:00Z"
    }
  ]
}
```

---

#### `get_alerts`

Returns active alerts for the account.

**Input:**
```json
{
  "accountId": "U1234567"
}
```

`accountId` is optional; defaults to the connected account.

**Output:**
```json
{
  "alerts": [
    {
      "alertId": 42,
      "name": "AAPL > 160",
      "active": true,
      "conditions": [
        {
          "symbol": "AAPL",
          "field": "LAST",
          "operator": ">=",
          "value": 160.0
        }
      ],
      "createdAt": "2026-04-28T10:00:00Z"
    }
  ]
}
```

---

### 5.4 Contract Reference

#### `get_contract_details`

Resolves a contract specification to its full details: conId, exchanges, trading hours, multiplier, etc. Essential for validating contract parameters before use in other tools.

**Input:**
```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "currency": "USD"
}
```

For options, include `expiry`, `strike`, `right`.

**Output:**
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

For options, output also includes `strike`, `right`, `expiry`, `multiplier`, `lastTradeDate`.

---

### 5.5 Flex Query Tools

These tools are registered **only** when the `IB_FLEX_TOKEN` environment variable is set. If omitted, neither tool is available and calls will return `TOOL_NOT_FOUND`.

#### `list_flex_queries`

Lists available flex query definitions configured in Account Management.

**Input:**
```json
{}
```

**Output:**
```json
{
  "queries": [
    {
      "queryId": "12345",
      "queryName": "Daily P&L",
      "type": "Statement"
    }
  ]
}
```

---

#### `get_flex_query`

Executes a flex query and returns parsed results.

**Input:**
```json
{
  "queryId": "12345",
  "queryName": "Daily P&L",
  "parseXml": true
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `queryId` | Conditional | Flex query ID (either this or `queryName` is required) |
| `queryName` | Conditional | Flex query name (alternative to `queryId`) |
| `parseXml` | No | Default `true`; if `false`, returns raw XML string |

**Output:** Parsed JSON representation of the flex query result. Schema varies by query type. The server should attempt to parse the XML response into structured JSON. If parsing fails, return the raw XML with a `parsed: false` flag.

---

## 6. Tool Registration

All tools are registered unconditionally (except flex query tools, which require `IB_FLEX_TOKEN`). There is no read-only/write-only toggle because the server is **entirely read-only by design**.

```python
TOOLS = [
    # Account & Portfolio
    get_account_info,
    get_positions,
    get_portfolio_greeks,
    # Market Data
    get_market_data,
    get_option_chain,
    get_historical_data,
    # Orders & Alerts
    get_order_status,
    get_live_orders,
    get_alerts,
    # Contract Reference
    get_contract_details,
]

FLEX_TOOLS = [list_flex_queries, get_flex_query]  # only if IB_FLEX_TOKEN set
```

Total: **10 core tools** + **2 conditional flex tools**.

---

## 7. Project Structure

```
ibkr-mcp-server/
├── pyproject.toml
├── README.md
├── .env.template
├── src/
│   └── ibkr_mcp_server/
│       ├── __init__.py
│       ├── __main__.py           # entry point: python -m ibkr_mcp_server
│       ├── server.py             # FastMCP app, lifespan, tool registration
│       ├── config.py             # Pydantic Settings from env vars
│       ├── connection.py         # IB Gateway connect/disconnect/reconnect
│       ├── models/
│       │   ├── __init__.py
│       │   ├── account.py        # AccountInfo schema
│       │   ├── market.py         # MarketData, OptionChain, HistoricalBar schemas
│       │   ├── positions.py       # Position, PortfolioGreeks schemas
│       │   ├── orders.py         # OrderStatus schemas
│       │   └── alerts.py         # Alert, AlertCondition schemas
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── account.py        # get_account_info, get_positions, get_portfolio_greeks
│       │   ├── market.py         # get_market_data, get_option_chain, get_historical_data
│       │   ├── orders.py         # get_order_status, get_live_orders, get_alerts
│       │   ├── contracts.py      # get_contract_details
│       │   └── flex.py           # list_flex_queries, get_flex_query
│       └── utils/
│           ├── __init__.py
│           └── contracts.py      # Contract construction helpers
├── tests/
│   ├── conftest.py
│   ├── test_account_tools.py
│   ├── test_market_tools.py
│   ├── test_order_tools.py
│   ├── test_contract_tools.py
│   ├── test_flex_tools.py
│   ├── test_config.py
│   └── test_connection.py
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 8. Dependencies

```toml
[project]
name = "ibkr-mcp-server"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.9.0",
    "ib_async>=0.9.86",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
]
```

Minimal dependency tree. No database drivers, no analysis libraries, no charting, no pandas. This is a thin read-only API wrapper.

---

## 9. Error Handling

All tools return errors as structured JSON. Tools MUST NOT raise unhandled exceptions.

**Error format:**
```json
{
  "error": "Not connected to IB Gateway",
  "code": "IB_NOT_CONNECTED"
}
```

**Error codes:**

| Code | Meaning |
|------|---------|
| `IB_NOT_CONNECTED` | Gateway connection is down; tools cannot serve data |
| `IB_CONNECTION_FAILED` | Initial connection attempt failed |
| `IB_TIMEOUT` | Request timed out waiting for TWS/Gateway response |
| `IB_INVALID_CONTRACT` | Contract specification could not be resolved |
| `IB_NO_MARKET_DATA` | No market data permission or subscription for this instrument |
| `IB_FLEX_ERROR` | Flex query execution failed (invalid token, query not found, server error) |
| `IB_ACCOUNT_NOT_FOUND` | Specified account ID is not linked to this Gateway connection |
| `VALIDATION_ERROR` | Input schema validation failed |

---

## 10. Startup Behaviour

On successful connection, the server logs to stderr:

```
IBKR MCP Server v0.1.0
Connected to IB Gateway at 127.0.0.1:4001 (client_id=1)
Account: U1234567 | Paper: true
Registered tools: 10 core, 2 flex
```

On connection failure:

```
IBKR MCP Server v0.1.0
WARNING: Failed to connect to IB Gateway at 127.0.0.1:4001
Tools will return IB_NOT_CONNECTED errors until connection is established.
Account: — | Paper: true
Registered tools: 10 core, 2 flex
```

This gives the spawning process or orchestrator immediate visibility into server state.

---

## 11. Design Principles

### What This Server IS

- **A read-only data access layer.** It fetches and returns data from IB Gateway; it never mutates state.
- **A thin wrapper.** Business logic, strategy, and risk analysis belong in the consumer, not here.
- **Stateless between calls.** Each tool call is independent. No session state, no caching, no accumulation.
- **Self-contained.** No external databases, no message queues, no filesystem persistence.

### What This Server is NOT

- **Not a trading platform.** No order placement, no strategy logic, no signal generation, no risk engine.
- **Not a database.** No local caching, no historical state persistence beyond what IB Gateway provides.
- **Not a charting library.** Data is returned as structured JSON only.
- **Not a news service.** News retrieval is out of scope.
- **Not a notification service.** No push alerts, no webhooks, no streaming. Consumers poll via tool calls.

---

## 12. Future Considerations (out of scope for v0.1)

These are explicitly deferred. The architecture should not preclude them, but they are not implemented:

- **Streaming data** — Real-time tick subscriptions via MCP server-initiated notifications (requires MCP protocol support beyond request/response)
- **Write tools (order management)** — If needed in future, can be added as a separate server instance or behind a feature flag. The read-only design ensures this server can never accidentally execute trades.
- **Multi-account switching** — Currently targets one account; could add account enumeration and switching
- **Rate limiting** — Per-tool rate limits to avoid TWS API throttling (ib_async queues requests, but explicit backpressure may be needed at high call rates)
- **WebSocket transport** — MCP WebSocket transport as alternative to stdio
- **Caching layer** — Optional short-TTL cache for expensive operations like `get_option_chain` to reduce TWS load
- **Health check endpoint** — For orchestrators that need to verify the server is alive and connected

---

## 13. Testing Strategy

1. **Unit tests** — Mock the `ib_async` client; test tool logic, input validation, and output schema conformance. These run in CI with no external dependencies.
2. **Integration tests** — Require a running TWS or IB Gateway with a paper account. Marked with `@pytest.mark.integration`, skipped in CI. Used for manual validation before release.
3. **Contract tests** — Verify that all tool schemas match this specification. Pydantic models serve as both runtime validators and schema documentation.

---

## 14. License

**Apache-2.0**