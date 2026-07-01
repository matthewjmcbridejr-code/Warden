"""WebStudio site registry: load and validate tracked SMB website configs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_REGISTRY_PATH = Path("configs/webstudio.sites.yaml")
EXAMPLE_REGISTRY_PATH = Path("configs/webstudio.sites.example.yaml")


class RegistryError(ValueError):
    """Raised when a site registry file is missing, malformed, or invalid."""


class SiteConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=255)
    repo_path: str = Field(min_length=1)
    framework: str = Field(default="unknown")
    package_manager: str = Field(default="npm")
    host_provider: str = Field(default="vercel")
    dns_provider: str = Field(default="namecheap")
    production_branch: str = Field(default="main")
    local_preview_command: Optional[str] = None
    build_command: Optional[str] = None
    test_command: Optional[str] = None
    install_command: Optional[str] = None
    client_name: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_is_slug_friendly(cls, value: str) -> str:
        if not all(c.isalnum() or c in "-_" for c in value):
            raise ValueError("name must contain only letters, numbers, '-' or '_'")
        return value

    @field_validator("package_manager")
    @classmethod
    def _known_package_manager(cls, value: str) -> str:
        allowed = {"npm", "pnpm", "yarn", "bun"}
        if value not in allowed:
            raise ValueError(f"package_manager must be one of {sorted(allowed)}")
        return value

    def resolved_repo_path(self) -> Path:
        return Path(self.repo_path).expanduser()


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise RegistryError(f"Registry file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"Could not read registry file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"Invalid YAML in {path}: {exc}") from exc
    return data


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> list[SiteConfig]:
    """Load and validate the WebStudio site registry.

    Falls back to the example registry only if explicitly pointed at it;
    callers should point at their own configs/webstudio.sites.yaml.
    """
    path = Path(path)
    data = _read_yaml(path)
    if not isinstance(data, dict) or "sites" not in data:
        raise RegistryError(f"Registry {path} must be a mapping with a top-level 'sites' list")
    raw_sites = data["sites"]
    if not isinstance(raw_sites, list) or not raw_sites:
        raise RegistryError(f"Registry {path} must define at least one site under 'sites'")

    sites: list[SiteConfig] = []
    seen_names: set[str] = set()
    for index, raw_site in enumerate(raw_sites):
        if not isinstance(raw_site, dict):
            raise RegistryError(f"Site entry #{index} in {path} must be a mapping")
        try:
            site = SiteConfig(**raw_site)
        except Exception as exc:
            raise RegistryError(f"Site entry #{index} in {path} is invalid: {exc}") from exc
        if site.name in seen_names:
            raise RegistryError(f"Duplicate site name in {path}: {site.name}")
        seen_names.add(site.name)
        sites.append(site)
    return sites


def get_site(name: str, path: Path | str = DEFAULT_REGISTRY_PATH) -> SiteConfig:
    sites = load_registry(path)
    for site in sites:
        if site.name == name:
            return site
    raise RegistryError(f"Unknown site '{name}' in registry {path}")
