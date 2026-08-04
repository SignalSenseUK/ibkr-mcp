# Setting up IBKR MCP as a systemd Service on Linux

This guide walks you through deploying the IBKR MCP Server as a background daemon on a Linux machine using `systemd`. This setup runs the server using the `streamable-http` transport, making it continuously available to one or more MCP clients.

---

## Prerequisites

1. A Linux machine with `systemd` installed.
2. Python 3.12+ and [`uv`](https://github.com/astral-sh/uv) (or standard `pip` / `venv`) installed.
3. The IBKR MCP Server repository cloned to the target server (e.g., `/opt/ibkr-mcp` or `/home/<user>/ibkr-mcp`).
4. A running instance of **IB Gateway** or **TWS** that is reachable from the server.

---

## Step 1: Install & Sync the Repository

First, ensure the repository is ready and dependencies are installed.

```bash
# Clone the repository (if not already done)
git clone https://github.com/SignalSenseUK/ibkr-mcp.git /opt/ibkr-mcp
cd /opt/ibkr-mcp

# Sync dependencies using uv to create the virtual environment
uv sync --frozen --no-dev
```

---

## Step 2: Configure Environment Variables

Create a dedicated environment file to hold configuration options securely.

1. Create a configuration directory:
   ```bash
   sudo mkdir -p /etc/ibkr-mcp
   ```

2. Create the configuration file `/etc/ibkr-mcp/ibkr-mcp.env`:
   ```bash
   sudo nano /etc/ibkr-mcp/ibkr-mcp.env
   ```

3. Populate the file with your configuration:
   ```env
   # --- IB Gateway / TWS Connection ---
   IB_HOST=127.0.0.1
   IB_PORT=4002
   IB_CLIENT_ID=1
   IB_PAPER_TRADING=true
   # IB_FLEX_TOKEN=your_flex_token_here
   IB_MARKET_DATA_TYPE=LIVE

   # --- MCP Transport ---
   MCP_TRANSPORT=streamable-http
   MCP_HTTP_HOST=127.0.0.1
   MCP_HTTP_PORT=8400

   # --- Logging ---
   LOG_LEVEL=INFO
   LOG_FORMAT=json
   LOG_TOOL_CALLS=false
   ```

4. Restrict file permissions so only root and the service user can read it:
   ```bash
   sudo chmod 600 /etc/ibkr-mcp/ibkr-mcp.env
   ```

---

## Step 3: Create the systemd Service File

Create the service unit file at `/etc/systemd/system/ibkr-mcp.service`:

```bash
sudo nano /etc/systemd/system/ibkr-mcp.service
```

Add the following content:

```ini
[Unit]
Description=IBKR MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Replace 'ibkrmcp' with the user/group that should run the daemon
User=ibkrmcp
Group=ibkrmcp

# Working directory of the repository
WorkingDirectory=/opt/ibkr-mcp

# Points directly to the virtual environment's executable.
# This avoids path issues and does not depend on a global uv installation.
ExecStart=/opt/ibkr-mcp/.venv/bin/ibkr-mcp

# Load environment configuration
EnvironmentFile=/etc/ibkr-mcp/ibkr-mcp.env

# Restart configuration on failure
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> [!NOTE]
> Ensure the user and group specified in the `User=` and `Group=` fields exist on the system and have read/write access to `/opt/ibkr-mcp`. If you haven't created a dedicated user, you can create one with `sudo useradd -r -s /usr/sbin/nologin ibkrmcp` and chown the project directory `sudo chown -R ibkrmcp:ibkrmcp /opt/ibkr-mcp`.

---

## Step 4: Manage the Service

Once configuration and service files are ready, register and control the daemon:

### Enable and Start the Service
```bash
# Reload systemd configuration to pick up the new unit file
sudo systemctl daemon-reload

# Enable the service to start at boot
sudo systemctl enable ibkr-mcp.service

# Start the service immediately
sudo systemctl start ibkr-mcp.service
```

### Stop or Restart the Service
```bash
# Stop the service
sudo systemctl stop ibkr-mcp.service

# Restart the service (useful after updating environment files)
sudo systemctl restart ibkr-mcp.service
```

### Check Service Status
```bash
sudo systemctl status ibkr-mcp.service
```

---

## Step 5: Troubleshooting & Monitoring Logs

Logs are sent to `journalctl`. Use the following commands to monitor and debug the service:

### View Live Log Stream
```bash
sudo journalctl -u ibkr-mcp.service -f
```

### Check for Errors
```bash
sudo journalctl -u ibkr-mcp.service --no-pager -n 100
```
