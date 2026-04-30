---
title: "IBKR MCP Server — Implementation Plan"
domain: infra
type: plan
created: 2026-04-29
updated: 2026-04-30
status: revised
---

# IBKR MCP Server — Implementation Plan

This plan operationalises `spec.md`. It is structured so that every step lands behind unit tests, all spec-mandated cross-cutting concerns (error codes, structured logging, tool-call logging, market-data-type, lifespan resilience, concurrency) are addressed once in shared infrastructure rather than ad-hoc in each tool, and the final repository matches the project structure declared in `spec.md` §8.

## 1. Project Blueprint

- **Milestone 1: Project Skeleton & Cross-Cutting Infrastructure**
  - **Goal:** Stand up the package, configuration, structured logging, error-code primitives, and the CI workflow before any tool code is written.
  - **Components:** `pyproject.toml`, `.env.template`, `src/ibkr_mcp/{config.py,errors.py,logging_decorators.py}`, `.github/workflows/ci.yml`.
  - **Artifacts:** `uv`-installable package; `ruff`, `mypy --strict`, and `pytest` all green on an empty test suite.

- **Milestone 2: Connection Lifecycle & MCP Server Core**
  - **Goal:** Implement an `ib_async` connection manager and a `FastMCP` lifespan that survives connection failure, resolves the active account, applies market-data-type, and exposes a typed `AppContext`.
  - **Components:** `connection.py`, `server.py`, `__main__.py`, `tests/fake_ib.py`, `tests/conftest.py`.
  - **Artifacts:** Server boots over both `stdio` and `streamable-http`, mounted at `/mcp`. `FakeIB` harness is in place so every subsequent step ships with tests.

- **Milestone 3: Server Status, Account & Position Tools (P0)**
  - **Goal:** First batch of tools covering server health, account summary, and positions.
  - **Components:** `models/{server,account,positions}.py`, `tools/{server,account}.py`, paired tests.
  - **Artifacts:** `get_server_status`, `get_account_info`, `get_positions` wired up and unit-tested.

- **Milestone 4: Market Data & Order Monitoring Tools (P0)**
  - **Goal:** Real-time snapshots, historical bars, and order monitoring, backed by reusable contract/duration utilities.
  - **Components:** `utils/{contracts,durations}.py`, `models/{market,orders}.py`, `tools/{market,orders}.py`, paired tests.
  - **Artifacts:** `get_market_data`, `get_historical_data`, `get_order_status`, `get_live_orders`.

- **Milestone 5: Reference Data & Flex Query Tools (P1)**
  - **Goal:** Contract lookup and conditional Flex query tools that work even when the gateway connection is down.
  - **Components:** `tools/contracts.py`, `tools/flex.py`, paired tests.
  - **Artifacts:** `get_contract_details`, `list_flex_queries`, `get_flex_query`.

- **Milestone 6: Deferred Tools (P2) & Final Hardening**
  - **Goal:** Option chain, portfolio Greeks (with Black-Scholes fallback), and an explicit not-implemented `get_alerts`. Final integration tests, README, and PyPI packaging polish.
  - **Components:** `models/alerts.py`, additions to `tools/{market,account,orders}.py`, BS helper in `utils/`, integration test stubs.
  - **Artifacts:** All 11 core tools + 2 conditional flex tools registered. Spec project tree fully realised.

---

## 2. Cross-Cutting Conventions (apply to every step)

These conventions are decided once here so individual steps do not re-litigate them.

### 2.1 Tool registration pattern

Tool functions are defined as plain `async def` functions in `tools/*.py`. Each module exposes a `register(mcp: FastMCP, app_ctx_factory) -> None` function that calls `mcp.tool()(fn)` for each tool. `server.py` imports these `register` functions and calls them. **No `tools/*.py` module imports the global `mcp` instance** — this avoids the circular-import trap.

### 2.2 Lifespan & `AppContext`

```python
@dataclass
class AppContext:
    settings: Settings
    ib: IB                      # always present; may be unconnected
    started_at: datetime
    account_id: str | None      # resolved after connect; None if connect failed
    server_version: str         # importlib.metadata.version("ibkr-mcp")
    ib_lock: asyncio.Lock       # serialises contended ib_async calls
```

The lifespan **must** wrap `connect()` in `try/except` so the server stays up on failure (`spec.md` §5). `AppContext` is the value yielded; tools access it via `ctx.request_context.lifespan_context`.

### 2.3 Error codes

`src/ibkr_mcp/errors.py` defines:

```python
class ErrorCode(StrEnum):
    IB_NOT_CONNECTED = "IB_NOT_CONNECTED"
    IB_CONNECTION_FAILED = "IB_CONNECTION_FAILED"
    IB_TIMEOUT = "IB_TIMEOUT"
    IB_INVALID_CONTRACT = "IB_INVALID_CONTRACT"
    IB_NO_MARKET_DATA = "IB_NO_MARKET_DATA"
    IB_FLEX_ERROR = "IB_FLEX_ERROR"
    IB_ACCOUNT_NOT_FOUND = "IB_ACCOUNT_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

class ErrorResponse(BaseModel):
    error: str
    code: ErrorCode

def make_error(code: ErrorCode, message: str) -> str:
    return ErrorResponse(error=message, code=code).model_dump_json()
```

Every tool returns a JSON **string** (per FastMCP best practice for structured output), either a Pydantic-serialised success model or `make_error(...)`.

### 2.4 Tool-call logging & error-handling decorators

`src/ibkr_mcp/logging_decorators.py` provides two decorators applied to **every** tool:

```python
@tool_error_handler         # catches exceptions, maps them to ErrorCode, returns JSON
@tool_call_logger           # if settings.LOG_TOOL_CALLS, emits structured log per call
async def get_market_data(ctx, ...): ...
```

Mapping of common `ib_async` exceptions to error codes lives in this module so each tool stays clean. Logger emits the schema in `spec.md` §12.3.

### 2.5 Tool docstrings

Each tool function's docstring **must** be the exact "MCP Description" text from `spec.md` §6 — FastMCP exposes the docstring as the tool's description to MCP clients.

### 2.6 Concurrency

Every direct `await ib.req...` call inside a tool is wrapped with `async with app_ctx.ib_lock:` to serialise gateway requests across concurrent HTTP clients. Exception: read-only accessors that don't issue gateway requests (`ib.positions()`, `ib.openOrders()`, `ib.trades()` once cached).

### 2.7 Snapshot semantics

`get_market_data` uses `ib.reqTickersAsync(contract)` (one-shot). For options, Greeks are extracted in this priority: `modelGreeks` → `lastGreeks` → `bidGreeks` → `askGreeks`. Streaming subscriptions are never created.

### 2.8 Market-data-type

`connection.py` calls `ib.reqMarketDataType(MAP[settings.IB_MARKET_DATA_TYPE])` immediately after a successful `connectAsync`. No tool re-issues this call.

### 2.9 Default port correction

The plan ships `pyproject.toml` and `Settings` with `IB_PORT` default `4002` (paper) to match the `IB_PAPER_TRADING=true` default. This corrects a contradiction in the spec; the `.env.template` includes both 4001 (live) and 4002 (paper) examples.

### 2.10 Pandas

Pandas is **dropped** from runtime dependencies. `ib_async.util.df()` is a convenience helper; we serialise via Pydantic. `pandas-stubs` is also dropped.

### 2.11 Testing cadence

Each step that produces tool or utility code lands its own `tests/test_*.py` in the same step. CI runs `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest -m "not integration"` on every step's diff.

---

## 3. Refined Implementation Steps

Step IDs are continuous; new infra steps are inserted up-front so later steps can rely on them.

### Milestone 1 — Skeleton & Cross-Cutting Infra

- **S1: Package structure, dependencies, mypy & ruff config, CI workflow.**
  - Create `pyproject.toml` with the dependency set (no `pandas`, no `pandas-stubs`).
  - Configure `[tool.mypy] strict = true`, `[tool.ruff]`, `[tool.pytest.ini_options]`.
  - Create directory tree exactly per `spec.md` §8.
  - Create `.env.template` with all 13 env vars from spec §3.1 documented.
  - Create `.github/workflows/ci.yml` running `ruff check`, `ruff format --check`, `mypy src/`, `pytest tests/ -m "not integration" --cov=ibkr_mcp`.
  - **Test:** CI passes on an empty test suite. `uv sync && uv run python -c "import ibkr_mcp"` succeeds.

- **S2: Configuration & structured logging.**
  - `src/ibkr_mcp/config.py`: Pydantic `BaseSettings` for all env vars (`IB_PORT` default `4002`). `setup_logging(settings)` configures `structlog` JSON or console renderer based on `LOG_FORMAT`.
  - **Test:** `tests/test_config.py` — env-var precedence, `.env` loading, `LOG_FORMAT` validator, paper/live port note.

- **S3: Error codes & tool decorators.**
  - `src/ibkr_mcp/errors.py`: `ErrorCode` StrEnum, `ErrorResponse` model, `make_error(...)`, exception → code mapping helpers.
  - `src/ibkr_mcp/logging_decorators.py`: `@tool_error_handler` and `@tool_call_logger` decorators per §2.4.
  - **Test:** `tests/test_errors.py` — JSON shape; `tests/test_logging_decorators.py` — outcomes captured, durations sane, errors mapped.

### Milestone 2 — Connection Lifecycle & Server Core

