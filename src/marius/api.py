import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .projects import get_projects, ProjectCard
from .memory import save_fact, recall_facts, get_where_left_off, set_where_left_off, get_recent_summaries
from .tools import get_system_status
from .router import chat_completion, create_handoff_prompt, get_ollama_diagnostics, test_ollama_model
from .provider_gateway import ProviderGateway
from .model_profiles import MODEL_PROFILES
from .grounding import GroundingPack

router = APIRouter(prefix="/api/mcharness/marius", tags=["marius-core"])
gateway = ProviderGateway()

class WorkspaceContext(BaseModel):
    repo_path: str
    branch: Optional[str] = "unknown"
    dirty: Optional[str] = "unknown"
    runner_enabled: bool

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    workspace: Optional[WorkspaceContext] = None
    brain_context: Optional[bool] = None

class ProfileRequest(BaseModel):
    profile: str

class ModeRequest(BaseModel):
    mode: str

class ModelRequest(BaseModel):
    model: str

class MemoryRequest(BaseModel):
    content: str
    category: str = "general"

class HandoffRequest(BaseModel):
    target: str
    context: str

@router.get("/health")
def health():
    return {"status": "OK", "service": "marius-core"}

@router.get("/status")
def status():
    # Tools already redacts secrets
    sys_status = get_system_status()
    ollama_diag = get_ollama_diagnostics()
    return {**sys_status, "model_backend": ollama_diag}

@router.get("/model/test")
def model_test():
    return test_ollama_model()

@router.post("/chat")
async def chat(req: ChatRequest):
    if req.model:
        gateway.forced_model = req.model
    
    workspace_dict = req.workspace.model_dump() if req.workspace else None
    result = await gateway.chat(req.message, req.history, workspace_dict, req.brain_context)
    return result

@router.get("/providers")
async def get_providers():
    return {
        "current_mode": gateway.mode,
        "allow_cloud": gateway.allow_cloud,
        "providers": [
            {"name": "ollama", "local": True, "configured": True},
            {"name": "groq", "local": False, "configured": bool(os.getenv("GROQ_API_KEY"))},
            {"name": "openrouter", "local": False, "configured": bool(os.getenv("OPENROUTER_API_KEY"))},
            {"name": "gemini", "local": False, "configured": bool(os.getenv("GEMINI_API_KEY"))},
        ]
    }

@router.post("/provider/mode")
async def set_provider_mode(req: ModeRequest):
    if req.mode not in ["local", "cloud", "auto"]:
        raise HTTPException(status_code=400, detail="Invalid mode")
    gateway.mode = req.mode
    return {"status": "ok", "mode": gateway.mode}

@router.get("/models")
async def get_models():
    available_ollama = await gateway.get_available_ollama_models()
    return {
        "current_profile": gateway.current_profile,
        "forced_model": gateway.forced_model,
        "available_ollama": available_ollama,
        "profiles": MODEL_PROFILES
    }

@router.post("/model/set")
async def set_model(req: ModelRequest):
    gateway.forced_model = req.model if req.model != "auto" else None
    gateway.config.set("model", gateway.forced_model)
    return {"status": "ok", "model": gateway.forced_model or "auto"}

@router.get("/model/why")
async def model_why():
    available_ollama = await gateway.get_available_ollama_models()
    provider, actual_model, profile, fallback_reason = await gateway.resolve_model_and_provider()
    
    # Check if loaded (Ollama specific)
    currently_loaded = False
    # This might require another Ollama API call like /api/ps
    # For now we'll just check if it's the one we resolved to.
    
    return {
        "config_path": str(gateway.config.path),
        "config_model": gateway.config.get("model"),
        "env_model": os.getenv("MARIUS_MODEL") or os.getenv("MARIUS_OLLAMA_MODEL"),
        "current_profile": gateway.current_profile,
        "selected_model": gateway.forced_model,
        "actual_model": actual_model,
        "installed": actual_model in available_ollama or f"{actual_model}:latest" in available_ollama,
        "fallback_reason": fallback_reason,
        "provider": provider
    }

@router.post("/model/profile")
async def set_profile(req: ProfileRequest):
    if req.profile not in MODEL_PROFILES:
        raise HTTPException(status_code=400, detail="Invalid profile")
    gateway.current_profile = req.profile
    return {"status": "ok", "profile": gateway.current_profile}

@router.post("/model/bench")
async def run_benchmark(req: Dict[str, Any] = None):
    req = req or {}
    quick = req.get("quick", True)
    return await gateway.benchmark(quick=quick)

@router.get("/model/recommendation")
async def get_recommendation():
    res = await gateway.benchmark(quick=True)
    return res["recommendations"]

@router.get("/model/missing")
async def get_missing_models():
    from .model_profiles import KNOWN_MODELS
    available = await gateway.get_available_ollama_models()
    missing = [m for m in KNOWN_MODELS if m not in available and f"{m}:latest" not in available]
    return {"missing": missing}

