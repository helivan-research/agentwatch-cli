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
OPENCLAW_AUTH_PROFILES_PATH = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"


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

    # Local OpenClaw gateway configuration (WebSocket)
    gateway_url: str = "ws://127.0.0.1:18789"
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
    Auto-discover gateway token from openclaw.json.

    Checks in order:
    1. Current directory: ./openclaw.json
    2. Home directory: ~/.openclaw/openclaw.json

    Returns:
        The gateway token if found, None otherwise.
    """
    # Check home directory first, then current directory
    search_paths = [
        OPENCLAW_CONFIG_PATH,
        Path.cwd() / "openclaw.json",
    ]

    for config_path in search_paths:
        if not config_path.exists():
            continue

        try:
            with open(config_path, "r") as f:
                openclaw_config = json.load(f)

            # Navigate to gateway.auth.token
            token = (
                openclaw_config.get("gateway", {})
                .get("auth", {})
                .get("token")
            )
            if token:
                return token
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

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


def discover_anthropic_api_key() -> Optional[str]:
    """
    Auto-discover Anthropic API key from OpenClaw auth profiles.

    OpenClaw stores API keys in ~/.openclaw/agents/main/agent/auth-profiles.json
    when users authenticate during setup (via OAuth or setup token).

    Returns:
        The active Anthropic API key if found, None otherwise.
    """
    if not OPENCLAW_AUTH_PROFILES_PATH.exists():
        return None

    try:
        with open(OPENCLAW_AUTH_PROFILES_PATH, "r") as f:
            auth_data = json.load(f)

        # Get the last good profile for Anthropic
        last_good = auth_data.get("lastGood", {}).get("anthropic")

        if last_good and last_good in auth_data.get("profiles", {}):
            profile = auth_data["profiles"][last_good]
            return profile.get("token")

        # Fallback: find any working Anthropic profile
        profiles = auth_data.get("profiles", {})
        for profile_name, profile in profiles.items():
            if (
                profile.get("provider") == "anthropic"
                and profile.get("type") == "token"
                and profile.get("token")
            ):
                return profile["token"]

    except (json.JSONDecodeError, KeyError, TypeError, FileNotFoundError):
        pass

    return None