- **S4: Connection manager.**
  - `src/ibkr_mcp/connection.py`: `ConnectionManager` wrapping `ib_async.IB`. Async `connect()` / `disconnect()`; `is_connected` property. After successful connect: call `ib.reqMarketDataType(...)`; resolve `account_id` from `IB_ACCOUNT` or `ib.managedAccounts()[0]`. All exceptions logged via `structlog` and surfaced as boolean failure (no crash).
  - **Test:** `tests/test_connection.py` — uses `FakeIB` (created next step) with `pytest-mock` to simulate connect failure, account fallback, and market-data-type propagation.

- **S5: FakeIB harness & shared fixtures.**
  - `tests/fake_ib.py`: `FakeIB` mock implementing every `ib_async.IB` method touched by tools (`isConnected`, `connectAsync`, `disconnectAsync`, `managedAccounts`, `accountSummaryAsync`, `reqPositionsAsync`, `reqTickersAsync`, `reqHistoricalDataAsync`, `reqContractDetailsAsync`, `reqOpenOrdersAsync`, `trades`, `positions`, `openOrders`, `reqSecDefOptParamsAsync`, `reqMarketDataType`). Methods return canned data driven by per-test attributes.
  - `tests/conftest.py`: `mock_ib` fixture, `app_ctx` fixture (builds an `AppContext` around `FakeIB`), `mcp_with_tools` fixture for end-to-end tool dispatch.
  - **Test:** `tests/test_fake_ib.py` — sanity tests on the harness itself.

- **S6: FastMCP server, lifespan & CLI entry point.**
  - `src/ibkr_mcp/server.py`: `FastMCP("IBKR", lifespan=lifespan)` with FastMCP's `streamable_http_path="/mcp"`. The `lifespan` builds `AppContext`, calls `ConnectionManager.connect()` inside `try/except` (server stays up on failure per spec §5), yields the context, calls `disconnect()` on teardown.
  - `src/ibkr_mcp/__main__.py`: argparse with `--transport {stdio,streamable-http}`. Loads settings, calls `setup_logging`, prints the spec §11 startup banner to stderr (success or warning variant), runs `mcp.run(transport=...)` with host/port from settings for HTTP.
  - **Test:** `tests/test_server_bootstrap.py` — server boots with a failing `FakeIB.connectAsync`, lifespan still yields, `AppContext.account_id` is `None`, banner emitted to stderr.

### Milestone 3 — Server Status, Account & Positions (P0)

- **S7: Server status tool.**
  - `models/server.py`: `ServerStatusResponse` per spec §6.2.
  - `tools/server.py`: `get_server_status` (docstring = spec MCP description). Reads `AppContext`, computes uptime, counts registered tools, reports transport. Decorated with `@tool_error_handler` + `@tool_call_logger`. Exposes `register(mcp, app_ctx_factory)`.
  - Wire `register(...)` from `server.py`.
  - **Test:** `tests/test_server_tools.py` — connected, disconnected, and uptime cases; schema matches spec exactly.

- **S8: Account info & positions tools.**
  - `models/account.py`, `models/positions.py`: schemas per spec §6.3.
  - `tools/account.py`: `get_account_info` (uses `ib.accountSummaryAsync()`), `get_positions` (uses `ib.reqPositionsAsync()` with optional `accountId` filter; emits option fields `right`, `strike`, `expiry`, `multiplier` when `secType == "OPT"`).
  - Both decorated; `register(...)` exposed; called from `server.py`.
  - **Test:** `tests/test_account_tools.py` — disconnected returns `IB_NOT_CONNECTED`; option position emits all option fields; account-id filter works; account-id mismatch returns `IB_ACCOUNT_NOT_FOUND`.

### Milestone 4 — Market Data & Orders (P0)

- **S9: Utility modules.**
  - `utils/contracts.py`: `build_contract(symbol, secType, exchange="SMART", currency="USD", expiry=None, strike=None, right=None)` returning the correct `ib_async.Contract` subclass; raises `ValueError` mapped to `IB_INVALID_CONTRACT` upstream.
  - `utils/durations.py`: `parse_duration(s)` translating ISO 8601 → IB-native exactly per spec §6.4 table; pass-through for IB-native strings.
  - **Test:** `tests/test_duration_utils.py` (full table from spec §6.4 plus invalid inputs); `tests/test_contracts_util.py` (each `secType`).

- **S10: Market data tools.**
  - `models/market.py`: `MarketDataEquityResponse`, `MarketDataOptionResponse` (with Greeks), `HistoricalBar`, `HistoricalDataResponse`.
  - `tools/market.py`: `get_market_data` using `ib.reqTickersAsync(contract)` (snapshot, no streaming subscription). For options, extract Greeks per §2.7 priority. `get_historical_data` using `ib.reqHistoricalDataAsync` with `parse_duration`. Both wrapped in `app_ctx.ib_lock`.
  - **Test:** `tests/test_market_tools.py` — equity snapshot, option snapshot with Greeks, historical with ISO and IB-native durations, invalid contract, no-market-data permission error.

