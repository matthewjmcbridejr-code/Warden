import os
from .base import BaseProvider

class OpenRouterProvider(BaseProvider):
    provider_name = "openrouter"

    def __init__(self, api_key: str, model: str, timeout: int = 45):
        super().__init__(api_key, model, "https://openrouter.ai/api/v1", timeout=timeout)

    async def complete(self, messages, **kwargs):
        # Add OpenRouter specific headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "https://marius.local"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "Marius"),
        }
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages, "stream": False, **kwargs}
        resp = await self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
