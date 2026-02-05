"""
Service installation for agentwatch-cli.

Supports:
- systemd (Linux)
- launchd (macOS)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# Service names
SYSTEMD_SERVICE_NAME = "agentwatch-cli"
LAUNCHD_SERVICE_NAME = "io.agentwatch.cli"


def get_platform() -> str:
    """Get the current platform."""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform.startswith("linux"):
        return "linux"
    else:
        return "unsupported"


def get_executable_path() -> str:
    """Get the path to the agentwatch-cli executable."""
    # Try to find it in PATH
    executable = shutil.which("agentwatch-cli")
    if executable:
        return executable

    # Fallback: assume it's in the same location as python
    python_path = Path(sys.executable)
    bin_dir = python_path.parent
    candidate = bin_dir / "agentwatch-cli"
    if candidate.exists():
        return str(candidate)

    # Last resort: use the module directly
    return f"{sys.executable} -m agentwatch_cli.cli"


def get_systemd_service_content(user: str, executable: str, home_dir: str) -> str:
    """Generate systemd service file content."""
    return f"""[Unit]
Description=AgentWatch CLI Connector
Documentation=https://github.com/helivan-research/agentwatch-cli
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Environment="HOME={home_dir}"
ExecStart={executable} start
Restart=always
RestartSec=10
# Wait for gateway to be available before giving up
TimeoutStartSec=300

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agentwatch-cli

[Install]
WantedBy=multi-user.target
"""


def get_launchd_plist_content(executable: str, home_dir: str) -> str:
    """Generate launchd plist file content."""
    # Handle case where executable might have spaces or be a python -m command
    if " " in executable:
        parts = executable.split()
        program_args = "\n".join(f"        <string>{p}</string>" for p in parts)
    else:
        program_args = f"        <string>{executable}</string>"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_SERVICE_NAME}</string>

    <key>ProgramArguments</key>
    <array>
{program_args}
        <string>start</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>NetworkState</key>
        <true/>
    </dict>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{home_dir}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>{home_dir}/Library/Logs/agentwatch-cli.log</string>

    <key>StandardErrorPath</key>
    <string>{home_dir}/Library/Logs/agentwatch-cli.error.log</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
"""


def install_systemd_service(user: Optional[str] = None) -> Tuple[bool, str]:
    """Install systemd service (Linux)."""
    if os.geteuid() != 0:
        return False, "Root privileges required. Run with: sudo agentwatch-cli install-service"

    user = user or os.environ.get("SUDO_USER") or os.getlogin()
    home_dir = str(Path(f"~{user}").expanduser())
    executable = get_executable_path()

    service_content = get_systemd_service_content(user, executable, home_dir)
    service_path = Path(f"/etc/systemd/system/{SYSTEMD_SERVICE_NAME}.service")

    try:
        # Write service file
        service_path.write_text(service_content)

        # Reload systemd
        subprocess.run(["systemctl", "daemon-reload"], check=True)

        # Enable service
        subprocess.run(["systemctl", "enable", SYSTEMD_SERVICE_NAME], check=True)

        # Start service
        subprocess.run(["systemctl", "start", SYSTEMD_SERVICE_NAME], check=True)

        return True, f"""Service installed successfully!

The connector will now:
- Start automatically on boot
- Restart if it crashes
- Run as user: {user}

Useful commands:
  sudo systemctl status {SYSTEMD_SERVICE_NAME}   # Check status
  sudo systemctl restart {SYSTEMD_SERVICE_NAME}  # Restart
  sudo systemctl stop {SYSTEMD_SERVICE_NAME}     # Stop
  journalctl -u {SYSTEMD_SERVICE_NAME} -f        # View logs
"""
    except subprocess.CalledProcessError as e:
        return False, f"Failed to install service: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def uninstall_systemd_service() -> Tuple[bool, str]:
    """Uninstall systemd service (Linux)."""
    if os.geteuid() != 0:
        return False, "Root privileges required. Run with: sudo agentwatch-cli uninstall-service"

    service_path = Path(f"/etc/systemd/system/{SYSTEMD_SERVICE_NAME}.service")

    try:
        # Stop service
        subprocess.run(["systemctl", "stop", SYSTEMD_SERVICE_NAME], check=False)

        # Disable service
        subprocess.run(["systemctl", "disable", SYSTEMD_SERVICE_NAME], check=False)

        # Remove service file
        if service_path.exists():
            service_path.unlink()

        # Reload systemd
        subprocess.run(["systemctl", "daemon-reload"], check=True)

        return True, "Service uninstalled successfully."
    except Exception as e:
        return False, f"Error: {e}"


