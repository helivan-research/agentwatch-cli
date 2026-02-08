# agentwatch-cli

[![PyPI version](https://badge.fury.io/py/agentwatch-cli.svg)](https://badge.fury.io/py/agentwatch-cli)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect your local Moltbot (OpenClaw) gateway to AgentWatch cloud without exposing your local network.

## Overview

`agentwatch-cli` is a secure bridge that allows AgentWatch to communicate with your locally-running Moltbot gateway. Instead of exposing your local network, the connector establishes an outbound WebSocket connection to AgentWatch cloud and relays messages between the two.

**Architecture:**
```
AgentWatch Cloud <--WebSocket--> agentwatch-cli <--HTTP--> Local Moltbot Gateway
     (cloud)                     (your machine)              (your machine)
```

**Key Benefits:**
- **No port forwarding required** - All connections are outbound
- **Secure** - TLS encryption, credentials never stored in plain text
- **Automatic reconnection** - Handles network interruptions gracefully
- **Service mode** - Runs in background, starts on boot

## Requirements

- Python 3.9 or higher
- A running Moltbot (OpenClaw) gateway on your local machine
- An AgentWatch account with a custom agent configured

## Installation

### macOS

**Option 1: Using pipx (Recommended)**
```bash
# Install pipx if you don't have it
brew install pipx
pipx ensurepath

# Install agentwatch-cli
pipx install agentwatch-cli
```

**Option 2: Using pip**
```bash
pip install --user agentwatch-cli

# Add to PATH (add this line to ~/.zshrc for persistence)
export PATH="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user"))'):$PATH"
```

### Linux (Ubuntu/Debian)

**Option 1: Using pipx (Recommended)**
```bash
# Install pipx if you don't have it
sudo apt install pipx
pipx ensurepath

# Install agentwatch-cli
pipx install agentwatch-cli
```

**Option 2: Using pip**
```bash
pip install --user agentwatch-cli
```

The script is installed to `~/.local/bin/` which should already be in your PATH.

### Linux (Fedora/RHEL)

```bash
# Install pipx
sudo dnf install pipx
pipx ensurepath

# Install agentwatch-cli
pipx install agentwatch-cli
```

### Verify Installation

```bash
agentwatch-cli --version
```

If you get "command not found", ensure your PATH includes the installation directory:
```bash
# For pip --user installs:
# macOS: ~/Library/Python/3.X/bin
# Linux: ~/.local/bin

# For pipx installs:
# Usually ~/.local/bin (run `pipx ensurepath` to fix)
```

## Quick Start

### 1. Create a Custom Agent in AgentWatch

1. Go to AgentWatch and navigate to **Custom Agents**
2. Click **Add Agent** and select **Moltbot**
3. You'll receive an 8-character enrollment code (e.g., `ABCD-1234`)

### 2. Enroll the Connector

**Quick install + enroll (single command):**
```bash
pip install --user --upgrade agentwatch-cli && export PATH="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user"))'):$PATH" && agentwatch-cli enroll --code ABCD-1234
```

**Or if already installed:**
```bash
agentwatch-cli enroll --code ABCD-1234
```

This will:
- Register your connector with AgentWatch
- Auto-discover your gateway token from `~/.openclaw/openclaw.json`
- Enable the HTTP chat completions endpoint in OpenClaw (if needed)
- Save configuration to `~/.agentwatch-cli/config.json`

### 3. Install as a Service (Recommended)

```bash
# Linux (requires sudo)
sudo agentwatch-cli install-service

# macOS (no sudo needed - uses launchd)
agentwatch-cli install-service
```

That's it! The connector will now:
- Start automatically on boot
- Run in the background
- Reconnect automatically if disconnected

### Alternative: Run Manually

```bash
agentwatch-cli start
```

## Commands

| Command | Description |
|---------|-------------|
| `enroll` | Enroll with an enrollment code from AgentWatch |
| `start` | Start the connector manually |
| `status` | Check connector status and gateway connectivity |
| `config` | Update configuration settings |
| `revoke` | Revoke enrollment and clear credentials |
| `install-service` | Install as a system service (auto-start) |
| `uninstall-service` | Remove the system service |
| `service-status` | Check if the background service is running |

### enroll

Enroll the connector with an enrollment code from AgentWatch.

```bash
agentwatch-cli enroll --code ABCD-1234
```

### start

Start the connector and begin relaying messages.

```bash
agentwatch-cli start

# With custom gateway URL (if not localhost)
agentwatch-cli start --gateway-url http://192.168.1.100:18789

# With explicit gateway token
agentwatch-cli start --gateway-token your-token-here
```

### status

Check the connector status and test gateway connectivity.

```bash
agentwatch-cli status
```

Example output:
```
AgentWatch CLI Connector Status
========================================
Enrolled: Yes
Agent: My Moltbot
Agent ID: abc123...
Connector ID: def456...

Gateway URL: http://127.0.0.1:18789
AgentWatch URL: wss://agentwatch.helivan.io
Gateway Token: <auto-discovered>

Testing gateway connection...
Gateway Status: ONLINE
```

### config

Configure connector settings.

```bash
# Set gateway URL (for remote gateways)
agentwatch-cli config --gateway-url http://192.168.1.100:18789

# Set gateway token explicitly
agentwatch-cli config --gateway-token your-token-here

# Set AgentWatch cloud URL (for self-hosted deployments)
agentwatch-cli config --agentwatch-url wss://your-agentwatch-instance.com
```

### revoke

Revoke enrollment and clear credentials.

```bash
agentwatch-cli revoke

# Skip confirmation prompt
agentwatch-cli revoke --force
```

### install-service

Install as a system service for automatic startup.

**Linux (systemd):**
```bash
# Requires sudo
sudo agentwatch-cli install-service

# Specify user (default: current user)
sudo agentwatch-cli install-service --user myuser
```

**macOS (launchd):**
```bash
# No sudo needed - installs to ~/Library/LaunchAgents
agentwatch-cli install-service
```

### uninstall-service

Remove the system service.

```bash
# Linux
sudo agentwatch-cli uninstall-service

# macOS
agentwatch-cli uninstall-service
```

### service-status

Check if the service is running.

```bash
agentwatch-cli service-status
```

## Configuration

Configuration is stored in `~/.agentwatch-cli/config.json`:

```json
{
  "connector_id": "uuid",
  "secret": "encrypted-secret",
  "agent_id": "uuid",
  "agent_name": "My Moltbot",
  "gateway_url": "http://127.0.0.1:18789",
  "gateway_token": null,
  "agentwatch_url": "wss://agentwatch.helivan.io"
}
```

### Gateway Token Auto-Discovery

If `gateway_token` is `null`, the connector automatically discovers the token from `~/.openclaw/openclaw.json`:

```json
{
  "gateway": {
    "auth": {
      "token": "your-gateway-token"
    }
  }
}
```

This is the recommended approach - the token is read fresh each time, so if OpenClaw rotates it, the connector automatically uses the new one.

## How It Works

1. **Enrollment**: When you run `enroll`, the CLI exchanges the one-time enrollment code for permanent credentials (connector_id + secret).

2. **Connection**: On `start`, the connector establishes a WebSocket connection to AgentWatch cloud, authenticating with its credentials.

3. **Message Relay**: When a user sends a message to your custom agent in AgentWatch:
   - AgentWatch sends the request through the WebSocket to your connector
   - The connector forwards it to your local Moltbot gateway via HTTP
   - The response flows back through the same path

4. **Streaming**: For streaming responses, the connector handles chunked responses and forwards them in real-time.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AGENTWATCH_ENROLLMENT_URL` | Override the enrollment API URL (for testing/self-hosted) |

## Security

- **Credentials protected**: Config file has restricted permissions (0600)
- **No plain text secrets**: The connector secret is hashed on the cloud side
- **TLS encryption**: All WebSocket and HTTP communication is encrypted
- **Outbound only**: No inbound ports required - the connector initiates all connections

## Troubleshooting

### "Cannot connect to local gateway"

Ensure your Moltbot gateway is running:
```bash
# Check if gateway is listening
curl http://127.0.0.1:18789/v1/models
```

If you get a connection refused error, start your Moltbot/OpenClaw gateway.

### "Invalid enrollment code"

- Enrollment codes expire after 24 hours
- Each code can only be used once
- Generate a new code in AgentWatch if yours has expired

### "Authentication failed"

Your connector credentials may have been revoked. Re-enroll:
```bash
agentwatch-cli revoke --force
agentwatch-cli enroll --code NEW_CODE
```

### "command not found: agentwatch-cli"

The CLI isn't in your PATH. Add the installation directory:

**macOS (pip --user):**
```bash
echo 'export PATH="'"$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user"))')"':$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Linux (pip --user):**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**pipx:**
```bash
pipx ensurepath
# Then restart your terminal
```

### Service won't start

Check the service logs:

**Linux:**
```bash
sudo journalctl -u agentwatch-cli -f
```

**macOS:**
```bash
cat ~/Library/Logs/agentwatch-cli.log
```

## Upgrading

**pipx:**
```bash
pipx upgrade agentwatch-cli
```

**pip:**
```bash
pip install --user --upgrade agentwatch-cli
```

After upgrading, restart the service if installed:
```bash
# Linux
sudo systemctl restart agentwatch-cli

# macOS
launchctl unload ~/Library/LaunchAgents/io.agentwatch.cli.plist
launchctl load ~/Library/LaunchAgents/io.agentwatch.cli.plist
```

## Uninstalling

```bash
# Remove service first (if installed)
agentwatch-cli uninstall-service  # or with sudo on Linux

# Remove package
pipx uninstall agentwatch-cli
# or
pip uninstall agentwatch-cli

# Optionally remove config
rm -rf ~/.agentwatch-cli
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/helivan-research/agentwatch-cli/issues)
- **Documentation**: [docs.agentwatch.io](https://docs.agentwatch.io)
