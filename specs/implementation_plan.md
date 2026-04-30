## 1. Project Blueprint

- **Milestone 1: Project Initialization & Configuration**
  - **Goal:** Establish the Python project skeleton, dependency management, and environment-based configuration.
  - **Components:** `pyproject.toml`, standard directory structure, and configuration models.
  - **Artifacts:** A buildable, empty `uv`-compatible project and a robust `config.py` module.
- **Milestone 2: Connection Lifecycle & Server Core**
  - **Goal:** Implement the `ib_async` connection logic and the `FastMCP` server application shell with a lifespan context.
  - **Components:** `connection.py`, `server.py`, `__main__.py`.
  - **Artifacts:** An executable MCP server that connects to IB Gateway and supports both stdio and HTTP transports.
- **Milestone 3: Server Status & Account Portfolio Tools (P0)**
  - **Goal:** Implement foundational tools to check server status, account information, and open positions.
  - **Components:** `models/server.py`, `models/account.py`, `tools/server.py`, `tools/account.py`.
  - **Artifacts:** Working, registered `get_server_status`, `get_account_info`, and `get_positions` tools.
- **Milestone 4: Market Data & Order Monitoring Tools (P0)**
  - **Goal:** Implement real-time quotes, historical data fetching, and order tracking, backed by reusable utility functions.
  - **Components:** `utils/contracts.py`, `utils/durations.py`, `models/market.py`, `models/orders.py`, `tools/market.py`, `tools/orders.py`.
  - **Artifacts:** Registered `get_market_data`, `get_historical_data`, `get_order_status`, and `get_live_orders` tools.
- **Milestone 5: Reference Data & Flex Query Tools (P1)**
  - **Goal:** Provide contract lookup capabilities and conditional execution of IBKR Flex Queries.
  - **Components:** `tools/contracts.py`, `tools/flex.py`.
  - **Artifacts:** Registered `get_contract_details`, `list_flex_queries`, and `get_flex_query` tools (conditionally loaded).
- **Milestone 6: Deferred Tools (P2) & Test Infrastructure**
  - **Goal:** Implement the remaining advanced tools and establish an offline testing framework.
  - **Components:** Deferred tool logic, `tests/fake_ib.py`, `tests/conftest.py`, `tests/test_server_tools.py`.
  - **Artifacts:** Registered options chains, Greeks, and alerts tools, plus a mock IB client for CI testing.

---

## 2. Refined Implementation Steps

- **S1 (Milestone 1): Package Structure & Dependencies.** Objective: Create the `pyproject.toml` and base package tree. Main changes: Add project metadata, entry points, dependencies (`mcp`, `ib_async`, `pydantic-settings`, etc.), and empty `__init__.py` files. Dependencies: None.
- **S2 (Milestone 1): Configuration & Logging.** Objective: Implement Pydantic `BaseSettings` and configure `structlog`. Main changes: Create `src/ibkr_mcp/config.py` for env vars and set up structured JSON/console logging. Dependencies: S1.
- **S3 (Milestone 2): Connection Management.** Objective: Build the `ib_async` connection logic. Main changes: Create `src/ibkr_mcp/connection.py` to handle connect, disconnect, and connection state checks with retries. Dependencies: S2.
- **S4 (Milestone 2): FastMCP Server Skeleton.** Objective: Set up the MCP server, lifespan, and CLI entry point. Main changes: Create `src/ibkr_mcp/server.py` with a FastMCP instance and lifespan context. Create `src/ibkr_mcp/__main__.py` to parse args and run the server (stdio or streamable-http). Dependencies: S2, S3.
- **S5 (Milestone 3): Error Handling & Status Tool.** Objective: Define standard JSON error formats and the server status tool. Main changes: Create `models/server.py` and `tools/server.py` (`get_server_status`). Register it in `server.py`. Dependencies: S4.
- **S6 (Milestone 3): Account & Position Tools.** Objective: Implement account info and position list tools. Main changes: Create `models/account.py`, `models/positions.py`, and `tools/account.py` (`get_account_info`, `get_positions`). Register in `server.py`. Dependencies: S5.
- **S7 (Milestone 4): Utility Modules.** Objective: Build helpers for contract construction and duration translation. Main changes: Create `utils/contracts.py` to map schemas to `ib_async.Contract` objects, and `utils/durations.py` to convert ISO 8601 to IB-native durations. Dependencies: S4.
- **S8 (Milestone 4): Market Data Tools.** Objective: Implement real-time quotes and historical data tools. Main changes: Create `models/market.py` and `tools/market.py` (`get_market_data`, `get_historical_data`) utilizing S7 utils. Register in `server.py`. Dependencies: S6, S7.
- **S9 (Milestone 4): Order Monitoring Tools.** Objective: Implement tools to check order status and list live orders. Main changes: Create `models/orders.py` and `tools/orders.py` (`get_order_status`, `get_live_orders`). Register in `server.py`. Dependencies: S8.
- **S10 (Milestone 5): Contract Reference & Flex Queries.** Objective: Implement contract lookups and conditionally register Flex tools. Main changes: Create `tools/contracts.py` and `tools/flex.py`. Update `server.py` to only register flex tools if `IB_FLEX_TOKEN` is present in config. Dependencies: S9.
- **S11 (Milestone 6): Deferred Tools (P2).** Objective: Add advanced options and alerts tools. Main changes: Implement `get_option_chain`, `get_portfolio_greeks`, and `get_alerts` in existing modules and register them. Dependencies: S10.
- **S12 (Milestone 6): FakeIB Test Infrastructure.** Objective: Build an offline test harness. Main changes: Create `tests/fake_ib.py` mocking `ib_async.IB`, a fixture in `conftest.py`, and a basic unit test in `test_server_tools.py` verifying everything wires up correctly. Dependencies: S11.

