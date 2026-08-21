# Warden Mission Control Browser Vertical Slice — Runtime & Event Contract Handoff

**From:** AGY (Architecture & Runtime Lead)  
**To:** Codex (Mission UI / Electron Lead) & Jules (Verification Lead)  
**Date:** 2026-08-20  
**PR:** [#60 — feat(computer-use): enforce Mission approval boundary and live event bridge](https://github.com/matthewjmcbridejr-code/Warden/pull/60)  
**Branch:** `feature/mission-control-browser-runtime-contract`  

---

## 1. Overview & Guarantees Delivered

This implementation delivers the complete backend, lifecycle state machine, hard confirmation boundary, and streaming event contract required for Codex to build the **Mission Control Browser Vertical Slice** in the Electron desktop.

All 8 architectural invariants are strictly enforced:
1. **Live Lifecycle Visibility**: Real Gemini Computer Use sessions expose active state while running (not just on completion).
2. **Hard Confirmation Gate**: Any action requiring operator confirmation (`destructive`, `auth`, `external_action`) halts before `execute_action()` is called on the browser/system executor.
3. **Denial Short-Circuit**: Operator denial terminates the session immediately without executing the pending action.
4. **Single-Use Action-Bound Approvals**: The public resolve payload requires `expected_session_id` and `expected_action_id` in addition to the path `confirmation_id`. Replay or cross-action authorization is rejected.
5. **Authoritative "Needs You" State**: The UI derives `Needs You` directly from pending confirmation records in `ConfirmationStore` and `ComputerSession.is_waiting_for_confirmation`.
6. **Live Event Stream**: Live Computer Use events are published in real time through the existing `GET /api/mcharness/chat/conversations/{id}/stream` SSE wire and stored in `GroupChatStore`.
7. **Safe Artifact & Screenshot Serving**: Screen observations are served through the local Warden REST endpoint (`/api/mcharness/computer/screenshots/{filename}`) with traversal protection and `private, no-store` cache semantics. Route-level authentication remains a deployment boundary.
8. **Truthful Telemetry**: Zero simulated or fake agent personas are emitted.

---

## 2. Event Contract & SSE Integration

### Event Types Published to SSE (`/api/mcharness/chat/conversations/{id}/stream`)

Each live Computer Use event is projected into a standard `ChatEvent` emitted to the SSE stream and persisted to SQLite:

| Computer Use Event | Projected `ChatEvent.event_type` | Payload / `metadata` | Purpose |
|---|---|---|---|
| `computer_session_started` | `agent_working` | `{"session_id": str, "objective": str, "environment": "browser"}` | Signals session initialization |
| `computer_action` | `task_progress` | `{"session_id": str, "action": dict, "action_index": int, "step": int}` | Emitted before executing an action |
| `computer_action_executed` | `task_progress` | `{"session_id": str, "action_id": str, "action_type": str, "executed": true, "step": int}` | Emitted only after `execute_action()` succeeds |
| `computer_observation` | `context_updated` | `{"session_id": str, "screenshot_url": str, "current_url": str, "page_title": str, "step": int}` | Live browser view update |
| `computer_confirmation_required` | `approval_requested` | `{"session_id": str, "confirmation_id": str, "action_id": str, "action": dict, "reason": str, "risk_level": str}` | Halts runtime, sets **Needs You** |
| `computer_confirmation_resolved` | `approval_granted` / `approval_denied` | `{"session_id": str, "confirmation_id": str, "action_id": str, "decision": "approve"|"deny", "executed": false}` | Records the authorization decision; it does not claim execution |
| `computer_session_completed` | `task_completed` / `task_failed` | `{"session_id": str, "success": bool, "steps_completed": int, "final_result": str, "error": str}` | Final outcome & artifacts |

---

## 3. REST API Contract for Mission UI

All endpoints are mounted under `/api/mcharness/computer/`:

### A. List Pending Confirmations
```http
GET /api/mcharness/computer/confirmations/pending
```
**Response (200 OK):**
```json
{
  "ok": true,
  "count": 1,
  "confirmations": [
    {
      "confirmation_id": "conf_1787260500_0",
      "session_id": "cs_1787260500_abc123",
      "action_id": "act_0_click",
      "action": {
        "action_type": "click",
        "coordinate": [640, 480],
        "reasoning": "Click submit button"
      },
      "reason": "Action 'click' matched confirmation policy (destructive/auth action)",
      "risk_level": "destructive",
      "status": "pending",
      "decision": null,
      "operator_id": null,
      "created_at": "2026-08-20T21:15:00.000Z",
      "resolved_at": null
    }
  ]
}
```

### B. Resolve Confirmation (Approve / Deny)
```http
POST /api/mcharness/computer/confirmations/{confirmation_id}/resolve
Content-Type: application/json

{
  "decision": "approve", // or "deny"
  "operator_id": "operator",
  "expected_session_id": "cs_1787260500_abc123",
  "expected_action_id": "act_0_click"
}
```
**Response (200 OK):**
```json
{
  "ok": true,
  "confirmation": {
    "confirmation_id": "conf_1787260500_0",
    "status": "approved",
    "decision": "approved",
    "operator_id": "operator",
    "resolved_at": "2026-08-20T21:15:05.123Z"
  }
}
```

### C. Active Sessions Query
```http
GET /api/mcharness/computer/sessions
GET /api/mcharness/computer/sessions/{session_id}
```
Both routes read the process-wide `default_session_registry`, which is also used by runtime-created `ComputerUseService` instances. They do not construct an isolated session store.
**Response (200 OK):**
```json
{
  "ok": true,
  "session": {
    "session_id": "cs_1787260500_abc123",
    "objective": "Log in to portal",
    "environment": "browser",
    "status": "waiting_for_confirmation", // "starting" | "running" | "waiting_for_confirmation" | "completed" | "failed"
    "current_step": 3,
    "active_confirmation_id": "conf_1787260500_0",
    "is_waiting_for_confirmation": true,
    "current_url": "https://example.com/checkout",
    "page_title": "Checkout - Acme",
    "latest_screenshot": "/api/mcharness/computer/screenshots/cs_1787260500_abc123_step_3.png",
    "final_result": null,
    "error": null
  }
}
```

### D. Screenshot Retrieval
```http
GET /api/mcharness/computer/screenshots/{filename}
```
Returns image (`image/png`) with traversal prevention.
Responses use `Cache-Control: private, no-store, max-age=0` because captures may contain authenticated browser state.

---

## 4. UI Implementation Guidance for Codex

1. **Needs You Badge / Banner**:
   - Inspect incoming SSE events for `approval_requested` or poll `GET /api/mcharness/computer/confirmations/pending`.
   - When a confirmation is pending:
     - Render the **Needs You** interactive drawer / modal.
     - Display `action_type`, target coordinates/elements, reasoning, and risk level.
     - Provide one-click **Approve** and **Deny** buttons calling `POST /api/mcharness/computer/confirmations/{id}/resolve`.

2. **Live Browser Activity Feed**:
   - On `agent_working` / `task_progress`: render step count, current URL, and action preview.
   - On `context_updated`: render live screenshot using `metadata.screenshot_url`.

3. **Reconnection & Deduplication**:
   - The SSE stream supports standard `Last-Event-ID` header and `?last_event_id={seq}` replay. Wire reconnection guarantees strictly increasing sequence numbers without dropped or duplicate events.

---

## 5. Verification Proof

- **Python Tests**: 18/18 passed in `tests/test_warden_computer_use.py`, `tests/test_group_chat_api.py`, `tests/test_real_sse_transport.py`.
- **Desktop Check**: 80/80 Vitest passed, TypeScript typecheck clean, Node build clean.
- **Security Audit**: `bash scripts/public_release_audit.sh` passed with 0 leaks detected.
