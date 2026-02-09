"""
CLI entry point for agentwatch-cli.
"""

import argparse
import asyncio
import json
import os
import secrets
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Optional

import httpx


def fix_script_permissions() -> bool:
    """
    Find and fix permissions on the agentwatch-cli script.

    Returns:
        True if permissions were fixed, False otherwise.
    """
    try:
        # Find the script location
        script_path = shutil.which("agentwatch-cli")

        if not script_path:
            # Try common locations across platforms
            possible_paths = [
                Path.home() / ".local" / "bin" / "agentwatch-cli",
                Path.home() / ".local" / "pipx" / "venvs" / "agentwatch-cli" / "bin" / "agentwatch-cli",
            ]
            # macOS: ~/Library/Python/3.X/bin/
            for v in range(9, 14):
                possible_paths.append(
                    Path.home() / "Library" / "Python" / f"3.{v}" / "bin" / "agentwatch-cli"
                )
            for path in possible_paths:
                if path.exists():
                    script_path = str(path)
                    break

        if not script_path:
            return False

        path = Path(script_path)
        current_mode = path.stat().st_mode
        new_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        if current_mode != new_mode:
            path.chmod(new_mode)
            return True
        return False
    except Exception:
        # Never fail enrollment due to permission issues
        return False

from . import __version__
from .config import (
    ConnectorConfig,
    load_config,
    save_config,
    discover_gateway_token,
    get_effective_gateway_token,
    get_config_path,
    discover_all_configs,
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


def _enroll_dry_run(config_name: Optional[str] = None) -> int:
    """
    Simulate full enrollment without calling the real API.

    Generates mock credentials, saves a test config, and verifies
    the entire pipeline (gateway, config, service readiness).
    """
    print("=" * 50)
    print("Dry run: Simulating full enrollment")
    print("=" * 50)
    print()

    all_ok = True

    # 1. CLI version
    print(f"CLI version: {__version__}")
    print(f"  ✓ agentwatch-cli is installed and running")
    print()

    # 2. Gateway token discovery
    token = discover_gateway_token()
    if token:
        print(f"Gateway token: <auto-discovered>")
        print(f"  ✓ Found gateway token")
    else:
        print(f"Gateway token: NOT FOUND")
        print(f"  ✗ Could not find gateway token in ~/.openclaw/openclaw.json")
        all_ok = False
    print()

    # 3. Gateway connectivity
    config = load_config(name=config_name)
    gateway_url = config.gateway_url or "http://127.0.0.1:18789"
    print(f"Gateway URL: {gateway_url}")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{gateway_url}/v1/models")
            if resp.status_code == 200:
                print(f"  ✓ Gateway is reachable")
            else:
                print(f"  ✗ Gateway returned HTTP {resp.status_code}")
                all_ok = False
    except Exception:
        print(f"  ✗ Cannot connect to gateway")
        all_ok = False
    print()

    # 4. Enrollment server connectivity
    enrollment_url = os.environ.get(
        "AGENTWATCH_ENROLLMENT_URL",
        "https://agentwatch-api-production.up.railway.app/api/connector/enroll",
    )
    base_url = enrollment_url.rsplit("/api/", 1)[0]
    print(f"AgentWatch API: {base_url}")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(base_url)
            print(f"  ✓ AgentWatch API is reachable")
    except Exception:
        print(f"  ✗ Cannot connect to AgentWatch API")
        all_ok = False
    print()

    if not all_ok:
        print("=" * 50)
        print("✗ Some checks failed. See above for details.")
        print("=" * 50)
        return 1

    # 5. Simulate enrollment API call
    print("-" * 50)
    print("Step 1: Enrollment API (simulated)")
    print("-" * 50)

    mock_enrollment_code = "TEST-DRY0"
    mock_connector_id = str(uuid.uuid4())
    mock_secret = secrets.token_hex(32)
    mock_agent_id = str(uuid.uuid4())
    mock_agent_name = "DryRun Test Agent"

    print(f"  POST {enrollment_url}")
    print(f"  Request:")
    print(f'    {{"enrollment_code": "{mock_enrollment_code}"}}')
    print()

    mock_response = {
        "success": True,
        "connector_id": mock_connector_id,
        "secret": mock_secret,
        "agent_id": mock_agent_id,
        "agent_name": mock_agent_name,
        "agentwatch_url": config.agentwatch_url,
    }
    print(f"  Response (mock):")
    print(f"    HTTP 200")
    print(f'    {{"success": true,')
    print(f'     "connector_id": "{mock_connector_id}",')
    print(f'     "secret": "{mock_secret[:16]}...",')
    print(f'     "agent_id": "{mock_agent_id}",')
    print(f'     "agent_name": "{mock_agent_name}",')
    print(f'     "agentwatch_url": "{config.agentwatch_url}"}}')
    print()
    print(f"  ✓ Enrollment API response parsed")
    print()

    # 6. Save config
    print("-" * 50)
    print("Step 2: Save configuration")
    print("-" * 50)

    config.connector_id = mock_connector_id
    config.secret = mock_secret
    config.agent_id = mock_agent_id
    config.agent_name = mock_agent_name

    dry_run_name = config_name or "_dry_run"
    save_config(config, name=dry_run_name)
    config_file = get_config_path(dry_run_name)

    print(f"  Config file: {config_file}")
    print(f"  Contents:")
    try:
        with open(config_file, "r") as f:
            saved_data = json.load(f)
        for key, value in saved_data.items():
            if key == "secret":
                print(f"    {key}: {str(value)[:16]}...")
            else:
                print(f"    {key}: {value}")
    except Exception as e:
        print(f"    (could not read: {e})")

    # Check file permissions
    file_stat = config_file.stat()
    perms = oct(file_stat.st_mode)[-3:]
    print(f"  Permissions: {perms}")
    if perms == "600":
        print(f"  ✓ Config saved with correct permissions (0600)")
    else:
        print(f"  ! Unexpected permissions: {perms} (expected 600)")
    print()

    # 7. Reload and verify
    print("-" * 50)
    print("Step 3: Verify config round-trip")
    print("-" * 50)

    reloaded = load_config(name=dry_run_name)
    checks = [
        ("connector_id", reloaded.connector_id == mock_connector_id),
        ("secret", reloaded.secret == mock_secret),
        ("agent_id", reloaded.agent_id == mock_agent_id),
        ("agent_name", reloaded.agent_name == mock_agent_name),
        ("is_enrolled()", reloaded.is_enrolled()),
    ]
    for field, ok in checks:
        status = "✓" if ok else "✗"
        print(f"  {status} {field}: {'OK' if ok else 'MISMATCH'}")
        if not ok:
            all_ok = False
    print()

    # 8. Gateway token resolution
    print("-" * 50)
    print("Step 4: Gateway token resolution")
    print("-" * 50)

    effective_token = get_effective_gateway_token(reloaded)
    if effective_token:
        source = "configured" if reloaded.gateway_token else "auto-discovered"
        print(f"  Token source: {source}")
        print(f"  Token: {effective_token[:8]}...{effective_token[-4:]}")
        print(f"  ✓ Gateway token resolved")
    else:
        print(f"  ✗ No gateway token available")
        all_ok = False
    print()

    # 9. Service install readiness
    print("-" * 50)
    print("Step 5: Service install readiness")
    print("-" * 50)

    from .service import get_executable_path, get_platform
    platform = get_platform()
    executable = get_executable_path()
    print(f"  Platform: {platform}")
    print(f"  Executable: {executable}")
    if platform in ("macos", "linux"):
        print(f"  ✓ Service installation supported")
    else:
        print(f"  ✗ Service installation not supported on this platform")
    print()

    # 10. Clean up
    print("-" * 50)
    print("Cleanup")
    print("-" * 50)
    try:
        config_file.unlink()
        print(f"  ✓ Removed {config_file}")
    except Exception as e:
        print(f"  ! Could not clean up {config_file}: {e}")
    print()

    # Summary
    print("=" * 50)
    if all_ok:
        print("✓ All checks passed! Full enrollment pipeline verified.")
        print()
        print("Run with a real enrollment code:")
        print("  agentwatch-cli enroll --code <YOUR_CODE>")
    else:
        print("✗ Some checks failed. See above for details.")
    print("=" * 50)

    return 0 if all_ok else 1


def enroll_command(args: argparse.Namespace) -> int:
    """Handle the enroll command."""
    config_name = getattr(args, 'name', None)
    dry_run = getattr(args, 'dry_run', False)

    if dry_run:
        return _enroll_dry_run(config_name)

    if not args.code:
        print("Error: --code is required (or use --dry-run to test installation)")
        return 1

    enrollment_code = normalize_enrollment_code(args.code)

    if config_name:
        print(f"Enrolling with code: {enrollment_code} (config: config-{config_name}.json)")
    else:
        print(f"Enrolling with code: {enrollment_code}")

    # Load existing config or create new
    config = load_config(name=config_name)

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
        save_config(config, name=config_name)

        # Fix script permissions (needed for pipx on macOS)
        if fix_script_permissions():
            print("Fixed script permissions")

        # Enable OpenClaw HTTP endpoint
        if ensure_openclaw_http_enabled():
            print("Enabled OpenClaw HTTP chat completions endpoint")
            print("Note: You may need to restart OpenClaw for changes to take effect")

        config_file = get_config_path(config_name)
        print()
        print("=" * 50)
        print("Enrollment successful!")
        print("=" * 50)
        print(f"Agent: {config.agent_name}")
        print(f"Config saved to: {config_file}")
        print()
        print("To start the connector, run:")
        print()
        if config_name:
            print(f"  agentwatch-cli start --name {config_name}")
        else:
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
    config_name = getattr(args, 'name', None)

    # If --name is provided, start only that connector
    if config_name:
        return _start_single_connector(config_name, args)

    # Otherwise, discover and start all enrolled connectors
    return _start_all_connectors(args)


def _start_single_connector(config_name: Optional[str], args: argparse.Namespace) -> int:
    """Start a single connector by name."""
    config = load_config(name=config_name)

    if not config.is_enrolled():
        config_file = get_config_path(config_name)
        print(f"Connector is not enrolled (config: {config_file})")
        if config_name:
            print(f"Please run: agentwatch-cli enroll --name {config_name} --code <YOUR_CODE>")
        else:
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


def _start_all_connectors(args: argparse.Namespace) -> int:
    """Discover and start all enrolled connectors."""
    all_configs = discover_all_configs()

    if not all_configs:
        print("No configurations found.")
        print("Please run: agentwatch-cli enroll --code <YOUR_CODE>")
        return 1

    # Load and filter to only enrolled configs
    enrolled_configs = []
    for name, config_path in all_configs:
        config = load_config(name=name)
        if config.is_enrolled():
            # Apply command line overrides
            if args.gateway_url:
                config.gateway_url = args.gateway_url
            if args.gateway_token:
                config.gateway_token = args.gateway_token
            enrolled_configs.append((name, config))

    if not enrolled_configs:
        print("No enrolled connectors found.")
        print("Please run: agentwatch-cli enroll --code <YOUR_CODE>")
        return 1

    print(f"Found {len(enrolled_configs)} enrolled connector(s):")
    for name, config in enrolled_configs:
        config_label = f"config-{name}.json" if name else "config.json"
        print(f"  - {config.agent_name} ({config_label})")
    print()

    # Start all connectors in parallel
    async def test_and_run_all():
        # Test all gateways first
        print("Testing gateway connections...")
        for name, config in enrolled_configs:
            config_label = f"config-{name}.json" if name else "config.json"
            if not await test_gateway_connection(config):
                print(f"✗ {config.agent_name} ({config_label}): Cannot connect to {config.gateway_url}")
                print("  Please make sure the Moltbot gateway is running.")
                return 1
            print(f"✓ {config.agent_name} ({config_label}): Gateway OK")

        print()
        print(f"Starting {len(enrolled_configs)} connector(s)...")
        print()

        # Create and run all connectors
        connectors = [MoltbotConnector(config) for _, config in enrolled_configs]

        # Run all connectors concurrently
        tasks = [connector.run() for connector in connectors]
        await asyncio.gather(*tasks)

        return 0

    try:
        return asyncio.run(test_and_run_all())
    except KeyboardInterrupt:
        print("\nStopped by user")
        return 0


def status_command(args: argparse.Namespace) -> int:
    """Handle the status command."""
    config_name = getattr(args, 'name', None)
    config = load_config(name=config_name)

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
    config_name = getattr(args, 'name', None)
    config = load_config(name=config_name)

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
    save_config(config, name=config_name)
    config_file = get_config_path(config_name)
    print(f"Configuration saved to {config_file}")

    return 0


def revoke_command(args: argparse.Namespace) -> int:
    """Handle the revoke command (clear enrollment)."""
    config_name = getattr(args, 'name', None)
    config = load_config(name=config_name)

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

    save_config(config, name=config_name)

    print("Enrollment revoked. You will need to re-enroll to use the connector.")
    return 0


def install_service_command(args: argparse.Namespace) -> int:
    """Handle the install-service command."""
    config_name = getattr(args, 'name', None)
    config = load_config(name=config_name)

    if not config.is_enrolled():
        print("Error: Connector is not enrolled.")
        if config_name:
            print(f"Please run 'agentwatch-cli enroll --name {config_name} --code <CODE>' first.")
        else:
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
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # enroll command
    enroll_parser = subparsers.add_parser(
        "enroll", help="Enroll connector with an enrollment code"
    )
    enroll_parser.add_argument(
        "--code", "-c", help="Enrollment code from AgentWatch"
    )
    enroll_parser.add_argument(
        "--name", "-n", help="Config name (uses config-{name}.json, e.g., 'main', 'work')"
    )
    enroll_parser.add_argument(
        "--dry-run", action="store_true",
        help="Test installation without enrolling (verifies CLI, PATH, and gateway)"
    )

    # start command
    start_parser = subparsers.add_parser(
        "start", help="Start connector(s) - starts all enrolled connectors by default"
    )
    start_parser.add_argument(
        "--name", "-n", help="Start only a specific config (if omitted, starts all enrolled connectors)"
    )
    start_parser.add_argument(
        "--gateway-url", help="Override gateway URL"
    )
    start_parser.add_argument(
        "--gateway-token", help="Override gateway token"
    )

    # status command
    status_parser = subparsers.add_parser(
        "status", help="Show connector status"
    )
    status_parser.add_argument(
        "--name", "-n", help="Config name (uses config-{name}.json, e.g., 'main', 'work')"
    )

    # config command
    config_parser = subparsers.add_parser(
        "config", help="Configure connector settings"
    )
    config_parser.add_argument(
        "--name", "-n", help="Config name (uses config-{name}.json, e.g., 'main', 'work')"
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
        "--name", "-n", help="Config name (uses config-{name}.json, e.g., 'main', 'work')"
    )
    revoke_parser.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation"
    )

    # install-service command
    install_service_parser = subparsers.add_parser(
        "install-service", help="Install as a system service (auto-start on boot)"
    )
    install_service_parser.add_argument(
        "--name", "-n", help="Config name (uses config-{name}.json, e.g., 'main', 'work')"
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
