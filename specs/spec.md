---
title: "IBKR MCP Server — Full Specification"
domain: infra
type: spec
created: 2026-04-29
updated: 2026-04-30
sources:
  - https://github.com/kelvingao/ibkr-mcp (evaluated, rejected — proprietary license, heavy dependency tree)
  - https://github.com/xiao81/IBKR-MCP-Server (evaluated, rejected — insufficient tool coverage)
tags: [infra, spec, mcp, ibkr]
status: final-draft
---

# IBKR MCP Server — Full Specification

## 1. Purpose

A read-only MCP (Model Context Protocol) server that exposes Interactive Brokers account and market data to AI agents and other MCP clients. The server connects to a locally running IB Gateway or TWS instance and provides structured access to account information, positions, market data, order status, historical data, contract details, and flex queries.

**This server is strictly read-only.** It cannot place, modify, or cancel orders. It is designed for portfolio monitoring, research, and analysis — not trade execution.

### 1.1 Target Audience

- **Primary:** The `local-agents` system (Forge, Ticker, Archon, Sigma) — AI agents requiring clean, stable IBKR data access via MCP.
- **Secondary:** The broader MCP ecosystem — developers building AI agents that need brokerage data.

### 1.2 Design Anti-Patterns (Lessons from Evaluated Alternatives)

- **No proprietary licensing.** Apache-2.0 only.
- **Minimal dependency tree.** Every dependency must earn its place.
- **Comprehensive tool coverage.** A thin server that exposes too few tools is not useful.

---

## 2. Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | **Python ≥3.12** | ib_async is the most mature async IBKR client library; broad ecosystem |
| IBKR client library | **ib_async** | Async-native, actively maintained, full TWS API coverage |
| MCP framework | **mcp[cli]** (FastMCP) | Standard Python MCP SDK; supports both stdio and Streamable HTTP; lifespan management |
| Data models | **Pydantic v2** | Type-safe input/output schemas; automatic JSON serialisation |
| Config | **Environment variables** | Simple, container-friendly, no config files required |
| Transport | **stdio + Streamable HTTP** | stdio for universal MCP client compatibility; Streamable HTTP for shared long-running server |
| Structured logging | **structlog** | JSON-line output, async-friendly, context binding for per-tool-call tracing |
| Persistence | **None** | All data comes live from IB Gateway; no local database or cache |
| Package manager | **uv** | Fast, modern Python package management |
| Linting | **ruff + mypy (strict)** | Consistent formatting and strict type safety |

---

## 3. Configuration

### 3.1 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IB_HOST` | No | `127.0.0.1` | IB Gateway / TWS host |
| `IB_PORT` | No | `4001` | IB Gateway port (4001 live, 4002 paper; 7497 TWS live, 7496 TWS paper) |
| `IB_CLIENT_ID` | No | `1` | TWS client ID; must be unique per connection to the same Gateway |
| `IB_ACCOUNT` | No | — | Specific account ID; if omitted, uses first linked account |
| `IB_PAPER_TRADING` | No | `true` | Informational flag; logged on startup for visibility |
| `IB_FLEX_TOKEN` | No | — | Required for flex query tools; if omitted, flex tools are not registered |
| `IB_MARKET_DATA_TYPE` | No | `LIVE` | One of: `LIVE`, `FROZEN`, `DELAYED`, `DELAYED_FROZEN` |
| `MCP_TRANSPORT` | No | `streamable-http` | Transport mode: `stdio` or `streamable-http` |
| `MCP_HTTP_HOST` | No | `127.0.0.1` | HTTP bind address (Streamable HTTP mode only). **Localhost-only in v0.1** |
| `MCP_HTTP_PORT` | No | `8400` | HTTP port (Streamable HTTP mode only) |
| `LOG_LEVEL` | No | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | No | `json` | Log output format: `json` (machine-readable) or `console` (human-readable) |
| `LOG_TOOL_CALLS` | No | `false` | If `true`, logs each tool invocation with input params, duration, and outcome |

### 3.2 Configuration Loading

Configuration is loaded via Pydantic `BaseSettings` with environment variable mapping. A `.env` file is supported via `python-dotenv` for local development.

---

## 4. Transport

### 4.1 Dual Transport Support

The server supports **both** transport modes. Tools are defined once; transport is selected at startup via `MCP_TRANSPORT`.

#### stdio Mode
- 1:1 client-server relationship (client spawns server as subprocess)
- Universal MCP client compatibility
- Server lifecycle tied to parent process
- Usage: `ibkr-mcp` or `python -m ibkr_mcp`

