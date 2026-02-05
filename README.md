# agentwatch-cli

[![PyPI version](https://badge.fury.io/py/agentwatch-cli.svg)](https://badge.fury.io/py/agentwatch-cli)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect your local Moltbot (OpenClaw) gateway to AgentWatch cloud without exposing your local network.

## Overview

`agentwatch-cli` is a bridge that allows AgentWatch to communicate with your locally-running Moltbot gateway. Instead of exposing your local network, the connector establishes an outbound connection to AgentWatch cloud and relays messages between the two.

**Architecture:**
```
AgentWatch Cloud <---> agentwatch-cli <---> Local Moltbot Gateway
      (cloud)         (your machine)           (your machine)
```

## Requirements

- Python 3.9 or higher
- A running Moltbot (OpenClaw) gateway on your local machine
- An AgentWatch account

## Installation

**Recommended:** Use `pipx` for CLI tools (handles PATH automatically):

```bash
# Install pipx if you don't have it
brew install pipx  # macOS
# or: pip install pipx

# Install agentwatch-cli
pipx install agentwatch-cli
```

**Alternative:** Use pip (may require PATH configuration):

```bash
pip install agentwatch-cli

# On macOS, you may need to add to PATH:
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

## Quick Start

### 1. Generate an enrollment code

In AgentWatch, add a new Moltbot agent. You'll receive a 6-character enrollment code like `ABC123`.

### 2. Enroll the connector

```bash
agentwatch-cli enroll --code ABC123
```

This will:
- Register your connector with AgentWatch
- Auto-discover your gateway token from `~/.openclaw/openclaw.json`
- Save configuration to `~/.agentwatch-cli/config.json`

### 3. Install as a service (recommended)

```bash
# Linux (requires sudo)
sudo agentwatch-cli install-service

# macOS
agentwatch-cli install-service
```

That's it! The connector will now:
- Start automatically on boot
- Run in the background
- Reconnect automatically if disconnected

### Alternative: Run manually

```bash
agentwatch-cli start
```

## Commands

### enroll

Enroll the connector with an enrollment code from AgentWatch.

```bash
agentwatch-cli enroll --code ABC123
```

### start

Start the connector and begin relaying messages.

```bash
agentwatch-cli start

# With custom gateway URL
agentwatch-cli start --gateway-url http://192.168.1.100:18789

# With explicit gateway token
agentwatch-cli start --gateway-token your-token-here
```

### status

Check the connector status and configuration.

```bash
agentwatch-cli status
```

### config

Configure connector settings.

```bash
# Set gateway URL
agentwatch-cli config --gateway-url http://192.168.1.100:18789

# Set gateway token
agentwatch-cli config --gateway-token your-token-here

# Set AgentWatch cloud URL (for self-hosted deployments)
agentwatch-cli config --agentwatch-url wss://your-agentwatch-instance.com
```

### revoke

Revoke enrollment and clear credentials.

```bash
agentwatch-cli revoke

# Skip confirmation
agentwatch-cli revoke --force
```

### install-service

Install as a system service for automatic startup.

```bash
# Linux (requires sudo)
sudo agentwatch-cli install-service

# macOS (no sudo needed)
agentwatch-cli install-service

# Specify user (Linux only)
sudo agentwatch-cli install-service --user myuser
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

If `gateway_token` is `null`, the connector automatically looks for the token in `~/.openclaw/openclaw.json`:

```json
{
  "gateway": {
    "auth": {
      "token": "your-gateway-token"
    }
  }
}
```

## Environment Variables

- `AGENTWATCH_ENROLLMENT_URL`: Override the enrollment API URL (for testing)

## Security

- Credentials are stored with restricted file permissions (0600)
- The connector secret is never stored in plain text on the cloud
- All communication uses TLS encryption
- The connector initiates outbound connections only - no inbound ports required

## Troubleshooting

### "Cannot connect to local gateway"

Ensure your Moltbot gateway is running:
```bash
# Check if gateway is listening
curl http://127.0.0.1:18789/v1/models
```

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

## License

MIT License - see LICENSE file for details.
