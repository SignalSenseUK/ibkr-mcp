# IBKR MCP Server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that exposes Interactive Brokers account and market data to AI agents and other MCP clients.

The server connects to a locally running **IB Gateway** or **TWS** instance and provides structured access to account information, positions, market data, order status, historical bars, contract details, option chains, portfolio Greeks, and Flex queries.

> **Read-only by design.** This server cannot place, modify, or cancel orders. It is intended for portfolio monitoring, research, and analysis — not trade execution.

[![CI](https://img.shields.io/badge/CI-passing-green)](.github/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## Table of Contents

1. [Highlights](#highlights)
2. [Quick start](#quick-start)
3. [Tools at a glance](#tools-at-a-glance)
4. [MCP client configuration](#mcp-client-configuration)
5. [Documentation map](#documentation-map)
6. [Project structure](#project-structure)
7. [Status & roadmap](#status--roadmap)
8. [License](#license)

---

## Highlights

- **11 core tools + 2 conditional Flex tools** covering server health, account summary, positions, market data (snapshots and historical bars), order status, contract details, option chains, portfolio Greeks, and Flex queries.
- **Two transports out of the box** — `stdio` (for clients that spawn the server as a subprocess) and `streamable-http` (for shared long-running deployments at `/mcp`).
- **Pure-Python Black-Scholes fallback** for portfolio Greeks when the gateway omits `modelGreeks`. No NumPy/SciPy dependency.
- **Resilient lifespan** — the server stays up even when IB Gateway is unreachable; tools surface a structured `IB_NOT_CONNECTED` error instead of crashing.
- **Strict typing & strong tests** — `mypy --strict`, `ruff`, and **216 unit tests** at **94% coverage**, with an in-memory `FakeIB` harness that needs no network access.
- **Apache-friendly licensing** — MIT, minimal dependency tree, no proprietary code.

---

## Quick start

### Prerequisites

- **Python 3.12+**
- **IB Gateway** or **TWS** running and logged in (paper or live)
- **Market-data subscriptions** for any instruments you'll query (or set `IB_MARKET_DATA_TYPE=DELAYED`)
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip` for dependency management

### Install (from source)

```bash
git clone https://github.com/<your-org>/ibkr-mcp.git
cd ibkr-mcp
uv sync                 # creates .venv and installs dependencies
cp .env.template .env   # adjust values to taste
```

### Run

```bash
# Streamable HTTP at http://127.0.0.1:8400/mcp (default)
uv run ibkr-mcp

# Stdio (for Claude Desktop, Cursor, etc.)
uv run ibkr-mcp --transport stdio

# Or via the module
uv run python -m ibkr_mcp --transport stdio
```

You should see a banner on stderr similar to:

```
IBKR MCP Server v0.1.0
Connected to IB Gateway at 127.0.0.1:4002 (client_id=1)
Account: U1234567 | Paper: true
Transport: streamable-http (127.0.0.1:8400)
```

> The server **does not exit** when IB Gateway is down. Instead, every tool returns `{"code": "IB_NOT_CONNECTED", "error": "..."}` until the gateway is reachable.

### Smoke-test it

With the server running over Streamable HTTP, call `get_server_status` from any MCP client (or via `curl` with the proper MCP framing — most users will use a client). A connected, healthy server returns:

```json
{
  "status": "connected",
  "ibHost": "127.0.0.1",
  "ibPort": 4002,
  "accountId": "U1234567",
  "paperTrading": true,
  "transport": "streamable-http",
  "uptimeSeconds": 12,
  "marketDataType": "LIVE",
  "registeredTools": 11,
  "timestamp": "2026-04-29T15:30:00Z"
}
```

---

## Tools at a glance

| Tier | Tool | Purpose |
|------|------|---------|
| **P0** | `get_server_status` | Health check, uptime, transport, registered tool count |
| **P0** | `get_account_info` | Net liquidation, cash, P&L, margin requirements |
| **P0** | `get_positions` | Open positions with full option fields |
| **P0** | `get_market_data` | Real-time snapshot quote (any sec type, with Greeks for OPT) |
| **P0** | `get_historical_data` | OHLCV bars; accepts ISO 8601 or IB-native durations |
| **P0** | `get_order_status` | Status, fills, commission for a specific `orderId` |
| **P0** | `get_live_orders` | All open / pending orders |
| **P1** | `get_contract_details` | Resolve symbol → conId, trading hours, long name, etc. |
| **P2** | `get_option_chain` | Discovery (no expiry) or full chain with Greeks (with expiry) |
| **P2** | `get_portfolio_greeks` | Aggregated and per-position Greeks (BS fallback when gateway omits) |
| **P2** | `get_alerts` | Returns `NOT_IMPLEMENTED` placeholder (see [docs/usage.md §6.13](docs/usage.md#613-get_alerts-not-implemented)) |
| **Flex** | `list_flex_queries` | Lists configured Flex queries (registered iff `IB_FLEX_TOKEN` set) |
| **Flex** | `get_flex_query` | Executes a Flex query by id or name; returns parsed JSON or raw XML |

Full input/output schemas, examples, and error semantics for every tool: [**docs/usage.md**](docs/usage.md).

---

## MCP client configuration

### Claude Desktop / Cursor / Continue (stdio)

```json
{
  "mcpServers": {
    "ibkr": {
      "command": "uv",
      "args": ["--directory", "/path/to/ibkr-mcp", "run", "ibkr-mcp", "--transport", "stdio"],
      "env": {
        "IB_HOST": "127.0.0.1",
        "IB_PORT": "4002",
        "IB_PAPER_TRADING": "true",
        "LOG_FORMAT": "console"
      }
    }
  }
}
```

### MCP clients that connect to a running server (Streamable HTTP)

```json
{
  "mcpServers": {
    "ibkr": {
      "url": "http://127.0.0.1:8400/mcp"
    }
  }
}
```

> **Localhost only.** The Streamable HTTP transport binds to `127.0.0.1` by default. Exposing it on other interfaces is **out of scope for v0.1** because no authentication layer is implemented. See [docs/deployment.md](docs/deployment.md#network-exposure) for safe ways to share the server across machines.

---

## Documentation map

| Document | What it covers |
|----------|----------------|
| [**docs/architecture.md**](docs/architecture.md) | Layered architecture, lifespan, concurrency model, Greeks priority, error mapping |
| [**docs/usage.md**](docs/usage.md) | Per-tool reference with input schema, output schema, examples, error codes |
| [**docs/configuration.md**](docs/configuration.md) | Full environment-variable reference and tuning advice |
| [**docs/deployment.md**](docs/deployment.md) | Stdio, Streamable HTTP, Docker, systemd, IBKR Gateway sidecar |
| [**docs/troubleshooting.md**](docs/troubleshooting.md) | IB Gateway pitfalls, daily restart, market-data permissions, common errors |
| [**docs/development.md**](docs/development.md) | Repo layout, FakeIB harness, CI gate, contribution workflow |
| [`specs/spec.md`](specs/spec.md) | Original full specification |
| [`specs/implementation_plan.md`](specs/implementation_plan.md) | Step-by-step implementation plan with cross-cutting conventions |

---

## Project structure

```
ibkr-mcp/
├── pyproject.toml
├── .env.template
├── README.md                       <- you are here
├── docs/                           <- detailed documentation
│   ├── architecture.md
│   ├── usage.md
│   ├── configuration.md
│   ├── deployment.md
│   ├── troubleshooting.md
│   └── development.md
├── specs/
│   ├── spec.md                     <- canonical specification
│   └── implementation_plan.md
├── src/ibkr_mcp/
│   ├── __init__.py
│   ├── __main__.py                 <- CLI entry point
│   ├── server.py                   <- FastMCP app, lifespan, AppContext
│   ├── config.py                   <- Pydantic Settings + structlog setup
│   ├── connection.py               <- ConnectionManager wrapping ib_async.IB
│   ├── errors.py                   <- ErrorCode enum, make_error, exception mapping
│   ├── logging_decorators.py       <- @tool_error_handler, @tool_call_logger
│   ├── models/                     <- Pydantic response schemas (camelCase)
│   ├── tools/                      <- Tool implementations + per-module register()
│   └── utils/
│       ├── contracts.py            <- build_contract for STK/OPT/FUT/CASH/BOND/IND
│       ├── durations.py            <- ISO 8601 → IB-native translation
│       └── black_scholes.py        <- pure-Python Greeks fallback
├── tests/
│   ├── fake_ib.py                  <- in-memory IB stand-in
│   ├── conftest.py                 <- shared fixtures
│   └── test_*.py                   <- 216 unit tests
└── .github/workflows/ci.yml        <- ruff + mypy + pytest
```

---

## Status & roadmap

- **v0.1 (current):** All 11 core tools + 2 conditional Flex tools registered. `get_alerts` is intentionally a `NOT_IMPLEMENTED` placeholder (see [usage docs](docs/usage.md#613-get_alerts-not-implemented)).
- **Out of scope for v0.1** (tracked in [spec.md §14](specs/spec.md)):
    - Authentication for the HTTP transport (must run localhost-only today)
    - Streaming/push notifications
    - Order placement (kept out of scope by the read-only design)
    - Custom reconnection / health-check logic beyond `ib_async`'s built-in retry
    - Caching layer for expensive operations (e.g. full option chains)

Contributions welcome — see [docs/development.md](docs/development.md).

---

## License

MIT — see [`LICENSE`](LICENSE).