def install_launchd_service() -> Tuple[bool, str]:
    """Install launchd service (macOS)."""
    home_dir = str(Path.home())
    executable = get_executable_path()

    plist_content = get_launchd_plist_content(executable, home_dir)
    plist_dir = Path(home_dir) / "Library" / "LaunchAgents"
    plist_path = plist_dir / f"{LAUNCHD_SERVICE_NAME}.plist"

    # Create logs directory
    logs_dir = Path(home_dir) / "Library" / "Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Create LaunchAgents directory if needed
        plist_dir.mkdir(parents=True, exist_ok=True)

        # Unload existing service if present
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)

        # Write plist file
        plist_path.write_text(plist_content)

        # Load service
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)

        return True, f"""Service installed successfully!

The connector will now:
- Start automatically on login
- Restart if it crashes

Useful commands:
  launchctl list | grep agentwatch     # Check if running
  launchctl stop {LAUNCHD_SERVICE_NAME}   # Stop
  launchctl start {LAUNCHD_SERVICE_NAME}  # Start

Logs:
  tail -f ~/Library/Logs/agentwatch-cli.log
  tail -f ~/Library/Logs/agentwatch-cli.error.log
"""
    except subprocess.CalledProcessError as e:
        return False, f"Failed to install service: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def uninstall_launchd_service() -> Tuple[bool, str]:
    """Uninstall launchd service (macOS)."""
    home_dir = str(Path.home())
    plist_path = Path(home_dir) / "Library" / "LaunchAgents" / f"{LAUNCHD_SERVICE_NAME}.plist"

    try:
        # Unload service
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()

        return True, "Service uninstalled successfully."
    except Exception as e:
        return False, f"Error: {e}"


def install_service(user: Optional[str] = None) -> Tuple[bool, str]:
    """Install the service for the current platform."""
    platform = get_platform()

    if platform == "linux":
        return install_systemd_service(user)
    elif platform == "macos":
        return install_launchd_service()
    else:
        return False, f"Unsupported platform: {sys.platform}"


def uninstall_service() -> Tuple[bool, str]:
    """Uninstall the service for the current platform."""
    platform = get_platform()

    if platform == "linux":
        return uninstall_systemd_service()
    elif platform == "macos":
        return uninstall_launchd_service()
    else:
        return False, f"Unsupported platform: {sys.platform}"


def get_service_status() -> Tuple[bool, str]:
    """Get the service status for the current platform."""
    platform = get_platform()

    try:
        if platform == "linux":
            result = subprocess.run(
                ["systemctl", "is-active", SYSTEMD_SERVICE_NAME],
                capture_output=True,
                text=True
            )
            is_active = result.returncode == 0
            status = result.stdout.strip()

            # Get more details
            result = subprocess.run(
                ["systemctl", "status", SYSTEMD_SERVICE_NAME, "--no-pager", "-l"],
                capture_output=True,
                text=True
            )
            details = result.stdout

            return is_active, f"Status: {status}\n\n{details}"

        elif platform == "macos":
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True
            )

            for line in result.stdout.split("\n"):
                if LAUNCHD_SERVICE_NAME in line:
                    parts = line.split()
                    pid = parts[0] if parts[0] != "-" else "not running"
                    return parts[0] != "-", f"Service: {LAUNCHD_SERVICE_NAME}\nPID: {pid}"

            return False, "Service not installed"
        else:
            return False, f"Unsupported platform: {sys.platform}"

    except Exception as e:
        return False, f"Error checking status: {e}"
