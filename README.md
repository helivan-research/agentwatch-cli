# agentwatch-cli

Connect your local Moltbot (OpenClaw) gateway to AgentWatch cloud without exposing your local network.

## Overview

`agentwatch-cli` is a bridge that allows AgentWatch to communicate with your locally-running Moltbot gateway. Instead of exposing your local network, the connector establishes an outbound connection to AgentWatch cloud and relays messages between the two.

**Architecture:**
```
AgentWatch Cloud <---> agentwatch-cli <---> Local Moltbot Gateway
      (cloud)         (your machine)           (your machine)
```

## Installation

```bash
pip install agentwatch-cli
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

### 3. Start the connector

```bash
agentwatch-cli start
```

The connector will:
- Connect to your local Moltbot gateway (default: `http://127.0.0.1:18789`)
- Establish a secure WebSocket connection to AgentWatch cloud
- Relay messages between AgentWatch and your local gateway

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
```

### revoke

Revoke enrollment and clear credentials.

```bash
agentwatch-cli revoke

# Skip confirmation
agentwatch-cli revoke --force
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
  "agentwatch_url": "wss://connector.agentwatch.io"
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

## Running as a Service

### systemd (Linux)

Create `/etc/systemd/system/agentwatch-cli.service`:

```ini
[Unit]
Description=AgentWatch CLI Connector
After=network.target

[Service]
Type=simple
User=your-username
ExecStart=/usr/local/bin/agentwatch-cli start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable agentwatch-cli
sudo systemctl start agentwatch-cli
```

### launchd (macOS)

Create `~/Library/LaunchAgents/io.agentwatch.agentwatch-cli.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.agentwatch.agentwatch-cli</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/agentwatch-cli</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/io.agentwatch.agentwatch-cli.plist
```

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
