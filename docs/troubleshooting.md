# Troubleshooting

This page collects the issues we've actually hit in development, mapped to their fixes.

---

## 1. Connection problems

### `IB_NOT_CONNECTED` on every call

Symptoms:

```json
{ "code": "IB_NOT_CONNECTED", "error": "Not connected to IB Gateway." }
```

Checklist:

1. **Is IB Gateway / TWS actually running and logged in?** A locked terminal session, an expired auto-login, or a daily forced logout will all break the gateway silently. Check the IB Gateway window.
2. **Are `IB_HOST` and `IB_PORT` correct?** Cross-check the [port table](configuration.md#ib-gateway--tws-port-reference). Default `4002` is **paper IB Gateway**; live is `4001`; TWS uses `7496`/`7497`.
3. **Is the API enabled inside Gateway/TWS?** *Configure → Settings → API → Settings*: tick **Enable ActiveX and Socket Clients**, untick **Read-Only API** (this is needed even though we're read-only — IB's terminology is misleading; their "Read-Only API" disables a different subset of calls).
4. **Are trusted IPs configured?** Same dialog: `127.0.0.1` (or the Docker bridge IP) must be in **Trusted IPs**. The default reject behaviour is silent.
5. **Is your `IB_CLIENT_ID` already in use?** If another tool (a manual script, another MCP server instance) connected first with the same ID, the gateway will boot the older connection and the new one will hang. Use a unique ID.
6. **Does the startup banner say `WARNING: Failed to connect`?** That confirms the failure happened at boot — fix the gateway and restart the server.

### `IB_CONNECTION_FAILED` at startup

Same root causes as above. Look at the structured log line `event=ib_connect_failed` for the underlying exception (usually `ConnectionRefusedError`).

### Connection drops every night

IB forces gateway logout daily at ~01:00 ET. `ib_async` will retry the underlying socket and the server self-heals once the gateway is back up. To minimise impact:

- Use [IBC](https://github.com/IbcAlpha/IBC) to auto-restart the gateway on schedule.
- Watch `get_server_status.status` from a health check.

---

## 2. Market-data problems

### `IB_NO_MARKET_DATA`

```json
{ "code": "IB_NO_MARKET_DATA", "error": "No market data returned for 'AAPL'." }
```

Causes, in rough order of likelihood:

1. **No live data subscription.** `IB_MARKET_DATA_TYPE=LIVE` is the default; if you don't have an IBKR market-data subscription for the instrument, IB returns nothing. Try `IB_MARKET_DATA_TYPE=DELAYED` (15-minute delayed; usually free for US equities).
2. **Out of regular trading hours and the symbol has no after-hours data.** Try during RTH or use historical bars instead of a snapshot.
3. **Instrument not actively traded today.** Holidays, halts, etc.

### Snapshot returns `null` for `lastPrice`

That symbol has no recent trades (e.g. illiquid options after market close). The bid/ask may still populate.

### Greeks all `null` for an option

The gateway does not always populate `modelGreeks` immediately. `get_market_data` walks `modelGreeks → lastGreeks → bidGreeks → askGreeks` and picks the first usable bundle. If all four are empty, you'll see `delta`/`gamma`/etc. omitted (`exclude_none=True` strips them).

For a portfolio aggregation, `get_portfolio_greeks` falls back to Black-Scholes when an IV is known. If even IV is missing, the position is marked `source: "missing"`.

---

## 3. Contract problems

### `IB_INVALID_CONTRACT`

```json
{ "code": "IB_INVALID_CONTRACT", "error": "Could not qualify contract for 'AAPL' ('STK')." }
```

1. **Symbol format.** IB uses its own conventions (`BRK B`, not `BRK.B`). When in doubt, run `get_contract_details` first; if that fails too, the symbol is the problem.
2. **Wrong sec type.** Looking up `BRK B` as `IND` instead of `STK`, or `EUR` as `STK` instead of `CASH`.
3. **Option requires `expiry` + `strike` + `right`.** All three are needed. `strike` is a float (`150.0`, not `150`).
4. **Future requires `expiry`.**
5. **Forex (`CASH`) uses `IDEALPRO`** by default and `currency` is the quote currency; `symbol` is the base.

### `get_option_chain` with expiry returns `IB_INVALID_CONTRACT`

The expiry isn't in the underlying's chain. Run discovery mode first (omit `expiry`) and use one of the values from `expirations`.

---

## 4. Account problems

### `IB_ACCOUNT_NOT_FOUND`

```json
{ "code": "IB_ACCOUNT_NOT_FOUND", "error": "Account 'U9999999' is not linked to this Gateway connection (managed accounts: ['U1234567'])." }
```

The `accountId` you passed isn't in `ib.managedAccounts()`. Either:

- Drop the `accountId` argument to use the default, **or**
- Connect with a gateway that has access to that account.

### `IB_ACCOUNT` rejected at startup

If `IB_ACCOUNT` is set to an account that isn't linked, the server **disconnects immediately** rather than serving the wrong account. This is intentional. Fix the env var and restart.

### Wrong account being used by default

If `IB_ACCOUNT` is unset and the gateway is linked to multiple accounts, the **first** managed account wins. Set `IB_ACCOUNT` explicitly.

---

## 5. Flex query problems

### `IB_FLEX_ERROR: IB_FLEX_TOKEN is not configured`

Set the token. After setting, you'll need to **restart the server**: tool registration is decided at startup based on whether `IB_FLEX_TOKEN` is set, not per-call.

### `IB_FLEX_ERROR: 1019: Invalid token`

The IB Flex Web Service rejected the token. Verify in IB Account Management → Reporting → Flex Queries → Settings.

### `VALIDATION_ERROR: queryName 'X' is not configured in IB_FLEX_QUERIES`

Either pass `queryId` directly, or add the query to `IB_FLEX_QUERIES`:

```bash
IB_FLEX_QUERIES='[{"queryId":"12345","queryName":"X"}]'
```

### Tool returns `parsed: false` and a raw XML payload

`FlexReport.extract` raised on the parsed XML. The raw XML is returned so you can investigate / parse it yourself. This usually means:

- The query has zero rows for the period.
- The query type isn't one of the standard topics ib_async knows about.
- IB returned an error envelope instead of report data — inspect the XML.

### Flex tools missing entirely

If `list_flex_queries` and `get_flex_query` aren't in the tool list, `IB_FLEX_TOKEN` is unset. They are **conditionally registered**. Set the token and restart.

---

## 6. Ordering / status problems

### `get_order_status` returns `VALIDATION_ERROR` for a known order

```json
{ "code": "VALIDATION_ERROR", "error": "Order 1001 not found in this session." }
```

`ib.trades()` only contains orders that the *current* MCP-server connection has seen. Orders placed via TWS UI or another client may not be reflected until the gateway pushes them through. `get_live_orders` calls `reqOpenOrdersAsync()` first, which usually triggers the push for open orders. For historical (filled/cancelled) orders, the API exposes them only for the lifetime of the session that placed them.

### `get_live_orders` returns nothing despite open orders in TWS

Same root cause. As a workaround, call `get_live_orders` immediately after a connection is established — that triggers a fresh fetch.

---

## 7. Configuration & startup problems

### `pydantic.ValidationError` on startup

A required env var is malformed. Common offenders:

- `IB_PORT` set to a non-integer or out of `1..65535`.
- `IB_MARKET_DATA_TYPE` not in `{LIVE, FROZEN, DELAYED, DELAYED_FROZEN}` (case-sensitive!).
- `MCP_TRANSPORT` not in `{stdio, streamable-http}` (lower-case + hyphen).

### Settings change isn't taking effect

`Settings()` reads env vars **once** at process start. After editing `.env` or your shell exports, you must **restart the server**.

### `LOG_FORMAT=console` is unreadable

`console` colours its output via TTY detection. If the server's stderr is being piped to a file or systemd's journal, the colour codes will appear as escape sequences. Switch to `LOG_FORMAT=json` for those environments.

### `LOG_TOOL_CALLS=true` floods my logs

That's expected at high RPS. Either disable it again or filter out `event=tool_call` events at the log aggregator. We've kept the per-call channel separate from connection / lifecycle events so it can be filtered cleanly.

---

## 8. Performance / latency problems

### `get_option_chain` with expiry takes seconds

It builds and snapshots one contract per `(strike, right)` combination. For a popular underlying that's ~100 contracts. The call is bounded by the gateway's per-request latency, not the server. If you only need calls or only puts, pass `right="C"` or `"P"` to halve the work.

### Multi-client requests are serialised

The `ib_lock` serialises every gateway call. If two clients each ask for `get_market_data` at the same time, one will wait for the other. This is by design — `ib_async`'s socket is not safe for concurrent use. If you need higher throughput, run multiple server instances against multiple `IB_CLIENT_ID`s.

---

## 9. Development / testing problems

### Tests fail with `ImportError: ib_async`

Run `uv sync` (or `pip install -e .[dev]`) to install dependencies into the venv.

### `pytest` runs the integration test against a live gateway

It shouldn't — `pyproject.toml` has `addopts = ["-m", "not integration"]` excluded by default? Actually no — the integration file uses `pytest.skip(allow_module_level=True)` unless `IBKR_MCP_INTEGRATION=1` is set, **and** the marker filter is applied via `-m "not integration"` in CI. To run it locally:

```bash
IBKR_MCP_INTEGRATION=1 uv run pytest tests/test_integration.py -m integration -v
```

### `mypy --strict` fails after edits

Common causes: untyped functions, missing return types, untyped third-party calls. The `pyproject.toml` already configures `ignore_missing_imports` for `ib_async.*` and `mcp.*`, but new dependencies may need their own override block.

### `ruff check` complains about `N803` / `N815`

Tool & model files mirror IBKR's camelCase. Per-file ignores are configured for `src/ibkr_mcp/{models,tools,utils}/*.py` and `tests/**/*.py`. If you're editing one of those, the existing override should cover you. If you're adding a new file, ensure it lands in one of those directories or add an explicit override.

---

## 10. When all else fails

1. **Read the structured logs.** Set `LOG_LEVEL=DEBUG` and `LOG_FORMAT=console`; the `event` field tells you exactly which step failed.
2. **Inspect the gateway log** at `~/Jts/launcher.log` (Linux) or the gateway's UI → "Display API messages…".
3. **Run with `LOG_TOOL_CALLS=true`** to see input args and timing for each call.
4. **Try `get_server_status` and `get_contract_details` first.** They isolate whether the problem is connection, contract resolution, or data permissions.
5. **Open an issue** with the redacted log output, the env config (no token!), and the failing tool input.