@router.get("/context")
async def get_context():
    gp = GroundingPack()
    return {"facts": gp.facts}

@router.post("/context/reload")
async def reload_context():
    return {"status": "ok", "message": "Grounding pack will be reloaded on next request."}

@router.post("/memory/remember")
def remember(req: MemoryRequest):
    save_fact(req.content, req.category)
    # If category is 'progress' or 'status', also update where_left_off
    if req.category.lower() in ["progress", "status", "leftoff"]:
        set_where_left_off(req.content)
    return {"status": "saved"}

@router.get("/memory/recall")
def recall(q: str):
    return recall_facts(q)

@router.get("/projects")
def projects():
    return get_projects()

@router.get("/whereleftoff")
def whereleftoff():
    return {
        "summary": get_where_left_off(),
        "recent_notes": get_recent_summaries()
    }

@router.post("/handoff/agent-prompt")
def handoff(req: HandoffRequest):
    return {"prompt": create_handoff_prompt(req.target, req.context)}

# --- Search / Brain Endpoints ---

class SearchQueryRequest(BaseModel):
    query: str
    project: Optional[str] = None
    limit: int = 5
    provider: Optional[str] = None

class SearchExportRequest(BaseModel):
    project: str
    repo_path: str

@router.get("/search/status")
async def get_search_status():
    from .search_provider import get_search_provider
    return get_search_provider().status()

@router.post("/search/export")
async def run_search_export(req: SearchExportRequest):
    from .search_provider import get_search_provider
    return get_search_provider().export(req.project, req.repo_path)

@router.post("/search/query")
async def run_search_query(req: SearchQueryRequest):
    from .search_provider import get_search_provider, LocalJsonlSearchProvider
    
    if req.provider == "local":
        provider = LocalJsonlSearchProvider()
    elif req.provider == "google":
        from .google_search_provider import GoogleAgentSearchProvider
        provider = GoogleAgentSearchProvider()
    else:
        provider = get_search_provider()
        
    results = provider.search(req.query, req.project, req.limit)
    status = provider.status()
    return {
        "provider": status.get("actual_provider"),
        "requested_provider": status.get("requested_provider"),
        "query": req.query,
        "project": req.project,
        "results": results
    }

# --- Brain / Ingest Endpoints ---

class URLIngestRequest(BaseModel):
    url: str
    project: str = "research"
    tags: Optional[List[str]] = None

class FileIngestRequest(BaseModel):
    path: str
    project: str = "unknown"
    tags: Optional[List[str]] = None

class TextIngestRequest(BaseModel):
    text: str
    title: str
    project: str = "personal"
    tags: Optional[List[str]] = None

@router.get("/brain/status")
async def get_brain_status():
    from .search_provider import get_search_provider, LocalJsonlSearchProvider
    from .brain_ingest import INBOX_DIR
    provider = get_search_provider()
    status = provider.status()
    
    # Always include local stats for brain status
    local = LocalJsonlSearchProvider()
    local_status = local.status()
    
    inbox_files = [f.name for f in INBOX_DIR.iterdir() if f.is_file()]
    
    return {
        "search": status,
        "local": local_status,
        "inbox": {
            "path": str(INBOX_DIR),
            "file_count": len(inbox_files),
            "files": inbox_files[:10]
        }
    }

@router.get("/brain/context")
async def get_brain_context(q: str, project: Optional[str] = None, limit: int = 5):
    from .brain_context import build_brain_context_pack
    return {"ok": True, "data": build_brain_context_pack(q, project, limit)}

@router.post("/brain/ingest/url")
async def ingest_url(req: URLIngestRequest):
    from .brain_ingest import BrainIngest
    bi = BrainIngest()
    return await bi.add_url(req.url, req.project, req.tags)

@router.post("/brain/ingest/file")
async def ingest_file(req: FileIngestRequest):
    from .brain_ingest import BrainIngest
    bi = BrainIngest()
    return bi.add_file(req.path, req.project, req.tags)

@router.post("/brain/ingest/text")
async def ingest_text(req: TextIngestRequest):
    from .brain_ingest import BrainIngest
    bi = BrainIngest()
    return bi.add_text(req.text, req.title, req.project, req.tags)

@router.post("/brain/inbox/scan")
async def scan_brain_inbox():
    from .brain_ingest import BrainIngest
    bi = BrainIngest()
    return bi.scan_inbox()

@router.post("/brain/profile/generate")
async def generate_brain_profile():
    from .brain_ingest import BrainIngest
    bi = BrainIngest()
    return bi.ingest_profiles()

@router.post("/brain/sync/google")
async def sync_brain_google(req: Dict[str, Any] = None):
    # This will be implemented in sync script or provider
    return {"status": "ok", "message": "Manual sync via CLI recommended: marius brain sync google --upload"}
