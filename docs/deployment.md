# Deployment

This guide covers how to run the IBKR MCP server in real environments. For one-off local use, the [README quick-start](../README.md#quick-start) is enough.

---

## Choosing a transport

| Transport | When to use | Notes |
|-----------|-------------|-------|
| **`stdio`** | The MCP client spawns the server as a child process (Claude Desktop, Cursor, Continue, custom agents that follow the official `mcp` SDK pattern). | Each client starts its own copy of the server; no port to manage. The lifespan runs once per client session. |
| **`streamable-http`** | Long-running shared deployments where multiple MCP clients (or the same client across restarts) reuse one connection to IB Gateway. | A single FastMCP process exposes `http://<host>:<port>/mcp`. Concurrent calls from multiple clients are serialised via `app_ctx.ib_lock` (see [architecture §6.1](architecture.md#61-the-ib_lock)). |

**`stdio` is the simpler default** if you just need an MCP-aware AI to access your IBKR data on your own machine.

---

## Pattern A — Stdio for an MCP-aware app

### Claude Desktop

Edit Claude's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ibkr": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/ibkr-mcp",
        "run", "ibkr-mcp", "--transport", "stdio"
      ],
      "env": {
        "IB_HOST": "127.0.0.1",
        "IB_PORT": "4002",
        "IB_PAPER_TRADING": "true",
        "IB_MARKET_DATA_TYPE": "DELAYED",
        "LOG_FORMAT": "console"
      }
    }
  }
}
```

Locations:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

After editing, fully quit and re-open Claude. The IBKR tools should appear in the tool picker.

### Cursor

`~/.cursor/mcp.json` accepts the same shape as Claude Desktop's config.

### Continue

In your `~/.continue/config.json`, add:

```json
{
  "mcpServers": {
    "ibkr": {
      "transport": { "type": "stdio" },
      "command": "uv",
      "args": ["--directory", "/path/to/ibkr-mcp", "run", "ibkr-mcp", "--transport", "stdio"]
    }
  }
}
```

### Generic stdio client (Python)

```python
from mcp.client.stdio import stdio_client, StdioServerParameters

params = StdioServerParameters(
    command="uv",
    args=["--directory", "/path/to/ibkr-mcp", "run", "ibkr-mcp", "--transport", "stdio"],
    env={"IB_HOST": "127.0.0.1", "IB_PORT": "4002"},
)

async with stdio_client(params) as (read, write):
    ...   # talk MCP over (read, write)
```

---

## Pattern B — Streamable HTTP (long-running server)

Run the server as a daemon and point one or many MCP clients at `http://<host>:8400/mcp`.

### Manual

```bash
uv run ibkr-mcp --transport streamable-http
# bound to MCP_HTTP_HOST:MCP_HTTP_PORT (defaults: 127.0.0.1:8400)
```

### Connecting an MCP client

```json
{
  "mcpServers": {
    "ibkr": { "url": "http://127.0.0.1:8400/mcp" }
  }
}
```

### `systemd` service (Linux)

`/etc/systemd/system/ibkr-mcp.service`:

```ini
[Unit]
Description=IBKR MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ibkrmcp
WorkingDirectory=/opt/ibkr-mcp
EnvironmentFile=/etc/ibkr-mcp/env
ExecStart=/usr/local/bin/uv run --directory /opt/ibkr-mcp ibkr-mcp --transport streamable-http
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/ibkr-mcp/env`:

```ini
IB_HOST=127.0.0.1
IB_PORT=4002
IB_PAPER_TRADING=true
IB_MARKET_DATA_TYPE=LIVE
MCP_TRANSPORT=streamable-http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=8400
LOG_LEVEL=INFO
LOG_FORMAT=json
```

```bash
sudo chown root:ibkrmcp /etc/ibkr-mcp/env && sudo chmod 640 /etc/ibkr-mcp/env
sudo systemctl daemon-reload
sudo systemctl enable --now ibkr-mcp
journalctl -u ibkr-mcp -f
```

### `launchd` service (macOS)

