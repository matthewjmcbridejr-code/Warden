"""WebStudio site registry: load and validate tracked SMB website configs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_REGISTRY_PATH = Path("configs/webstudio.sites.yaml")
EXAMPLE_REGISTRY_PATH = Path("configs/webstudio.sites.example.yaml")

# Registrar (who the domain is bought through) and DNS host (who answers DNS
# queries) are separate concerns. A domain can be registered at Namecheap
# while its nameservers point at Vercel — that's the recommended setup for
# Vercel-hosted WebStudio sites. Namecheap's own DNS (BasicDNS host records)
# is a fallback path for domains that need Namecheap-specific services
# (email forwarding, URL forwarding, Dynamic DNS) or non-Vercel routing.
DNS_PROVIDERS = {"vercel", "namecheap", "cloudflare", "other"}
DNS_STRATEGIES = {"vercel_nameservers", "external_dns_records", "namecheap_basicdns"}

# migration_status tracks where a domain is in the DNS migration lifecycle:
#   existing  — production domain, current DNS setup untouched (default; no
#               automatic migration is ever recommended for this status)
#   sandbox   — disposable/non-critical domain safe to migrate directly
#   planned   — a migration has been scoped (inventory + parity checklist
#               drafted) but not yet approved
#   approved  — Matt has explicitly approved the cutover
#   migrated  — cutover has been completed and verified
MIGRATION_STATUSES = {"existing", "sandbox", "planned", "approved", "migrated"}


class RegistryError(ValueError):
    """Raised when a site registry file is missing, malformed, or invalid."""


class SiteConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=255)
    repo_path: str = Field(min_length=1)
    framework: str = Field(default="unknown")
    package_manager: str = Field(default="npm")
    host_provider: str = Field(default="vercel")
    registrar_provider: str = Field(default="namecheap")
    dns_provider: str = Field(default="vercel")
    dns_strategy: Optional[str] = Field(default=None)
    nameserver_target: Optional[str] = Field(default=None)
    production_domain: Optional[str] = Field(default=None)
    aliases: list[str] = Field(default_factory=list)
    migration_status: str = Field(default="existing")
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

    @field_validator("dns_provider")
    @classmethod
    def _known_dns_provider(cls, value: str) -> str:
        if value not in DNS_PROVIDERS:
            raise ValueError(f"dns_provider must be one of {sorted(DNS_PROVIDERS)}")
        return value

    @field_validator("dns_strategy")
    @classmethod
    def _known_dns_strategy(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in DNS_STRATEGIES:
            raise ValueError(f"dns_strategy must be one of {sorted(DNS_STRATEGIES)}")
        return value

    @field_validator("migration_status")
    @classmethod
    def _known_migration_status(cls, value: str) -> str:
        if value not in MIGRATION_STATUSES:
            raise ValueError(f"migration_status must be one of {sorted(MIGRATION_STATUSES)}")
        return value

    @model_validator(mode="after")
    def _fill_dns_strategy_defaults(self) -> "SiteConfig":
        # Default strategy: Vercel-hosted sites prefer nameserver delegation to
        # Vercel; anything else falls back to explicit DNS record management
        # (Namecheap BasicDNS if that's the configured dns_provider). This is
        # purely descriptive of the *current/target configuration* — whether
        # that target is actually recommended for migration right now depends
        # on migration_status (see dns_strategy.recommend_migration_action()).
        if self.dns_strategy is None:
            if self.host_provider == "vercel" and self.dns_provider == "vercel":
                self.dns_strategy = "vercel_nameservers"
            elif self.dns_provider == "namecheap":
                self.dns_strategy = "namecheap_basicdns"
            else:
                self.dns_strategy = "external_dns_records"
        if self.dns_strategy == "vercel_nameservers" and not self.nameserver_target:
            self.nameserver_target = "vercel"
        if not self.production_domain:
            self.production_domain = self.domain
        return self

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
