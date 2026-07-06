Implement Warden v2 per docs/warden_v2_vision_alignment.md, in order v2.1→v2.6 (skip v2.7, autonomy — out of scope). One PR per phase, on branch feat/warden-v2-{phase}. Read the alignment doc once at start; don't re-derive it.

Rules: reuse existing models/routes, don't rewrite them. Every new capability gets a proof gate + test. No auto-dispatch. Keep master untouched.

**v2.1 Skill playbook engine**
Extend `WorkbenchSkill` (src/warden/workbench.py) with fields: when_to_use, inspect_files[], commands_allowed[], commands_forbidden[], proof_format, acceptance_checks[], rollback_notes, report_template. Migrate existing skill JSON files in-place (add fields, default empty). Add dispatch: skill_id + project_id + objective → reuses agent_dispatcher.py + proof_gates.py to create a run, same lifecycle as Captain steps. New route: POST /skills/{id}/dispatch. Tests: skill CRUD with new fields, dispatch creates run+gate, acceptance_checks stored on run evidence.

**v2.2 Unified project view**
New aggregation route GET /projects/{id}/context returning: recent memories, runs, pending gates, worktrees, assigned agents, applicable skills — mirror what warden_bootstrap/warden_context_pack already assemble for MCP agents (brain_mcp_server.py), just exposed over HTTP. UI: new project detail section in the canonical UI (see v2.3 — land this after or directly on the consolidated surface, don't add a 4th UI). Test: route returns non-empty aggregate for a project with existing runs/memories.

**v2.3 UI consolidation**
Per fable5_user_feature_audit.md §"Build Next A": make app.html canonical. Port Proof Gates + Runner Sessions panels from index.html into app.html sections (nav slots already exist). command-deck.html's task board becomes a section too. Old pages (index.html, command-deck.html) become redirect stubs to app.html. Add scripts/warden-up (activates venv, starts uvicorn on 6969, prints URL). Fix README/quickstart port refs to 6969. Test: update tests/browser/warden-cockpit.spec.js selectors to canonical page; add redirect test.

**v2.4 Memory unification**
Execute docs/personal_ai_os_plan.md PRs 2–6 as written (Brain Inbox UI, capture fidelity/raw_content field, source_ref auto-linking, explicit promotion action Memory→vault, Captain plan-generation pulling warden_context_pack). Follow that doc's acceptance criteria per PR — don't replan.

**v2.5 Bounded agent roles**
Expand SafetyProfile (workbench.py) beyond operator_local into: explorer (read-only), planner, builder (branch/worktree only), verifier, reviewer, deployer, archivist. Each role = tool allowlist + thread/file scope. Wire skill dispatch (v2.1) to pick a role's safety_profile_id. Test: builder role rejects a network/deploy tool call; explorer role rejects a write.

**v2.6 Measurable loops**
Add to Captain plans: a check_command, a turn/step budget, and file-scope constraints per plan (Captain plan model in captain.py/captain_plans.py). Watcher stops and reports blocker if budget exceeded or check_command fails after N tries. Test: plan with a failing check_command halts at budget with a blocker report, doesn't loop forever.

After each phase: run its tests, `git diff` review, proof gate created for the change itself if the phase touches dispatch/execution code, then stop for review before starting the next phase.