#### Streamable HTTP Mode (Default)
- Multiple clients connect to a single long-running server instance
- Server runs as an HTTP service bound to `MCP_HTTP_HOST:MCP_HTTP_PORT`
- Supports concurrent tool calls from multiple AI agents
- **Bound to localhost only in v0.1** — no authentication mechanism
- Usage: `ibkr-mcp --transport streamable-http`

---

## 5. Connection Lifecycle

```
MCP server starts (stdio or HTTP)
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

## 6. Tool Definitions

### 6.1 Priority Tiers

| Tier | Tools |
|------|-------|
| **P0 — Core** | `get_server_status`, `get_account_info`, `get_positions`, `get_market_data`, `get_historical_data`, `get_order_status`, `get_live_orders` |
| **P1 — Important** | `get_contract_details`, `list_flex_queries`, `get_flex_query` |
| **P2 — Deferred** | `get_option_chain`, `get_portfolio_greeks`, `get_alerts` |

P2 tools are included in the spec for completeness but may be deferred to a later release. `get_alerts` requires feasibility validation against `ib_async` capabilities.

---

### 6.2 Server Status

#### `get_server_status`

**MCP Description:** *"Check the health and connection status of the IBKR MCP server. Call this before making data requests to verify the server is connected to IB Gateway. Returns connection state, uptime, account ID, and server version."*

**Input:**
```json
{}
```

**Output:**
```json
{
  "status": "connected",
  "ibHost": "127.0.0.1",
  "ibPort": 4001,
  "clientId": 1,
  "accountId": "U1234567",
  "paperTrading": true,
  "serverVersion": "0.1.0",
  "transport": "streamable-http",
  "uptimeSeconds": 3600,
  "marketDataType": "LIVE",
  "registeredTools": 10,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

`status` values: `connected`, `disconnected`, `connecting`.

---

### 6.3 Account & Portfolio

#### `get_account_info`

**MCP Description:** *"Retrieve account summary including net liquidation value, buying power, available funds, margin requirements, and P&L. Use this to understand the current financial state of the IBKR account."*

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
  "initMarginReq": 70000.00,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

---

#### `get_positions`

**MCP Description:** *"Get all open positions in the portfolio with contract details, quantity, average cost, market price, and unrealized P&L. Optionally filter by account ID. Includes full contract details for options (strike, expiry, right, multiplier)."*

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

### 6.4 Market Data

#### `get_market_data`

**MCP Description:** *"Get a real-time snapshot quote for any instrument — stocks, options, futures, forex, bonds, or indices. Provide the symbol and security type. For options, also provide expiry, strike, and right (C/P). Returns bid, ask, last price, volume, and for options also includes Greeks (delta, gamma, theta, vega) and implied volatility."*

**Input (equity):**
```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "currency": "USD"
}
```

**Input (option):**
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

#### `get_historical_data`

**MCP Description:** *"Retrieve historical OHLCV price bars for any instrument. Specify duration (how far back) and bar size (candle interval). Accepts both IB-native duration strings (e.g. '30 D', '1 Y') and ISO 8601 durations (e.g. 'P30D', 'P1Y', 'PT1H'). Bar sizes follow IB format: '1 min', '5 mins', '1 hour', '1 day', '1 week'."*

**Input:**
```json
{
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "currency": "USD",
  "duration": "P30D",
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
| `duration` | Yes | IB-native (`30 D`, `1 Y`, `3600 S`) or ISO 8601 (`P30D`, `P1Y`, `PT1H`) |
| `barSize` | Yes | IB bar size: `1 secs`, `5 secs`, `10 secs`, `15 secs`, `30 secs`, `1 min`, `2 mins`, `3 mins`, `5 mins`, `10 mins`, `15 mins`, `20 mins`, `30 mins`, `1 hour`, `2 hours`, `3 hours`, `4 hours`, `8 hours`, `1 day`, `1 week`, `1 month` |
| `endDateTime` | No | End point for data; defaults to now |
| `expiry` | Conditional | Option/future expiry (YYYYMMDD) |
| `strike` | Conditional | Option strike price |
| `right` | Conditional | `C` or `P` |

#### ISO 8601 Duration Translation

The server accepts ISO 8601 durations and translates them internally:

| ISO 8601 | IB Native |
|----------|-----------|
| `PT3600S` | `3600 S` |
| `P30D` | `30 D` |
| `P2W` | `2 W` |
| `P6M` | `6 M` |
| `P1Y` | `1 Y` |
| `PT1H` | `3600 S` |

IB-native strings are passed through unmodified.

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

### 6.5 Orders

#### `get_order_status`

**MCP Description:** *"Get the current status of a specific order by its order ID. Returns fill status, quantities, prices, commission, and timestamps. Use this to check if an order has been filled, partially filled, or cancelled."*

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

**MCP Description:** *"List all currently open or pending orders for the account. Returns order details including status, symbol, action, quantity, order type, and limit/stop prices. Optionally filter by account ID."*

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

### 6.6 Contract Reference (P1)

#### `get_contract_details`

**MCP Description:** *"Look up full contract details for any instrument — resolves a symbol to its contract ID, primary exchange, trading hours, long name, industry classification, and other metadata. Essential for validating contract parameters before use in other tools. For options, also returns strike, expiry, multiplier, and last trade date."*

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

### 6.7 Flex Query Tools (P1, Conditional)

These tools are registered **only** when the `IB_FLEX_TOKEN` environment variable is set. If omitted, neither tool is available.

Flex queries use `ib_async`'s built-in `FlexReport` class, which communicates directly with IB's Flex Web Service over HTTPS. This does **not** require a TWS/Gateway connection.

#### `list_flex_queries`

**MCP Description:** *"List all available Flex Query definitions configured in your IBKR Account Management portal. Returns query IDs and names that can be passed to get_flex_query to execute."*

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

**MCP Description:** *"Execute a Flex Query by ID or name and return the parsed results as structured JSON. Flex Queries provide access to historical account data, trade reports, and statements configured in your IBKR Account Management portal. Requires IB_FLEX_TOKEN to be configured."*

**Input:**
```json
{
  "queryId": "12345",
  "topic": "Trade"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `queryId` | Conditional | Flex query ID (either this or `queryName` is required) |
| `queryName` | Conditional | Flex query name (alternative to `queryId`) |
| `topic` | No | XML section to extract (e.g., `Trade`, `Order`, `OpenPosition`). If omitted, returns all sections |

**Output:** Parsed JSON representation of the flex query result. Schema varies by query type. The server uses `FlexReport.extract()` to parse XML into structured data, then serialises to JSON. If extraction fails, returns the raw XML with a `parsed: false` flag.

---

### 6.8 Deferred Tools (P2)

The following tools are included in the spec for completeness. They SHOULD be implemented but MAY be deferred to a later release.

#### `get_option_chain`

**MCP Description:** *"Fetch the option chain for an underlying symbol. Without an expiry date, returns available expirations and strikes (discovery mode). With an expiry date, returns full per-contract data including bid, ask, volume, open interest, and Greeks for each strike."*

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
| `expiry` | No | If omitted, returns discovery payload only (expirations + strikes, no per-contract data) |
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
    }
  ]
}
```

**Rate limit note:** When `expiry` is omitted, the server MUST return only the discovery payload and NOT fetch per-contract data. This avoids hitting TWS rate limits with hundreds of concurrent snapshot requests.

---

#### `get_portfolio_greeks`

**MCP Description:** *"Get aggregated Greeks (delta, gamma, theta, vega) across all option positions in the portfolio. Also returns per-position Greek breakdowns. Useful for understanding overall portfolio risk exposure from options."*

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

#### `get_alerts`

**MCP Description:** *"List active price and condition alerts configured for the account. Returns alert names, conditions, and status."*

> **⚠️ Feasibility Note:** IB's TWS API support for reading alerts programmatically is limited. `ib_async` primarily handles price conditions via `PriceCondition` objects on orders, not standalone alerts. This tool requires feasibility validation before implementation.

**Input:**
```json
{
  "accountId": "U1234567"
}
```

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

## 7. Tool Registration

All tools are registered unconditionally (except flex query tools, which require `IB_FLEX_TOKEN`). There is no read-only/write-only toggle because the server is **entirely read-only by design**.

```python
P0_TOOLS = [
    get_server_status,
    get_account_info,
    get_positions,
    get_market_data,
    get_historical_data,
    get_order_status,
    get_live_orders,
]

