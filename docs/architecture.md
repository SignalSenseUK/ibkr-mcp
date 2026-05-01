# Architecture

This document describes how the IBKR MCP server is put together: the layers, the lifecycle, the concurrency model, the cross-cutting decorators, and the conventions that every tool obeys.

For a per-tool reference, see [usage.md](usage.md). For deployment scenarios, see [deployment.md](deployment.md).

---

## 1. High-level diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                           MCP client                                 │
│  (Claude Desktop, Cursor, Continue, custom agents, ...)              │
└──────────────────────────────────────────────────────────────────────┘
                                 │
                ┌────────────────┴────────────────┐
                │  stdio                          │  Streamable HTTP /mcp
                ▼                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        ibkr-mcp (FastMCP)                            │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │  build_mcp(settings)  →  register_all_tools(mcp, factory, settings)│
│ │  lifespan: connect → yield AppContext → disconnect                │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐  ┌─────────┐  │
│  │ tools/      │   │ models/      │   │ utils/       │  │ errors/ │  │
│  │ - server    │   │ - server     │   │ - contracts  │  │ codes   │  │
│  │ - account   │   │ - account    │   │ - durations  │  │ mapping │  │
│  │ - market    │   │ - positions  │   │ - black_scholes │ │         │  │
│  │ - orders    │   │ - market     │   └──────────────┘  └─────────┘  │
│  │ - contracts │   │ - orders     │                                  │
│  │ - flex      │   │ - contracts  │                                  │
│  └─────────────┘   │ - flex       │                                  │
│                    │ - alerts     │                                  │
│                    └──────────────┘                                  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ ConnectionManager (ib_async.IB wrapper)                      │     │
│  │  - connect() / disconnect()                                  │     │
│  │  - applies reqMarketDataType                                 │     │
│  │  - resolves account_id                                       │     │
│  │  - asyncio.Lock to serialise gateway requests                │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ TWS API (TCP)
                                   ▼
                     ┌─────────────────────────────┐
                     │  IB Gateway / TWS (local)   │
                     └─────────────────────────────┘
