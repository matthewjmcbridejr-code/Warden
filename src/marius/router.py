import requests
import json
import os
from typing import Tuple, Optional, Dict, Any, List

def get_ollama_urls() -> Tuple[str, str, str]:
    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    return base_url, f"{base_url}/api/chat", f"{base_url}/api/tags"

def chat_completion(prompt: str, model: Optional[str] = None) -> Tuple[str, str, str]:
    base_url, chat_url, _ = get_ollama_urls()
    target_model = model or os.getenv("MARIUS_OLLAMA_MODEL", "llama3.2:3b")
    
    # Separate timeouts: Health is short, Chat is long
    chat_timeout = int(os.getenv("MARIUS_OLLAMA_CHAT_TIMEOUT", "90"))
    
    try:
        response = requests.post(
            chat_url,
            json={
                "model": target_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=chat_timeout
        )
        if response.status_code == 200:
            try:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                return content, "ollama", target_model
            except json.JSONDecodeError:
                reason = "ollama_bad_response"
                error_msg = "Ollama returned a malformed response (invalid JSON)."
        elif response.status_code == 404:
            reason = "model_not_found"
            error_msg = f"Model '{target_model}' not found in Ollama. Try 'ollama pull {target_model}'."
        else:
            reason = f"http_{response.status_code}"
            error_msg = f"Ollama returned HTTP {response.status_code}."
    except requests.exceptions.Timeout:
        reason = "ollama_timeout"
        error_msg = f"Ollama chat timed out after {chat_timeout}s while using {target_model}. Try a smaller model or increase MARIUS_OLLAMA_CHAT_TIMEOUT."
    except requests.exceptions.ConnectionError:
        reason = "connection_refused"
        error_msg = "Could not connect to Ollama. Ensure it is running at " + base_url
    except Exception as e:
        reason = "unknown_error"
        error_msg = f"Ollama error: {str(e)}"
    
    return (f"{error_msg}\n[provider: fallback | reason: {reason}]", "fallback", "")

def test_ollama_model() -> Dict[str, Any]:
    import time
    base_url, chat_url, _ = get_ollama_urls()
    target_model = os.getenv("MARIUS_OLLAMA_MODEL", "llama3.2:3b")
    chat_timeout = int(os.getenv("MARIUS_OLLAMA_CHAT_TIMEOUT", "90"))
    
    start_time = time.time()
    try:
        response = requests.post(
            chat_url,
            json={
                "model": target_model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "stream": False
            },
            timeout=chat_timeout
        )
        elapsed = int((time.time() - start_time) * 1000)
        
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "").strip()
            ok = "OK" in content
            return {
                "ok": ok,
                "provider": "ollama",
                "model": target_model,
                "elapsed_ms": elapsed,
                "response": content
            }
        else:
            return {
                "ok": False,
                "provider": "ollama",
                "model": target_model,
                "elapsed_ms": elapsed,
                "reason": f"http_{response.status_code}",
                "error": response.text[:100]
            }
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        reason = "timeout" if isinstance(e, requests.exceptions.Timeout) else "error"
        return {
            "ok": False,
            "provider": "ollama",
            "model": target_model,
            "elapsed_ms": elapsed,
            "reason": reason,
            "error": str(e)
        }

def get_ollama_diagnostics() -> Dict[str, Any]:
    base_url, _, tags_url = get_ollama_urls()
    reachable = False
    available_models = []
    configured_model = os.getenv("MARIUS_OLLAMA_MODEL", "llama3.2:3b")
    health_timeout = int(os.getenv("MARIUS_OLLAMA_HEALTH_TIMEOUT", "2"))
    
    try:
        resp = requests.get(tags_url, timeout=health_timeout)
        if resp.status_code == 200:
            reachable = True
            available_models = [m.get("name") for m in resp.json().get("models", [])]
    except Exception:
        pass
    
    return {
        "ollama_reachable": reachable,
        "ollama_url": base_url,
        "configured_model": configured_model,
        "available_models": available_models,
        "active_provider": "ollama" if reachable else "fallback"
    }

def create_handoff_prompt(target: str, context: str) -> str:
    prompts = {
        "codex": f"--- CODEX HANDOFF ---\nContext: {context}\n\nTask: Please continue the development based on the above context.",
        "grok": f"--- GROK HANDOFF ---\nContext: {context}\n\nHey Grok, here is where I am. Can you take it from here?",
        "antigravity": f"--- ANTIGRAVITY HANDOFF ---\nContext: {context}\n\nExecute mission with following constraints: {context}",
    }
    return prompts.get(target.lower(), f"--- GENERIC HANDOFF ---\nContext: {context}")