- **S11: Order monitoring tools.**
  - `models/orders.py`: `OrderStatusResponse`, `LiveOrdersResponse`.
  - `tools/orders.py`: `get_live_orders` (from `ib.openOrders()` / `ib.reqOpenOrdersAsync()` for refresh); `get_order_status` (look up `Trade` in `ib.trades()`, then read `trade.orderStatus`, `trade.fills` for `avgFillPrice` and `commissionReport`-derived commission, plus order timestamps).
  - **Test:** `tests/test_order_tools.py` — open order, filled order with commission from `fills`, unknown order id, account-id filter.

### Milestone 5 — Contract Reference & Flex Queries (P1)

- **S12: Contract details tool.**
  - `tools/contracts.py`: `get_contract_details` using `ib.reqContractDetailsAsync(build_contract(...))`. Output mirrors spec §6.6, including option-specific fields when applicable.
  - **Test:** `tests/test_contract_tools.py` — STK lookup, OPT lookup with strike/expiry/right populated, ambiguous symbol, no contract found.

- **S13: Flex query tools (conditional registration).**
  - `tools/flex.py`: `list_flex_queries` and `get_flex_query` using `ib_async.FlexReport`. **These tools must function when `ib.isConnected()` is `false`** (they hit IB's Flex Web Service over HTTPS, not the gateway). They never use `app_ctx.ib_lock`. `get_flex_query` accepts `queryId` xor `queryName`, optional `topic`; uses `FlexReport.extract()`; on parse failure returns the raw XML with `parsed: false`.
  - `server.py` registers these only when `settings.IB_FLEX_TOKEN` is set.
  - **Test:** `tests/test_flex_tools.py` — flex tools registered iff token set; bad token → `IB_FLEX_ERROR`; topic filter; XML fallback when extraction fails. Uses `pytest-mock` to patch `FlexReport`.

### Milestone 6 — Deferred Tools (P2) & Hardening

- **S14: Option chain (`get_option_chain`).**
  - Extend `tools/market.py`. Without `expiry`: discovery only via `ib.reqSecDefOptParamsAsync(...)` (spec §6.8 explicit "rate limit note" — no per-contract data). With `expiry`: enumerate strikes and call `reqTickersAsync` in batches; emit Greeks.
  - **Test:** discovery output shape; with-expiry output shape; verifies discovery branch never issues per-contract requests.

- **S15: Portfolio Greeks (`get_portfolio_greeks`) with Black-Scholes fallback.**
  - Extend `tools/account.py`. Aggregate position-level Greeks. When `modelGreeks` is missing for a position, compute via Black-Scholes from last known IV.
  - `utils/black_scholes.py`: pure-Python Greeks (no scipy dependency; use `math.erf` for the normal CDF).
  - **Test:** `tests/test_portfolio_greeks.py` — happy path with TWS Greeks; fallback path with synthetic IV; aggregation math.

- **S16: `get_alerts` placeholder.**
  - `models/alerts.py`: `Alert`, `AlertCondition`, `AlertsResponse` per spec §6.8.
  - `tools/orders.py` adds `get_alerts` returning `make_error(ErrorCode.NOT_IMPLEMENTED, "get_alerts requires feasibility validation")`. Documented in code with a TODO referencing spec §6.8 feasibility note.
  - **Test:** `tests/test_alerts_tool.py` — returns `NOT_IMPLEMENTED`; schema present so future implementation is type-safe.

- **S17: Final hardening.**
  - Verify the on-disk tree matches `spec.md` §8 exactly (including empty `__init__.py` files and `models/alerts.py`).
  - Add `tests/test_integration.py` with `@pytest.mark.integration` smoke tests against a paper account (skipped in CI).
  - Confirm `mcp.run(transport="streamable-http")` exposes `/mcp` and that the MCP client config in spec §16.3 works end-to-end.
  - Run full local CI: `ruff check`, `ruff format --check`, `mypy --strict src/`, `pytest tests/ -m "not integration" --cov=ibkr_mcp`.

---

## 4. Step Dependency Graph

```
S1 ──► S2 ──► S3 ──┐
                   ├─► S4 ──► S5 ──► S6 ──► S7 ──► S8 ──► S9 ──► S10 ──► S11 ──► S12 ──► S13 ──► S14 ──► S15 ──► S16 ──► S17
                   │                       (P0 status / account / positions)   (P0 market / orders)   (P1 contracts / flex)   (P2 chain / greeks / alerts)   (final)
```

S5 (FakeIB harness) is the critical inflection point: every step from S6 onward is required to ship with paired unit tests using this harness. No step is considered done until `pytest`, `ruff`, and `mypy --strict` are green.

---

## 5. Code-Generation Prompt Pack

Each prompt below is meant to be passed (one at a time) to a code-generation LLM. Prompts assume earlier prompts have completed and committed.

### Step S1 — Package Structure, Dependencies, Tooling Config, CI

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- New project ibkr-mcp: a read-only MCP server backed by ib_async. Spec is at specs/spec.md.

Task:
- Create the pyproject.toml, base directory tree, .env.template, and CI workflow.

Requirements:
- pyproject.toml with project name "ibkr-mcp", version "0.1.0", requires-python ">=3.12".
- Runtime deps: mcp[cli]>=1.9.0, ib_async>=0.9.86, pydantic>=2.0.0, pydantic-settings>=2.0.0, python-dotenv>=1.0.0, structlog>=24.0.0. (DO NOT include pandas.)
- Optional dev deps: pytest>=8.0.0, pytest-asyncio>=0.24.0, pytest-mock>=3.14.0, pytest-cov, ruff>=0.8.0, mypy>=1.13.0.
- [project.scripts] entry: ibkr-mcp = "ibkr_mcp.__main__:main".
- Configure [tool.mypy] strict=true, python_version="3.12", and ignore-missing-imports for ib_async and mcp.
- Configure [tool.ruff] line-length=100 and the standard rule set; [tool.ruff.format] preserve.
- Configure [tool.pytest.ini_options] with asyncio_mode="auto" and markers={integration}.
- Create the directory tree from spec §8 with empty __init__.py files in src/ibkr_mcp, src/ibkr_mcp/models, src/ibkr_mcp/tools, src/ibkr_mcp/utils.
- Create .env.template documenting every variable from spec §3.1 with both paper (4002) and live (4001) examples commented.
- Create .github/workflows/ci.yml that runs on push/PR: install uv, uv sync, run `ruff check`, `ruff format --check`, `mypy src/`, `pytest tests/ -m "not integration" --cov=ibkr_mcp`.

Output:
- All file contents and a one-line note per created file.
```

### Step S2 — Settings & structlog

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- pyproject.toml exists. pydantic-settings and structlog are installed.

Task:
- Create src/ibkr_mcp/config.py and tests/test_config.py.

Requirements:
- Settings(BaseSettings) loads from env + .env. Fields exactly match spec §3.1, with IB_PORT default 4002 (paper).
- IB_MARKET_DATA_TYPE is a StrEnum {LIVE, FROZEN, DELAYED, DELAYED_FROZEN}.
- MCP_TRANSPORT is a StrEnum {stdio, streamable-http}.
- LOG_FORMAT is a StrEnum {json, console}.
- All str-yes/no flags use the typed bool field.
- setup_logging(settings) configures structlog: JSON renderer when LOG_FORMAT==json, console renderer otherwise; level from LOG_LEVEL.
- Tests cover: env precedence, .env loading via tmp_path, default port = 4002, invalid LOG_FORMAT raises ValidationError.

Do NOT touch any other files.
```

### Step S3 — Error Codes & Decorators

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Settings module exists.

Task:
- Create src/ibkr_mcp/errors.py and src/ibkr_mcp/logging_decorators.py, plus tests.

Requirements (errors.py):
- class ErrorCode(StrEnum) with the 9 values listed in section 2.3 of the implementation plan.
- class ErrorResponse(BaseModel): error: str; code: ErrorCode.
- def make_error(code, message) -> str returning model_dump_json().
- def map_exception(exc) -> ErrorCode mapping common ib_async / asyncio exceptions to codes (TimeoutError→IB_TIMEOUT, ConnectionError→IB_NOT_CONNECTED, etc.).

Requirements (logging_decorators.py):
- @tool_error_handler: wraps an async tool; on exception returns make_error(map_exception(e), str(e)).
- @tool_call_logger: when settings.LOG_TOOL_CALLS is True, emits a structlog "tool_call" event matching the schema in spec §12.3 (event, tool, input, duration_ms, outcome, error_code, timestamp).
- Decorators are stackable in the order [@tool_error_handler, @tool_call_logger] reading top-down, so logger sees the post-error-handling outcome.

Tests cover: error JSON shape, exception mapping, logger emits success and error variants and never raises.

Do NOT touch any other files.
```

### Step S4 — Connection Manager

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Settings, errors, decorators exist. ib_async is installed.

Task:
- Create src/ibkr_mcp/connection.py and tests/test_connection.py (using FakeIB stubs from S5 — write the tests against pytest-mock for now, S5 will replace stubs with FakeIB).

Requirements:
- ConnectionManager wraps an ib_async.IB instance. Methods:
  - async connect() -> bool — calls ib.connectAsync(host, port, clientId), then ib.reqMarketDataType(<int per IB_MARKET_DATA_TYPE>), then resolves account_id (IB_ACCOUNT or ib.managedAccounts()[0]). Returns True/False; logs but never raises.
  - async disconnect()
  - property is_connected -> bool
  - property account_id -> str | None
  - property ib -> IB
- Map IB_MARKET_DATA_TYPE → int per ib_async docs (LIVE=1, FROZEN=2, DELAYED=3, DELAYED_FROZEN=4).

Tests cover:
- Successful connect resolves account_id from managed accounts when IB_ACCOUNT is unset.
- Successful connect uses IB_ACCOUNT when set and present in managedAccounts.
- IB_ACCOUNT not in managedAccounts → connect returns False, account_id is None, error logged.
- connectAsync raises → connect returns False, no exception bubbles.
- reqMarketDataType called with correct int.

Do NOT touch any other files.
```

### Step S5 — FakeIB Harness & Shared Fixtures

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Connection manager exists with stubbed tests.

Task:
- Create tests/fake_ib.py and tests/conftest.py.

Requirements (fake_ib.py):
- class FakeIB exposes the methods listed in implementation plan §S5 (isConnected, connectAsync, disconnectAsync, managedAccounts, accountSummaryAsync, reqPositionsAsync, reqTickersAsync, reqHistoricalDataAsync, reqContractDetailsAsync, reqOpenOrdersAsync, trades, positions, openOrders, reqSecDefOptParamsAsync, reqMarketDataType).
- Each method returns canned data from instance attributes (e.g., self._account_summary, self._positions). Async methods are awaitable.
- Helper builders: make_position(...), make_account_summary(...), make_ticker(...), make_historical_bar(...), make_trade(...).

Requirements (conftest.py):
- Fixture mock_ib() yields a fresh FakeIB.
- Fixture settings_factory() returns a Settings constructor accepting overrides.
- Fixture app_ctx(mock_ib, settings_factory) yields an AppContext built around the FakeIB, with account_id="U1234567" by default.
- Fixture mcp_with_tools(app_ctx) registers all tools and lets tests dispatch by name.

Replace the pytest-mock stubs in test_connection.py with FakeIB-driven tests. All tests must still pass.
```

### Step S6 — FastMCP Server, Lifespan & CLI

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- ConnectionManager and FakeIB exist.

Task:
- Create src/ibkr_mcp/server.py and src/ibkr_mcp/__main__.py and tests/test_server_bootstrap.py.

Requirements (server.py):
- @dataclass AppContext per §2.2 of the implementation plan.
- @asynccontextmanager async def lifespan(app: FastMCP) -> AsyncIterator[AppContext]:
    - Read Settings, build ConnectionManager, try await mgr.connect() inside try/except Exception.
    - Build AppContext with started_at=datetime.utcnow(), server_version=importlib.metadata.version("ibkr-mcp"), account_id from mgr, ib_lock=asyncio.Lock().
    - yield app_ctx; on teardown await mgr.disconnect().
- mcp = FastMCP("IBKR", lifespan=lifespan, streamable_http_path="/mcp").
- def register_all_tools(mcp, app_ctx_factory) — placeholder that subsequent steps will populate.

Requirements (__main__.py):
- argparse: --transport {stdio,streamable-http} (default from settings).
- def main(): load Settings, setup_logging, print spec §11 banner to stderr (success or warning variant), call mcp.run(transport=...). For streamable-http, pass host/port via FastMCP's settings (mcp.settings.host, mcp.settings.port).

Requirements (tests):
- test_server_bootstrap: monkeypatch ConnectionManager.connect to raise; assert lifespan still yields a valid AppContext with account_id is None and ib_lock is an asyncio.Lock; assert banner emitted to stderr contains "WARNING: Failed to connect".
- test_server_bootstrap: monkeypatch successful connect; assert banner contains "Connected to IB Gateway" and account id.
```

### Step S7 — Server Status Tool

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Server core, lifespan, and FakeIB harness exist.

Task:
- Create src/ibkr_mcp/models/server.py, src/ibkr_mcp/tools/server.py, tests/test_server_tools.py.

Requirements:
- ServerStatusResponse schema exactly per spec §6.2.
- tools/server.py:
    - async def get_server_status(ctx: Context) -> str. Docstring is the exact MCP description from spec §6.2.
    - Decorate with @tool_error_handler then @tool_call_logger (top-down).
    - Read app_ctx from ctx.request_context.lifespan_context.
    - Compute uptimeSeconds = (utcnow - started_at).total_seconds().
    - registeredTools = len(ctx.fastmcp._tool_manager._tools)  (or equivalent public API).
- def register(mcp, app_ctx_factory) -> None: mcp.tool()(get_server_status).
- Wire into server.register_all_tools.

Tests:
- Connected, disconnected, mid-connecting states.
- Uptime increases monotonically.
- All response fields populated and match schema.
```

### Step S8 — Account & Position Tools

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Server status tool registered.

Task:
- Create models/account.py, models/positions.py, tools/account.py, tests/test_account_tools.py.

Requirements:
- Schemas per spec §6.3, including option-specific fields (right, strike, expiry, multiplier) for OPT positions.
- get_account_info — uses ib.accountSummaryAsync(); maps tag/value pairs (NetLiquidation, etc.) to AccountInfoResponse; respects optional accountId.
- get_positions — uses ib.reqPositionsAsync(); optional accountId filter; emits option fields when secType=="OPT".
- Both tools decorated with @tool_error_handler + @tool_call_logger; both wrap their ib calls in `async with app_ctx.ib_lock`.
- Both check ib.isConnected() and short-circuit with IB_NOT_CONNECTED when false.
- register(mcp, app_ctx_factory) registers both. Hook into server.register_all_tools.

Tests:
- Disconnected → IB_NOT_CONNECTED for both.
- Mismatched accountId → IB_ACCOUNT_NOT_FOUND.
- OPT position emits all option fields.
- Account summary mapping covers all spec fields.
```

### Step S9 — Utility Modules

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- P0 account/position tools shipped.

Task:
- Create utils/contracts.py, utils/durations.py, tests/test_contracts_util.py, tests/test_duration_utils.py.

Requirements:
- build_contract(symbol, secType, exchange="SMART", currency="USD", expiry=None, strike=None, right=None) -> ib_async.Contract.
    - STK→Stock, OPT→Option (requires expiry, strike, right), FUT→Future, CASH→Forex, BOND→Bond, IND→Index.
    - Raises ValueError on invalid combos (e.g., OPT without strike).
- parse_duration(s) — translates ISO 8601 to IB-native exactly per spec §6.4 table; pass-through for valid IB strings; raises ValueError on garbage.

Tests cover every row of the spec table plus invalid inputs and every secType.
```

### Step S10 — Market Data Tools

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Utilities exist.

Task:
- Create models/market.py, tools/market.py, tests/test_market_tools.py.

Requirements:
- Schemas per spec §6.4 (equity vs. option Greeks variants).
- get_market_data: build_contract → await ib.qualifyContractsAsync(c) → await ib.reqTickersAsync(c). For options, extract Greeks in priority modelGreeks → lastGreeks → bidGreeks → askGreeks. Single snapshot — never subscribe to streaming.
- get_historical_data: parse_duration → await ib.reqHistoricalDataAsync(...). Returns HistoricalDataResponse.
- Both wrap ib calls in app_ctx.ib_lock; both decorated.
- IB_INVALID_CONTRACT for unresolvable contracts; IB_NO_MARKET_DATA when no permission.

Tests:
- Equity snapshot returns full fields.
- Option snapshot returns Greeks (modelGreeks priority verified by FakeIB toggle).
- Historical with both ISO 8601 and IB-native durations.
- Unresolvable contract → IB_INVALID_CONTRACT.
- Permission error → IB_NO_MARKET_DATA.
```

### Step S11 — Order Monitoring Tools

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Market tools shipped.

Task:
- Create models/orders.py, tools/orders.py, tests/test_order_tools.py.

Requirements:
- get_live_orders: list ib.openOrders() (refresh via ib.reqOpenOrdersAsync first); optional accountId filter.
- get_order_status: scan ib.trades() for matching orderId; pull status from trade.orderStatus; pull avgFillPrice and commission from trade.fills[*].commissionReport (sum commissions across fills); pull timestamps from trade.log entries.
- Both decorated; both lock around ib calls.
- Unknown orderId → make_error with VALIDATION_ERROR or a dedicated message.

Tests:
- Empty open orders.
- Filled order with two fills aggregates commission correctly.
- Unknown orderId returns structured error.
- Account-id filter excludes other accounts.
```

### Step S12 — Contract Details Tool

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All P0 tools shipped.

Task:
- Create tools/contracts.py, tests/test_contract_tools.py.

Requirements:
- get_contract_details: build_contract → await ib.reqContractDetailsAsync(c). Map first ContractDetails to spec §6.6 schema. For OPT, populate strike/right/expiry/multiplier/lastTradeDate from the resolved contract.
- Decorated; locks around ib call.
- Empty result list → IB_INVALID_CONTRACT.

Tests:
- STK lookup populates primaryExchange, longName, industry.
- OPT lookup populates option-specific fields.
- Empty resolution → IB_INVALID_CONTRACT.
```

### Step S13 — Flex Query Tools (Conditional)

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All P0/P1 tools shipped except flex.

Task:
- Create tools/flex.py, tests/test_flex_tools.py.

Requirements:
- list_flex_queries and get_flex_query both use ib_async.FlexReport directly with settings.IB_FLEX_TOKEN. They must NOT require ib.isConnected() and must NOT take ib_lock.
- get_flex_query accepts queryId xor queryName, plus optional topic. Uses FlexReport.extract(topic). On extraction failure returns the raw XML with parsed=false.
- Token errors and HTTP errors → IB_FLEX_ERROR.
- register(mcp, app_ctx_factory): registers both ONLY when settings.IB_FLEX_TOKEN is set (read from app_ctx.settings inside register).

Tests:
- Flex tools registered only when token set.
- Bad token → IB_FLEX_ERROR.
- Topic filter narrows result.
- Parse failure returns raw XML with parsed=false.
- Tools work even with FakeIB.isConnected()==False.
```

### Step S14 — Option Chain Tool

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All P1 tools shipped.

Task:
- Extend tools/market.py with get_option_chain; add tests in tests/test_market_tools.py.

Requirements:
- Without expiry: discovery only via ib.reqSecDefOptParamsAsync(symbol, ...). Return exchanges, expirations, strikes, multiplier. MUST NOT issue per-contract requests (spec §6.8 rate-limit note — enforce via test).
- With expiry: enumerate strikes for the given expiry/right, build contracts in batch, await ib.reqTickersAsync(*contracts). Emit per-strike data with Greeks.

Tests:
- Discovery output shape matches spec.
- With-expiry output shape matches spec.
- Verify FakeIB records zero per-contract calls in discovery mode.
```

### Step S15 — Portfolio Greeks with Black-Scholes Fallback

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Option chain shipped.

Task:
- Create utils/black_scholes.py, extend tools/account.py with get_portfolio_greeks, add tests/test_portfolio_greeks.py.

Requirements (black_scholes.py):
- Pure-Python implementations of delta, gamma, theta, vega for European calls/puts using math.erf-based normal CDF/PDF (no scipy).
- def fallback_greeks(option_position, underlying_price, iv, risk_free_rate=0.0) -> dict.

Requirements (tool):
- Iterate OPT positions, prefer ib.modelGreeks; fall back to fallback_greeks(...) when modelGreeks is missing and last IV is known. Aggregate totals; emit per-position breakdown per spec §6.8.
- Decorated; locks around any ib calls.

Tests:
- BS implementation matches reference values for a known case (within 1e-4).
- Aggregation: 3 positions, mixed model/fallback Greeks.
- All-stock portfolio yields zero option Greeks.
```

### Step S16 — `get_alerts` Placeholder

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All other tools shipped.

Task:
- Create models/alerts.py and extend tools/orders.py with get_alerts. Add tests/test_alerts_tool.py.

Requirements:
- models/alerts.py: Alert, AlertCondition, AlertsResponse schemas per spec §6.8.
- get_alerts always returns make_error(ErrorCode.NOT_IMPLEMENTED, "get_alerts requires feasibility validation against ib_async; see spec §6.8.").
- Tool docstring is the exact MCP description from spec §6.8.

Tests:
- Tool registered.
- Returns NOT_IMPLEMENTED JSON.
- Schemas in models/alerts.py validate sample data from spec.
```

### Step S17 — Final Hardening

```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All tools shipped.

Task:
- Final polish: tree audit, integration smoke tests, README.

Requirements:
- Verify on-disk tree exactly matches spec §8 (every file listed exists; no extras besides this implementation plan).
- Add tests/test_integration.py with @pytest.mark.integration smoke tests covering get_server_status and get_account_info against a real paper account (skipped in CI).
- Confirm `mcp.run(transport="streamable-http")` exposes /mcp and matches the spec §16.3 client config.
- Run full local CI gate: ruff check, ruff format --check, mypy --strict src/, pytest tests/ -m "not integration" --cov=ibkr_mcp.
- Optional: README.md only if explicitly requested.
```

---

## 6. Key Decisions Recap

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tool registration | Per-module `register(mcp, app_ctx_factory)` functions | Avoids circular imports between `tools/*` and `server.py` |
| Cross-cutting concerns | Two decorators (`@tool_error_handler`, `@tool_call_logger`) applied to every tool | Keeps each tool focused; centralises error mapping and §12.3 logging |
| Lifespan | Yields a typed `AppContext` (settings, ib, started_at, account_id, server_version, ib_lock) | Survives connection failure; gives tools typed access |
| Concurrency | `asyncio.Lock` around ib_async calls inside `AppContext` | Streamable HTTP serves multiple clients on one IB instance |
| Snapshot semantics | `reqTickersAsync` for `get_market_data` | Stateless, no subscription leaks |
| Greeks priority | `modelGreeks` → `lastGreeks` → `bidGreeks` → `askGreeks` | Most stable to most volatile |
| Market data type | Set once in `connection.py` post-connect | Avoids per-tool repetition |
| Flex tools | Independent of IB connection; conditional registration | Spec §6.7 |
| Default port | `4002` (paper) | Matches `IB_PAPER_TRADING=true` default; corrects spec contradiction |
| Pandas | Removed from dependencies | `ib_async.util.df()` is convenience-only; we serialise via Pydantic |
| BS fallback | Pure-Python via `math.erf`, no scipy | Keeps dependency tree minimal per spec §1.2 |
| Testing cadence | Tests land in the same step as the code | Avoids the prior plan's back-loading of test infrastructure |
