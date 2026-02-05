"""
CLI entry point for agentwatch-cli.
"""

import argparse
import asyncio
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Optional

import httpx


def fix_script_permissions() -> bool:
    """
    Find and fix permissions on the agentwatch-cli script.

    Returns:
        True if permissions were fixed, False otherwise.
    """
    # Find the script location
    script_path = shutil.which("agentwatch-cli")

    if not script_path:
        # Try common locations
        possible_paths = [
            Path.home() / ".local" / "bin" / "agentwatch-cli",
            Path.home() / "Library" / "Python" / "3.9" / "bin" / "agentwatch-cli",
            Path.home() / "Library" / "Python" / "3.10" / "bin" / "agentwatch-cli",
            Path.home() / "Library" / "Python" / "3.11" / "bin" / "agentwatch-cli",
            Path.home() / "Library" / "Python" / "3.12" / "bin" / "agentwatch-cli",
        ]
        for path in possible_paths:
            if path.exists():
                script_path = str(path)
                break

    if not script_path:
        return False

    try:
        path = Path(script_path)
        # Add execute permission for owner, group, and others
        current_mode = path.stat().st_mode
        new_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        path.chmod(new_mode)
        return True
    except Exception as e:
        print(f"Warning: Could not fix script permissions: {e}")
        return False

from .config import (
    ConnectorConfig,
    load_config,
    save_config,
    discover_gateway_token,
    get_effective_gateway_token,
    DEFAULT_CONFIG_FILE,
)
from .connector import MoltbotConnector, test_gateway_connection
from .service import install_service, uninstall_service, get_service_status

def find_openclaw_config() -> Optional[Path]:
    """Find the OpenClaw config file."""
    # Check home directory first, then current directory
    search_paths = [
        Path.home() / ".openclaw" / "openclaw.json",
        Path.cwd() / "openclaw.json",
    ]
    for path in search_paths:
        if path.exists():
            return path
    return None


def ensure_openclaw_http_enabled() -> bool:
    """
    Ensure OpenClaw's HTTP chat completions endpoint is enabled.

    Returns:
        True if config was updated, False if already enabled or file not found
    """
    config_path = find_openclaw_config()
    if not config_path:
        return False

    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        # Navigate to gateway.http.endpoints.chatCompletions.enabled
        # Create nested dicts if they don't exist
        if "gateway" not in config:
            config["gateway"] = {}
        if "http" not in config["gateway"]:
            config["gateway"]["http"] = {}
        if "endpoints" not in config["gateway"]["http"]:
            config["gateway"]["http"]["endpoints"] = {}
        if "chatCompletions" not in config["gateway"]["http"]["endpoints"]:
            config["gateway"]["http"]["endpoints"]["chatCompletions"] = {}

        # Check if already enabled
        if config["gateway"]["http"]["endpoints"]["chatCompletions"].get("enabled") == True:
            return False

        # Enable it
        config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"] = True

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        return True
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not update OpenClaw config: {e}")
        return False


def normalize_enrollment_code(code: str) -> str:
    """Normalize enrollment code to XXXX-XXXX format."""
    # Remove any dashes and whitespace, uppercase
    clean = code.replace("-", "").replace(" ", "").upper()
    if len(clean) == 8:
        return f"{clean[:4]}-{clean[4:]}"
    return code.upper()


def enroll_command(args: argparse.Namespace) -> int:
    """Handle the enroll command."""
    enrollment_code = normalize_enrollment_code(args.code)

    print(f"Enrolling with code: {enrollment_code}")

    # Load existing config or create new
    config = load_config()

    # Determine enrollment endpoint
    # First try environment variable, then default
    import os

    enrollment_url = os.environ.get(
        "AGENTWATCH_ENROLLMENT_URL",
        "https://agentwatch-api-production.up.railway.app/api/connector/enroll",
    )

    try:
        # Call enrollment API
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                enrollment_url,
                json={"enrollment_code": enrollment_code},
            )

            if response.status_code == 429:
                # Rate limited
                try:
                    error_data = response.json()
                    retry_after = error_data.get('retry_after', 900)
                    print(f"Rate limited: Too many enrollment attempts.")
                    print(f"Please try again in {retry_after // 60} minutes.")
                except json.JSONDecodeError:
                    print("Rate limited: Too many enrollment attempts. Please try again later.")
                return 1

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

        # Fix script permissions (needed for pipx on macOS)
        if fix_script_permissions():
            print("Fixed script permissions")

        # Enable OpenClaw HTTP endpoint
        if ensure_openclaw_http_enabled():
            print("Enabled OpenClaw HTTP chat completions endpoint")
            print("Note: You may need to restart OpenClaw for changes to take effect")

        print()
        print("=" * 50)
        print("Enrollment successful!")
        print("=" * 50)
        print(f"Agent: {config.agent_name}")
        print(f"Config saved to: {DEFAULT_CONFIG_FILE}")
        print()
        print("To start the connector, run:")
        print()
        print("  agentwatch-cli start")
        print()
        print("Or install as a background service:")
        print()
        print("  agentwatch-cli install-service")
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


def install_service_command(args: argparse.Namespace) -> int:
    """Handle the install-service command."""
    config = load_config()

    if not config.is_enrolled():
        print("Error: Connector is not enrolled.")
        print("Please run 'agentwatch-cli enroll --code <CODE>' first.")
        return 1

    print("Installing agentwatch-cli as a system service...")
    print()

    success, message = install_service(user=getattr(args, 'user', None))

    print(message)
    return 0 if success else 1


def uninstall_service_command(args: argparse.Namespace) -> int:
    """Handle the uninstall-service command."""
    print("Uninstalling agentwatch-cli service...")

    success, message = uninstall_service()

    print(message)
    return 0 if success else 1


def service_status_command(args: argparse.Namespace) -> int:
    """Handle the service-status command."""
    is_running, message = get_service_status()

    print("AgentWatch CLI Service Status")
    print("=" * 40)
    print(message)

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

    # install-service command
    install_service_parser = subparsers.add_parser(
        "install-service", help="Install as a system service (auto-start on boot)"
    )
    install_service_parser.add_argument(
        "--user", help="User to run the service as (Linux only, default: current user)"
    )

    # uninstall-service command
    subparsers.add_parser(
        "uninstall-service", help="Uninstall the system service"
    )

    # service-status command
    subparsers.add_parser(
        "service-status", help="Check the system service status"
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
        "install-service": install_service_command,
        "uninstall-service": uninstall_service_command,
        "service-status": service_status_command,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
