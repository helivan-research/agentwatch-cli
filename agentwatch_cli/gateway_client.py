"""
Client for communicating with the local OpenClaw gateway via WebSocket.
"""

import asyncio
import json
import uuid
from typing import List, Dict, Any, Optional

import websockets
from websockets.client import WebSocketClientProtocol


class GatewayClient:
    """WebSocket client for the local OpenClaw gateway."""

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 120.0):
        """
        Initialize the gateway client.

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
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None

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

            # Start receiving messages
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Wait for challenge and send connect request
            challenge_msg = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            challenge = json.loads(challenge_msg)

            if challenge.get("type") == "event" and challenge.get("event") == "connect.challenge":
                # Send connect request
                connect_req = {
                    "type": "req",
                    "id": str(uuid.uuid4()),
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "client": {
                            "id": "operator",
                            "mode": "operator",
                            "version": "0.1.0",
                            "platform": "python"
                        },
                        "role": "operator",
                        "scopes": ["operator.read", "operator.write"],
                    }
                }

                if self.token:
                    connect_req["params"]["auth"] = {"token": self.token}

                await self._ws.send(json.dumps(connect_req))

                # Wait for connect response
                response = await self._send_request_internal(connect_req["id"], timeout=5.0)
                if response.get("ok"):
                    self._connected = True
                    return True
                else:
                    print(f"Connect failed: {response.get('error')}")
                    return False
            else:
                # No challenge, might be already connected or different protocol
                self._connected = True
                return True

        except asyncio.TimeoutError:
            print("Connection timeout")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    async def _receive_loop(self):
        """Background task to receive messages."""
        try:
            while self._ws and not self._ws.closed:
                try:
                    msg = await self._ws.recv()
                    data = json.loads(msg)

                    # Handle response messages
                    if data.get("type") == "res":
                        req_id = data.get("id")
                        if req_id and req_id in self._pending_requests:
                            self._pending_requests[req_id].set_result(data)

                    # Handle events (ignore for now)
                    elif data.get("type") == "event":
                        pass

                except websockets.ConnectionClosed:
                    break
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        finally:
            self._connected = False

    async def _send_request_internal(self, req_id: str, timeout: float) -> Dict[str, Any]:
        """Wait for a response to a request."""
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self._pending_requests.pop(req_id, None)

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a request and wait for response.

        Args:
            method: RPC method name
            params: Method parameters

        Returns:
            Response payload
        """
        if not self._ws or not self._connected:
            raise Exception("Not connected to gateway")

        req_id = str(uuid.uuid4())
        request = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params
        }

        # Create future before sending
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future

        try:
            await self._ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=self.timeout)

            if not result.get("ok"):
                raise Exception(result.get("error", "Request failed"))

            return result.get("payload", {})
        finally:
            self._pending_requests.pop(req_id, None)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: str = "openclaw",
    ) -> str:
        """
        Send a chat request to the gateway.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Generation temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response
            model: Model name to use

        Returns:
            The assistant's response text

        Raises:
            Exception: If the request fails
        """
        if not self._connected:
            connected = await self.connect()
            if not connected:
                raise Exception("Failed to connect to gateway")

        # Try different method names that OpenClaw might use
        params = {
            "messages": messages,
            "temperature": temperature,
            "maxTokens": max_tokens,
            "model": model,
        }

        try:
            # Try 'chat.completions' method
            result = await self._send_request("chat.completions", params)
            return result.get("content", result.get("message", {}).get("content", str(result)))
        except Exception as e:
            if "unknown method" in str(e).lower() or "not found" in str(e).lower():
                # Try alternative method names
                try:
                    result = await self._send_request("chat", params)
                    return result.get("content", result.get("message", {}).get("content", str(result)))
                except:
                    pass
                try:
                    result = await self._send_request("completion", params)
                    return result.get("content", str(result))
                except:
                    pass
            raise

    async def health_check(self) -> bool:
        """
        Check if the gateway is healthy.

        Returns:
            True if the gateway is reachable
        """
        try:
            if not self._connected:
                return await self.connect()
            return True
        except Exception:
            return False

    async def disconnect(self):
        """Disconnect from the gateway."""
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None


class SyncGatewayClient:
    """Synchronous wrapper for the WebSocket gateway client."""

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 120.0):
        self.url = url
        self.token = token
        self.timeout = timeout

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: str = "openclaw",
    ) -> str:
        async def _chat():
            client = GatewayClient(self.url, self.token, self.timeout)
            try:
                return await client.chat(messages, temperature, max_tokens, model)
            finally:
                await client.disconnect()

        return asyncio.run(_chat())

    def health_check(self) -> bool:
        async def _health():
            client = GatewayClient(self.url, self.token, self.timeout)
            try:
                return await client.health_check()
            finally:
                await client.disconnect()

        try:
            return asyncio.run(_health())
        except Exception:
            return False
