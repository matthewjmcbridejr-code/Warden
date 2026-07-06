# Warden v2 — Vision Alignment (Karpathy Method → Current Repo)

Date: 2026-07-05 · Status: docs only, no code changes.
Companion docs: [architecture.md](architecture.md) (system map), [personal_ai_os_plan.md](personal_ai_os_plan.md) (memory/capture roadmap), [fable5_user_feature_audit.md](fable5_user_feature_audit.md) (UX audit).

---

## 1. Thesis

The Karpathy lesson (World of Bits, 2017 → his later reflection) is not "don't build agents" — it is "don't confuse orchestration for intelligence." Agents built before the representations were strong enough failed; the right ordering is **foundation → skills → bounded agents → measurable loops → autonomy**, with verification at every layer. The 2026 Claude Code analysis paper makes the same point from the product side: the model/tool loop is simple; the surrounding harness (permissions, memory, subagents, hooks, isolation) is where the value lives.

Warden's position follows directly: **Warden is the harness/control plane; models (Claude Code, Codex, Gemini) are workers.** Warden does not compete with Claude Code — it supervises it: durable project memory, executable playbooks, bounded agent roles, proof gates, and human approval between agent output and anything that ships. This is already the stated design posture in [architecture.md](architecture.md) ("Supervised, not autonomous").

## 2. Layer-by-Layer Reality Map

The vision defines five layers. Most of the proposed "Skill + Agent Registry MVP" already exists in this repo. Status: ✓ built · ◐ partial · ✗ missing.

### Layer 1 — Foundation memory ("representations first")

| Vision asks for | Exists today | Status |
|---|---|---|
| Who Matt is, priorities, projects | `src/warden/personal_memory.py`, `_mctable/personal_profile.json`, `warden_me`/`warden_update_me` MCP tools | ✓ |
| Structured operational memory (decisions, proofs, failures, handoffs) | `WorkbenchMemory` in `src/warden/workbench.py` — 15 kinds, project tags, embedding search | ✓ |
| Durable knowledge vault | `src/warden/brain/` — Markdown vault, hybrid local FTS + optional Google mirror | ✓ (with fidelity limits, see §3) |
| Auto-capture (browser, files, shell) | Browser extension → `browser_ingest`; dropzone watcher `src/warden/brain/dropzone.py` | ✓/◐ |
| Per-project operating manual (`WARDEN.md`/`RUNBOOK.md`/`CURRENT_STATE.md` pattern) | Not formalized; project registry exists (`src/warden/projects.py`) but no per-project doc pack | ✗ |
| Last verified state / proof history per project | Runs + evidence exist but not aggregated per project | ◐ |

### Layer 2 — Skills / playbooks

| Vision asks for | Exists today | Status |
|---|---|---|
| Skill records | `WorkbenchSkill` (`workbench.py`), CRUD routes `GET/POST /skills` | ◐ |
| Structured playbook fields (when to use, commands, proof format, acceptance, rollback) | Only `name/description/prompt/enabled` | ✗ |
| Skill → dispatch trigger (skill runs an agent, produces a run + gates) | No playbook engine; skills are inert data | ✗ |

**This is the biggest gap.** Skills exist as rows, not as executable procedures.

### Layer 3 — Bounded agents

| Vision asks for | Exists today | Status |
|---|---|---|
| Agent registry with CRUD + connection tests | `src/warden/agent_registry.py` — built-in CLI detection (`codex_cli`, `claude_code_cli`, `grok_build_cli`), Jules remote, status probes | ✓ |
| Bounded roles (explorer/planner/builder/verifier/reviewer/deployer/archivist) | Single `operator_local` `SafetyProfile`; no role taxonomy | ✗ |
| Isolated execution (branch/worktree) | Worktree management in `projects.py`; runner sessions (`runner_sessions.py`) | ✓ |
| Dispatch | `agent_dispatcher.py` via Captain steps — manual, human-approved per step | ✓ (by design) |

### Layer 4 — Loops

| Vision asks for | Exists today | Status |
|---|---|---|
| Objective → plan → steps | Captain (`captain.py`, `captain_plans.py`) | ✓ |
| Auto-poll / continue-on-completion | Captain Watchers | ✓ |
| Measurable completion conditions (`/goal`-style: check command + stop criteria + scope constraints) | Plans are step lists; no machine-checked end condition or turn budget | ✗ |

### Layer 5 — Hooks / verifiers (the moat)

| Vision asks for | Exists today | Status |
|---|---|---|
| Approval gates on agent output | `src/warden/proof_gates.py` — open/approved/rejected/blocked lifecycle, Notion sync | ✓ |
| Evidence attached to runs | `EvidenceRecord`, run events, Markdown run reports (`run_reports.py`) | ✓ |
| Prompt-level guardrails | `CAPTAIN_ANTI_CLOBBER_GUARDRAIL` in both dispatch-prompt builders (see [personal_ai_os_plan.md](personal_ai_os_plan.md) §5) | ✓ |
| Secret protection | Dropzone secret-pattern skip; mail send blocked; public port runner-disabled | ✓ |
| Generalized interceptor (file writes, deploys, DNS, email, CRM, merges) risk-classified across all runtimes | Only within Captain dispatch path today | ◐ |

## 3. Key Architectural Findings

