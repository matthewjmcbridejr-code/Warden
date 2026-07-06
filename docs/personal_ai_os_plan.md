# Warden Personal AI OS — Foundation Plan

Status: foundation pass (this PR). Audit + guardrails + source-fidelity proof only. No Brain Inbox UI, no auto-distillation, no auto-dispatch yet.

## 1. Vision

Warden already has two working subsystems: a Markdown-native knowledge vault (Brain) and a structured, project-scoped memory store (Workbench/Memory). The goal is to connect them into one loop so that anything captured (browser pages, AI chat conversations, Obsidian notes, repo context, agent proofs, and eventually mail/calendar) becomes durable, retrievable project memory that can drive planning and execution — not just a search index.

Loop:

```
Capture → Normalize → Distill → Link → Retrieve → Plan → Act → Verify → Remember
```

- **Capture**: browser extension events, Obsidian vault files, repo state, agent run output, chat transcripts.
- **Normalize**: turn heterogeneous capture payloads into one canonical record shape (title, url, tags, project, raw content, summary, timestamps).
- **Distill**: extractive/LLM summarization, tagging, project detection (partially built today).
- **Link**: cross-reference captures/memories/vault notes to each other and to project/task context (`source_ref` exists; not consistently populated).
- **Retrieve**: hybrid search across Brain + Memory (`warden_context_pack` already merges both).
- **Plan**: Captain turns a goal into ordered steps (built).
- **Act**: Captain dispatches steps to CLI agents (built, actively hardened this cycle).
- **Verify**: proof gates on dispatch results (built).
- **Remember**: `warden_remember` persists decisions/proofs/failures back into Memory, ideally cross-linked to the vault note or run that produced them (built, but promotion-to-vault is manual).

This PR does not touch Distill/Link/Retrieve behavior. It proves the Capture step is trustworthy enough to build on, and hardens Act so future automation doesn't clobber the app while unattended.

## 2. What Is Already Built

| Capability | Location | Status |
|---|---|---|
| Browser event ingest → structured memory | `src/warden/api.py:browser_ingest` (`POST /warden/browser/ingest`) | Built. Handles `search`, `ai_conversation`, `selection`, `input`, `copy`, `github`, `media`, `reference`, `browse` event kinds. |
| Markdown vault (Obsidian-compatible) ingest | `src/warden/brain/ingest.py`, `src/warden/brain/vault.py` | Built. Webpage/YouTube/PDF/selection → Markdown note with YAML frontmatter. |
| Local extractive + optional Ollama summarization | `src/warden/brain/ingest.py:_summarize` | Built. |
| Hybrid local FTS + Google Discovery Engine search | `src/warden/brain/hybrid.py`, `local_provider.py`, `google_provider.py` | Built (Google optional/off by default). |
| Structured memory records (decision/proof/failure/handoff/etc.) | `src/warden/workbench.py` (`WorkbenchMemory`) | Built. |
| Memory ↔ Brain merged context | `warden_context_pack` combines `build_memory_context_pack` (workbench) + brain search (`src/warden/brain_mcp_server.py:331`) | Built. |
| `source_ref` field on memory records | `src/warden/workbench.py:WorkbenchMemory` | Field exists; rarely populated by ingest paths today. |
| Captain plan generation (LLM + local heuristic fallback) | `src/warden/api.py:_plan_from_json_content`, `_local_preview_plan` | Built. |
| Captain step dispatch to CLI agents + proof gates | `src/warden/agent_dispatcher.py`, `src/warden/proof_gates.py` | Built, actively hardened (Captain Watchers). |

## 3. What Is Missing (Confirmed by Audit)

Audit method: `grep -R` over `src/warden`, `web/warden`, `tests` for `browser|memory|remember|source_url|url|raw_text|content|summary`, then read the concrete ingest code paths end to end.

1. **No full page body capture for plain page visits.** The `browse` event kind (`src/warden/api.py:browser_ingest`, `kind == "browse"` branch) stores only `Visited: <title>\nURL: <url>\nDwell: Ns, scroll: M%` — the extension does not send page body text for this event kind, and even if it did, this code path has no field to hold it. This is exactly the symptom the user observed: two Substack articles saved via `[browsed] ...` events have titles and summaries but no extractable body for "what did paragraph 3 say."
2. **Hard truncation in the Brain vault ingest path.** `src/warden/brain/ingest.py:_build_note_body` truncates page content to `content[:2000]` when writing the Markdown note. Anything past ~2000 characters of the source page is permanently lost — there is no full-text field stored anywhere (not in the note, not in frontmatter, not in a side file).
3. **Source URL is not structured metadata in vault notes.** `write_note` (`src/warden/brain/vault.py`) only writes `title`, `tags`, `created`, `source` to YAML frontmatter. The URL is embedded as a body text line (`**Source:** <url>`), not a queryable field — so "find all notes from aimaker.substack.com" requires body text parsing, not a metadata filter.
4. **No promotion path from Memory to Brain.** `source_ref` on `WorkbenchMemory` is designed to point at a vault path, but nothing writes it automatically, and there is no code path that turns a recurring/important memory into a durable vault note.
5. **No de-duplication/linking across captures on the same topic.** Two notes ingested minutes apart on the same subject (confirmed: the two Substack articles used as context for this PR) do not reference each other; there's no `index.md`/backlink mechanism.
6. **Captain-generated dispatch prompts could clobber app entrypoints.** Confirmed via a real incident: a vague dispatched step previously overwrote `web/warden/index.html` with a hello-world stub. Proof gates caught it, but the prompt itself carried no guardrail against it. Fixed in this PR (see §5).

