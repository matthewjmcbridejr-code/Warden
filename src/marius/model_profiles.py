from typing import Dict, Any, List, Optional

MODEL_PROFILES = {
    "fast": {
        "models": ["llama3.2:1b", "gemma3:1b", "qwen3:0.6b"],
        "max_tokens": 128,
        "temperature": 0.2,
        "timeout": 45,
    },
    "balanced": {
        "models": ["llama3.2:3b", "marius-default", "qwen3:4b"],
        "max_tokens": 192,
        "temperature": 0.25,
        "timeout": 90,
    },
    "code": {
        "models": ["marius-code-local", "qwen2.5-coder:3b", "qwen2.5:7b-instruct-2k"],
        "max_tokens": 256,
        "temperature": 0.15,
        "timeout": 120,
    },
    "deep": {
        "models": ["qwen3:4b", "qwen2.5:7b-instruct-2k", "qwen2.5:7b-instruct"],
        "max_tokens": 384,
        "temperature": 0.15,
        "timeout": 180,
    }
}

DEFAULT_PROFILE = "fast"

ROUTER_MODELS = ["marius-fast"]
EMBEDDING_MODELS = ["mxbai-embed-large"]

SYSTEM_PROMPTS = {
    "fast": "You are Marius, the current operator's local terminal resident assistant. Be terse. Route, classify, summarize. Do not invent project facts. No commands unless requested.",
    "balanced": "You are Marius, the current operator's local terminal resident assistant. Be concise by default. Answer in 2-5 sentences unless asked for detail. Prefer exact next actions. Do not invent project facts. Do not claim files or services changed unless proven by command output. Prefer safe inspection before modification. Do not suggest destructive git commands unless explicitly requested and risk is flagged. Do not suggest sudo or service restarts by default. For coding/devops, give commands only when asked or clearly useful. Never expose secrets. Never reveal hidden chain-of-thought.",
    "code": "You are Marius. Explain code/diffs. Draft implementation prompts. Identify likely bugs. No destructive git commands. No service restarts. Escalate real implementation to Codex/Gemini/AGY when appropriate.",
    "deep": "You are Marius. Think carefully, but only return final concise reasoning summary. Do not reveal hidden chain-of-thought. Prefer uncertainty over invented facts.",
    "default": "You are Marius, the current operator's local terminal resident assistant. Be concise by default. Answer in 2-5 sentences unless asked for detail. Prefer exact next actions. Do not invent project facts. Do not claim files or services changed unless proven by command output. Prefer safe inspection before modification. Do not suggest destructive git commands unless explicitly requested and risk is flagged. Do not suggest sudo or service restarts by default. For coding/devops, give commands only when asked or clearly useful. Never expose secrets. Never reveal hidden chain-of-thought."
}

def get_profile(name: str) -> Dict[str, Any]:
    return MODEL_PROFILES.get(name, MODEL_PROFILES[DEFAULT_PROFILE])

def get_system_prompt(profile_name: str) -> str:
    return SYSTEM_PROMPTS.get(profile_name, SYSTEM_PROMPTS["default"])

# Cloud provider candidates per profile — tried in order, first with a valid API key wins.
# Model names use LiteLLM's provider/model format.
CLOUD_PROFILES: dict[str, list[dict]] = {
    "fast": [
        {"provider": "groq",       "model": "groq/llama-3.1-8b-instant",            "env": "GROQ_API_KEY"},
        {"provider": "cerebras",   "model": "cerebras/llama3.1-8b",                  "env": "CEREBRAS_API_KEY"},
        {"provider": "openrouter", "model": "openrouter/google/gemma-3-12b-it:free", "env": "OPENROUTER_API_KEY"},
    ],
    "balanced": [
        {"provider": "groq",       "model": "groq/llama-3.3-70b-versatile",               "env": "GROQ_API_KEY"},
        {"provider": "cerebras",   "model": "cerebras/llama-3.3-70b",                      "env": "CEREBRAS_API_KEY"},
        {"provider": "openrouter", "model": "openrouter/qwen/qwen3-235b-a22b:free",        "env": "OPENROUTER_API_KEY"},
    ],
    "code": [
        {"provider": "openrouter", "model": "openrouter/qwen/qwen2.5-coder-32b-instruct:free", "env": "OPENROUTER_API_KEY"},
        {"provider": "groq",       "model": "groq/llama-3.3-70b-versatile",                    "env": "GROQ_API_KEY"},
    ],
    "deep": [
        {"provider": "openrouter", "model": "openrouter/qwen/qwen3-235b-a22b:free", "env": "OPENROUTER_API_KEY"},
        {"provider": "groq",       "model": "groq/llama-3.3-70b-versatile",         "env": "GROQ_API_KEY"},
        {"provider": "huggingface","model": "huggingface/Qwen/Qwen2.5-72B-Instruct","env": "HF_TOKEN"},
    ],
}

# Best tool-calling model per available key (for WardenAgent)
TOOL_CALL_CLOUD_CANDIDATES = [
    {"provider": "groq",       "model": "groq/llama-3.3-70b-versatile", "env": "GROQ_API_KEY"},
    {"provider": "cerebras",   "model": "cerebras/llama-3.3-70b",        "env": "CEREBRAS_API_KEY"},
    {"provider": "openrouter", "model": "openrouter/qwen/qwen3-235b-a22b:free", "env": "OPENROUTER_API_KEY"},
]

KNOWN_MODELS = [
    "marius-fast", "marius-default", "marius-code-local",
    "llama3.2:1b", "llama3.2:3b", "qwen3:0.6b", "qwen3:4b", "gemma3:1b",
    "qwen2.5-coder:3b", "qwen2.5:7b", "qwen2.5:7b-instruct", "qwen2.5:7b-instruct-2k",
    "mxbai-embed-large"
]
