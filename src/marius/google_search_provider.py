import os
import logging
from typing import List, Dict, Optional, Any
from .search_provider import SearchProvider, LocalJsonlSearchProvider

logger = logging.getLogger(__name__)

class GoogleAgentSearchProvider(SearchProvider):
    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GOOGLE_AGENT_SEARCH_LOCATION", "global")
        self.engine_id = os.getenv("GOOGLE_AGENT_SEARCH_ENGINE_ID")
        self.data_store_id = os.getenv("GOOGLE_AGENT_SEARCH_DATA_STORE_ID")
        self.serving_config_id = os.getenv("GOOGLE_AGENT_SEARCH_SERVING_CONFIG", "default_config")
        
        self.client = None
        self.init_error = None
        self._init_client()

    def _init_client(self):
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine
            self.client = discoveryengine.SearchServiceClient()
        except ImportError:
            self.init_error = "google-cloud-discoveryengine package not installed"
        except Exception as e:
            self.init_error = str(e)

    def status(self) -> Dict[str, Any]:
        requested = (os.getenv("MARIUS_SEARCH_PROVIDER") or "local").lower()
        ready = all([self.project_id, self.engine_id, self.client])
        
        # Determine actual serving config path for display
        config_path = "N/A"
        if self.project_id and self.engine_id:
            # Prefer engine path as it is standard for Search Apps
            config_path = f"projects/{self.project_id}/locations/{self.location}/collections/default_collection/engines/{self.engine_id}/servingConfigs/{self.serving_config_id}"

        return {
            "requested_provider": requested,
            "actual_provider": "google" if ready else "local (fallback)",
            "fallback_reason": self.init_error if not self.client else (None if ready else "missing configuration"),
            "provider": "google",
            "project_id": self.project_id,
            "location": self.location,
            "engine_id": self.engine_id,
            "data_store_id": self.data_store_id,
            "serving_config_id": self.serving_config_id,
            "serving_config_path": config_path,
            "client_installed": self.client is not None,
            "ready": ready
        }

    def export(self, project: str, repo_path: str) -> Dict[str, Any]:
        # Google export is local export followed by a note
        local = LocalJsonlSearchProvider()
        res = local.export(project, repo_path)
        res["google_note"] = "Local JSONL generated. Use scripts/marius_brain_gcs_setup.sh to upload to GCS and scripts/marius_brain_discovery_setup.py --import to index."
        return res

    def search(self, query: str, project: Optional[str] = None, limit: int = 5, collection: Optional[str] = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        if not self.client or not self.project_id or not self.engine_id:
            # If Google was requested but not ready, we return the error record
            reason = self.init_error or "missing configuration (GOOGLE_CLOUD_PROJECT or GOOGLE_AGENT_SEARCH_ENGINE_ID)"
            return [{
                "project": "error",
                "source_path": "n/a",
                "source_type": "error",
                "title": "Google Search Configuration Error",
                "snippet": f"Google provider requested but not ready: {reason}",
                "score": 0.0,
                "record_id": "err",
                "provider": "local fallback"
            }]

        try:
            from google.cloud import discoveryengine_v1 as discoveryengine
            
            # The search engine path - try engine-based serving config first
            serving_config = self.client.serving_config_path(
                project=self.project_id,
                location=self.location,
                data_store=self.data_store_id or self.engine_id,
                serving_config=self.serving_config_id,
            )
            
            # Build filter string only if enabled via env
            filter_enabled = os.getenv("GOOGLE_AGENT_SEARCH_ENABLE_METADATA_FILTERS") == "1"
            filter_str = ""
            filter_note = None
            
            if filter_enabled:
                filters = []
                if project:
                    filters.append(f'project: ANY("{project}")')
                if collection:
                    filters.append(f'collection: ANY("{collection}")')
                if tags:
                    for tag in tags:
                        filters.append(f'tags: ANY("{tag}")')
                filter_str = " AND ".join(filters) if filters else ""
            elif project or collection or tags:
                filter_note = "Google metadata filters disabled; project/tags not applied server-side"

            request = discoveryengine.SearchRequest(
                serving_config=serving_config,
                query=query,
                page_size=limit,
                filter=filter_str
            )

            pager = self.client.search(request)
            
            results = []
            for result in pager:
                doc = result.document
                data = doc.derived_struct_data
                
                snippet = "No snippet available."
                if "snippets" in data and len(data["snippets"]) > 0:
                    snippet = data["snippets"][0].get("snippet", snippet)
                elif "extractive_answers" in data and len(data["extractive_answers"]) > 0:
                    snippet = data["extractive_answers"][0].get("content", snippet)
                
                res = {
                    "project": project or "google-brain",
                    "collection": "google",
                    "source_path": data.get("link", doc.name),
                    "source_type": "google_agent_search",
                    "title": data.get("title", doc.id),
                    "tags": [],
                    "snippet": snippet,
                    "score": 1.0, # Result is already ranked
                    "record_id": doc.id,
                    "resource_name": doc.name,
                    "provider": "google",
                    "captured_at": None
                }
                if filter_note:
                    res["filter_note"] = filter_note
                results.append(res)
            return results

        except Exception as e:
            logger.error(f"Google Agent Search failed: {e}")
            # Fallback to local instead of returning error record if it's a transient failure?
            # User requirement 4: "Do not silently fallback to local. If Google fails, show exact error."
            return [{
                "project": "error",
                "source_path": "n/a",
                "source_type": "error",
                "title": "Google Search API Error",
                "snippet": f"Google Agent Search failed: {type(e).__name__}: {str(e)}",
                "score": 0.0,
                "record_id": "err",
                "provider": "local fallback"
            }]
