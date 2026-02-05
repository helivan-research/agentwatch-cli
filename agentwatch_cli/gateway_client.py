"""
Client for communicating with the local Moltbot (OpenClaw) gateway.
"""

import httpx
from typing import List, Dict, Any, Optional


class GatewayClient:
    """Client for the local Moltbot/OpenClaw gateway."""

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 120.0):
        """
        Initialize the gateway client.

        Args:
            url: The gateway URL (e.g., "http://127.0.0.1:18789")
            token: The gateway authentication token
            timeout: Request timeout in seconds
        """
        self.base_url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

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
        endpoint = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                endpoint,
                headers=self._get_headers(),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        # Extract response text from OpenAI-compatible format
        choices = result.get("choices", [])
        if not choices:
            raise Exception("No response choices returned from gateway")

        return choices[0].get("message", {}).get("content", "")

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        List available models from the gateway.

        Returns:
            List of model information dicts
        """
        endpoint = f"{self.base_url}/v1/models"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                endpoint,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()

        return result.get("data", [])

    async def health_check(self) -> bool:
        """
        Check if the gateway is healthy.

        Returns:
            True if the gateway is reachable and authenticated
        """
        try:
            models = await self.list_models()
            return len(models) > 0
        except Exception:
            return False


class SyncGatewayClient:
    """Synchronous client for the local Moltbot/OpenClaw gateway."""

    def __init__(self, url: str, token: Optional[str] = None, timeout: float = 120.0):
        """
        Initialize the gateway client.

        Args:
            url: The gateway URL (e.g., "http://127.0.0.1:18789")
            token: The gateway authentication token
            timeout: Request timeout in seconds
        """
        self.base_url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def chat(
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
        endpoint = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                endpoint,
                headers=self._get_headers(),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        # Extract response text from OpenAI-compatible format
        choices = result.get("choices", [])
        if not choices:
            raise Exception("No response choices returned from gateway")

        return choices[0].get("message", {}).get("content", "")

    def health_check(self) -> bool:
        """
        Check if the gateway is healthy.

        Returns:
            True if the gateway is reachable and authenticated
        """
        try:
            endpoint = f"{self.base_url}/v1/models"
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    endpoint,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                return True
        except Exception:
            return False
