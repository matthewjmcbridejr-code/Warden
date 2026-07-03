from .base import BaseProvider

class GeminiProvider(BaseProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        # Gemini OpenAI-compatible base URL
        super().__init__(api_key, model, "https://generativelanguage.googleapis.com/v1beta/openai", timeout=timeout)
