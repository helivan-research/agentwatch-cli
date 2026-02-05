"""
CLI entry point for agentwatch-cli.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from .config import (
    ConnectorConfig,
    load_config,
    save_config,
    discover_gateway_token,
    get_effective_gateway_token,
    DEFAULT_CONFIG_FILE,
)
from .connector import MoltbotConnector, test_gateway_connection


def enroll_command(args: argparse.Namespace) -> int:
    """Handle the enroll command."""
    enrollment_code = args.code

    print(f"Enrolling with code: {enrollment_code}")

    # Load existing config or create new
    config = load_config()

    # Determine enrollment endpoint
    # First try environment variable, then default
    import os

    enrollment_url = os.environ.get(
        "AGENTWATCH_ENROLLMENT_URL",
        "https://connector.agentwatch.io/api/connector/enroll",
    )

    try:
        # Call enrollment API
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                enrollment_url,
                json={"enrollment_code": enrollment_code},
            )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    print(f"Enrollment failed: {error_data.get('error', 'Unknown error')}")
                except json.JSONDecodeError:
                    print(f"Enrollment failed: HTTP {response.status_code}")
                return 1

            data = response.json()

            if not data.get("success"):
                print(f"Enrollment failed: {data.get('error', 'Unknown error')}")
                return 1

        # Update config with enrollment data
        config.connector_id = data["connector_id"]
        config.secret = data["secret"]
        config.agent_id = data["agent_id"]
        config.agent_name = data["agent_name"]
        config.agentwatch_url = data.get("agentwatch_url", config.agentwatch_url)

        # Try to auto-discover gateway token
        discovered_token = discover_gateway_token()
        if discovered_token:
            print("Auto-discovered gateway token from ~/.openclaw/openclaw.json")
            # Don't save the token - let it be discovered each time for security

        # Save config
        save_config(config)

        print()
        print("=" * 50)
        print("Enrollment successful!")
        print("=" * 50)
        print(f"Agent: {config.agent_name}")
        print(f"Config saved to: {DEFAULT_CONFIG_FILE}")
        print()
        print("Next steps:")
        print("  1. Make sure your Moltbot gateway is running")
        print("  2. Run: agentwatch-cli start")
        print()

        return 0

    except httpx.ConnectError:
        print(f"Failed to connect to enrollment server at {enrollment_url}")
        print("Please check your internet connection.")
        return 1
    except Exception as e:
        print(f"Enrollment error: {e}")
        return 1


def start_command(args: argparse.Namespace) -> int:
    """Handle the start command."""
    config = load_config()

    if not config.is_enrolled():
        print("Connector is not enrolled.")
        print("Please run: agentwatch-cli enroll --code <YOUR_CODE>")
        return 1

    # Apply command line overrides
    if args.gateway_url:
        config.gateway_url = args.gateway_url
    if args.gateway_token:
        config.gateway_token = args.gateway_token

    print(f"Starting connector for agent: {config.agent_name}")
    print(f"Local gateway: {config.gateway_url}")
    print(f"AgentWatch cloud: {config.agentwatch_url}")
    print()

    # Test gateway connection first
    async def test_and_run():
        # Test gateway
        if not await test_gateway_connection(config):
            print(f"Cannot connect to local gateway at {config.gateway_url}")
            print("Please make sure your Moltbot gateway is running.")
            return 1

        print("Local gateway connection: OK")
        print()

        # Start connector
        connector = MoltbotConnector(config)
        await connector.run()
        return 0

    try:
        return asyncio.run(test_and_run())
    except KeyboardInterrupt:
        print("\nStopped by user")
        return 0


def status_command(args: argparse.Namespace) -> int:
    """Handle the status command."""
    config = load_config()

    print("AgentWatch CLI Connector Status")
    print("=" * 40)

    if config.is_enrolled():
        print(f"Enrolled: Yes")
        print(f"Agent: {config.agent_name}")
        print(f"Agent ID: {config.agent_id}")
        print(f"Connector ID: {config.connector_id[:8]}...")
    else:
        print("Enrolled: No")
        print()
        print("Run 'agentwatch-cli enroll --code <CODE>' to enroll")
        return 0

    print()
    print(f"Gateway URL: {config.gateway_url}")
    print(f"AgentWatch URL: {config.agentwatch_url}")

    # Check gateway token
    token = get_effective_gateway_token(config)
    if token:
        print(f"Gateway Token: {'<configured>' if config.gateway_token else '<auto-discovered>'}")
    else:
        print("Gateway Token: NOT FOUND")
        print("  Run: agentwatch-cli config --gateway-token <TOKEN>")
        print("  Or ensure ~/.openclaw/openclaw.json exists")

    print()

    # Test gateway connection
    print("Testing gateway connection...")

    async def test():
        return await test_gateway_connection(config)

    try:
        is_healthy = asyncio.run(test())
        if is_healthy:
            print("Gateway Status: ONLINE")
        else:
            print("Gateway Status: OFFLINE or UNREACHABLE")
    except Exception as e:
        print(f"Gateway Status: ERROR ({e})")

    return 0


def config_command(args: argparse.Namespace) -> int:
    """Handle the config command."""
    config = load_config()

    if args.gateway_url:
        config.gateway_url = args.gateway_url
        print(f"Set gateway_url = {args.gateway_url}")

    if args.gateway_token:
        config.gateway_token = args.gateway_token
        print(f"Set gateway_token = <hidden>")

    if args.agentwatch_url:
        config.agentwatch_url = args.agentwatch_url
        print(f"Set agentwatch_url = {args.agentwatch_url}")

    # Save updated config
    save_config(config)
    print(f"Configuration saved to {DEFAULT_CONFIG_FILE}")

    return 0


def revoke_command(args: argparse.Namespace) -> int:
    """Handle the revoke command (clear enrollment)."""
    config = load_config()

    if not config.is_enrolled():
        print("Connector is not enrolled.")
        return 0

    # Confirm
    if not args.force:
        response = input(
            f"This will revoke enrollment for agent '{config.agent_name}'. Continue? [y/N] "
        )
        if response.lower() != "y":
            print("Cancelled.")
            return 0

    # Clear enrollment data
    config.connector_id = None
    config.secret = None
    config.agent_id = None
    config.agent_name = None

    save_config(config)

    print("Enrollment revoked. You will need to re-enroll to use the connector.")
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agentwatch-cli",
        description="Connect your local Moltbot gateway to AgentWatch cloud",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # enroll command
    enroll_parser = subparsers.add_parser(
        "enroll", help="Enroll connector with an enrollment code"
    )
    enroll_parser.add_argument(
        "--code", "-c", required=True, help="Enrollment code from AgentWatch"
    )

    # start command
    start_parser = subparsers.add_parser(
        "start", help="Start the connector"
    )
    start_parser.add_argument(
        "--gateway-url", help="Override gateway URL"
    )
    start_parser.add_argument(
        "--gateway-token", help="Override gateway token"
    )

    # status command
    subparsers.add_parser(
        "status", help="Show connector status"
    )

    # config command
    config_parser = subparsers.add_parser(
        "config", help="Configure connector settings"
    )
    config_parser.add_argument(
        "--gateway-url", help="Set gateway URL"
    )
    config_parser.add_argument(
        "--gateway-token", help="Set gateway token"
    )
    config_parser.add_argument(
        "--agentwatch-url", help="Set AgentWatch cloud URL"
    )

    # revoke command
    revoke_parser = subparsers.add_parser(
        "revoke", help="Revoke enrollment"
    )
    revoke_parser.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # Dispatch to command handler
    handlers = {
        "enroll": enroll_command,
        "start": start_command,
        "status": status_command,
        "config": config_command,
        "revoke": revoke_command,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