## 4. Proposed Data Model (Future PR, Not This One)

Canonical capture record (superset of today's `WorkbenchMemory` + Brain vault frontmatter):

```
capture_id, kind (browse|selection|ai_conversation|repo_event|agent_proof|...),
title, url, project_id, tags[], source (browser_extension|brain_ingest|captain|manual),
raw_content (bounded, redacted), raw_content_truncated: bool,
summary, created_at, indexed_at,
vault_note_ref (path, if promoted), memory_ref (memory_id, if distilled),
linked_capture_ids[]
```

Key change from today: `raw_content` and `raw_content_truncated` become first-class fields on both Memory and Brain records, so downstream distillation can tell the difference between "nothing more to say" and "we threw it away."

## 5. This PR's Changes (Foundation)

1. **Audit** (this document) — confirmed capture fidelity gaps above with file:line references.
2. **Anti-clobber Captain guardrail** — `src/warden/api.py`: added `CAPTAIN_ANTI_CLOBBER_GUARDRAIL` constant, injected into both dispatch-prompt builders (`_captain_prompt_wrapper`, used for LLM-generated plans; `_local_preview_plan`, the no-API-key fallback that generated the incident). Proof gates and manual approval are unchanged — this only changes prompt text, not execution/approval flow.
3. **Source-fidelity tests** — `tests/test_warden_brain_source_fidelity.py`: two tests that pin down current behavior (not fake full-body capture):
   - `test_browser_ingest_browse_event_captures_title_url_not_full_body` — proves a `browse` event's stored `WorkbenchMemory` has `title`/`url`/dwell/scroll metadata but no body/content field.
   - `test_brain_ingest_webpage_truncates_content_and_drops_structured_url` — proves `ingest_webpage` truncates content at 2000 chars and does not write a structured `url` frontmatter field.

## 6. Phased Roadmap (Subsequent PRs)

- **PR 2 — Brain Inbox UI**: surface `00-inbox`-equivalent captures in the cockpit UI as a reviewable feed (read-only), so gaps in fidelity are visible to the user before any auto-distillation is built.
- **PR 3 — Capture fidelity**: extend browser extension `browse` events to optionally include page body text (size-capped, user-controlled); store bounded raw content + `raw_content_truncated` flag on both Memory and vault notes; add structured `url` frontmatter to vault notes.
- **PR 4 — Linking**: populate `source_ref` automatically from ingest context; add a lightweight `index.md`/backlink pass so same-topic captures reference each other (Karpathy LLM Wiki pattern).
- **PR 5 — Promotion**: explicit (user-triggered, not automatic) "promote memory to vault note" action; never silent/automatic promotion of raw captures into durable project memory.
- **PR 6 — Distillation-assisted planning**: let Captain's plan generator optionally pull relevant Brain/Memory context into the goal prompt (already partially possible via `warden_context_pack`; wire it into the Captain plan-generation call path).

Each PR must keep proof gates intact and must not introduce auto-dispatch from captured research — a human goal always starts a Captain plan; captures only ever inform context, they never trigger actions on their own.

## 7. UI Surfaces (Future)

- Brain Inbox: reverse-chronological review feed for raw captures, with an explicit "promote to vault" and "discard" action per item.
- Memory Today: reverse-chronological feed of `warden_remember` writes (this is the Fable 5 audit's #2 recommendation — a glanceable proof that capture is actually happening).
- Neither exists yet; both are out of scope for this PR.

## 8. Risks

- **Data growth**: storing full raw content instead of 2000-char excerpts increases vault/workbench disk usage — needs a bound + redaction pass before PR 3 ships (secrets must never be captured raw).
- **False promotion**: any future auto-promotion (Memory → vault) risks polluting the durable knowledge base with noise; keep promotion explicit/user-triggered.
- **Prompt guardrail drift**: the anti-clobber guardrail is now duplicated conceptually across two prompt builders via one shared constant (`CAPTAIN_ANTI_CLOBBER_GUARDRAIL`) — if a third dispatch-prompt builder is added later, it must also reference the same constant or the protection silently doesn't apply there.
- **Paywalled/partial content**: some captured articles (confirmed: aimaker.substack.com posts marked "Paid") only yield free-preview text; distillation features must not assume captured content is the full source.

## 9. Acceptance Criteria (This PR)

- [x] Audit completed with concrete file:line references for capture storage across browser ingest, Brain vault ingest, and Memory records.
- [x] `docs/personal_ai_os_plan.md` written (this file), implementation-oriented.
- [x] Anti-clobber guardrail injected into both Captain dispatch-prompt builders; proof gates, manual approval, and auto-dispatch restrictions unchanged.
- [x] Source-fidelity tests added and passing, proving current capture behavior (no fabricated capabilities).
- [x] No Brain Inbox UI built in this PR.
- [x] No new dependencies introduced.
- [x] `master` untouched; work stays on `feat/personal-ai-os-foundation`.
