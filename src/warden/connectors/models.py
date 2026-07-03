"""Data models for the Warden Connectors platform."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectorProvider:
    provider_id: str
    display_name: str
    auth_type: str  # oauth2_authorization_code | app_password | api_key | none
    configured: bool
    enabled: bool
    capabilities: list[str] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    risk_level: str = "read_only"  # read_only | write_gated | destructive_blocked
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "auth_type": self.auth_type,
            "configured": self.configured,
            "enabled": self.enabled,
            "capabilities": self.capabilities,
            "required_scopes": self.required_scopes,
            "risk_level": self.risk_level,
            "notes": self.notes,
        }


@dataclass
class ConnectedAccount:
    account_id: str
    user_id: str
    provider: str
    display_email: str
    status: str  # connected | needs_reauth | error | disabled
    scopes: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""
    token_ref: str = ""  # reference to vault entry, never the raw token
    metadata: dict = field(default_factory=dict)

    def to_dict(self, redact: bool = True) -> dict:
        d = {
            "account_id": self.account_id,
            "user_id": self.user_id,
            "provider": self.provider,
            "display_email": self.display_email,
            "status": self.status,
            "scopes": self.scopes,
            "capabilities": self.capabilities,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "token_ref": "[redacted]" if redact else self.token_ref,
        }
        return d


@dataclass
class ConnectorTool:
    tool_id: str
    provider_id: str
    name: str
    description: str
    risk_level: str = "read_only"
    requires_confirmation: bool = False
    enabled: bool = True
    configured: bool = False
    input_schema: str = ""
    output_schema: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "provider_id": self.provider_id,
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "enabled": self.enabled,
            "configured": self.configured,
            "notes": self.notes,
        }