`~/Library/LaunchAgents/com.example.ibkr-mcp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>com.example.ibkr-mcp</string>
  <key>WorkingDirectory</key> <string>/Users/me/code/ibkr-mcp</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>ibkr-mcp</string>
    <string>--transport</string>
    <string>streamable-http</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>IB_HOST</key><string>127.0.0.1</string>
    <key>IB_PORT</key><string>4002</string>
    <key>IB_PAPER_TRADING</key><string>true</string>
  </dict>
  <key>KeepAlive</key>        <true/>
  <key>RunAtLoad</key>        <true/>
  <key>StandardOutPath</key>  <string>/tmp/ibkr-mcp.out</string>
  <key>StandardErrorPath</key><string>/tmp/ibkr-mcp.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.example.ibkr-mcp.plist
launchctl start com.example.ibkr-mcp
```

---

## Pattern C — Docker

A minimal `Dockerfile` (not shipped, but recommended):

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PYTHONUNBUFFERED=1
EXPOSE 8400
CMD ["uv", "run", "ibkr-mcp", "--transport", "streamable-http"]
```

> **Important: IB Gateway runs on the host, not inside this container.** The container needs to reach the gateway, which usually means setting `IB_HOST=host.docker.internal` (Docker Desktop) or the host's LAN IP, plus mapping `--network=host` on Linux.

`docker-compose.yml`:

```yaml
services:
  ibkr-mcp:
    build: .
    network_mode: host          # IB Gateway listens on the host
    environment:
      IB_HOST: 127.0.0.1
      IB_PORT: "4002"
      IB_PAPER_TRADING: "true"
      MCP_HTTP_PORT: "8400"
      LOG_LEVEL: INFO
      LOG_FORMAT: json
    restart: unless-stopped
```

> **Auto-starting IB Gateway in Docker** is a separate, larger project (it requires a desktop session because the gateway is a Java GUI app). Tools like `IBC` exist to automate this; pairing them with this MCP server is out of scope here.

---

## Network exposure

> **Default: localhost only.** `MCP_HTTP_HOST=127.0.0.1` means only processes on the same machine can hit `/mcp`.

There is **no built-in authentication** in v0.1. If you bind to a public interface, anyone who reaches the port can read your account data. Don't do this without one of:

1. **An SSH tunnel.** Forward a local port to the remote `:8400` over SSH:
   ```bash
   ssh -N -L 8400:127.0.0.1:8400 user@your-server
   ```
   The MCP client points at `http://127.0.0.1:8400/mcp`; the server stays bound to localhost on the remote.

2. **A reverse proxy with auth.** Put nginx/Caddy/Traefik in front and require Basic Auth or mTLS. Example nginx snippet:

   ```nginx
   server {
     listen 443 ssl;
     server_name ibkr-mcp.example.com;
     auth_basic "ibkr-mcp"; auth_basic_user_file /etc/nginx/htpasswd;
     location /mcp { proxy_pass http://127.0.0.1:8400/mcp; }
   }
   ```

3. **A VPN / Tailscale.** Bind to a private interface only reachable over your VPN.

Authentication built into the server is on the v0.2 wishlist; until it lands, treat the HTTP transport as a development convenience.

---

## Operational considerations

### IB Gateway daily restart

IB Gateway is forced to log out daily (typically around midnight ET). The MCP server doesn't crash, but tools will start returning `IB_NOT_CONNECTED` until the gateway is back up. `ib_async` automatically retries the underlying socket connection, so the server typically self-heals once the gateway is back.

If you need stronger guarantees:

- Use [IBC](https://github.com/IbcAlpha/IBC) to auto-restart the gateway on schedule.
- Run `get_server_status` from a healthcheck loop and alert when `status != "connected"` for more than N minutes.

### Concurrent clients on one server

The Streamable HTTP transport handles multiple clients fine. The `ib_lock` serialises gateway calls; throughput is therefore bounded by IB's response time per request, **not** by the number of clients. A noisy client can starve others — consider per-client rate limiting at the proxy layer if this matters.

### Resource footprint

- Steady state ~50 MB RSS, mostly the Python runtime and `ib_async`.
- Per-tool latency depends on the gateway. Snapshot quotes are typically 100–300 ms; full option chains scale with strike count.

### Logging volume

`LOG_TOOL_CALLS=true` emits one structured event per call. At 100 calls/minute that's ~144 K events/day — manageable but worth ingesting via a structured log pipeline. Keep it `false` in production unless you're actively debugging.

### Versioning

The server reports its version via `get_server_status.serverVersion` and on the startup banner. Upgrading is a `git pull && uv sync` cycle. Models use `populate_by_name=True` so renaming an alias is technically backward-compatible — but breaking JSON output is rare and would be flagged in release notes.
