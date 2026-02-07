"""
WebSocket client for Moltbot using the chat.send method.

This client creates a dedicated session for the connector (to avoid interfering
with the user's active session) and clears the session history after each request
to ensure fresh context for every question.
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional
import websockets
from websockets.client import WebSocketClientProtocol


class MoltbotClient:
    """WebSocket client for Moltbot using chat.send method with session pooling for parallel requests."""

    CONNECTOR_SESSION_PREFIX = "agent:main:agentwatch-connector"
    SESSIONS_FILE = Path.home() / ".openclaw" / "agents" / "main" / "sessions" / "sessions.json"
    SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"

    def __init__(self, url: str, token: str, timeout: float = 120.0, pool_size: int = 5):
        """
        Initialize the Moltbot client with session pooling.

        Args:
            url: The gateway WebSocket URL (e.g., "ws://127.0.0.1:18789")
            token: The gateway authentication token
            timeout: Request timeout in seconds
            pool_size: Number of sessions in the pool for parallel requests
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
        self.pool_size = pool_size
        self._ws: Optional[WebSocketClientProtocol] = None
        self._connected = False

        # Session slots: limit concurrency without reusing sessions
        self._session_semaphore: Optional[asyncio.Semaphore] = None
        self._session_counter = 0

        # Message routing for parallel requests
        self._pending_requests: Dict[str, asyncio.Queue] = {}
        self._receiver_task: Optional[asyncio.Task] = None
        self._receiver_lock = asyncio.Lock()

        # Snapshot agent state for consistent evaluation
        self._agent_snapshot = self._capture_agent_snapshot()

        # Initialize session semaphore for concurrency control
        self._session_semaphore = asyncio.Semaphore(pool_size)
        print(f"Session concurrency limit: {pool_size}")

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
                    # Start background receiver task
                    self._receiver_task = asyncio.create_task(self._receive_messages())
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

    async def _receive_messages(self):
        """Background task that receives messages and routes them to pending requests."""
        try:
            while self._connected and self._ws:
                try:
                    msg = await self._ws.recv()
                    data = json.loads(msg)

                    # Route message based on request ID
                    req_id = data.get("id")
                    if req_id and req_id in self._pending_requests:
                        request_info = self._pending_requests[req_id]
                        await request_info["queue"].put(data)

                        # Store runId if this is the initial response
                        if data.get("type") == "res" and data.get("ok"):
                            run_id = data.get("payload", {}).get("runId")
                            if run_id:
                                request_info["run_id"] = run_id

                    elif data.get("type") == "event":
                        payload = data.get("payload", {})
                        run_id = payload.get("runId")
                        session_key = payload.get("sessionKey")

                        # Route event to the request that matches runId or sessionKey
                        for req_id, request_info in list(self._pending_requests.items()):
                            if run_id and request_info["run_id"] == run_id:
                                try:
                                    request_info["queue"].put_nowait(data)
                                except asyncio.QueueFull:
                                    pass
                                break
                            elif session_key and request_info["session_key"] == session_key and not run_id:
                                # Fallback to sessionKey matching for events without runId
                                try:
                                    request_info["queue"].put_nowait(data)
                                except asyncio.QueueFull:
                                    pass
                                break

                except Exception as e:
                    if self._connected:
                        print(f"Receiver error: {e}")
                    break
        except asyncio.CancelledError:
            pass

    def _capture_agent_snapshot(self) -> Dict:
        """Capture a snapshot of the main agent's state for consistent evaluation."""
        if not self.SESSIONS_FILE.exists():
            print(f"Warning: Sessions file not found at {self.SESSIONS_FILE}")
            return {}

        try:
            with open(self.SESSIONS_FILE, 'r') as f:
                sessions = json.load(f)

            # Get the main session as template
            main_session = sessions.get("agent:main:main", {})

            # Extract snapshot fields (these define agent state)
            snapshot = {
                "skillsSnapshot": main_session.get("skillsSnapshot"),
                "systemPromptReport": main_session.get("systemPromptReport"),
                "modelProvider": main_session.get("modelProvider", "anthropic"),
                "model": main_session.get("model", "claude-opus-4-5"),
                "contextTokens": main_session.get("contextTokens", 200000),
                "authProfileOverride": main_session.get("authProfileOverride"),
                "authProfileOverrideSource": main_session.get("authProfileOverrideSource"),
            }

            print(f"Captured agent snapshot from main session")
            if snapshot.get("skillsSnapshot"):
                skill_count = len(snapshot["skillsSnapshot"].get("skills", []))
                print(f"  Skills: {skill_count}")
            if snapshot.get("systemPromptReport"):
                file_count = len(snapshot["systemPromptReport"].get("injectedWorkspaceFiles", []))
                print(f"  Workspace files: {file_count}")

            return snapshot

        except Exception as e:
            print(f"Warning: Failed to capture agent snapshot: {e}")
            return {}

    def _create_fresh_session(self) -> tuple[str, str]:
        """Create a fresh session for a request."""
        import uuid
        from datetime import datetime

        # Generate unique session ID
        session_id = str(uuid.uuid4())
        self._session_counter += 1
        session_key = f"{self.CONNECTOR_SESSION_PREFIX}-{self._session_counter}"

        try:
            # Create session in sessions.json
            if self.SESSIONS_FILE.exists():
                with open(self.SESSIONS_FILE, 'r') as f:
                    sessions = json.load(f)
            else:
                sessions = {}

            # Create session data with snapshot
            session_data = {
                "sessionId": session_id,
                "type": "embedded",
                "createdAt": int(time.time() * 1000),
                "updatedAt": int(time.time() * 1000),
                "modelProvider": self._agent_snapshot.get("modelProvider", "anthropic"),
                "model": self._agent_snapshot.get("model", "claude-opus-4-5"),
                "contextTokens": self._agent_snapshot.get("contextTokens", 200000),
            }

            # Add snapshot metadata if available
            if self._agent_snapshot.get("skillsSnapshot"):
                session_data["skillsSnapshot"] = self._agent_snapshot["skillsSnapshot"]
            if self._agent_snapshot.get("systemPromptReport"):
                session_data["systemPromptReport"] = self._agent_snapshot["systemPromptReport"]
            if self._agent_snapshot.get("authProfileOverride"):
                session_data["authProfileOverride"] = self._agent_snapshot["authProfileOverride"]
                session_data["authProfileOverrideSource"] = self._agent_snapshot.get("authProfileOverrideSource", "auto")

            sessions[session_key] = session_data

            # Write sessions.json
            with open(self.SESSIONS_FILE, 'w') as f:
                json.dump(sessions, f, indent=2)

            # Create session file
            session_file = self.SESSIONS_DIR / f"{session_id}.jsonl"
            session_header = {
                "type": "session",
                "version": 3,
                "id": session_id,
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "cwd": str(Path.home() / ".openclaw" / "workspace")
            }
            with open(session_file, 'w') as f:
                f.write(json.dumps(session_header) + "\n")

            return (session_key, session_id)

        except Exception as e:
            print(f"Warning: Failed to create fresh session: {e}")
            # Fallback to basic session
            return (session_key, session_id)

    def _cleanup_session(self, session_key: str, session_id: str) -> None:
        """Clean up a session after use."""
        try:
            # Delete session file
            session_file = self.SESSIONS_DIR / f"{session_id}.jsonl"
            if session_file.exists():
                session_file.unlink()

            # Remove from sessions.json
            if self.SESSIONS_FILE.exists():
                with open(self.SESSIONS_FILE, 'r') as f:
                    sessions = json.load(f)

                if session_key in sessions:
                    del sessions[session_key]
                    with open(self.SESSIONS_FILE, 'w') as f:
                        json.dump(sessions, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to clean up session: {e}")

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
                # Connect if not already connected
                if not self._connected:
                    connected = await self.connect()
                    if not connected:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        raise Exception("Failed to connect to Moltbot")

                # Acquire slot from semaphore (limits concurrency)
                async with self._session_semaphore:
                    # Create fresh session for this request
                    session_key, session_id = self._create_fresh_session()

                    try:
                        response = await self._send_chat_request(messages, session_key, session_id)
                        return response
                    finally:
                        # Clean up session after use
                        self._cleanup_session(session_key, session_id)

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if it's a retryable error
                is_connection_error = any(x in error_str for x in ["connection", "restart", "closed", "keepalive", "ping timeout", "1011"])
                is_empty_response = "empty response" in error_str

                if is_connection_error or is_empty_response:
                    if attempt < max_retries - 1:
                        if is_connection_error:
                            # Reset connection state for connection errors
                            self._connected = False
                        if is_empty_response:
                            print(f"Warning: Empty response on attempt {attempt + 1}, retrying...")
                        await asyncio.sleep(2 ** attempt)
                        continue

                # Not a retryable error, raise immediately
                raise

        # All retries exhausted
        raise Exception(f"Failed after {max_retries} attempts: {last_error}")

    async def _send_chat_request(self, messages: List[Dict[str, str]], session_key: str, session_id: str) -> str:
        """Internal method to send chat request without retry logic."""

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

        # Create queue for this request, store with both req_id and session_key
        message_queue = asyncio.Queue(maxsize=100)
        self._pending_requests[req_id] = {
            "queue": message_queue,
            "session_key": session_key,
            "run_id": None
        }

        try:
            await self._ws.send(json.dumps(request))

            # Wait for initial response and events
            initial_response_received = False
            response_content = []
            timeout_start = asyncio.get_event_loop().time()
            request_info = self._pending_requests[req_id]

            while True:
                try:
                    # Calculate remaining timeout
                    elapsed = asyncio.get_event_loop().time() - timeout_start
                    remaining_timeout = self.timeout - elapsed
                    if remaining_timeout <= 0:
                        raise asyncio.TimeoutError()

                    data = await asyncio.wait_for(request_info["queue"].get(), timeout=remaining_timeout)

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
                    # Provide more context about what we were waiting for
                    if initial_response_received:
                        raise Exception("Timeout waiting for final response content (got initial response but no content)")
                    else:
                        raise Exception("Timeout waiting for Moltbot response (no initial response received)")

        finally:
            # Clean up pending request
            if req_id in self._pending_requests:
                del self._pending_requests[req_id]

        response = "".join(response_content) if response_content else ""

        # Validate response is not empty
        if not response or not response.strip():
            raise Exception(
                f"Received empty response from Moltbot (session: {session_key}). "
                "This may indicate an error in the agent or the request."
            )

        # Note: Session cleanup happens in chat() finally block
        return response

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

        # Cancel receiver task
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        # Clear pending requests
        self._pending_requests.clear()