---

## 3. Code-Generation Prompt Pack

### Step S1 — Package Structure & Dependencies
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- We are starting a new project: `ibkr-mcp`, a read-only Model Context Protocol (MCP) server that connects to Interactive Brokers via `ib_async`.
- No code exists yet.

Task:
- Create the standard Python project structure and `pyproject.toml` as defined in the spec.

Requirements:
- Create `pyproject.toml` using standard `project` metadata (compatible with `uv`).
- Define the project name as `ibkr-mcp`, version `0.1.0`, Python `>=3.12`.
- Required dependencies: `mcp[cli]>=1.9.0`, `ib_async>=0.9.86`, `pydantic>=2.0.0`, `pydantic-settings>=2.0.0`, `python-dotenv>=1.0.0`, `structlog>=24.0.0`, `pandas>=2.0.0`.
- Optional dev dependencies: `pytest>=8.0.0`, `pytest-asyncio>=0.24.0`, `pytest-mock>=3.14.0`, `ruff>=0.8.0`, `mypy>=1.13.0`, `pandas-stubs>=2.0.0`.
- Create a `[project.scripts]` entry point: `ibkr-mcp = "ibkr_mcp.__main__:main"`.
- Create the directory structure: `src/ibkr_mcp/`, `src/ibkr_mcp/models/`, `src/ibkr_mcp/tools/`, `src/ibkr_mcp/utils/`, and `tests/`. Add empty `__init__.py` files to each source folder.

Output:
- The contents of `pyproject.toml` and shell commands (or script) to create the folder structure.
- A short note summarizing what changed.
```

### Step S2 — Configuration & Logging
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Project structure and dependencies (including `pydantic-settings` and `structlog`) are set up.

Task:
- Create the configuration management module and logging setup.

Requirements:
- Create `src/ibkr_mcp/config.py`.
- Define a Pydantic `BaseSettings` class named `Settings` that loads from environment variables (and `.env` file).
- Include variables: `IB_HOST` (127.0.0.1), `IB_PORT` (4001), `IB_CLIENT_ID` (1), `IB_ACCOUNT` (optional str), `IB_PAPER_TRADING` (true), `IB_FLEX_TOKEN` (optional str), `IB_MARKET_DATA_TYPE` (LIVE), `MCP_TRANSPORT` (streamable-http), `MCP_HTTP_HOST` (127.0.0.1), `MCP_HTTP_PORT` (8400), `LOG_LEVEL` (INFO), `LOG_FORMAT` (json), `LOG_TOOL_CALLS` (false).
- Create a `setup_logging(settings: Settings)` function in `config.py` that configures `structlog`. Use JSON rendering if `LOG_FORMAT` is 'json', else console rendering. Set the global log level based on `LOG_LEVEL`.

Output:
- The new `src/ibkr_mcp/config.py` file.
- A short note summarizing what changed.
```

### Step S3 — IBKR Connection Manager
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- `config.py` is available with connection parameters.
- We need to establish the async connection to IB Gateway using `ib_async`.

Task:
- Implement the connection management module.

