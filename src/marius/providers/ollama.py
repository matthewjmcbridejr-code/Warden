import httpx
import logging
import json
import os
from typing import Dict, Any, List, Optional, AsyncGenerator

logger = logging.getLogger(__name__)

class OllamaProvider:
    provider_name = "ollama"

    def __init__(self, model: str, base_url: str = None, timeout: int = 90):
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Return a non-streaming completion using native /api/chat."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 256),
            }
        }
        
        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        content = data.get("message", {}).get("content", "")
        
        return {
            "choices": [{
                "message": {"content": content, "role": "assistant"},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            }
        }

    async def stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """Stream responses from Ollama's native /api/chat as OpenAI-like SSE."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 256),
            }
        }
        
        async with self.client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)
                    
                    # Wrap in OpenAI-like format
                    openai_chunk = {
                        "choices": [{
                            "delta": {"content": content} if not done else {},
                            "finish_reason": "stop" if done else None
                        }]
                    }
                    yield f"data: {json.dumps(openai_chunk)}\n\n"
                    if done:
                        yield "data: [DONE]\n\n"
                except json.JSONDecodeError:
                    continue

    async def cleanup(self):
        await self.client.aclose()