```

Everything between the MCP client and IB Gateway lives **in one Python process**. There is no database, queue, or cache.

---

## 2. Layers

| Layer | Responsibility |
|-------|----------------|
| **`config.py`** | Pydantic `Settings` (single source of truth for env vars), `setup_logging` (structlog JSON / console renderers). |
| **`connection.py`** | `ConnectionManager` wraps `ib_async.IB` with idempotent `connect()` / `disconnect()`, post-connect `reqMarketDataType` and account resolution. **Never raises** on connection failure. |
| **`server.py`** | `AppContext` dataclass, `build_lifespan(settings)`, `build_mcp(settings)`, `register_all_tools(mcp, factory, settings)`. Each `tools/*.py` module is imported lazily inside this function to avoid circular imports. |
| **`tools/*.py`** | Pure async tool functions stacked with `@tool_error_handler` and `@tool_call_logger`. Each module exposes a `register(mcp)` (or `register_if_enabled` for Flex) function called by `register_all_tools`. |
| **`models/*.py`** | Pydantic v2 response schemas with `populate_by_name=True`. Field names mirror the JSON the spec documents (camelCase). |
| **`utils/*.py`** | Pure helpers (no I/O): `build_contract`, `parse_duration`, `black_scholes_greeks`, `fallback_greeks`. |
| **`errors.py`** | `ErrorCode` `StrEnum`, `ErrorResponse` model, `make_error(code, message)` and `map_exception(exc)` helpers. |
| **`logging_decorators.py`** | `@tool_error_handler` (catches exceptions → JSON error response) and `@tool_call_logger` (emits structlog event when `LOG_TOOL_CALLS=true`). |

---

## 3. Lifecycle

### 3.1 Startup sequence

```
__main__.main()
    │
    ├── parse argv  (--transport overrides MCP_TRANSPORT)
    ├── settings = Settings()      # reads env vars + .env
    ├── setup_logging(settings)
    ├── mcp = build_mcp(settings)
    │     └── register_all_tools(mcp, factory, settings)
    │             └── Each module's register() / register_if_enabled() is called.
    │                 The flex module registers iff IB_FLEX_TOKEN is set.
    │
    ├── _probe()  ── one-shot connect to determine connected/disconnected
    │     so the banner can report the truth without blocking the lifespan.
    │
    ├── _print_banner(...)         # spec §11
    └── mcp.run(transport=...)     # starts FastMCP serving
        │
        ▼
        FastMCP lifespan runs:
            manager = ConnectionManager(settings)
            await manager.connect()        # MUST NOT raise
            yield AppContext(..., manager, ...)
            await manager.disconnect()
```

The probe-connect at boot exists only to print an accurate banner; the FastMCP lifespan **always** runs its own `connect()` (and is allowed to fail without crashing the server, per spec §5).

### 3.2 `AppContext`

```python
@dataclass
class AppContext:
    settings: Settings
    manager: ConnectionManager
    started_at: datetime
    server_version: str
    ib_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def account_id(self) -> str | None:
        return self.manager.account_id
```

Tools read this from `ctx.request_context.lifespan_context`. They never:

- import `Settings()` directly,
- hold their own reference to the `IB` client,
- create their own `asyncio.Lock`.

This is the **only** way tools see runtime state. Tests build their own `AppContext` around a `FakeIB` instance.

---

## 4. Tool registration (no circular imports)

Each `tools/*.py` module is a leaf — it imports from `models/`, `errors`, `logging_decorators`, and `server.AppContext`, but **never** the bound `mcp` instance. Instead it exposes:

```python
def register(mcp: FastMCP[AppContext]) -> None:
    mcp.tool()(get_thing)
    mcp.tool()(get_other_thing)
```

`server.register_all_tools` is the only place that knows about every module:

```python
def register_all_tools(mcp, app_ctx_factory, settings):
    from ibkr_mcp.tools import account, contracts, flex, market, orders, server as server_tool
    server_tool.register(mcp)
    account.register(mcp)
    market.register(mcp)
    orders.register(mcp)
    contracts.register(mcp)
    flex.register_if_enabled(mcp, settings)   # iff IB_FLEX_TOKEN is set
```

The lazy imports inside this function deliberately break the import cycle that would otherwise form if `tools/*.py` reached for the global `mcp` instance.

---

## 5. Cross-cutting decorators

Every tool is wrapped with both decorators (in this order):

```python
@tool_error_handler         # catches, maps to ErrorCode, returns JSON
@tool_call_logger           # emits structured log when LOG_TOOL_CALLS=true
async def get_market_data(ctx, ...): ...
```

### 5.1 `@tool_error_handler`

- Any exception raised inside the tool is caught.
- `errors.map_exception(exc)` chooses an `ErrorCode` (e.g. `IB_TIMEOUT`, `IB_NOT_CONNECTED`, `VALIDATION_ERROR`, …).
- Returns a JSON-serialised `ErrorResponse` so the MCP client always receives valid JSON.

### 5.2 `@tool_call_logger`

- When `settings.LOG_TOOL_CALLS=false` (default), this is a no-op.
- When `true`, emits one structlog event per tool call with: tool name, sanitised input, duration, outcome (`success`/`error`), and `error_code` on failure.

The two decorators are independent — you can disable per-call logging without losing the error-mapping safety net.

---

## 6. Concurrency model

### 6.1 The `ib_lock`

The Streamable HTTP transport may serve **multiple concurrent MCP clients** sharing one `ib_async.IB` client instance. `ib_async`'s socket is not safe for unsynchronised concurrent calls. To serialise gateway-bound requests, every tool call wraps its `ib.req...` invocations in:

```python
async with app_ctx.ib_lock:
    qualified = await ib.qualifyContractsAsync(contract)
    tickers = await ib.reqTickersAsync(*qualified)
```

**Exceptions to the rule:**

- `ib.trades()`, `ib.openOrders()`, `ib.positions()`, `ib.portfolio()` are pure cache reads — they don't issue gateway round-trips. These run lock-free.
- The Flex query tools talk to IB's Flex Web Service over HTTPS, **not** the gateway, so they don't touch `ib_lock`.

### 6.2 Snapshot vs streaming

`get_market_data` uses `ib.reqTickersAsync(contract)` — a **one-shot snapshot**. Streaming subscriptions are never opened. This keeps each tool call stateless and prevents subscription leaks.

### 6.3 Greeks priority

For options, ib_async's `Ticker` exposes Greeks under several attributes (most-stable → most-volatile):

```python
modelGreeks → lastGreeks → bidGreeks → askGreeks
```

`tools/market.py:_extract_greeks` walks these in order and returns the first non-empty bundle. The same priority applies inside `get_portfolio_greeks` and `get_option_chain`.

### 6.4 Black-Scholes fallback

`get_portfolio_greeks` first tries the priority cascade above. If **no** bundle has any usable values **but** an implied volatility is known, it falls back to a pure-Python Black-Scholes computation in `utils/black_scholes.py`:

```python
black_scholes_greeks(right, spot, strike, T, iv, r=0, q=0)
    → {"delta", "gamma", "theta" (per day), "vega" (per 1.00 vol)}
```

If neither model Greeks **nor** an IV are available, the position is emitted with `source="missing"` and contributes nothing to the totals. This avoids silently fabricating numbers.

---

## 7. Error model

Every tool returns either a **JSON-serialised success model** or a **JSON-serialised `ErrorResponse`**. Tools never raise across the MCP boundary.

```python
class ErrorCode(StrEnum):
    IB_NOT_CONNECTED      = "IB_NOT_CONNECTED"
    IB_CONNECTION_FAILED  = "IB_CONNECTION_FAILED"
    IB_TIMEOUT            = "IB_TIMEOUT"
    IB_INVALID_CONTRACT   = "IB_INVALID_CONTRACT"
    IB_NO_MARKET_DATA     = "IB_NO_MARKET_DATA"
    IB_FLEX_ERROR         = "IB_FLEX_ERROR"
    IB_ACCOUNT_NOT_FOUND  = "IB_ACCOUNT_NOT_FOUND"
    VALIDATION_ERROR      = "VALIDATION_ERROR"
    NOT_IMPLEMENTED       = "NOT_IMPLEMENTED"
```

`errors.map_exception` is conservative: anything it can't classify is bucketed as `VALIDATION_ERROR`. Specific mappings include:

| Exception | ErrorCode |
|-----------|-----------|
| `asyncio.TimeoutError`, `TimeoutError` | `IB_TIMEOUT` |
| `ConnectionError` | `IB_NOT_CONNECTED` |
| `NotImplementedError` | `NOT_IMPLEMENTED` |
| `pydantic.ValidationError` | `VALIDATION_ERROR` |
| `ValueError` (any) | `VALIDATION_ERROR` |
| Message contains `"flex"` | `IB_FLEX_ERROR` |
| Message contains `"no security definition"`, `"ambiguous contract"` | `IB_INVALID_CONTRACT` |
| Message contains `"market data is not subscribed"` | `IB_NO_MARKET_DATA` |
| Message contains `"account"` | `IB_ACCOUNT_NOT_FOUND` |

---

## 8. Resilience: connection failure ≠ server crash

Per spec §5, the server **must stay up** when IB Gateway is unreachable so MCP clients receive structured errors instead of broken pipes. This is enforced in three places:

1. `ConnectionManager.connect()` returns a `bool` — it never raises, even on `ConnectionRefusedError`. All exceptions are logged via structlog.
2. `build_lifespan` wraps the connect call in `try/except` for defence in depth.
3. The CLI banner is printed **after** a probe connect, so an operator can see the failure on stderr without the process exiting.

While disconnected:

- All gateway-bound tools short-circuit with `IB_NOT_CONNECTED`.
- Flex query tools continue to function (they hit a different service).
- `get_server_status` reports `status: "disconnected"` so clients can detect the state.

---

## 9. Schema conventions

- Response models live in `src/ibkr_mcp/models/*.py`.
- Field names mirror the JSON in spec §6 verbatim — **camelCase** (e.g. `lastPrice`, `marketValue`, `unrealizedPnL`). Per-file `ruff` ignores for `N815` are configured in `pyproject.toml`.
- Every model uses `model_config = ConfigDict(populate_by_name=True)` so callers may use either alias or field name when constructing.
- Tools serialise responses with `.model_dump_json(exclude_none=True)` so optional fields don't pollute the wire payload with nulls.

---

## 10. Why these choices?

| Decision | Rationale |
|----------|-----------|
| FastMCP (`mcp[cli]`) | Standard Python MCP SDK; supports both stdio and Streamable HTTP; built-in lifespan management. |
| `ib_async` | Async-native, actively maintained, full TWS API coverage. |
| Pydantic v2 | Type-safe schemas, automatic JSON serialisation, validates at the boundary. |
| structlog | JSON-line output, async-friendly, context-bind for per-tool tracing. |
| `uv` | Fast, modern dependency management. |
| ruff + mypy --strict | Catches errors at edit time; minimal CI surface. |
| **No pandas** | `ib_async.util.df()` is a convenience helper — we serialise via Pydantic instead. Drops a heavy dependency. |
| **No SciPy** | Black-Scholes Greeks computed via `math.erf`. Keeps the runtime tree minimal. |
| Default port `4002` | Matches `IB_PAPER_TRADING=true` default; corrects a contradiction in earlier drafts. |

---

## 11. Where to look in the source

| You want to … | Look at |
|---------------|---------|
| Add a new tool | Pick the right `tools/*.py` module, write the async function, decorate with `@tool_error_handler` and `@tool_call_logger`, append to `register(mcp)` in that module. The lazy import in `server.register_all_tools` will pick it up automatically. |
| Add a new env var | Add a `Field(...)` to `Settings` in `config.py`, document it in `.env.template`, and (if user-visible) reflect it in `docs/configuration.md`. |
| Change the connection lifecycle | `connection.py:ConnectionManager` and `server.py:build_lifespan`. |
| Adjust tool-call logging | `logging_decorators.py:tool_call_logger`. |
| Add a new error code | `errors.py:ErrorCode` and (optionally) `_MESSAGE_HINTS` to influence `map_exception`. |
| Change Black-Scholes assumptions | `utils/black_scholes.py`. |
