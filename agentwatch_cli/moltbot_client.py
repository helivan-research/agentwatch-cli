"""
WebSocket client for Moltbot using the chat.send method.
This is the working approach for sending messages to a local Moltbot.
"""

import asyncio
import json
import uuid
from typing import List, Dict, Optional
import websockets
from websockets.client import WebSocketClientProtocol


class MoltbotClient:
    """WebSocket client for Moltbot using chat.send method."""

    def __init__(self, url: str, token: str, timeout: float = 120.0):
        """
        Initialize the Moltbot client.

        Args:
            url: The gateway WebSocket URL (e.g., "ws://127.0.0.1:18789")
            token: The gateway authentication token
            timeout: Request timeout in seconds
        """
        # Normalize URL to ws://
        if url.startswith("http://"):
            url = "ws://" + url[7:]
        elif url.startswith("https://"):
            url = "wss://" + url[8:]
        elif not url.startswith("ws://") and not url.startswith("wss://"):
            url = "ws://" + url

        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._ws: Optional[WebSocketClientProtocol] = None
        self._connected = False
        self._session_key: Optional[str] = None

    async def connect(self) -> bool:
        """
        Connect to the gateway and complete handshake.

        Returns:
            True if connection successful
        """
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.url),
                timeout=10.0
            )

            # Wait for challenge
            challenge_msg = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            challenge = json.loads(challenge_msg)

            if challenge.get("type") == "event" and challenge.get("event") == "connect.challenge":
                # Send connect request with admin scope (required for chat.send)
                connect_req = {
                    "type": "req",
                    "id": str(uuid.uuid4()),
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "client": {
                            "id": "gateway-client",
                            "mode": "backend",
                            "version": "0.1.0",
                            "platform": "python"
                        },
                        "role": "operator",
                        "scopes": ["operator.read", "operator.write", "operator.admin"],
                        "auth": {"token": self.token}
                    }
                }

                await self._ws.send(json.dumps(connect_req))

                # Wait for connect response
                response_msg = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                response = json.loads(response_msg)

                if response.get("type") == "res" and response.get("ok"):
                    self._connected = True
                    return True
                else:
                    error = response.get("error", response)
                    print(f"Connect failed: {error}")
                    return False

        except asyncio.TimeoutError:
            print("Connection timeout")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    async def _get_session_key(self) -> str:
        """Get a session key for chat.send."""
        if self._session_key:
            return self._session_key

        req_id = str(uuid.uuid4())
        request = {
            "type": "req",
            "id": req_id,
            "method": "sessions.list",
            "params": {}
        }

        await self._ws.send(json.dumps(request))

        # Wait for response
        while True:
            msg = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
            data = json.loads(msg)

            if data.get("type") == "res" and data.get("id") == req_id:
                if data.get("ok"):
                    sessions = data.get("payload", {}).get("sessions", [])
                    if not sessions:
                        raise Exception("No sessions available")
                    self._session_key = sessions[0]["key"]
                    return self._session_key
                else:
                    raise Exception(f"Failed to get sessions: {data.get('error')}")

            elif data.get("type") == "event":
                # Skip events
                continue

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: str = "openclaw",
        max_retries: int = 3,
    ) -> str:
        """
        Send a chat request to Moltbot with automatic reconnection.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Generation temperature (ignored - uses Moltbot defaults)
            max_tokens: Maximum tokens (ignored - uses Moltbot defaults)
            model: Model name (ignored - uses Moltbot configured model)
            max_retries: Maximum number of retry attempts on connection errors

        Returns:
            The assistant's response text
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                # Always reconnect to avoid stale WebSocket connections
                if self._connected:
                    await self.disconnect()
                if not self._connected:
                    connected = await self.connect()
                    if not connected:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        raise Exception("Failed to connect to Moltbot")

                return await self._send_chat_request(messages)

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if it's a connection error we can retry
                if any(x in error_str for x in ["connection", "restart", "closed", "keepalive", "ping timeout", "1011"]):
                    if attempt < max_retries - 1:
                        # Reset connection state
                        self._connected = False
                        self._session_key = None
                        await asyncio.sleep(2 ** attempt)
                        continue

                # Not a retryable error, raise immediately
                raise

        # All retries exhausted
        raise Exception(f"Failed after {max_retries} attempts: {last_error}")

    async def _send_chat_request(self, messages: List[Dict[str, str]]) -> str:
        """Internal method to send chat request without retry logic."""

        # Use a unique session key per request to avoid context bleed
        session_key = f"agentwatch-{uuid.uuid4()}"

        # Extract user message (last user message)
        user_message = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content")
                break

        if not user_message:
            raise Exception("No user message found")

        # Send chat.send request
        req_id = str(uuid.uuid4())
        request = {
            "type": "req",
            "id": req_id,
            "method": "chat.send",
            "params": {
                "sessionKey": session_key,
                "message": user_message,
                "idempotencyKey": str(uuid.uuid4())
            }
        }

        await self._ws.send(json.dumps(request))

        # Wait for initial response
        initial_response_received = False
        response_content = []

        while True:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
                data = json.loads(msg)

                if data.get("type") == "res" and data.get("id") == req_id:
                    if not data.get("ok"):
                        raise Exception(f"chat.send failed: {data.get('error')}")
                    initial_response_received = True
                    # Continue to collect turn events

                elif data.get("type") == "event":
                    event = data.get("event", "")
                    payload = data.get("payload", {})

                    # Response is in chat events with message.content[].text structure
                    # Only collect from the final state to avoid duplicates
                    if event == "chat" and payload.get("state") == "final":
                        message = payload.get("message", {})
                        content_blocks = message.get("content", [])
                        for block in content_blocks:
                            if block.get("type") == "text" and block.get("text"):
                                response_content.append(block["text"])
                        break

            except asyncio.TimeoutError:
                # If we got some content, return it
                if response_content:
                    break
                raise Exception("Timeout waiting for Moltbot response")

        return "".join(response_content) if response_content else ""

    async def health_check(self) -> bool:
        """
        Check if Moltbot is healthy.

        Returns:
            True if connected
        """
        try:
            if not self._connected:
                return await self.connect()
            return True
        except Exception:
            return False

    async def disconnect(self):
        """Disconnect from Moltbot."""
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._session_key = None
