from .base import BaseProvider

class GroqProvider(BaseProvider):
    provider_name = "groq"

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        super().__init__(api_key, model, "https://api.groq.com/openai/v1", timeout=timeout)
