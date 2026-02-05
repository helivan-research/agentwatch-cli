"""
Configuration management for agentwatch-cli.
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# Default paths
DEFAULT_CONFIG_DIR = Path.home() / ".agentwatch-cli"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"


@dataclass
class ConnectorConfig:
    """Configuration for the agentwatch-cli connector."""

    # Credentials (set after enrollment)
    connector_id: Optional[str] = None
    secret: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None

    # AgentWatch cloud URL
    agentwatch_url: str = "wss://agentwatch.helivan.io"

    # Local Moltbot gateway configuration
    gateway_url: str = "http://127.0.0.1:18789"
    gateway_token: Optional[str] = None

    def is_enrolled(self) -> bool:
        """Check if the connector is enrolled."""
        return bool(self.connector_id and self.secret and self.agent_id)


def load_config(config_path: Optional[Path] = None) -> ConnectorConfig:
    """Load configuration from file."""
    path = config_path or DEFAULT_CONFIG_FILE

    if not path.exists():
        return ConnectorConfig()

    try:
        with open(path, "r") as f:
            data = json.load(f)
        return ConnectorConfig(**data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Failed to load config from {path}: {e}")
        return ConnectorConfig()


def save_config(config: ConnectorConfig, config_path: Optional[Path] = None) -> None:
    """Save configuration to file."""
    path = config_path or DEFAULT_CONFIG_FILE

    # Create directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(asdict(config), f, indent=2)

    # Set restrictive permissions (only owner can read/write)
    os.chmod(path, 0o600)


def discover_gateway_token() -> Optional[str]:
    """
    Auto-discover gateway token from ~/.openclaw/openclaw.json.

    Returns:
        The gateway token if found, None otherwise.
    """
    if not OPENCLAW_CONFIG_PATH.exists():
        return None

    try:
        with open(OPENCLAW_CONFIG_PATH, "r") as f:
            openclaw_config = json.load(f)

        # Navigate to gateway.auth.token
        token = (
            openclaw_config.get("gateway", {})
            .get("auth", {})
            .get("token")
        )
        return token
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def get_effective_gateway_token(config: ConnectorConfig) -> Optional[str]:
    """
    Get the effective gateway token, preferring config over auto-discovery.

    Args:
        config: The connector configuration.

    Returns:
        The gateway token from config, or auto-discovered from OpenClaw config.
    """
    if config.gateway_token:
        return config.gateway_token

    return discover_gateway_token()