P1_TOOLS = [
    get_contract_details,
]

P2_TOOLS = [
    get_option_chain,
    get_portfolio_greeks,
    get_alerts,  # pending feasibility validation
]

FLEX_TOOLS = [list_flex_queries, get_flex_query]  # only if IB_FLEX_TOKEN set
```

Total: **11 core tools** + **2 conditional flex tools**.

---

## 8. Project Structure

```
ibkr-mcp/
├── pyproject.toml
├── README.md
├── .env.template
├── specs/
│   └── spec.md                    # this specification
├── src/
│   └── ibkr_mcp/
│       ├── __init__.py
│       ├── __main__.py            # entry point: python -m ibkr_mcp
│       ├── server.py              # FastMCP app, lifespan, tool registration
│       ├── config.py              # Pydantic Settings from env vars
│       ├── connection.py          # IB Gateway connect/disconnect/reconnect
│       ├── models/
│       │   ├── __init__.py
│       │   ├── account.py         # AccountInfo schema
│       │   ├── market.py          # MarketData, OptionChain, HistoricalBar schemas
│       │   ├── positions.py       # Position, PortfolioGreeks schemas
│       │   ├── orders.py          # OrderStatus schemas
│       │   ├── alerts.py          # Alert, AlertCondition schemas
│       │   └── server.py          # ServerStatus schema
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── server.py          # get_server_status
│       │   ├── account.py         # get_account_info, get_positions, get_portfolio_greeks
│       │   ├── market.py          # get_market_data, get_option_chain, get_historical_data
│       │   ├── orders.py          # get_order_status, get_live_orders, get_alerts
│       │   ├── contracts.py       # get_contract_details
│       │   └── flex.py            # list_flex_queries, get_flex_query
│       └── utils/
│           ├── __init__.py
│           ├── contracts.py       # Contract construction helpers
│           └── durations.py       # ISO 8601 → IB duration translation
├── tests/
│   ├── conftest.py                # FakeIB client, shared fixtures
│   ├── fake_ib.py                 # FakeIB implementation for testing
│   ├── test_server_tools.py
│   ├── test_account_tools.py
│   ├── test_market_tools.py
│   ├── test_order_tools.py
│   ├── test_contract_tools.py
│   ├── test_flex_tools.py
│   ├── test_config.py
│   ├── test_connection.py
│   └── test_duration_utils.py
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 9. Dependencies

