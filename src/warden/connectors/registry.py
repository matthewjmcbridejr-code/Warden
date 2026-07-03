"""Connector provider and tool registry."""
from __future__ import annotations
import os
from .models import ConnectorProvider, ConnectorTool


def _gmail_configured() -> bool:
    return bool(os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID") and
                os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET"))


def _outlook_configured() -> bool:
    return bool(os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_ID") and
                os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_SECRET"))


PROVIDERS: list[ConnectorProvider] = [
    ConnectorProvider(
        provider_id="gmail",
        display_name="Gmail",
        auth_type="oauth2_authorization_code",
        configured=False,  # updated at runtime
        enabled=True,
        capabilities=["mail.read", "mail.search"],
        required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        risk_level="read_only",
        notes="Requires WARDEN_GOOGLE_OAUTH_CLIENT_ID + WARDEN_GOOGLE_OAUTH_CLIENT_SECRET.",
    ),
    ConnectorProvider(
        provider_id="outlook",
        display_name="Outlook / Microsoft 365",
        auth_type="oauth2_authorization_code",
        configured=False,
        enabled=True,
        capabilities=["mail.read", "mail.search"],
        required_scopes=["openid", "email", "offline_access", "Mail.Read"],
        risk_level="read_only",
        notes="Requires WARDEN_MICROSOFT_OAUTH_CLIENT_ID + WARDEN_MICROSOFT_OAUTH_CLIENT_SECRET.",
    ),
    ConnectorProvider(
        provider_id="icloud",
        display_name="iCloud Mail",
        auth_type="app_password",
        configured=False,
        enabled=True,
        capabilities=["mail.read", "mail.search"],
        required_scopes=[],
        risk_level="read_only",
        notes="Uses app-specific password via IMAP. Password stored in local vault only.",
    ),
]

TOOLS: list[ConnectorTool] = [
    ConnectorTool("connectors.providers", "all", "List Providers",
                  "List available connector providers and their status.",
                  risk_level="read_only", configured=True),
    ConnectorTool("connectors.accounts", "all", "List Connected Accounts",
                  "List connected user accounts (no tokens returned).",
                  risk_level="read_only", configured=True),
    ConnectorTool("connectors.disconnect", "all", "Disconnect Account",
                  "Disconnect a connected account and revoke its token/secret.",
                  risk_level="write_gated", requires_confirmation=True, configured=True),
    ConnectorTool("mail.accounts_status", "all", "Mail Accounts Status",
                  "Check status of connected mail accounts.",
                  risk_level="read_only", configured=False,
                  notes="Requires at least one connected mail account."),
    ConnectorTool("mail.search", "all", "Search Mail",
                  "Search mail in a connected account.",
                  risk_level="read_only", configured=False,
                  notes="Requires connected mail account with mail.read scope."),
    ConnectorTool("mail.read_message", "all", "Read Message",
                  "Read a mail message by ID.",
                  risk_level="read_only", configured=False),
    ConnectorTool("mail.create_draft", "all", "Create Draft",
                  "Create a mail draft (not sent automatically).",
                  risk_level="write_gated", requires_confirmation=True, configured=False,
                  notes="Requires WARDEN_MAIL_ALLOW_SEND=1."),
    ConnectorTool("mail.send_draft", "all", "Send Draft",
                  "Send a previously created draft. Requires explicit confirmation.",
                  risk_level="write_gated", requires_confirmation=True, configured=False,
                  notes="Blocked by default. Requires WARDEN_MAIL_ALLOW_SEND=1 and user confirmation."),
]


def list_providers() -> list[dict]:
    providers = []
    for p in PROVIDERS:
        p.configured = (
            _gmail_configured() if p.provider_id == "gmail"
            else _outlook_configured() if p.provider_id == "outlook"
            else False
        )
        providers.append(p.to_dict())
    return providers


def list_tools() -> list[dict]:
    return [t.to_dict() for t in TOOLS]
