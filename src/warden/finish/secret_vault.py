"""Secret Vault for opaque secret references (secret://project/<id>/<key>).

Prevents raw secrets from leaking into chat events, logs, proofs, or job states.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from .models import SecretRef


class SecretVault:
    def __init__(self, vault_dir: Optional[Path] = None):
        if vault_dir is None:
            vault_dir = Path.cwd() / "_mctable" / "finish" / "secrets"
        self.vault_dir = vault_dir
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, str] = {}
        self._load_all()

    def _vault_file(self) -> Path:
        return self.vault_dir / "vault_store.json"

    def _load_all(self) -> None:
        file = self._vault_file()
        if file.exists():
            try:
                with open(file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def _save_all(self) -> None:
        file = self._vault_file()
        with open(file, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2)

    def store_secret(self, project_id: str, key: str, value: str, description: Optional[str] = None) -> SecretRef:
        ref = SecretRef.create(project_id, key, description=description)
        self._cache[ref.ref_uri] = value
        self._save_all()
        return ref

    def resolve_secret(self, ref_uri: str) -> Optional[str]:
        return self._cache.get(ref_uri)

    def resolve_secrets_for_job(self, secret_refs: List[SecretRef]) -> Dict[str, str]:
        resolved: Dict[str, str] = {}
        for sref in secret_refs:
            val = self.resolve_secret(sref.ref_uri)
            if val is not None:
                resolved[sref.key] = val
        return resolved

    def redact_text(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        for uri, val in self._cache.items():
            if val and len(val) >= 4 and val in redacted:
                redacted = redacted.replace(val, f"[SECRET_REF: {uri}]")
        return redacted
