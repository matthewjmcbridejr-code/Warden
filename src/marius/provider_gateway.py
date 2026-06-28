import os
import logging
import httpx
import json
import time
from typing import Dict, Any, List, Optional, AsyncGenerator, Union
from .providers.ollama import OllamaProvider
from .providers.openrouter import OpenRouterProvider
from .providers.groq import GroqProvider
from .providers.gemini import GeminiProvider
from .model_profiles import get_profile, get_system_prompt, DEFAULT_PROFILE, EMBEDDING_MODELS, CLOUD_PROFILES
from .grounding import get_grounding_pack
from .memory import get_where_left_off
from .brain_context import build_brain_context_pack
from .config import get_config
from .calculator import safe_calc, is_math_query

logger = logging.getLogger(__name__)

class ProviderGateway:
    def __init__(self):
        self.config = get_config()
        self.mode = os.getenv("MARIUS_PROVIDER_MODE") or self.config.get("provider", "local").lower()
        self.allow_cloud = os.getenv("MARIUS_ALLOW_CLOUD", "0") == "1"
        self.current_profile = os.getenv("MARIUS_MODEL_PROFILE") or self.config.get("profile", DEFAULT_PROFILE).lower()
        self.forced_model = os.getenv("MARIUS_MODEL") or os.getenv("MARIUS_OLLAMA_MODEL") or self.config.get("model")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        
        # Chat Mode / Context limits
        self.chat_mode = os.getenv("MARIUS_CHAT_MODE", "fast").lower()
        self.brain_context_enabled = os.getenv("MARIUS_BRAIN_CONTEXT", "1") == "1"
        
        # Defaults for context pack
        mode_limits = {
            "fast": {"max_records": 2, "max_chars": 800},
            "balanced": {"max_records": 4, "max_chars": 1800},
            "deep": {"max_records": 6, "max_chars": 3500}
        }
        limits = mode_limits.get(self.chat_mode, mode_limits["fast"])
        self.max_brain_records = int(os.getenv("MARIUS_BRAIN_MAX_RECORDS", str(limits["max_records"])))
        self.max_brain_chars = int(os.getenv("MARIUS_BRAIN_MAX_CHARS", str(limits["max_chars"])))

    async def get_available_ollama_models(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{self.ollama_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    return [m.get("name") for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    async def resolve_model_and_provider(self) -> tuple:
        """Resolve which model and provider to use based on mode and profile."""
        profile = get_profile(self.current_profile)
        available_ollama = await self.get_available_ollama_models()
        
        fallback_reason = None
        requested_model = self.forced_model

        # Priority 1: Forced model
        if self.forced_model:
            if self.forced_model in available_ollama or f"{self.forced_model}:latest" in available_ollama:
                return "ollama", self.forced_model, profile, None
            else:
                # User explicitly set a model but it's not there.
                fallback_reason = f"requested model '{self.forced_model}' not installed"
                # If we have a requested model that is missing, we SHOULD NOT silently fallback 
                # unless we want to, but the user mission says: 
                # "Do not silently choose llama if the user explicitly set qwen."
                # However, for the chat() method to work, we might need a fallback.
                # Let's see. Phase 2 says: "fail clearly with: Model not installed. Run: ollama pull <model>"
                # This suggests the chat() method should return an error if forced model is missing.
                return "fallback", self.forced_model, profile, fallback_reason

        # Priority 2: Resolve from profile models (Local preferred)
        if self.mode in ["local", "auto"]:
            for model in profile["models"]:
                if model in available_ollama or f"{model}:latest" in available_ollama:
                    return "ollama", model, profile, None

        # Priority 3: Cloud (if enabled and mode is cloud/auto)
        if (self.mode in ["cloud", "auto"]) and self.allow_cloud:
            candidates = CLOUD_PROFILES.get(self.current_profile, CLOUD_PROFILES["fast"])
            for cand in candidates:
                if os.getenv(cand["env"]):
                    return cand["provider"], cand["model"], profile, None

        # Priority 4: Fallback for local: use the first available model that isn't an embedding model
        if self.mode in ["local", "auto"]:
            for model in available_ollama:
                if model not in EMBEDDING_MODELS and not any(m in model for m in EMBEDDING_MODELS):
                    return "ollama", model, profile, "profile models missing"

        # Ultimate fallback
        if available_ollama:
            return "ollama", "llama3.2:3b", profile, "all preferences missing"

        return "fallback", "none", profile, "ollama unreachable"

    async def chat(self, prompt: str, history: List[Dict[str, str]] = None, workspace: Dict[str, Any] = None, brain_enabled: Optional[bool] = None) -> Dict[str, Any]:
        from .model_profiles import ROUTER_MODELS, EMBEDDING_MODELS
        
        requested_model = self.forced_model or "auto"
        
        # Override if passed
        current_brain_enabled = self.brain_context_enabled if brain_enabled is None else brain_enabled
        
        # 0. Calculator Route
        if is_math_query(prompt):
            calc_res = safe_calc(prompt)
            if calc_res:
                return {
                    "response": calc_res,
                    "provider": "local_calculator",
                    "requested": requested_model,
                    "actual": "calculator",
                    "elapsed": 0
                }

        provider_name, model, profile, fallback_reason = await self.resolve_model_and_provider()
        
        if provider_name == "fallback" and fallback_reason and "not installed" in fallback_reason:
             return {
                "response": f"Model not installed. Run: ollama pull {model}",
                "provider": "fallback",
                "requested": requested_model,
                "actual": "none",
                "fallback_reason": fallback_reason,
                "elapsed": 0
            }

        auto_switch_msg = None
        # Check if the model is router-only or embedding-only
        if model in ROUTER_MODELS or model in EMBEDDING_MODELS or any(m in model for m in EMBEDDING_MODELS):
            # Auto-switch to best installed chat model
            available = await self.get_available_ollama_models()
            chat_priorities = ['llama3.2:1b', 'gemma3:1b', 'qwen3:0.6b', 'llama3.2:3b']
            target_model = None
            for m in chat_priorities:
                if m in available or f"{m}:latest" in available:
                    target_model = m
                    break
            
            if target_model:
                auto_switch_msg = f"{model} is router-only. Switched chat model to {target_model}."
                model = target_model
                provider_name = "ollama"
            else:
                return {
                    "response": f"Selected model {model} is not suitable for chat and no alternatives were found.",
                    "provider": "fallback",
                    "model": model,
                    "elapsed": 0
                }

        messages = history or []
        # Build systematic grounding context
        if not any(m["role"] == "system" for m in messages):
            # 1. Base system behavior
            system_prompt = get_system_prompt(self.current_profile)
            
            # 2. Grounding pack (Identity, Projects, Anti-hallucination)
            grounding_pack = get_grounding_pack()
            
            # 3. Recent progress / Memory context
            where_left_off = get_where_left_off()
            memory_context = f"\n## Recent Progress\n{where_left_off}\n"
            
            # 4. Workspace context
            ws_context = ""
            if workspace:
                ws_context = f"\n## Current Workspace\nRepo: {workspace.get('repo_path')}\nRunner Enabled: {workspace.get('runner_enabled')}\n"
            
            # 5. Brain Context Retrieval
            brain_pack = None
            brain_context_text = ""
            
            # Selective brain context logic
            should_run_brain = current_brain_enabled
            if should_run_brain:
                # Skip for very simple/generic prompts
                skip_keywords = ["hello", "hi", "say ok", "who are you"]
                prompt_lower = prompt.lower()
                if any(k == prompt_lower for k in skip_keywords) or len(prompt_lower) < 5:
                    should_run_brain = False
                
                # Force for project/specific keywords
                force_keywords = ["grademy", "warden", "marius", "my", "priorities", "what do you know", "what should i work on", "project", "next"]
                if any(k in prompt_lower for k in force_keywords):
                    should_run_brain = True
            
            if should_run_brain:
                # Use project from workspace if available
                target_project = workspace.get("project") if workspace else None
                brain_pack = build_brain_context_pack(prompt, project=target_project, limit=self.max_brain_records, max_chars=self.max_brain_chars)
                brain_context_text = f"\n## Brain Memory\n{brain_pack['context_text']}\n"
                brain_context_text += "Instruction: Use Brain Memory when relevant. Cite record IDs if used. Do not invent facts outside context.\n"
            
            full_system_msg = f"{system_prompt}\n\n{grounding_pack}\n\n{memory_context}\n{ws_context}\n{brain_context_text}"
            messages.insert(0, {"role": "system", "content": full_system_msg})
        
        messages.append({"role": "user", "content": prompt})

        _LITELLM_PROVIDERS = {"groq", "openrouter", "cerebras", "huggingface"}

        provider = None
        if provider_name == "ollama":
            provider = OllamaProvider(model, base_url=self.ollama_url, timeout=profile["timeout"])
        elif provider_name == "gemini":
            provider = GeminiProvider(os.getenv("GEMINI_API_KEY"), model, timeout=profile["timeout"])
        elif provider_name in _LITELLM_PROVIDERS:
            pass  # handled below via litellm
        elif provider_name == "groq":
            provider = GroqProvider(os.getenv("GROQ_API_KEY"), model, timeout=profile["timeout"])
        elif provider_name == "openrouter":
            provider = OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"), model, timeout=profile["timeout"])

        if provider_name in _LITELLM_PROVIDERS:
            try:
                import litellm
                start_time = time.time()
                resp = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=profile["temperature"],
                    max_tokens=profile["max_tokens"],
                    timeout=profile["timeout"],
                )
                elapsed = time.time() - start_time
                response_text = resp.choices[0].message.content or ""
                return {
                    "response": response_text,
                    "provider": provider_name,
                    "requested": requested_model,
                    "actual": model,
                    "elapsed": round(elapsed, 1),
                    "profile": self.current_profile,
                    "warning": auto_switch_msg,
                    "fallback_reason": fallback_reason,
                    "brain_context": {
                        "enabled": current_brain_enabled,
                        "record_ids": brain_pack["record_ids"] if brain_pack else []
                    } if current_brain_enabled else None,
                }
            except Exception as e:
                logger.warning("LiteLLM cloud call failed (%s/%s): %s", provider_name, model, e)
                return {
                    "response": f"Cloud provider error ({provider_name}): {e}",
                    "provider": "fallback",
                    "requested": requested_model,
                    "actual": model,
                    "elapsed": 0,
                }

        if provider:
            try:
                start_time = time.time()
                result = await provider.complete(
                    messages,
                    temperature=profile["temperature"],
                    max_tokens=profile["max_tokens"]
                )
                elapsed = time.time() - start_time

                response_text = result["choices"][0]["message"]["content"]
                return {
                    "response": response_text,
                    "provider": provider_name,
                    "requested": requested_model,
                    "actual": model,
                    "elapsed": round(elapsed, 1),
                    "profile": self.current_profile,
                    "warning": auto_switch_msg,
                    "fallback_reason": fallback_reason,
                    "brain_context": {
                        "enabled": current_brain_enabled,
                        "record_ids": brain_pack["record_ids"] if brain_pack else []
                    } if current_brain_enabled else None
                }
            finally:
                if hasattr(provider, "cleanup"):
                    await provider.cleanup()
        
        return {
            "response": f"No suitable provider found or configured. {fallback_reason or ''}",
            "provider": "fallback",
            "requested": requested_model,
            "actual": "none",
            "fallback_reason": fallback_reason,
            "elapsed": 0
        }

    async def benchmark(self, models: List[str] = None, quick: bool = True) -> Dict[str, Any]:
        from .benchmark import MariusBenchmark
        available = await self.get_available_ollama_models()
        target_models = models or ["marius-fast", "marius-default", "marius-code-local", "qwen3:0.6b", "gemma3:1b", "llama3.2:1b", "llama3.2:3b", "qwen2.5-coder:3b", "qwen3:4b"]
        
        valid_targets = [m for m in target_models if m in available or f"{m}:latest" in available]
        
        benchmarker = MariusBenchmark(self)
        results = await benchmarker.run_benchmark(valid_targets, quick=quick)
        recommendations = benchmarker.get_recommendations(results)
        
        return {
            "results": results,
            "recommendations": recommendations
        }