```toml
[project]
name = "ibkr-mcp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.9.0",
    "ib_async>=0.9.86",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
    "structlog>=24.0.0",
    "pandas>=2.0.0",
]

[project.scripts]
ibkr-mcp = "ibkr_mcp.__main__:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "pandas-stubs>=2.0.0",
]
```

---

## 10. Error Handling

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

## 11. Startup Behaviour

On successful connection, the server logs to stderr:

```
IBKR MCP Server v0.1.0
Connected to IB Gateway at 127.0.0.1:4001 (client_id=1)
Account: U1234567 | Paper: true
Transport: streamable-http (127.0.0.1:8400)
Registered tools: 11 core, 2 flex
```

On connection failure:

```
IBKR MCP Server v0.1.0
WARNING: Failed to connect to IB Gateway at 127.0.0.1:4001
Tools will return IB_NOT_CONNECTED errors until connection is established.
Account: — | Paper: true
Transport: streamable-http (127.0.0.1:8400)
Registered tools: 11 core, 2 flex
```

---

## 12. Logging

### 12.1 Framework

Structured logging via `structlog`. Output format is configurable:
- **`json`** (default) — Machine-readable JSON lines, suitable for log aggregation
- **`console`** — Human-readable coloured output for local development

### 12.2 Log Levels

Controlled via `LOG_LEVEL` environment variable:
- **`DEBUG`** — All internal events, ib_async protocol messages
- **`INFO`** (default) — Startup, shutdown, connection events, tool registrations
- **`WARNING`** — Connection failures, retries, degraded operation
- **`ERROR`** — Unhandled errors, tool failures

### 12.3 Per-Tool-Call Logging

When `LOG_TOOL_CALLS=true`, each tool invocation is logged with:

```json
{
  "event": "tool_call",
  "tool": "get_market_data",
  "input": {"symbol": "AAPL", "secType": "STK"},
  "duration_ms": 145,
  "outcome": "success",
  "timestamp": "2026-04-29T15:30:00.145Z"
}
```

On error:
```json
{
  "event": "tool_call",
  "tool": "get_market_data",
  "input": {"symbol": "INVALID", "secType": "STK"},
  "duration_ms": 12,
  "outcome": "error",
  "error_code": "IB_INVALID_CONTRACT",
  "timestamp": "2026-04-29T15:30:00.012Z"
}
```

