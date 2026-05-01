# Development Guide

Everything you need to hack on the server: repo layout, the in-memory `FakeIB` test harness, the CI gate, and conventions for adding new tools.

---

## 1. Setup

```bash
git clone https://github.com/<org>/ibkr-mcp.git
cd ibkr-mcp
uv sync               # installs runtime + dev dependencies into .venv
cp .env.template .env # adjust as needed
```

`uv sync` reads the lock file, so everyone gets the same versions. The dev dependency group (`pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`, `ruff`, `mypy`) is included automatically when `[project.optional-dependencies].dev` is present.

---

## 2. Running the test suite

```bash
# Unit tests only (default — skips integration tests)
uv run pytest

# Verbose with the test names
uv run pytest -v

# A specific module
uv run pytest tests/test_market_tools.py -v

# A specific test
uv run pytest tests/test_market_tools.py::TestGetMarketData::test_equity_snapshot -v

# With coverage report
uv run pytest --cov=ibkr_mcp --cov-report=term-missing

# Integration tests (requires a real IB Gateway and an opt-in env var)
IBKR_MCP_INTEGRATION=1 uv run pytest -m integration -v
```

The integration tests are deliberately ring-fenced: they're skipped at module level unless `IBKR_MCP_INTEGRATION=1` is set, **and** filtered out by `pyproject.toml` so a vanilla `pytest` run never hits them.

---

## 3. Linting, formatting, type-checking

The CI gate runs four commands. Any one failing will block a merge.

```bash
uv run ruff check src/ tests/        # lint
uv run ruff format --check src/ tests/  # formatting check
uv run ruff format src/ tests/       # auto-format
uv run mypy src/                     # strict type-checking
```

Convenience: a single composed command (matches what CI does):

```bash
uv run ruff check src/ tests/ \
  && uv run ruff format --check src/ tests/ \
  && uv run mypy src/ \
  && uv run pytest -m "not integration" --cov=ibkr_mcp
```

### Per-file ignores worth knowing about

`pyproject.toml` defines per-file rule overrides because IBKR's API uses camelCase identifiers that ruff's `pep8-naming` rules dislike. These are intentional:

```toml
"tests/**/*.py" = ["N802", "N803", "N815"]
"src/ibkr_mcp/models/*.py" = ["N815"]   # camelCase JSON fields
"src/ibkr_mcp/tools/*.py"  = ["N803", "N815"]  # camelCase params + fields
"src/ibkr_mcp/utils/*.py"  = ["N803"]   # build_contract(secType=..., …)
```

If you add a file outside these directories that needs camelCase, prefer adding an explicit per-file override over `# noqa` comments.

---

## 4. Repo layout

```
src/ibkr_mcp/
├── __init__.py             # exposes __version__
├── __main__.py             # CLI entry: --transport, banner, probe-connect
├── server.py               # AppContext, build_lifespan, build_mcp, register_all_tools
├── config.py               # Pydantic Settings + structlog setup
├── connection.py           # ConnectionManager wrapping ib_async.IB
├── errors.py               # ErrorCode enum, make_error, map_exception
├── logging_decorators.py   # @tool_error_handler, @tool_call_logger
├── models/                 # Pydantic schemas (camelCase)
│   ├── server.py
│   ├── account.py
│   ├── positions.py        # PositionItem, PortfolioGreekItem, ...
│   ├── market.py           # MarketDataResponse, HistoricalBar, OptionChain*
│   ├── orders.py
│   ├── contracts.py
│   ├── flex.py
│   └── alerts.py
├── tools/                  # async tool functions + per-module register()
│   ├── server.py           # get_server_status
│   ├── account.py          # get_account_info, get_positions, get_portfolio_greeks
│   ├── market.py           # get_market_data, get_historical_data, get_option_chain
│   ├── orders.py           # get_order_status, get_live_orders, get_alerts
│   ├── contracts.py        # get_contract_details
│   └── flex.py             # list_flex_queries, get_flex_query
└── utils/
    ├── contracts.py        # build_contract for STK/OPT/FUT/CASH/BOND/IND
    ├── durations.py        # ISO 8601 → IB-native translation
    └── black_scholes.py    # pure-Python Greeks fallback

tests/
├── fake_ib.py              # FakeIB harness + builders (FakeContract, FakeTicker, ...)
├── conftest.py             # shared fixtures (mock_ib, settings_factory, ...)
├── test_*.py               # one file per source module (mostly)
└── test_integration.py     # @pytest.mark.integration smoke tests (opt-in)
```

---

## 5. The `FakeIB` test harness

Every unit test in this project talks to a `FakeIB` instance that lives entirely in memory — no socket, no IB Gateway, no live data. This is the single biggest reason the test suite is fast and deterministic.

`tests/fake_ib.py` exposes:

- **`FakeIB`** — a stand-in for `ib_async.IB`. Every method touched by the tools is implemented and driven by mutable per-test attributes (`fake_ib.account_summary = [...]`, `fake_ib.tickers = [...]`, etc.).
- **Builder helpers** — `make_account_summary`, `make_stock_position`, `make_option_position`.
- **Fake data classes** — `FakeContract`, `FakeTicker`, `FakeGreeks`, `FakeHistoricalBar`, `FakeOrder`, `FakeOrderStatus`, `FakeFill`, `FakeCommissionReport`, `FakeTradeLogEntry`, `FakeTrade`, `FakeOptionChain`, `FakeContractDetails`.

### Building a tool-test context

Every tool-test file has a small `_make_ctx(fake_ib, settings)` helper that wires up an `AppContext` around the `FakeIB`. The pattern is:

