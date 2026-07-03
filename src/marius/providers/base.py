import os
import httpx
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator

logger = logging.getLogger(__name__)

class BaseProvider:
    provider_name = "generic"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Return a non-streaming completion."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            **kwargs
        }
        
        resp = await self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """Stream responses in OpenAI format."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        async with self.client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    yield line

    async def cleanup(self):
        await self.client.aclose()