Requirements:
- Create `src/ibkr_mcp/connection.py`.
- Create a `ConnectionManager` class that wraps `ib_async.IB`.
- Implement async methods to `connect()`, `disconnect()`, and a property `is_connected`.
- `connect()` should use `settings.IB_HOST`, `settings.IB_PORT`, and `settings.IB_CLIENT_ID`.
- Handle `ib_async` exceptions cleanly, returning a boolean or logging errors via `structlog` rather than crashing. The spec mandates the server should stay alive even if the initial IB connection fails.
- Do NOT rewrite `config.py`. Simply import it.

Output:
- The new `src/ibkr_mcp/connection.py` file.
- A short note summarizing what changed.
```

### Step S4 — FastMCP Server & CLI Entry Point
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- We have configuration and an IB connection manager.
- We need the core MCP server application.

Task:
- Implement `server.py` with FastMCP and `__main__.py` to run it.

Requirements:
- Create `src/ibkr_mcp/server.py`. Import `FastMCP` from `mcp.server.fastmcp`.
- Create an `@asynccontextmanager` lifespan function that initializes `ConnectionManager`, calls `connect()`, yields the `IB` client instance to the server context, and calls `disconnect()` on exit.
- Instantiate `FastMCP("IBKR", lifespan=lifespan)`.
- Create `src/ibkr_mcp/__main__.py`. It should import the `FastMCP` app, parse CLI arguments (e.g., `--transport`), read settings from `config.py`, and run the server. If transport is `stdio`, use `mcp.run()`. If `streamable-http`, use the appropriate FastMCP HTTP serving mechanism bound to `MCP_HTTP_HOST` and `MCP_HTTP_PORT`.
- Do not modify existing files.

Output:
- The new `src/ibkr_mcp/server.py` and `src/ibkr_mcp/__main__.py` files.
- A short note summarizing what changed.
```

### Step S5 — Error Handling & Server Status Tool
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- The base FastMCP server is running with a lifespan context yielding the `ib_async.IB` object.
- The spec mandates all tools return standard JSON error schemas instead of throwing unhandled exceptions.

Task:
- Implement structured error responses and the `get_server_status` tool.

Requirements:
- Create `src/ibkr_mcp/models/server.py` with Pydantic models for `ServerStatusResponse` and a generic `ErrorResponse`.
- Create `src/ibkr_mcp/tools/server.py`. Write the `get_server_status` async tool function. It should accept the `Context` (to extract the `IB` object), check connection state, read uptime, and return a JSON serialized `ServerStatusResponse`.
- Update `src/ibkr_mcp/server.py` to import and register this tool using `@mcp.tool()`.
- Ensure the tool handles exceptions by returning an `ErrorResponse` serialized to JSON.

Output:
- The new `models/server.py` and `tools/server.py` files.
- The updated `server.py` file with the tool registered.
- A short note summarizing what changed.
```

### Step S6 — Account & Position Tools
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- FastMCP server is set up and `get_server_status` is registered.

Task:
- Implement P0 tools: `get_account_info` and `get_positions`.

Requirements:
- Create `src/ibkr_mcp/models/account.py` and `src/ibkr_mcp/models/positions.py` with Pydantic schemas corresponding to the spec.
- Create `src/ibkr_mcp/tools/account.py`.
- Implement `get_account_info` (using `ib.accountSummaryAsync()`) and `get_positions` (using `ib.reqPositionsAsync()`).
- Map `ib_async` objects to the Pydantic models, then return them as JSON strings.
- Add error handling (e.g. returning `IB_NOT_CONNECTED` if `ib.isConnected()` is false).
- Update `src/ibkr_mcp/server.py` to register these new tools.

Output:
- The new models and tools files.
- The updated `server.py` file.
- A short note summarizing what changed.
```

### Step S7 — Utility Modules
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Account tools are complete. We are preparing for Market Data tools which require complex parameter parsing.

Task:
- Implement utility functions for IBKR contract construction and ISO duration parsing.

Requirements:
- Create `src/ibkr_mcp/utils/contracts.py`. Write a function `build_contract(symbol, secType, exchange, currency, expiry=None, strike=None, right=None) -> Contract` that returns the correct `ib_async.Contract` subclass (Stock, Option, Future, etc.).
- Create `src/ibkr_mcp/utils/durations.py`. Write a function `parse_duration(duration: str) -> str` that translates ISO 8601 strings (like `P30D`, `PT1H`) into IB-native duration strings (`30 D`, `3600 S`). Pass through valid IB strings unmodified.

