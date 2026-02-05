"""
agentwatch-cli: Connect your local Moltbot gateway to AgentWatch cloud.

This package provides a connector that allows AgentWatch to communicate with
your local Moltbot (OpenClaw) gateway without exposing your local network.
"""

__version__ = "0.1.0"
__author__ = "AgentWatch"

from .connector import MoltbotConnector
from .config import ConnectorConfig, load_config, save_config

__all__ = [
    "MoltbotConnector",
    "ConnectorConfig",
    "load_config",
    "save_config",
]
