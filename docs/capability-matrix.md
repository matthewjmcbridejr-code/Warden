# Desktop capability matrix

This matrix describes behavior proven by the 0.3.0 implementation, not provider marketing availability. Every structured capability also depends on a compatible official client installed and authenticated on the machine.

| Capability | Codex | Claude Code | Gemini CLI | Grok Build | Web Platform |
|---|---|---|---|---|---|
| Persistent website | ChatGPT | Claude | Gemini | Grok | Yes |
| Named Chromium profile | Yes | Yes | Yes | Yes | Yes |
| Official subscription login for Build | `codex login` / ChatGPT | Claude.ai login in Claude Code | Google account / Code Assist | `grok login` | Not applicable |
| Structured stream | App Server JSON-RPC | Headless stream JSON | Headless stream JSON | Headless streaming JSON | No |
| Normalized events | Yes | Yes | Yes | Yes | No |
| Provider raw metadata retained after redaction | Yes | Yes | Yes | Yes | No |
| Warden approval bridge | **Yes** | No | No | No | No |
| Cancellation | Yes | Yes | Yes | Yes | Navigation stop only |
| Resume/session ID | Yes | Yes | Yes | Yes | Browser navigation state |
| Changed-file events | Yes | Not claimed | Not claimed | Not claimed | No |
| Evidence collected from repository | Yes | Yes | Yes | Yes | No |
| Explicit API fallback | If configured | If configured | If configured | If configured | No |

## Authentication states

Warden reports one of these before a run starts:

- **subscription authenticated** — official local client reports usable subscription login/entitlement.
- **API-key authenticated** — an optional API credential exists, but using it still requires explicit selection and per-run approval.
- **disconnected** — client or account cannot currently reach the provider.
- **installed but not authenticated** — client exists but requires official sign-in.
- **unsupported** — installed client/account mode is known not to support this integration.
- **unknown entitlement** — Warden cannot prove the plan/account can start a subscription-backed run.

Unknown is not treated as success. Subscription execution never silently inherits API credentials.

## Approval status

Codex App Server exposes bidirectional approval request/response messages, so Warden can offer approve once, approve session, and deny. The currently supported Claude Code, Gemini CLI, and Grok headless streams do not expose an equivalent Warden-controlled callback. Their adapters report `approvals: false`; Warden does not simulate an approval bridge from terminal text.

## Web Platform boundary

Starter presets are convenience data, not privileged integrations. HyperAgent and arbitrary HTTPS sites have persistent sessions, navigation, OAuth handling, and split-view support, but no local execution or Warden data access. A future trusted extension must be separately installed and reviewed.