Output:
- The new `src/ibkr_mcp/utils/contracts.py` and `src/ibkr_mcp/utils/durations.py` files.
- A short note summarizing what changed.
```

### Step S8 — Market Data Tools
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- `build_contract` and `parse_duration` utilities are ready.

Task:
- Implement P0 Market Data tools: `get_market_data` and `get_historical_data`.

Requirements:
- Create `src/ibkr_mcp/models/market.py` with schema definitions.
- Create `src/ibkr_mcp/tools/market.py`.
- Implement `get_market_data`: Use `build_contract`, qualify it, then use `ib.reqMktData` (or `ib.reqTickers`). Return snapshot prices, volume, and Greeks if it's an option.
- Implement `get_historical_data`: Use `parse_duration`, then `ib.reqHistoricalDataAsync`.
- Serialize results to JSON strings via the Pydantic models. Catch exceptions and return JSON errors.
- Update `src/ibkr_mcp/server.py` to register these tools.

Output:
- The new market models and tools files.
- The updated `server.py` file.
- A short note summarizing what changed.
```

### Step S9 — Order Monitoring Tools
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- Market data tools are integrated.

Task:
- Implement P0 Order tools: `get_order_status` and `get_live_orders`.

Requirements:
- Create `src/ibkr_mcp/models/orders.py` with schemas for order status.
- Create `src/ibkr_mcp/tools/orders.py`.
- Implement `get_live_orders`: Fetch `ib.reqOpenOrders()` or use `ib.openOrders()`, mapping the results to the Pydantic models.
- Implement `get_order_status`: Accept an `orderId`, find the specific order from `ib.trades()` or open orders, and return its status, fill price, commission, etc.
- Return results as JSON strings.
- Update `src/ibkr_mcp/server.py` to register these tools.

Output:
- The new order models and tools files.
- The updated `server.py` file.
- A short note summarizing what changed.
```

### Step S10 — Contract Reference & Flex Query Tools
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All P0 core tools are complete.

Task:
- Implement P1 tools: `get_contract_details`, `list_flex_queries`, and `get_flex_query`.

Requirements:
- Create `src/ibkr_mcp/tools/contracts.py`. Implement `get_contract_details` using `ib.reqContractDetailsAsync`.
- Create `src/ibkr_mcp/tools/flex.py`. Implement `list_flex_queries` and `get_flex_query` using `ib_async.FlexReport`. Note these require the `IB_FLEX_TOKEN` from settings.
- Update `src/ibkr_mcp/server.py` to register `get_contract_details` unconditionally.
- Update `src/ibkr_mcp/server.py` to read `IB_FLEX_TOKEN` from settings. If it exists, conditionally register the two flex query tools.

Output:
- The new contracts and flex tools files.
- The updated `server.py` file.
- A short note summarizing what changed.
```

### Step S11 — Deferred Tools (P2)
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- The server currently exposes P0 and P1 tools.

Task:
- Implement the deferred P2 tools: `get_option_chain`, `get_portfolio_greeks`, and `get_alerts`.

Requirements:
- In `tools/market.py`, add `get_option_chain`. If expiry is not provided, use `ib.reqSecDefOptParamsAsync` for discovery. If expiry is provided, fetch full chain data.
- In `tools/account.py`, add `get_portfolio_greeks`. Aggregate position data and per-contract Greeks.
- In `tools/orders.py` (or a new `alerts.py`), add a placeholder `get_alerts` tool returning a predefined empty list or NotImplemented JSON error, as the spec notes feasibility validation is required.
- Update schemas in `models/` as necessary.
- Register all three in `server.py`.

Output:
- The updated tools files and models.
- The updated `server.py` file.
- A short note summarizing what changed.
```

### Step S12 — FakeIB Test Infrastructure
```text
[INSTRUCTIONS FOR THE CODE-GENERATION LLM]

Context:
- All tool logic is implemented. We need a way to test the tools in CI without a live IB Gateway.

Task:
- Implement the `FakeIB` mock client and wire up basic tests.

Requirements:
- Create `tests/fake_ib.py`. Implement a `FakeIB` class that mocks essential `ib_async.IB` methods used by the tools (e.g., `isConnected`, `accountSummaryAsync`, `reqPositionsAsync`) to return static mock data.
- Create `tests/conftest.py`. Write a pytest fixture `mock_ib` that yields `FakeIB()`.
- Create `tests/test_server_tools.py`. Write at least one `pytest-asyncio` test for `get_server_status` that injects the mock and asserts the returned JSON structure is correct.
- Ensure `pytest` can run cleanly via `pytest tests/`.

Output:
- The new test files in the `tests/` directory.
- A short note summarizing what changed.
```