```python
fake_ib.connected = True
fake_ib.tickers = [FakeTicker(last=150.50, bid=150.48, ask=150.52)]
ctx = _make_ctx(fake_ib, settings_factory())

payload = json.loads(await get_market_data(ctx, symbol="AAPL", secType="STK"))
assert payload["lastPrice"] == 150.50
```

### Mocking individual ib_async methods

For one-off behaviours (e.g. asserting that a method is called once), `pytest-mock` and direct `monkeypatch.setattr` both work:

```python
async def empty_qualify(*_a, **_kw):
    return []

monkeypatch.setattr(fake_ib, "qualifyContractsAsync", empty_qualify)
```

The Flex query tests also patch the **module-level** download function so HTTPS traffic is never attempted:

```python
monkeypatch.setattr(
    "ibkr_mcp.tools.flex._download_blocking",
    lambda token, query_id: _FakeReport(topics_data={"Trade": []}),
)
```

---

## 6. Adding a new tool

1. **Pick the right module.** New tools go into the existing `tools/*.py` module that matches the topic. Don't create a new module unless you're adding a new top-level area (e.g. "futures-only" tooling).
2. **Define the response model** in `src/ibkr_mcp/models/<topic>.py`. Use `populate_by_name=True` and camelCase field names (mirror the spec / IB API).
3. **Write the tool.**

   ```python
   from mcp.server.fastmcp import Context, FastMCP

   from ibkr_mcp.errors import ErrorCode, make_error
   from ibkr_mcp.logging_decorators import tool_call_logger, tool_error_handler
   from ibkr_mcp.server import AppContext

   @tool_error_handler
   @tool_call_logger
   async def my_new_tool(
       ctx: Context,  # type: ignore[type-arg]
       symbol: str,
   ) -> str:
       """One-line MCP description copied verbatim from spec.md."""
       app_ctx: AppContext = ctx.request_context.lifespan_context
       if not app_ctx.manager.is_connected:
           return make_error(ErrorCode.IB_NOT_CONNECTED, "Not connected to IB Gateway.")

       async with app_ctx.ib_lock:
           result = await app_ctx.manager.ib.someAsync(symbol)

       return MyResponseModel.model_validate(result).model_dump_json(exclude_none=True)
   ```

4. **Append to `register(mcp)`** in the same module.
5. **Write paired tests** in `tests/test_<topic>.py`. Use `_make_ctx` and `FakeIB`.
6. **Run the CI gate** locally; fix any lint/type issues.
7. **Update `docs/usage.md`** with the new tool's input/output and error semantics.

### Conventions, in order of importance

1. **Always return a JSON string.** Never raise across the MCP boundary; the decorators catch it but explicit is better.
2. **Always check `is_connected` first** for tools that hit the gateway.
3. **Always wrap gateway calls in `app_ctx.ib_lock`** unless you're hitting Flex Web Service or reading a cached method.
4. **Always serialise with `exclude_none=True`** so optional fields don't bloat the wire payload.
5. **Docstrings are MCP-visible.** Make them user-facing prose; the spec's "MCP Description" is the canonical text.
6. **Don't import `Settings()` inside a tool.** Read everything from `app_ctx`.

---

## 7. Adding a new error code

1. Append to `errors.ErrorCode`.
2. Optionally add a substring rule to `errors._MESSAGE_HINTS` so `map_exception` picks it up automatically.
3. Document it in `docs/usage.md` and `docs/architecture.md` (§7).

---

## 8. Modifying the connection lifecycle

`connection.py:ConnectionManager` is small on purpose. The key invariants:

- `connect()` **never raises** — it returns a `bool`.
- After a successful connect, `reqMarketDataType` is applied **once** for the lifetime of the connection. Tools never re-issue this call.
- Account resolution happens once, after market-data-type. If the user-requested account isn't in `managedAccounts()`, we disconnect to fail loud.
- `disconnect()` is idempotent.

`server.py:build_lifespan` wraps `connect()` in `try/except` for defence in depth. If you change the connection logic, please preserve the never-raise invariant — the lifespan **must** always yield an `AppContext` even when the gateway is unreachable.

---

## 9. CI

`.github/workflows/ci.yml`:

```yaml
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy src/
      - run: uv run pytest tests/ -m "not integration" --cov=ibkr_mcp --cov-report=term-missing
```

If a check fails locally, it will fail in CI. Run the gate locally before pushing.

---

## 10. Philosophy / what NOT to do

- **Don't add streaming tools.** Streaming is out of scope for v0.1 (see [spec §14](../specs/spec.md)).
- **Don't add order-placement tools.** This server is read-only by contract. If you need writes, run a separate process.
- **Don't add a cache.** Stateless-by-design — every call goes to IB. Caching has to consider data freshness and is intentionally deferred.
- **Don't import `pandas` or `scipy`.** The dependency tree is curated; both have been deliberately rejected. `pandas` because `ib_async.util.df()` is a convenience helper and we serialise via Pydantic; `scipy` because Black-Scholes via `math.erf` is small and dependency-free.
- **Don't create circular imports.** `tools/*.py` imports from `models/`, `errors`, `logging_decorators`, and `server.AppContext` — but **never** the bound `mcp` instance. `server.register_all_tools` is the only place that knows about every tool module, and it imports them lazily.

---

## 11. Releasing

1. Bump `[project].version` in `pyproject.toml`.
2. Bump `__version__` in `src/ibkr_mcp/__init__.py`.
3. Update relevant docs (especially the "Status & roadmap" section of the README).
4. Tag the commit: `git tag v0.x.y && git push --tags`.
5. (When ready) `uv build && uv publish`.

The version is exposed at runtime via `get_server_status.serverVersion` and on the startup banner.
