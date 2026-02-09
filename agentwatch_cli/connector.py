"""
Main connector class that bridges AgentWatch cloud to local Moltbot gateway.
"""

import asyncio
import time
from typing import Dict, Any, Optional, Callable
import socketio
from nacl.signing import SigningKey

from .config import ConnectorConfig, get_effective_gateway_token
from .moltbot_client import MoltbotClient


def compute_ed25519_signature(private_key_hex: str, challenge: str, timestamp: int) -> str:
    """
    Compute Ed25519 signature for authentication.

    The server will verify this signature using the stored public key.

    Args:
        private_key_hex: The Ed25519 private key seed (hex, 32 bytes)
        challenge: The challenge nonce from the server
        timestamp: Current timestamp in milliseconds

    Returns:
        Hex-encoded Ed25519 signature (64 bytes)
    """
    signing_key = SigningKey(bytes.fromhex(private_key_hex))
    message = f"{challenge}:{timestamp}".encode('utf-8')
    signed = signing_key.sign(message)
    return signed.signature.hex()


class MoltbotConnector:
    """
    Connector that bridges AgentWatch cloud to a local Moltbot gateway.

    This connector:
    1. Connects to AgentWatch cloud via WebSocket
    2. Authenticates using connector credentials
    3. Receives job requests from the cloud
    4. Forwards requests to the local Moltbot gateway
    5. Returns responses back to the cloud
    """

    def __init__(self, config: ConnectorConfig):
        """
        Initialize the connector.

        Args:
            config: Connector configuration
        """
        self.config = config
        self.sio: Optional[socketio.AsyncClient] = None
        self.gateway_client: Optional[MoltbotClient] = None
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 0  # 0 = infinite
        self.on_status_change: Optional[Callable[[str], None]] = None

        # Heartbeat
        self.heartbeat_interval = 30  # seconds
        self.heartbeat_task: Optional[asyncio.Task] = None

        # Authentication challenge (received from server)
        self.pending_challenge: Optional[str] = None
        self.challenge_expires_at: Optional[int] = None

    def _log(self, message: str, level: str = "info") -> None:
        """Log a message with timestamp."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        prefix = {"info": "[INFO]", "error": "[ERROR]", "warn": "[WARN]"}.get(
            level, "[INFO]"
        )
        print(f"{timestamp} {prefix} {message}")

    async def connect(self) -> bool:
        """
        Connect to AgentWatch cloud.

        Returns:
            True if connection and authentication successful
        """
        if not self.config.is_enrolled():
            self._log("Connector is not enrolled. Run 'agentwatch-cli enroll' first.", "error")
            return False

        # Initialize Moltbot client
        gateway_token = get_effective_gateway_token(self.config)
        self.gateway_client = MoltbotClient(
            url=self.config.gateway_url,
            token=gateway_token,
        )

        # Test gateway connection first
        if not await self.gateway_client.health_check():
            self._log(f"Cannot connect to local gateway at {self.config.gateway_url}", "error")
            self._log("Make sure your Moltbot gateway is running.", "error")
            return False

        self._log(f"Local gateway at {self.config.gateway_url} is reachable")

        # Initialize Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=self.max_reconnect_attempts,
            reconnection_delay=1,
            reconnection_delay_max=60,
            logger=False,
            engineio_logger=False,
        )

        # Set up event handlers
        self._setup_event_handlers()

        try:
            self._log(f"Connecting to AgentWatch at {self.config.agentwatch_url}...")
            await self.sio.connect(
                self.config.agentwatch_url,
                transports=["websocket", "polling"],
            )

            # Authentication will happen when we receive the challenge event

            return True
        except Exception as e:
            self._log(f"Failed to connect: {e}", "error")
            return False

    def _setup_event_handlers(self) -> None:
        """Set up Socket.IO event handlers."""
        if not self.sio:
            return

        @self.sio.on("challenge")
        async def on_challenge(data: Dict[str, Any]):
            """Handle authentication challenge from server."""
            self.pending_challenge = data.get("challenge")
            self.challenge_expires_at = data.get("expires_at")
            self._log("Received authentication challenge")
            # Authenticate with HMAC
            await self._authenticate()

        @self.sio.event
        async def connect():
            self._log("Connected to AgentWatch cloud")
            self.reconnect_attempts = 0
            # Don't authenticate here - wait for challenge

        @self.sio.event
        async def disconnect():
            self._log("Disconnected from AgentWatch cloud", "warn")
            if self.on_status_change:
                self.on_status_change("disconnected")

        @self.sio.event
        async def connect_error(data):
            self._log(f"Connection error: {data}", "error")

        @self.sio.on("auth_response")
        async def on_auth_response(data: Dict[str, Any]):
            if data.get("success"):
                self._log(f"Authenticated as agent: {self.config.agent_name}")
                if self.on_status_change:
                    self.on_status_change("online")
                # Start heartbeat
                await self._start_heartbeat()
            else:
                self._log(f"Authentication failed: {data.get('error')}", "error")
                if self.on_status_change:
                    self.on_status_change("auth_failed")

        @self.sio.on("job")
        async def on_job(data: Dict[str, Any]):
            await self._handle_job(data)

        @self.sio.on("health_check")
        async def on_health_check(data: Dict[str, Any]):
            await self._handle_health_check(data)

        @self.sio.on("ping")
        async def on_ping(data: Dict[str, Any]):
            # Respond to ping with heartbeat
            await self._send_heartbeat()

    async def _authenticate(self) -> None:
        """Send authentication message to cloud using Ed25519 signature."""
        if not self.sio:
            return

        # Resolve gateway token for auth payload
        gateway_token = get_effective_gateway_token(self.config)

        if not self.pending_challenge:
            self._log("No challenge received from server — cannot authenticate", "error")
            return

        if not self.config.private_key:
            self._log("No private key configured — cannot authenticate", "error")
            return

        timestamp = int(time.time() * 1000)
        signature = compute_ed25519_signature(
            self.config.private_key,
            self.pending_challenge,
            timestamp
        )

        auth_message = {
            "type": "auth",
            "connector_id": self.config.connector_id,
            "auth_method": "ed25519",
            "challenge": self.pending_challenge,
            "timestamp": timestamp,
            "signature": signature,
            "gateway_url": self.config.gateway_url,
            "gateway_token": gateway_token,
        }
        self._log("Authenticating with Ed25519 signature")

        await self.sio.emit("auth", auth_message)

        # Clear the challenge after use
        self.pending_challenge = None
        self.challenge_expires_at = None

    async def _start_heartbeat(self) -> None:
        """Start the heartbeat task."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to keep connection alive."""
        while self.running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Heartbeat error: {e}", "warn")

    async def _send_heartbeat(self) -> None:
        """Send a heartbeat message."""
        if not self.sio or not self.sio.connected:
            return

        heartbeat = {
            "type": "heartbeat",
            "timestamp": int(time.time() * 1000),
        }
        await self.sio.emit("heartbeat", heartbeat)

    async def _handle_job(self, data: Dict[str, Any]) -> None:
        """
        Handle an incoming job request from the cloud.

        Args:
            data: Job data containing messages and parameters
        """
        job_id = data.get("job_id")
        if not job_id:
            self._log("Received job without job_id", "error")
            return

        self._log(f"Received job: {job_id}")

        try:
            # Extract job parameters
            messages = data.get("messages", [])
            temperature = data.get("temperature", 0.7)
            max_tokens = data.get("max_tokens", 4000)
            system_prompt = data.get("system_prompt")

            # Prepend system prompt if provided
            if system_prompt:
                messages = [{"role": "system", "content": system_prompt}] + messages

            # Forward to local Moltbot via WebSocket (chat.send method)
            if not self.gateway_client:
                raise Exception("Gateway client not initialized")

            response = await self.gateway_client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Send success response
            await self.sio.emit(
                "job_response",
                {
                    "type": "job_response",
                    "job_id": job_id,
                    "success": True,
                    "response": response,
                },
            )
            self._log(f"Job {job_id} completed successfully")

        except Exception as e:
            self._log(f"Job {job_id} failed: {e}", "error")
            # Send error response
            await self.sio.emit(
                "job_response",
                {
                    "type": "job_response",
                    "job_id": job_id,
                    "success": False,
                    "error": str(e),
                },
            )

    async def _handle_health_check(self, data: Dict[str, Any]) -> None:
        """
        Handle a health check request from the cloud.
        Verifies connectivity to the local gateway without requiring admin scope.

        Args:
            data: Health check data containing job_id
        """
        job_id = data.get("job_id")
        if not job_id:
            self._log("Received health_check without job_id", "error")
            return

        self._log(f"Received health check: {job_id}")

        try:
            # Just verify we can connect to the gateway (no chat completion needed)
            if not self.gateway_client:
                raise Exception("Gateway client not initialized")

            is_healthy = await self.gateway_client.health_check()

            if is_healthy:
                # Send success response
                await self.sio.emit(
                    "job_response",
                    {
                        "type": "job_response",
                        "job_id": job_id,
                        "success": True,
                        "response": "Gateway is healthy",
                    },
                )
                self._log(f"Health check {job_id} passed")
            else:
                raise Exception("Gateway health check failed")

        except Exception as e:
            self._log(f"Health check {job_id} failed: {e}", "error")
            # Send error response
            await self.sio.emit(
                "job_response",
                {
                    "type": "job_response",
                    "job_id": job_id,
                    "success": False,
                    "error": str(e),
                },
            )

    async def run(self) -> None:
        """
        Run the connector, maintaining connection to the cloud.

        This method blocks until the connector is stopped.
        """
        self.running = True

        if not await self.connect():
            self.running = False
            return

        self._log("Connector is running. Press Ctrl+C to stop.")

        try:
            # Wait for disconnect
            await self.sio.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the connector and disconnect."""
        self.running = False

        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.sio and self.sio.connected:
            await self.sio.disconnect()

        self._log("Connector stopped")

    def run_sync(self) -> None:
        """Run the connector synchronously (blocking)."""
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            self._log("Interrupted by user")


async def test_gateway_connection(config: ConnectorConfig) -> bool:
    """
    Test connection to the local Moltbot gateway.

    Args:
        config: Connector configuration

    Returns:
        True if connection is successful
    """
    gateway_token = get_effective_gateway_token(config)
    client = MoltbotClient(
        url=config.gateway_url,
        token=gateway_token,
    )
    return await client.health_check()
