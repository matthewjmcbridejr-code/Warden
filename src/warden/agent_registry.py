"""Safe Agent Registry — bounded CLI/remote agent profiles for McHarness."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from fastapi import HTTPException
from pydantic import BaseModel, Field

BUILTIN_CODEX_ID = "codex_cli"
JULES_API_BASE = "https://jules.googleapis.com/v1alpha"
JULES_TEST_TIMEOUT_SECONDS = 5.0

AgentKind = Literal["cli", "remote"]
AgentAdapter = Literal["codex_cli", "jules_remote", "agy_cli", "custom_cli", "custom_remote"]
AgentStatus = Literal["ready", "not_configured", "disabled", "unsupported", "error", "unverified"]
ConnectionStatus = Literal["connected", "invalid_key", "not_verified", "error", "not_configured"]

SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "secret",
        "token",
        "password",
        "credential",
        "private_key",
        "openrouter_api_key",
    }
)

REGISTERABLE_ADAPTERS = frozenset({"jules_remote"})
DISABLED_TEMPLATE_ADAPTERS = frozenset({"agy_cli", "custom_cli", "custom_remote"})

_FILE_LOCK = threading.Lock()


class McHarnessAgentTestConfigRequest(BaseModel):
    adapter: Literal["jules_remote"]
    api_key: str = Field(min_length=1)
    default_repo_id: str | None = None
    default_branch: str | None = None


class McHarnessAgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: AgentKind
    adapter: AgentAdapter
    description: str = Field(default="", max_length=2000)
    capabilities: list[str] = Field(default_factory=list)
    default_repo_id: str | None = None
    default_branch: str | None = None
    require_plan_approval: bool = True
    enabled: bool = True
    api_key: str | None = None
    allow_unverified: bool = False


class McHarnessAgentPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    capabilities: list[str] | None = None
    default_repo_id: str | None = None
    default_branch: str | None = None
    require_plan_approval: bool | None = None
    enabled: bool | None = None


class McHarnessAgentConfigPatchRequest(BaseModel):
    api_key: str | None = None
    default_repo_id: str | None = None
    default_branch: str | None = None
    require_plan_approval: bool | None = None
    allow_unverified: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def agents_registry_path(root: Path) -> Path:
    return root / "agents" / "agents.json"


def agent_secret_path(root: Path, agent_id: str) -> Path:
    return root / "secrets" / f"agent_{agent_id}.json"


def agent_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "codex_cli",
            "label": "Codex CLI",
            "kind": "cli",
            "adapter": "codex_cli",
            "registerable": False,
            "runnable": True,
            "builtin": True,
            "requires_config": False,
            "description": "OpenAI Codex CLI via the existing private tmux runner.",
        },
        {
            "id": "jules_remote",
            "label": "Jules Remote",
            "kind": "remote",
            "adapter": "jules_remote",
            "registerable": True,
            "runnable": False,
            "builtin": False,
            "requires_config": True,
            "description": "Configure Jules Remote for planning and status. Execution comes next.",
        },
        {
            "id": "agy_cli",
            "label": "AGY CLI Coming Later",
            "kind": "cli",
            "adapter": "agy_cli",
            "registerable": False,
            "runnable": False,
            "builtin": False,
            "requires_config": False,
            "description": "Planned AGY / Antigravity CLI adapter. Not available yet.",
        },
        {
            "id": "custom_cli",
            "label": "Custom CLI Coming Later",
            "kind": "cli",
            "adapter": "custom_cli",
            "registerable": False,
            "runnable": False,
            "builtin": False,
            "requires_config": False,
            "description": "Custom CLI adapters are disabled to prevent arbitrary shell execution.",
        },
        {
            "id": "custom_remote",
            "label": "Custom Remote Coming Later",
            "kind": "remote",
            "adapter": "custom_remote",
            "registerable": False,
            "runnable": False,
            "builtin": False,
            "requires_config": False,
            "description": "Custom remote adapters are disabled in this version.",
        },
    ]


def _ensure_registry_dir(root: Path) -> None:
    agents_registry_path(root).parent.mkdir(parents=True, exist_ok=True)


def _ensure_secrets_dir(root: Path) -> Path:
    secrets_dir = root / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(secrets_dir, 0o700)
    except Exception:
        pass
    return secrets_dir


def _load_registry_document(root: Path) -> dict[str, Any]:
    path = agents_registry_path(root)
    if not path.exists():
        return {"version": 1, "agents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Agent registry file is unreadable.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Agent registry file has invalid shape.")
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise HTTPException(status_code=500, detail="Agent registry file has invalid agents list.")
    return data


def _save_registry_document(root: Path, document: dict[str, Any]) -> None:
    _ensure_registry_dir(root)
    path = agents_registry_path(root)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def load_registered_agents(root: Path) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        document = _load_registry_document(root)
        agents = document.get("agents") or []
        return [dict(item) for item in agents if isinstance(item, dict)]


def _save_registered_agents(root: Path, agents: list[dict[str, Any]]) -> None:
    with _FILE_LOCK:
        document = _load_registry_document(root)
        document["agents"] = agents
        document["updated_at"] = _now_iso()
        _save_registry_document(root, document)


def sanitize_agent_profile(agent: dict[str, Any]) -> dict[str, Any]:
    """Return a safe public view of an agent profile with no secret fields."""
    clean: dict[str, Any] = {}
    for key, value in agent.items():
        lowered = key.lower()
        if lowered in SECRET_FIELD_NAMES or "secret" in lowered or "api_key" in lowered:
            continue
        clean[key] = value
    return clean


def _validate_jules_api_key_format(api_key: str) -> None:
    key = (api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Jules API key is required.")
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="Jules API key looks too short.")


def _write_agent_secret(root: Path, agent_id: str, *, adapter: str, api_key: str) -> None:
    _ensure_secrets_dir(root)
    path = agent_secret_path(root, agent_id)
    payload = {
        "adapter": adapter,
        "api_key": api_key.strip(),
        "updated_at": _now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _read_agent_secret(root: Path, agent_id: str) -> dict[str, Any] | None:
    path = agent_secret_path(root, agent_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _delete_agent_secret(root: Path, agent_id: str) -> bool:
    path = agent_secret_path(root, agent_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def agent_has_secret(root: Path, agent_id: str) -> bool:
    secret = _read_agent_secret(root, agent_id)
    return bool((secret or {}).get("api_key"))


def test_jules_remote_config(
    *,
    api_key: str,
    default_repo_id: str | None = None,
    default_branch: str | None = None,
) -> dict[str, Any]:
    _validate_jules_api_key_format(api_key)
    request = URLRequest(
        f"{JULES_API_BASE}/sources?pageSize=1",
        headers={"x-goog-api-key": api_key.strip()},
        method="GET",
    )
    try:
        with urlopen(request, timeout=JULES_TEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
            sources = payload.get("sources") if isinstance(payload, dict) else None
            source_count = len(sources) if isinstance(sources, list) else 0
            safe_details: dict[str, Any] = {"sources_count": source_count}
            if default_repo_id:
                safe_details["default_repo_id"] = default_repo_id
            if default_branch:
                safe_details["default_branch"] = default_branch
            return {
                "ok": True,
                "adapter": "jules_remote",
                "status": "connected",
                "message": "Jules API key verified via sources list.",
                "safe_details": safe_details,
            }
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return {
                "ok": True,
                "adapter": "jules_remote",
                "status": "invalid_key",
                "message": "Jules API rejected the API key.",
                "safe_details": {},
            }
        return {
            "ok": True,
            "adapter": "jules_remote",
            "status": "error",
            "message": f"Jules API returned HTTP {exc.code}.",
            "safe_details": {},
        }
    except URLError:
        return {
            "ok": True,
            "adapter": "jules_remote",
            "status": "error",
            "message": "Could not reach Jules API.",
            "safe_details": {},
        }
    except Exception:
        return {
            "ok": True,
            "adapter": "jules_remote",
            "status": "error",
            "message": "Jules API verification failed.",
            "safe_details": {},
        }


def test_agent_config(payload: McHarnessAgentTestConfigRequest) -> dict[str, Any]:
    if payload.adapter != "jules_remote":
        raise HTTPException(status_code=400, detail="Only jules_remote test-config is supported in this version.")
    return test_jules_remote_config(
        api_key=payload.api_key,
        default_repo_id=payload.default_repo_id,
        default_branch=payload.default_branch,
    )


def _codex_capabilities() -> list[str]:
    return ["live_terminal", "code_editing", "tests", "read_only_inspection"]


def _jules_default_capabilities() -> list[str]:
    return ["remote_planning", "status_tracking"]


def build_builtin_codex_profile(
    *,
    codex_runner_ready: bool,
    private_only: bool,
) -> dict[str, Any]:
    now = _now_iso()
    status: AgentStatus = "ready" if codex_runner_ready else "disabled"
    return {
        "id": BUILTIN_CODEX_ID,
        "name": "Codex CLI",
        "kind": "cli",
        "adapter": "codex_cli",
        "enabled": True,
        "private_only": private_only,
        "builtin": True,
        "user_created": False,
        "description": "OpenAI Codex CLI for code generation and edits via the private tmux runner.",
        "capabilities": _codex_capabilities(),
        "default_repo_id": None,
        "default_branch": None,
        "require_plan_approval": True,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "connection_status": "connected" if codex_runner_ready else "not_configured",
        "configured": True,
        "runnable": codex_runner_ready,
        "lane_id": BUILTIN_CODEX_ID,
    }


def _jules_profile_status(agent: dict[str, Any], *, has_secret: bool) -> AgentStatus:
    connection_status = str(agent.get("connection_status") or "")
    if not has_secret:
        return "not_configured"
    if connection_status == "connected":
        return "ready"
    if connection_status == "unverified":
        return "unverified"
    if connection_status == "invalid_key":
        return "error"
    return "not_configured"


def _jules_connection_status(agent: dict[str, Any], *, has_secret: bool) -> ConnectionStatus:
    if not has_secret:
        return "not_configured"
    stored = str(agent.get("connection_status") or "not_configured")
    if stored in {"connected", "unverified", "invalid_key", "error", "not_configured"}:
        return stored  # type: ignore[return-value]
    return "not_configured"


def _status_for_registered(agent: dict[str, Any], *, codex_runner_ready: bool, root: Path | None = None) -> AgentStatus:
    adapter = str(agent.get("adapter") or "")
    enabled = bool(agent.get("enabled", True))
    if adapter in DISABLED_TEMPLATE_ADAPTERS:
        return "unsupported"
    if adapter == "codex_cli":
        return "ready" if codex_runner_ready and enabled else "disabled"
    if adapter == "jules_remote":
        has_secret = agent_has_secret(root, str(agent.get("id") or "")) if root is not None else bool(agent.get("configured"))
        if not enabled:
            return "disabled"
        return _jules_profile_status(agent, has_secret=has_secret)
    return "unsupported"


def _runnable_for_agent(agent: dict[str, Any], *, codex_runner_ready: bool) -> bool:
    if not bool(agent.get("enabled", True)):
        return False
    adapter = str(agent.get("adapter") or "")
    if adapter == "codex_cli":
        return codex_runner_ready
    return False


def enrich_agent_profile(agent: dict[str, Any], *, codex_runner_ready: bool, root: Path | None = None) -> dict[str, Any]:
    enriched = sanitize_agent_profile(dict(agent))
    if enriched.get("builtin"):
        enriched["status"] = "ready" if codex_runner_ready else "disabled"
        enriched["connection_status"] = "connected" if codex_runner_ready else "not_configured"
        enriched["configured"] = True
        enriched["runnable"] = codex_runner_ready
        enriched["lane_id"] = BUILTIN_CODEX_ID
    else:
        agent_id = str(enriched.get("id") or "")
        has_secret = agent_has_secret(root, agent_id) if root is not None else bool(enriched.get("configured"))
        enriched["configured"] = has_secret
        enriched["connection_status"] = _jules_connection_status(enriched, has_secret=has_secret) if enriched.get("adapter") == "jules_remote" else enriched.get("connection_status")
        enriched["status"] = _status_for_registered(enriched, codex_runner_ready=codex_runner_ready, root=root)
        enriched["runnable"] = _runnable_for_agent(enriched, codex_runner_ready=codex_runner_ready)
        adapter = str(enriched.get("adapter") or "")
        enriched["lane_id"] = BUILTIN_CODEX_ID if adapter == "codex_cli" else None
    return enriched


def list_all_agents(root: Path, *, codex_runner_ready: bool, private_only: bool) -> list[dict[str, Any]]:
    builtin = build_builtin_codex_profile(codex_runner_ready=codex_runner_ready, private_only=private_only)
    registered = [
        enrich_agent_profile(item, codex_runner_ready=codex_runner_ready, root=root)
        for item in load_registered_agents(root)
    ]
    
    marius_agent = None
    try:
        from src.marius.api import gateway, get_ollama_diagnostics
        diag = get_ollama_diagnostics()
        online = diag.get("ollama_reachable", False)
        
        marius_agent = {
            "id": "marius",
            "name": "Marius Local Agent",
            "kind": "resident_local_agent",
            "adapter": "resident_local_agent",
            "status": "ready" if online else "error",
            "provider": "ollama",
            "model": gateway.forced_model or "auto",
            "profile": gateway.current_profile,
            "description": "Local terminal resident assistant on McServer",
            "capabilities": [
                "local_chat",
                "model_profiles",
                "ollama_benchmark",
                "memory_recall",
                "safe_command_planning",
                "agent_handoff_prompts"
            ],
            "enabled": True,
            "runnable": False, # Prevent running via generic worker flow
            "connection_status": "connected" if online else "error",
            "configured": True,
            "lane_id": None
        }
    except ImportError:
        pass

    if marius_agent:
        return [builtin, marius_agent, *registered]
    return [builtin, *registered]


def get_agent_by_id(root: Path, agent_id: str, *, codex_runner_ready: bool, private_only: bool) -> dict[str, Any] | None:
    for agent in list_all_agents(root, codex_runner_ready=codex_runner_ready, private_only=private_only):
        if agent.get("id") == agent_id:
            return agent
    return None


def validate_create_request(payload: McHarnessAgentCreateRequest) -> None:
    if payload.adapter == BUILTIN_CODEX_ID or payload.adapter == "codex_cli":
        raise HTTPException(status_code=400, detail="Codex CLI is built-in and cannot be registered again.")
    if payload.adapter in DISABLED_TEMPLATE_ADAPTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Adapter '{payload.adapter}' is not available for registration in this version.",
        )
    if payload.adapter not in REGISTERABLE_ADAPTERS:
        raise HTTPException(status_code=400, detail=f"Adapter '{payload.adapter}' is not supported for registration.")
    template = next((item for item in agent_templates() if item["adapter"] == payload.adapter), None)
    if template is None:
        raise HTTPException(status_code=400, detail=f"Unknown adapter: {payload.adapter}")
    if payload.kind != template["kind"]:
        raise HTTPException(status_code=400, detail=f"Adapter '{payload.adapter}' must use kind '{template['kind']}'.")


def _resolve_jules_save_connection(
    *,
    api_key: str,
    allow_unverified: bool,
    default_repo_id: str | None,
    default_branch: str | None,
) -> ConnectionStatus:
    test_result = test_jules_remote_config(
        api_key=api_key,
        default_repo_id=default_repo_id,
        default_branch=default_branch,
    )
    status = str(test_result.get("status") or "error")
    if status == "connected":
        return "connected"
    if status == "invalid_key":
        raise HTTPException(status_code=400, detail="Jules API key was rejected. Update the key and test again.")
    if allow_unverified and status in {"error", "not_verified"}:
        return "unverified"
    if status == "error":
        raise HTTPException(status_code=502, detail=test_result.get("message") or "Jules API verification failed.")
    raise HTTPException(
        status_code=400,
        detail="Test the Jules configuration first or explicitly allow saving as unverified.",
    )


def create_registered_agent(root: Path, payload: McHarnessAgentCreateRequest) -> dict[str, Any]:
    validate_create_request(payload)
    if payload.adapter == "jules_remote":
        if not payload.api_key:
            raise HTTPException(status_code=400, detail="Jules API key is required to save this agent.")
        connection_status = _resolve_jules_save_connection(
            api_key=payload.api_key,
            allow_unverified=payload.allow_unverified,
            default_repo_id=payload.default_repo_id,
            default_branch=payload.default_branch,
        )
    else:
        connection_status = "not_configured"

    now = _now_iso()
    agent_id = f"{payload.adapter}_{uuid.uuid4().hex[:8]}"
    profile: dict[str, Any] = {
        "id": agent_id,
        "name": payload.name.strip(),
        "kind": payload.kind,
        "adapter": payload.adapter,
        "enabled": payload.enabled,
        "private_only": True,
        "builtin": False,
        "user_created": True,
        "description": (payload.description or "").strip(),
        "capabilities": list(payload.capabilities or (_jules_default_capabilities() if payload.adapter == "jules_remote" else [])),
        "default_repo_id": payload.default_repo_id,
        "default_branch": payload.default_branch,
        "require_plan_approval": payload.require_plan_approval,
        "connection_status": connection_status,
        "configured": payload.adapter == "jules_remote",
        "created_at": now,
        "updated_at": now,
    }
    agents = load_registered_agents(root)
    agents.append(profile)
    _save_registered_agents(root, agents)
    if payload.adapter == "jules_remote" and payload.api_key:
        _write_agent_secret(root, agent_id, adapter="jules_remote", api_key=payload.api_key)
    return enrich_agent_profile(profile, codex_runner_ready=False, root=root)


def update_registered_agent(root: Path, agent_id: str, payload: McHarnessAgentPatchRequest) -> dict[str, Any]:
    if agent_id == BUILTIN_CODEX_ID:
        raise HTTPException(status_code=400, detail="Built-in Codex profile metadata cannot be changed through the registry.")
    agents = load_registered_agents(root)
    index = next((idx for idx, item in enumerate(agents) if item.get("id") == agent_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    agent = dict(agents[index])
    if payload.name is not None:
        agent["name"] = payload.name.strip()
    if payload.description is not None:
        agent["description"] = payload.description.strip()
    if payload.capabilities is not None:
        agent["capabilities"] = list(payload.capabilities)
    if payload.default_repo_id is not None:
        agent["default_repo_id"] = payload.default_repo_id or None
    if payload.default_branch is not None:
        agent["default_branch"] = payload.default_branch or None
    if payload.require_plan_approval is not None:
        agent["require_plan_approval"] = payload.require_plan_approval
    if payload.enabled is not None:
        agent["enabled"] = payload.enabled
    agent["updated_at"] = _now_iso()
    agents[index] = agent
    _save_registered_agents(root, agents)
    return enrich_agent_profile(agent, codex_runner_ready=False, root=root)


def update_registered_agent_config(root: Path, agent_id: str, payload: McHarnessAgentConfigPatchRequest) -> dict[str, Any]:
    if agent_id == BUILTIN_CODEX_ID:
        raise HTTPException(status_code=400, detail="Built-in Codex profile cannot be reconfigured through the registry.")
    agents = load_registered_agents(root)
    index = next((idx for idx, item in enumerate(agents) if item.get("id") == agent_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    agent = dict(agents[index])
    if agent.get("adapter") != "jules_remote":
        raise HTTPException(status_code=400, detail="Only Jules Remote agents support configuration updates in this version.")

    if payload.default_repo_id is not None:
        agent["default_repo_id"] = payload.default_repo_id or None
    if payload.default_branch is not None:
        agent["default_branch"] = payload.default_branch or None
    if payload.require_plan_approval is not None:
        agent["require_plan_approval"] = payload.require_plan_approval

    if payload.api_key:
        connection_status = _resolve_jules_save_connection(
            api_key=payload.api_key,
            allow_unverified=payload.allow_unverified,
            default_repo_id=agent.get("default_repo_id"),
            default_branch=agent.get("default_branch"),
        )
        agent["connection_status"] = connection_status
        agent["configured"] = True
        _write_agent_secret(root, agent_id, adapter="jules_remote", api_key=payload.api_key)

    agent["updated_at"] = _now_iso()
    agents[index] = agent
    _save_registered_agents(root, agents)
    return enrich_agent_profile(agent, codex_runner_ready=False, root=root)


def delete_registered_agent(root: Path, agent_id: str) -> dict[str, Any]:
    if agent_id == BUILTIN_CODEX_ID:
        raise HTTPException(status_code=400, detail="Built-in Codex profile cannot be deleted.")
    agents = load_registered_agents(root)
    remaining = [item for item in agents if item.get("id") != agent_id]
    if len(remaining) == len(agents):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    _save_registered_agents(root, remaining)
    _delete_agent_secret(root, agent_id)
    return {"ok": True, "deleted_id": agent_id}


def agent_status_payload(
    agent: dict[str, Any],
    *,
    codex_runner_ready: bool,
    root: Path | None = None,
    probe_codex: Callable[[], dict[str, Any]] | None = None,
    last_checked_at: str | None = None,
) -> dict[str, Any]:
    enriched = enrich_agent_profile(agent, codex_runner_ready=codex_runner_ready, root=root)
    payload: dict[str, Any] = {
        "id": enriched["id"],
        "name": enriched["name"],
        "adapter": enriched["adapter"],
        "status": enriched["status"],
        "connection_status": enriched.get("connection_status"),
        "configured": enriched.get("configured", False),
        "runnable": enriched["runnable"],
        "enabled": enriched.get("enabled", True),
        "notes": [],
        "last_checked_at": last_checked_at,
    }
    adapter = str(enriched.get("adapter") or "")
    if adapter == "codex_cli" and probe_codex is not None:
        probe = probe_codex()
        payload["probe"] = probe
        if probe.get("installed"):
            payload["notes"].append("Codex executable detected.")
        else:
            payload["notes"].append("Codex executable not detected on host.")
    elif adapter == "jules_remote":
        connection_status = enriched.get("connection_status")
        if connection_status == "connected":
            payload["notes"].append("Jules API key verified. Execution support comes next.")
        elif connection_status == "unverified":
            payload["notes"].append("Jules profile saved without live API verification.")
        elif connection_status == "invalid_key":
            payload["notes"].append("Stored Jules API key was rejected by Jules API.")
        else:
            payload["notes"].append("Jules Remote is configured for planning/status only. Execution comes next.")
    return sanitize_agent_profile(payload)


def probe_agent(
    agent: dict[str, Any],
    *,
    codex_runner_ready: bool,
    root: Path | None = None,
    probe_codex: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checked_at = _now_iso()
    adapter = str(agent.get("adapter") or "")
    if adapter == "codex_cli":
        if probe_codex is None:
            raise HTTPException(status_code=503, detail="Codex probe is unavailable.")
        probe = probe_codex()
        return {
            "id": agent.get("id"),
            "adapter": adapter,
            "status": "ready" if probe.get("installed") and codex_runner_ready else "disabled",
            "runnable": bool(probe.get("installed") and codex_runner_ready),
            "probe": probe,
            "last_checked_at": checked_at,
            "notes": ["Probe checks executable presence only. No run was started."],
        }
    if adapter == "jules_remote":
        agent_id = str(agent.get("id") or "")
        secret = _read_agent_secret(root, agent_id) if root is not None else None
        api_key = (secret or {}).get("api_key") if secret else None
        if not api_key:
            return {
                "id": agent.get("id"),
                "adapter": adapter,
                "status": "not_configured",
                "connection_status": "not_configured",
                "runnable": False,
                "last_checked_at": checked_at,
                "notes": ["Jules API key is not configured for this agent."],
            }
        test_result = test_jules_remote_config(
            api_key=str(api_key),
            default_repo_id=agent.get("default_repo_id"),
            default_branch=agent.get("default_branch"),
        )
        status = str(test_result.get("status") or "error")
        return {
            "id": agent.get("id"),
            "adapter": adapter,
            "status": "ready" if status == "connected" else status,
            "connection_status": status,
            "runnable": False,
            "message": test_result.get("message"),
            "safe_details": test_result.get("safe_details") or {},
            "last_checked_at": checked_at,
            "notes": ["Jules probe checks API key only. No session was started. Planning only; execution comes next."],
        }
    raise HTTPException(status_code=400, detail=f"Probe is not supported for adapter '{adapter}'.")


def refresh_agent_statuses(
    root: Path,
    *,
    codex_runner_ready: bool,
    private_only: bool,
    probe_codex: Callable[[], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for agent in list_all_agents(root, codex_runner_ready=codex_runner_ready, private_only=private_only):
        try:
            probed = probe_agent(
                agent,
                codex_runner_ready=codex_runner_ready,
                root=root,
                probe_codex=probe_codex if agent.get("adapter") == "codex_cli" else None,
            )
        except HTTPException:
            probed = {"status": agent.get("status"), "last_checked_at": _now_iso()}
        payload = sanitize_agent_profile(agent)
        payload["last_checked_at"] = probed.get("last_checked_at")
        if "status" in probed:
            payload["status"] = probed["status"]
        if "connection_status" in probed:
            payload["connection_status"] = probed["connection_status"]
        if "runnable" in probed:
            payload["runnable"] = probed["runnable"]
        elif agent.get("adapter") == "jules_remote":
            payload["runnable"] = False
        payload["notes"] = list(probed.get("notes") or [])
        refreshed.append(payload)
    return refreshed