---

## 13. Design Principles

### What This Server IS

- **A read-only data access layer.** It fetches and returns data from IB Gateway; it never mutates state.
- **A thin wrapper.** Business logic, strategy, and risk analysis belong in the consumer, not here.
- **Stateless between calls.** Each tool call is independent. No session state, no caching, no accumulation.
- **Self-contained.** No external databases, no message queues, no filesystem persistence.
- **Agent-friendly.** Tool descriptions are crafted for LLM consumption. Input formats accept both IB-native and standard formats.

### What This Server is NOT

- **Not a trading platform.** No order placement, no strategy logic, no signal generation, no risk engine.
- **Not a database.** No local caching, no historical state persistence beyond what IB Gateway provides.
- **Not a charting library.** Data is returned as structured JSON only.
- **Not a news service.** News retrieval is out of scope.
- **Not a notification service.** No push alerts, no webhooks, no streaming. Consumers poll via tool calls.

---

## 14. Future Considerations (out of scope for v0.1)

These are explicitly deferred. The architecture should not preclude them, but they are not implemented:

- **Explicit rate limiting** — Per-tool rate limits to avoid TWS API throttling. Currently relying on `ib_async`'s internal request queuing, but explicit backpressure may be needed at high call rates with multiple concurrent clients.
- **Enhanced reconnection logic** — Custom retry/backoff beyond `ib_async`'s built-in handling, particularly for IB Gateway daily restarts (midnight ET). Periodic health checks and connection watchdog.
- **Authentication & access control** — Bearer token / API key authentication for Streamable HTTP transport. Required before binding to non-localhost interfaces.
- **Streaming data** — Real-time tick subscriptions via MCP server-initiated notifications (requires MCP protocol support beyond request/response).
- **Write tools (order management)** — If needed in future, can be added as a separate server instance or behind a feature flag. The read-only design ensures this server can never accidentally execute trades.
- **Multi-account switching** — Currently targets one account; could add account enumeration and switching.
- **WebSocket transport** — MCP WebSocket transport as alternative to stdio/Streamable HTTP.
- **Caching layer** — Optional short-TTL cache for expensive operations like `get_option_chain` to reduce TWS load.
- **Health check endpoint** — HTTP `/health` endpoint for orchestrators (separate from `get_server_status` tool).

---

## 15. Testing Strategy

### 15.1 Approach: Hybrid (FakeIB + pytest-mock)

- **`FakeIB` client** — A lightweight in-memory implementation of the `ib_async.IB` interface that returns canned responses. Used for happy-path testing of all data tools. Lives in `tests/fake_ib.py`.
- **`pytest-mock`** — Used for edge cases: connection failures, timeouts, invalid contracts, partial data. Patches specific methods on the `FakeIB` or real `IB` class.

### 15.2 Test Tiers

1. **Unit tests** — Use `FakeIB`; test tool logic, input validation, output schema conformance, ISO duration translation, and error handling. Run in CI with no external dependencies.
2. **Integration tests** — Require a running TWS or IB Gateway with a paper account. Marked with `@pytest.mark.integration`, skipped in CI. Used for manual validation before release.
3. **Contract tests** — Verify that all tool schemas match this specification. Pydantic models serve as both runtime validators and schema documentation.

### 15.3 CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    - ruff check src/ tests/
    - ruff format --check src/ tests/
    - mypy src/
  test:
    - pytest tests/ -m "not integration" --cov=ibkr_mcp
```

---

## 16. Distribution

### 16.1 PyPI Package

Published as `ibkr-mcp` on PyPI. Install via:
```bash
pip install ibkr-mcp
# or
uv add ibkr-mcp
```

### 16.2 CLI Entry Point

```bash
# Via CLI entry point
ibkr-mcp
ibkr-mcp --transport stdio

# Via module execution
python -m ibkr_mcp
python -m ibkr_mcp --transport stdio
```

### 16.3 MCP Client Configuration

For MCP clients that spawn servers as subprocesses (stdio mode):
```json
{
  "mcpServers": {
    "ibkr": {
      "command": "ibkr-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "IB_HOST": "127.0.0.1",
        "IB_PORT": "4001"
      }
    }
  }
}
```

For MCP clients connecting to a running server (Streamable HTTP mode):
```json
{
  "mcpServers": {
    "ibkr": {
      "url": "http://127.0.0.1:8400/mcp"
    }
  }
}
```

---

## 17. License

**MIT**
