# Configuration

All configuration is loaded from environment variables (and an optional `.env` file in the working directory). The single source of truth is [`src/ibkr_mcp/config.py:Settings`](../src/ibkr_mcp/config.py); no other module reads `os.environ` directly.

The shipped `.env.template` documents every variable with sensible defaults; copy it to `.env` and edit to taste.

```bash
cp .env.template .env
```

---

## Environment variable reference

### IB Gateway / TWS connection

| Variable | Default | Description |
|----------|---------|-------------|
| `IB_HOST` | `127.0.0.1` | Host where IB Gateway / TWS is listening. |
| `IB_PORT` | `4002` | Gateway / TWS port. **`4002` matches `IB_PAPER_TRADING=true`** (see port table below). |
| `IB_CLIENT_ID` | `1` | TWS client ID. **Must be unique** per concurrent connection to the same Gateway. |
| `IB_ACCOUNT` | unset | Specific account ID. If omitted, the first managed account is used. If set to an account that isn't linked to this gateway, the server **disconnects on startup** to fail loud rather than serve the wrong account. |
| `IB_PAPER_TRADING` | `true` | Informational flag; logged on startup so operators can see at a glance which environment is active. |
| `IB_MARKET_DATA_TYPE` | `LIVE` | One of `LIVE`, `FROZEN`, `DELAYED`, `DELAYED_FROZEN`. Applied once after a successful connect via `reqMarketDataType`. |
| `IB_FLEX_TOKEN` | unset | If set, registers `list_flex_queries` and `get_flex_query`. If unset, those two tools are **not** registered. |
| `IB_FLEX_QUERIES` | unset | Optional JSON-encoded list of `{queryId, queryName, type?}` describing the Flex queries you want to expose via `list_flex_queries` and resolve by name in `get_flex_query`. |

#### IB Gateway / TWS port reference

| Mode | Port |
|------|------|
| **IB Gateway, paper** | `4002` ← default |
| IB Gateway, live | `4001` |
| **TWS, paper** | `7497` |
| TWS, live | `7496` |

> **Why is the default 4002 instead of 4001 (as some IBKR docs suggest)?** Because `IB_PAPER_TRADING=true` is also the default; using `4001` would mean the out-of-the-box config tries to talk to a *live* gateway while claiming to be paper. We pick `4002` so both defaults agree.

### MCP transport

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `streamable-http` | `stdio` or `streamable-http`. Override at the CLI with `--transport`. |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP bind address. **Localhost-only in v0.1** (no auth layer). |
| `MCP_HTTP_PORT` | `8400` | HTTP bind port. The path is fixed at `/mcp`. |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `json` | `json` (one structured event per line) or `console` (coloured human-readable). |
| `LOG_TOOL_CALLS` | `false` | When `true`, every tool invocation is logged with input args, duration, and outcome. Useful for development; disable in noisy production environments. |

---

## Where settings are read

```
$PWD/.env
    ↓ (lowest precedence)
process environment
    ↓ (highest precedence)
Settings()  ←  loaded once at process start
```

`Settings` is a Pydantic v2 `BaseSettings` model with `extra="ignore"` — unknown env vars are silently dropped, so adding new variables to your shell environment never breaks the server.

---

## Tuning advice

### Logging in production

```bash
LOG_FORMAT=json
LOG_LEVEL=INFO
LOG_TOOL_CALLS=false
```

JSON output ships well into log aggregators (Loki, Datadog, CloudWatch, ELK). Per-tool-call logging is **off** in production by default because it can be very chatty under load. Toggle it on briefly for debugging or feature-flag it via your orchestrator.

### Logging in development

```bash
LOG_FORMAT=console
LOG_LEVEL=DEBUG
LOG_TOOL_CALLS=true
```

You'll see every tool call with full input and timing in a colourised stderr stream.

### Tighter market data control

If you don't have IB market-data subscriptions but want to exercise the tooling against AAPL etc., set:

```bash
IB_MARKET_DATA_TYPE=DELAYED
```

15-minute delayed data is free for most US equities and behaves the same way through the API. Snapshots return slightly stale prices but every other tool works.

### Multiple connections to the same gateway

IB Gateway permits multiple concurrent TWS API clients **as long as each uses a unique `IB_CLIENT_ID`**. If you run the MCP server and another tool (e.g. a manual trading script) against the same gateway, give each one a different `IB_CLIENT_ID`. Reusing an ID will silently bump off the older connection.

### Multi-account setups

The server currently targets **one account per process**. If `IB_ACCOUNT` is unset and the gateway is linked to multiple accounts, the **first** managed account is used. If you need fan-out across accounts:

- Run one MCP server per account, with distinct `IB_CLIENT_ID` and `MCP_HTTP_PORT`, **or**
- Pass `accountId` explicitly to every tool that supports it (`get_account_info`, `get_positions`, `get_live_orders`, `get_portfolio_greeks`). Trying to read an account that isn't linked to the gateway returns `IB_ACCOUNT_NOT_FOUND`.

### Flex queries

To enable Flex query tooling:

1. **Generate a Flex token** in IB Account Management → Reporting → Flex Queries → Settings. Copy it into `IB_FLEX_TOKEN`.
2. **Create one or more Flex queries** in the same UI. Note each `Query ID` (a numeric string) and a friendly name.
3. **Register them in `IB_FLEX_QUERIES`** so `list_flex_queries` returns useful output and `get_flex_query` can resolve by name:

   ```bash
   IB_FLEX_QUERIES='[{"queryId":"12345","queryName":"Daily P&L","type":"Statement"},{"queryId":"67890","queryName":"Trades"}]'
   ```

> **Token security.** The Flex token is equivalent to read-only API access to your activity history. Treat it like a password. Don't commit it to git; never echo it in shared logs. The server itself never logs the value (only its presence/absence).

---

## Common Pydantic validation errors at boot

### `IB_PORT` must be 1–65535

```
ValidationError: ... IB_PORT
  Input should be greater than or equal to 1
```

You set `IB_PORT=0` or to a non-integer.

### `IB_MARKET_DATA_TYPE` must be one of LIVE / FROZEN / DELAYED / DELAYED_FROZEN

```
ValidationError: ... IB_MARKET_DATA_TYPE
  Input should be 'LIVE', 'FROZEN', 'DELAYED' or 'DELAYED_FROZEN'
```

The check is case-sensitive. Common typo: `Delayed` instead of `DELAYED`.

### `MCP_TRANSPORT` must be `stdio` or `streamable-http`

```
ValidationError: ... MCP_TRANSPORT
  Input should be 'stdio' or 'streamable-http'
```

Note the lower-case + hyphen; `STREAMABLE-HTTP` and `streamable_http` are both invalid.

---

## Inspecting the resolved settings at runtime

```python
from ibkr_mcp.config import Settings

s = Settings()
print(s.model_dump())
```

Or just look at the startup banner — it logs the values that drive boot.

---

## Programmatic configuration

You can build `Settings` manually rather than from env:

```python
from ibkr_mcp.config import Settings, MarketDataType, TransportMode
from ibkr_mcp.server import build_mcp

settings = Settings(
    IB_HOST="127.0.0.1",
    IB_PORT=4002,
    IB_MARKET_DATA_TYPE=MarketDataType.DELAYED,
    MCP_TRANSPORT=TransportMode.STDIO,
)
mcp = build_mcp(settings)
mcp.run(transport="stdio")
```

This is how the test suite drives the server without touching the environment.