1. **Two memory silos.** `WorkbenchMemory` (structured, project-tagged, embedded) and the Brain vault (Markdown, full-text) are separate; `warden_context_pack` merges them at read time, but there is no promotion path, no dedup/linking, and vault ingest truncates at 2,000 chars. All confirmed with tests in `tests/test_warden_brain_source_fidelity.py` — this is exactly what [personal_ai_os_plan.md](personal_ai_os_plan.md) PRs 3–5 fix. Don't redesign it here; execute that plan.
2. **Skills are CRUD, not executable.** No playbook schema, no dispatch trigger. Layer 2 is the vision's differentiator and the repo's thinnest layer.
3. **Agents are registered, dispatch is manual.** That's the intended safety posture, not a gap — autonomy should only expand behind verifier coverage (Layer 5) and measurable loop conditions (Layer 4).
4. **Projects are loosely linked.** `warden_bootstrap`/`warden_context_pack` already stitch profile + memory + brain + board for agents over MCP; there is no equivalent web surface. A "project view" (memories + runs + pending gates + worktrees + agents + skills for one project) requires stitching many endpoints today.
5. **Three competing UIs.** `index.html`, `app.html`, `command-deck.html` — audit item #1 in [fable5_user_feature_audit.md](fable5_user_feature_audit.md). Consolidation is a prerequisite for any of the above being legible.

## 4. Claude Code Feature Mapping

| Claude Code | Warden equivalent | Who's ahead |
|---|---|---|
| `CLAUDE.md` / memory | `personal_memory.py` + Workbench memory + Brain vault | Warden (richer, cross-tool) but less per-project |
| Skills (`SKILL.md`) | `WorkbenchSkill` | Claude Code — Warden skills aren't executable |
| Subagents (isolated context/tools) | Agent registry + safety profiles | Claude Code — Warden lacks role taxonomy |
| Hooks (block/audit/approve) | Proof gates + anti-clobber guardrail | Warden for approvals; Claude Code for interception breadth |
| `/goal` (measurable completion) | Captain plans + Watchers | Claude Code — no machine-checked end condition in Captain |
| `/batch` + worktrees | `projects.py` worktrees + runner sessions | Parity |
| MCP connectors | `connectors/`, `mail/`, brain MCP server (38 tools) | Warden (it *is* an MCP server) |
| `/run` + `/verify` | Evidence records + run reports + Playwright e2e | Rough parity |
| Checkpoint/rewind | Git worktree isolation only | Claude Code |

Takeaway: Warden should copy the *shape* of Claude Code's skills/goal/hooks primitives while remaining the cross-runtime control plane Claude Code isn't.

## 5. Sequenced Roadmap (ordered, no dates)

Ordering rule from the thesis: never add autonomy above a layer that isn't verified yet.

- **v2.1 — Skill playbook engine.** Extend `WorkbenchSkill` to a structured playbook: `when_to_use`, `inspect_files`, `commands_allowed`, `commands_forbidden`, `proof_format`, `acceptance_checks`, `rollback_notes`, `report_template`. Add a dispatch path: skill + project + objective → Captain-style run with proof gates. Reuse `agent_dispatcher.py`, `proof_gates.py`, run/evidence models — no new execution machinery.
- **v2.2 — Unified project view.** One project-scoped surface aggregating memories, runs, pending gates, worktrees, assigned agents, applicable skills. Backend already exists in `warden_context_pack` / `warden_bootstrap`; this is mostly an API aggregation route + UI section.
- **v2.3 — UI consolidation + `warden-up`.** Execute fable5 audit #1: one canonical UI, redirect stubs, single start script, port consistency. (Could sensibly run before v2.2; v2.2's UI should land on the canonical surface.)
- **v2.4 — Memory unification.** Already planned as [personal_ai_os_plan.md](personal_ai_os_plan.md) PRs 2–6 (inbox UI, capture fidelity, linking, explicit promotion, distillation-assisted planning). This doc adds nothing to that plan; it just slots it after the skill/project work in priority — or in parallel, since it touches different files.
- **v2.5 — Bounded agent roles.** Expand `SafetyProfile` into the explorer/planner/builder/verifier/reviewer role set, each with tool/thread constraints. Only useful once skills (v2.1) give roles something structured to execute.
- **v2.6 — Measurable loops.** `/goal`-style completion conditions on Captain plans: a check command, a turn/step budget, scoped file constraints, and an evaluator pass. Prerequisite for any autonomy expansion.
- **v2.7 — Autonomy, gated.** Auto-dispatch of low-risk steps only where a verifier (acceptance check from the skill playbook) exists and passes, with proof gates unchanged for everything else. Per [personal_ai_os_plan.md](personal_ai_os_plan.md) §6: captures never trigger actions; a human goal always starts a plan.

## 6. Positioning

Not "an AI platform," not "autonomous agents," not a passive second brain.

**Warden is the agent workbench for builders who ship with Claude Code/Codex but need memory, proof, and control.** Every agent gets durable project memory, executable playbooks, guardrails, proof requirements, and human approval gates. Claude Code is one worker runtime among several; Warden is the control plane above them. The moat is the verifier layer: most people will build agents, fewer will build the thing that tells you what is proven, what is claimed, what broke, and what to run next.
