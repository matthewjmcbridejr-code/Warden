# Warden Assistant

Warden Assistant is a private-runner-only helper for quick operator questions inside the cockpit.

## Goals

- Use Warden Memory when available.
- Read only a small allowlist of project docs.
- Return deterministic local answers when no LLM provider is configured.
- Redact likely secrets before rendering.
- Expose a disabled-by-default Google RAG adapter slot without requiring credentials.

## Allowlisted Project Docs

The assistant may read only these repo-local files:

- `README.md`
- `CLAUDE.md`
- `docs/warden_memory.md`
- `docs/warden_memory_style.md`
- `docs/warden_memory_examples.md`
- `docs/warden_assistant.md`

It does not crawl arbitrary files or follow user-supplied paths outside the allowlist.

## API

Private-only routes:

- `GET /api/mcharness/warden/assistant/health`
- `POST /api/mcharness/warden/assistant/context`
- `POST /api/mcharness/warden/assistant/chat`

Public service behavior:

- Returns `403`
- Does not proxy assistant reads through the public service

## Google RAG Slot

Google RAG exists as an adapter interface only.

- Disabled by default
- No Google credentials required
- No Google SDK required
- When requested while disabled, the assistant returns a warning and continues normally
