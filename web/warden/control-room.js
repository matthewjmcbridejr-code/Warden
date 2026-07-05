(function () {
  const MCH = "/api/mcharness";
  const POLL_MS = 12000;

  const DEMO_SNAPSHOT = {
    service_mode: "private",
    generated_at: new Date().toISOString(),
    mission: {
      status: "in_progress",
      title: "Warden auth hardening sprint",
      mission_id: "plan_demo01",
      progress_pct: 62,
      current_step: "Add proof gate review flow",
      current_agent: "codex_cli",
      eta: "45m",
      started_at: new Date(Date.now() - 3600000).toISOString(),
      updated_at: new Date().toISOString(),
    },
    plan: {
      plan_id: "plan_demo01",
      steps: [
        { step_id: "step_1", title: "Audit auth middleware", status: "passed", agent_id: "codex_cli", gate_status: "approved", duration_seconds: 1800 },
        { step_id: "step_2", title: "Add proof gate review flow", status: "in_progress", agent_id: "codex_cli", gate_status: "pending", duration_seconds: 900, current: true },
        { step_id: "step_3", title: "Ship operator smoke proof", status: "queued", agent_id: "codex_cli", gate_status: null },
      ],
    },
    timeline: {
      items: [
        { id: "tl1", kind: "run_started", label: "Run started", title: "Codex run dispatched", summary: "Step 2 prompt sent to private runner.", status: "running", created_at: new Date(Date.now() - 900000).toISOString(), links: { run_id: "run_demo01" } },
        { id: "tl2", kind: "gate_pending", label: "Proof gate", title: "Gate awaiting review", summary: "Operator approval required before step completes.", status: "pending", created_at: new Date(Date.now() - 600000).toISOString() },
        { id: "tl3", kind: "evidence_saved", label: "Evidence", title: "Transcript saved", summary: "Run transcript attached as evidence.", status: "saved", created_at: new Date(Date.now() - 300000).toISOString(), links: { evidence_id: "ev_demo01" } },
      ],
    },
    worklog: {
      items: [
        { id: "wl1", kind: "run_started", label: "Run started", title: "Codex run dispatched", summary: "Private runner session active.", status: "running", created_at: new Date(Date.now() - 900000).toISOString() },
        { id: "wl2", kind: "gate_pending", label: "Proof gate", title: "Awaiting operator review", summary: "No auto-dispatch after approval.", status: "pending", created_at: new Date(Date.now() - 600000).toISOString() },
      ],
    },
    proof_gates: {
      summary: { passed: 1, pending: 1, blocked: 0, needs_more_evidence: 0, total: 2 },
      items: [
        { gate_id: "gate_demo01", title: "Auth middleware audit", status: "approved", step_id: "step_1" },
        { gate_id: "gate_demo02", title: "Proof gate review flow", status: "pending", step_id: "step_2" },
      ],
    },
    agents: {
      summary: { ready: 2, working: 1, idle: 0 },
      items: [
        { id: "captain", name: "Captain", kind: "orchestrator", status: "ready", mode: "orchestrator", runnable: false },
        { id: "codex_cli", name: "Codex CLI", kind: "cli", status: "working", mode: "execution", runnable: true },
        { id: "jules_remote", name: "Jules Remote", kind: "remote", status: "ready", mode: "planning_only", runnable: false },
      ],
    },
    safety: {
      secure: true,
      public_runner_enabled: false,
      private_runner_enabled: true,
      arbitrary_shell_input: false,
      jules_runnable: false,
      secrets_exposed: false,
      items: [
        { key: "public_runner", label: "Public runner", status: "disabled", severity: "good", summary: "Public runner is disabled." },
        { key: "private_runner", label: "Private runner", status: "controlled", severity: "good", summary: "Private runner is controlled and write-gated." },
        { key: "runner_sessions", label: "Runner sessions", status: "healthy", severity: "good", summary: "2 active runner sessions." },
      ],
    },
    runner_sessions: { max_active_runner_sessions: 4, total_runner_sessions: 2, active_runner_sessions: 2, stale_runner_sessions: 0 },
    next_move: { label: "Review proof gate", description: "Approve or request more evidence before advancing the mission.", action: "review_gate" },
    evidence: {
      items: [
        { evidence_id: "ev_demo01", title: "Codex run transcript", type: "transcript", created_at: new Date(Date.now() - 300000).toISOString() },
        { evidence_id: "ev_demo02", title: "Auth middleware diff", type: "diff", created_at: new Date(Date.now() - 1800000).toISOString() },
      ],
    },
  };

  const DEMO_RUNNER = {
    max_active_runner_sessions: 4,
    total_runner_sessions: 2,
    active_runner_sessions: 2,
    stale_runner_sessions: 0,
    items: [
      { session_name: "mch_run_run_demo01", command: "node", title: "mcharness-public-export", age_seconds: 900, stale: false, active: true, safe_to_manage: true, linked_run_id: "run_demo01" },
      { session_name: "mch_run_run_demo02", command: "codex", title: "hybrid-agent-os", age_seconds: 420, stale: false, active: false, safe_to_manage: true, linked_run_id: null },
    ],
  };

  const crState = {
    demoMode: false,
    snapshot: null,
    runnerSessions: null,
    activeTab: "timeline",
    timelineFilter: "all",
    polling: null,
    lastRefresh: null,
    loadStatus: "connecting",
    loadError: null,
    initialized: false,
    registryWriteEnabled: false,
    dryRunResult: null,
    lastCleanupResult: null,
  };

  function escapeHtml(v) {
    return String(v || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function requestJson(url, opts = {}) {
    const res = await fetch(url, {
      headers: { "content-type": "application/json" },
      ...opts,
      body: opts.body ? (typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body)) : undefined,
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(txt || res.statusText);
    }
    return res.json();
  }

  function isDemoMode() {
    return crState.demoMode;
  }

  function formatTs(value) {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleString();
    } catch (e) {
      return String(value);
    }
  }

  function statusChipClass(status) {
    const s = String(status || "").toLowerCase();
    if (["healthy", "ready", "passed", "approved", "good", "disabled", "controlled"].includes(s)) return "chip-good";
    if (["warning", "pending", "needs_more_evidence", "idle", "planned"].includes(s)) return "chip-warn";
    if (["danger", "blocked", "limit_reached", "error", "stopped"].includes(s)) return "chip-bad";
    if (["running", "working", "in_progress"].includes(s)) return "chip-active";
    return "chip-muted";
  }

  function showToast(message, type = "info") {
    const host = document.getElementById("warden-toast-host");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `warden-toast warden-toast-${type}`;
    el.setAttribute("data-testid", "warden-toast");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "flex";
  }

  function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  }

  function missionActive(snapshot) {
    const m = snapshot && snapshot.mission;
    return m && m.mission_id && m.status && m.status !== "idle";
  }

  async function loadSnapshot() {
    if (crState.demoMode) {
      crState.snapshot = JSON.parse(JSON.stringify(DEMO_SNAPSHOT));
      crState.registryWriteEnabled = false;
      return crState.snapshot;
    }
    const data = await requestJson(`${MCH}/mission-control/snapshot`);
    crState.snapshot = data;
    crState.registryWriteEnabled = data.service_mode === "private";
    return data;
  }

  async function loadRunnerSessions() {
    if (crState.demoMode) {
      crState.runnerSessions = JSON.parse(JSON.stringify(DEMO_RUNNER));
      return crState.runnerSessions;
    }
    const data = await requestJson(`${MCH}/runner/sessions`);
    crState.runnerSessions = data;
    return data;
  }

  function setPolling(active) {
    if (crState.polling) {
      clearInterval(crState.polling);
      crState.polling = null;
    }
    if (!active || crState.demoMode) return;
    crState.polling = setInterval(() => {
      if (document.querySelector("#warden-section-mission.active")) {
        refreshAll({ quiet: true }).catch(() => {});
      }
    }, POLL_MS);
  }

  function renderDemoBanner() {
    const banner = document.getElementById("demo-mode-banner");
    if (!banner) return;
    banner.style.display = crState.demoMode ? "flex" : "none";
  }

  function serviceModeLabel(mode) {
    if (mode === "private") return "Private";
    if (mode === "public") return "Public";
    return null;
  }

  function renderTopBar() {
    const snap = crState.snapshot || {};
    const title = document.getElementById("topbar-page-title");
    if (title) title.textContent = "Control Room";
    const refreshed = document.getElementById("topbar-last-refresh");
    if (refreshed) refreshed.textContent = "";
    const live = document.getElementById("topbar-live-indicator");
    if (live) {
      if (crState.demoMode) {
        live.classList.remove("live-on");
        live.textContent = "Demo";
      } else if (crState.loadStatus === "degraded") {
        live.classList.remove("live-on");
        live.textContent = "Degraded";
      } else if (crState.loadStatus === "connecting") {
        live.classList.remove("live-on");
        live.textContent = "Connecting";
      } else {
        live.classList.toggle("live-on", true);
        live.textContent = "Live";
      }
    }
    const mode = document.getElementById("sidebar-service-mode");
    const modePill = document.getElementById("sidebar-mode-pill");
    const knownMode = serviceModeLabel(snap.service_mode);
    if (mode) mode.textContent = "";
    if (modePill) {
      if (crState.demoMode || snap.service_mode === "private") {
        modePill.textContent = "Private";
        modePill.className = "mode-pill mode-private";
      } else if (snap.service_mode === "public") {
        modePill.textContent = "Public";
        modePill.className = "mode-pill mode-public";
      } else if (crState.loadStatus === "connecting") {
        modePill.textContent = "…";
        modePill.className = "mode-pill mode-connecting";
      } else {
        modePill.textContent = "Unknown";
        modePill.className = "mode-pill mode-unknown";
      }
    }
  }

  function renderHero() {
    const snap = crState.snapshot || {};
    const mission = snap.mission || {};
    const active = missionActive(snap);
    const statusEl = document.getElementById("cr-mission-status-pill");
    if (statusEl) {
      statusEl.textContent = String(mission.status || "idle").replace(/_/g, " ");
      statusEl.className = `status-pill ${statusChipClass(mission.status || "idle")}`;
    }
    const captain = snap.agents && snap.agents.items && snap.agents.items.find((a) => a.id === "captain");
    const chips = [
      ["cr-chip-private-runner", snap.safety && snap.safety.private_runner_enabled ? "Private · Controlled" : "Private · Off", snap.safety && snap.safety.private_runner_enabled ? "chip-good" : "chip-muted"],
      ["hero-captain-status", captain ? `Captain · ${captain.status || "ready"}` : "Captain · —", "chip-active"],
      ["cr-chip-runner-health", snap.runner_sessions ? `Sessions · ${snap.runner_sessions.active_runner_sessions}/${snap.runner_sessions.max_active_runner_sessions}` : "Sessions · —", (snap.runner_sessions && snap.runner_sessions.active_runner_sessions >= snap.runner_sessions.max_active_runner_sessions) ? "chip-bad" : "chip-good"],
    ];
    chips.forEach(([id, text, cls]) => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = text;
        el.className = `hero-status-chip ${cls}`;
      }
    });

    const empty = document.getElementById("cr-mission-empty");
    const activeCard = document.getElementById("cr-mission-active");
    const captainPlan = document.getElementById("current-mission-plan");
    if (!empty || !activeCard) return;
    if (!active) {
      empty.style.display = "";
      activeCard.style.display = "none";
      return;
    }
    if (captainPlan) captainPlan.style.display = "none";
    empty.style.display = "none";
    activeCard.style.display = "";
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set("cr-mission-title", mission.title || "Active mission");
    set("cr-mission-id", mission.mission_id || "—");
    set("cr-mission-step", mission.current_step || "—");
    set("cr-mission-agent", mission.current_agent || "—");
    set("cr-mission-eta", mission.eta || "—");
    set("cr-mission-started", formatTs(mission.started_at));
    set("cr-mission-updated", formatTs(mission.updated_at));
    const pct = Number(mission.progress_pct || 0);
    const bar = document.getElementById("cr-mission-progress-bar");
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    set("cr-mission-progress-label", `${pct}%`);

    const pauseBtn = document.getElementById("cr-pause-mission");
    const adjustBtn = document.getElementById("cr-adjust-plan");
    const canAct = !crState.demoMode && crState.registryWriteEnabled && active;
    if (pauseBtn) pauseBtn.disabled = !canAct;
    if (adjustBtn) adjustBtn.disabled = !canAct;
  }

  function filteredTimelineItems() {
    const items = (crState.snapshot && crState.snapshot.timeline && crState.snapshot.timeline.items) || [];
    const f = crState.timelineFilter;
    if (f === "all") return items;
    const map = {
      plans: ["plan", "mission", "captain"],
      runs: ["run"],
      evidence: ["evidence"],
      gates: ["gate"],
      safety: ["runner", "safety", "cleanup"],
    };
    const keys = map[f] || [];
    return items.filter((item) => {
      const kind = String(item.kind || "").toLowerCase();
      return keys.some((k) => kind.includes(k));
    });
  }

  function setTabEmptyState(emptyEl, visible, message) {
    if (!emptyEl) return;
    if (!visible) {
      emptyEl.style.display = "none";
      emptyEl.textContent = "";
      return;
    }
    emptyEl.style.display = "";
    emptyEl.textContent = message;
  }

  function renderTimelineTab() {
    const list = document.getElementById("cr-tab-timeline-content");
    const empty = document.getElementById("cr-tab-timeline-empty");
    if (!list) return;
    const all = (crState.snapshot && crState.snapshot.timeline && crState.snapshot.timeline.items) || [];
    const items = filteredTimelineItems();
    document.querySelectorAll("[data-cr-timeline-filter]").forEach((btn) => {
      btn.classList.toggle("active", (btn.getAttribute("data-cr-timeline-filter") || "all") === crState.timelineFilter);
    });
    if (!all.length) {
      list.innerHTML = "";
      setTabEmptyState(empty, true, "No activity yet.");
      return;
    }
    if (!items.length) {
      list.innerHTML = "";
      setTabEmptyState(empty, true, "No events match this filter.");
      return;
    }
    setTabEmptyState(empty, false);
    list.innerHTML = items.map((item) => `
      <div class="timeline-rail-item timeline-rail-item-compact" data-testid="cr-timeline-item">
        <div class="timeline-rail-body">
          <div class="timeline-rail-top">
            <span class="timeline-rail-title">${escapeHtml(item.title || item.label || "Event")}</span>
            <span class="status-pill ${statusChipClass(item.status)}">${escapeHtml(String(item.status || "").toUpperCase())}</span>
          </div>
          <div class="timeline-rail-summary">${escapeHtml(item.summary || "")}</div>
          <span class="timeline-rail-time">${escapeHtml(formatTs(item.created_at))}</span>
        </div>
      </div>
    `).join("");
  }

  function renderPlanTab() {
    const host = document.getElementById("cr-tab-plan-content");
    const empty = document.getElementById("cr-tab-plan-empty");
    if (!host) return;
    const steps = (crState.snapshot && crState.snapshot.plan && crState.snapshot.plan.steps) || [];
    if (!steps.length) {
      host.innerHTML = "";
      if (empty) { empty.style.display = ""; empty.textContent = "No Captain plan loaded. Open Captain to develop a supervised plan."; }
      return;
    }
    if (empty) empty.style.display = "none";
    host.innerHTML = steps.map((step, i) => {
      const blocked = step.gate_status === "blocked" || step.status === "blocked";
      const needs = step.gate_status === "needs_more_evidence";
      return `
        <div class="plan-step-card ${step.current ? "current" : ""} ${blocked ? "blocked" : ""} ${needs ? "needs-evidence" : ""}" data-testid="cr-plan-step">
          <div class="plan-step-top">
            <span class="plan-step-num">Step ${i + 1}</span>
            <span class="status-pill ${statusChipClass(step.status)}">${escapeHtml(String(step.status || "queued").toUpperCase())}</span>
          </div>
          <div class="plan-step-title">${escapeHtml(step.title || step.step_id || "Step")}</div>
          <div class="plan-step-meta">Agent: ${escapeHtml(step.agent_id || "—")} · Gate: ${escapeHtml(step.gate_status || "none")} · ${step.duration_seconds ? `${step.duration_seconds}s` : "—"}</div>
          ${blocked ? '<div class="plan-step-alert">Blocked — resolve gate before continuing.</div>' : ""}
          ${needs ? '<div class="plan-step-alert warn">Needs more evidence before approval.</div>' : ""}
        </div>
      `;
    }).join("");
  }

  function renderWorklogTab() {
    const host = document.getElementById("cr-tab-worklog-content");
    const empty = document.getElementById("cr-tab-worklog-empty");
    if (!host) return;
    const items = (crState.snapshot && crState.snapshot.worklog && crState.snapshot.worklog.items) || [];
    if (!items.length) {
      host.innerHTML = "";
      setTabEmptyState(empty, true, "No worklog entries yet.");
      return;
    }
    setTabEmptyState(empty, false);
    host.innerHTML = items.map((item) => `
      <div class="worklog-line" data-testid="cr-worklog-line">
        <span class="worklog-line-time">${escapeHtml(formatTs(item.created_at))}</span>
        <span class="worklog-line-kind">${escapeHtml(item.label || item.kind || "log")}</span>
        <span class="worklog-line-msg">${escapeHtml(item.summary || item.title || "")}</span>
      </div>
    `).join("");
  }

  function renderEvidenceTab() {
    const host = document.getElementById("cr-tab-evidence-content");
    const empty = document.getElementById("cr-tab-evidence-empty");
    if (!host) return;
    const items = (crState.snapshot && crState.snapshot.evidence && crState.snapshot.evidence.items) || [];
    if (!items.length) {
      host.innerHTML = "";
      if (empty) {
        empty.style.display = "";
        empty.innerHTML = 'No evidence captured yet. Agent runs will attach transcripts, diffs, tests, and artifacts here. <button type="button" class="btn linkish" data-action="goto-evidence">Open Evidence view</button>';
        const btn = empty.querySelector("[data-action='goto-evidence']");
        if (btn) btn.addEventListener("click", () => window.WardenApp && window.WardenApp.setActiveSection("evidence"));
      }
      return;
    }
    if (empty) empty.style.display = "none";
    host.innerHTML = items.map((item) => `
      <div class="evidence-row" data-testid="cr-evidence-row">
        <strong>${escapeHtml(item.title || item.evidence_id || "Evidence")}</strong>
        <span class="muted">${escapeHtml(item.type || "")} · ${escapeHtml(formatTs(item.created_at))}</span>
      </div>
    `).join("");
  }

  function renderGatesTab() {
    const host = document.getElementById("cr-tab-gates-content");
    const empty = document.getElementById("cr-tab-gates-empty");
    if (!host) return;
    const gates = (crState.snapshot && crState.snapshot.proof_gates && crState.snapshot.proof_gates.items) || [];
    if (!gates.length) {
      host.innerHTML = "";
      if (empty) { empty.style.display = ""; empty.textContent = "No proof gates yet. Gates appear when runs need human review."; }
      return;
    }
    if (empty) empty.style.display = "none";
    host.innerHTML = gates.map((gate) => `
      <div class="gate-row" data-testid="cr-gate-row">
        <div class="gate-row-top">
          <strong>${escapeHtml(gate.title || gate.gate_id)}</strong>
          <span class="status-pill ${statusChipClass(gate.status)}">${escapeHtml(String(gate.status || "pending").toUpperCase())}</span>
        </div>
        <div class="muted">Step: ${escapeHtml(gate.step_id || "—")}</div>
      </div>
    `).join("");
  }

  function renderTabs() {
    document.querySelectorAll("[data-cr-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-cr-tab") === crState.activeTab);
    });
    document.querySelectorAll(".cr-tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.getAttribute("data-cr-panel") === crState.activeTab);
    });
    if (crState.activeTab === "timeline") renderTimelineTab();
    if (crState.activeTab === "plan") renderPlanTab();
    if (crState.activeTab === "worklog") renderWorklogTab();
    if (crState.activeTab === "evidence") renderEvidenceTab();
    if (crState.activeTab === "gates") renderGatesTab();
  }

  function renderRailGates() {
    const host = document.getElementById("rail-proof-gates");
    if (!host) return;
    const pg = (crState.snapshot && crState.snapshot.proof_gates) || {};
    const summary = pg.summary || {};
    const items = pg.items || [];
    host.innerHTML = `
      <div class="rail-stat-row">
        <span class="rail-stat good">${Number(summary.passed || 0)} passed</span>
        <span class="rail-stat warn">${Number(summary.pending || 0)} pending</span>
        <span class="rail-stat bad">${Number(summary.blocked || 0)} blocked</span>
        <span class="rail-stat warn">${Number(summary.needs_more_evidence || 0)} needs evidence</span>
      </div>
      <div class="rail-mini-list">${items.slice(0, 3).map((g) => `<div class="rail-mini-item"><span>${escapeHtml(g.title || g.gate_id)}</span><span class="status-pill ${statusChipClass(g.status)}">${escapeHtml(g.status)}</span></div>`).join("") || '<div class="muted">No gates yet</div>'}</div>
    `;
  }

  function railAgentTypeLabel(agent) {
    const id = String(agent.id || "");
    const kind = String(agent.kind || "").toLowerCase();
    const mode = String(agent.mode || "").toLowerCase();
    if (id === "captain" || kind === "orchestrator" || mode === "orchestrator") return "Orchestrator";
    if (id === "codex_cli" || kind === "cli") return "CLI Agent";
    if (kind === "remote" || mode === "planning_only") return "Remote · Planning only";
    return kind || "Agent";
  }

  function railAgentStatusLabel(agent) {
    const mode = String(agent.mode || "").toLowerCase();
    if (mode === "planning_only") return "Planning only";
    if (agent.id === "captain") return agent.status === "ready" ? "Configured" : "Not configured";
    return agent.status || "idle";
  }

  function sortRailAgents(items) {
    const order = { captain: 0, codex_cli: 1 };
    return [...items].sort((a, b) => {
      const aRank = Object.prototype.hasOwnProperty.call(order, a.id) ? order[a.id] : 2;
      const bRank = Object.prototype.hasOwnProperty.call(order, b.id) ? order[b.id] : 2;
      if (aRank !== bRank) return aRank - bRank;
      return String(a.name || a.id).localeCompare(String(b.name || b.id));
    });
  }

  function renderRailAgents() {
    const host = document.getElementById("rail-connected-agents");
    if (!host) return;
    const items = sortRailAgents((crState.snapshot && crState.snapshot.agents && crState.snapshot.agents.items) || []);
    host.innerHTML = items.map((agent) => `
      <div class="rail-agent-row" data-testid="rail-agent-row">
        <div class="rail-agent-copy">
          <span class="rail-agent-name">${escapeHtml(agent.name || agent.id)}</span>
          <span class="rail-agent-type muted">${escapeHtml(railAgentTypeLabel(agent))}</span>
        </div>
        <span class="status-pill ${statusChipClass(agent.status || agent.mode)}">${escapeHtml(railAgentStatusLabel(agent))}</span>
      </div>
    `).join("") || '<div class="muted">No agents loaded</div>';
  }

  function renderRailRunner() {
    const host = document.getElementById("rail-runner-sessions");
    if (!host) return;
    const rs = crState.runnerSessions || (crState.snapshot && crState.snapshot.runner_sessions) || {};
    const atLimit = Number(rs.active_runner_sessions || 0) >= Number(rs.max_active_runner_sessions || 4);
    const items = rs.items || [];
    host.innerHTML = `
      <div class="rail-stat-row">
        <span class="rail-stat ${atLimit ? "bad" : "good"}">${Number(rs.active_runner_sessions || 0)} active</span>
        <span class="rail-stat muted">max ${Number(rs.max_active_runner_sessions || 4)}</span>
        <span class="rail-stat warn">${Number(rs.stale_runner_sessions || 0)} stale</span>
        <span class="rail-stat muted">${Number(rs.total_runner_sessions || 0)} total</span>
      </div>
      <div class="rail-mini-list">${items.slice(0, 3).map((row) => `
        <div class="rail-mini-item" data-testid="rail-runner-session-row">
          <span class="mono">${escapeHtml(row.session_name)}</span>
          <span class="status-pill ${row.active ? "chip-active" : "chip-muted"}">${row.active ? "active" : "idle"}</span>
        </div>
      `).join("") || '<div class="muted">No runner sessions</div>'}</div>
      ${atLimit ? '<div class="rail-alert bad">Session limit reached.</div>' : ""}
    `;
    const dryBtn = document.getElementById("rail-runner-dry-run");
    const confirmBtn = document.getElementById("rail-runner-confirm");
    const canCleanup = !crState.demoMode && crState.registryWriteEnabled;
    if (dryBtn) {
      dryBtn.disabled = !canCleanup;
      dryBtn.title = canCleanup ? "Dry-run cleanup (no kills)" : "Cleanup requires private write-enabled service";
    }
    if (confirmBtn) {
      confirmBtn.disabled = !canCleanup || !crState.dryRunResult;
      confirmBtn.title = !canCleanup ? "Public cleanup blocked" : (!crState.dryRunResult ? "Run dry-run first" : "Confirm cleanup");
    }
  }

  function safetyRowLabel(key, label) {
    const map = {
      public_runner: "Public runner",
      private_runner: "Private runner",
      runner_sessions: "Runner sessions",
      shell_input: "Shell access",
      arbitrary_shell_input: "Shell access",
      agent_registration: "Registration",
    };
    return map[key] || label || key;
  }

  function safetyRowValue(item) {
    const key = String(item.key || "").toLowerCase();
    const status = String(item.status || "").toLowerCase();
    if (key === "public_runner") return status === "disabled" ? "Off" : "On";
    if (key === "private_runner") return status === "controlled" ? "Controlled" : status === "disabled" ? "Off" : "On";
    if (key === "runner_sessions") return status === "healthy" ? "Healthy" : status;
    if (key.includes("shell")) return status === "disabled" ? "Restricted" : "Enabled";
    return item.summary || item.status || "—";
  }

  function renderRailSafety() {
    const host = document.getElementById("rail-safety-status");
    if (!host) return;
    const snap = crState.snapshot && crState.snapshot.safety;
    // A safety indicator must default to the SAFE reading when its data hasn't
    // loaded yet — previously "no snapshot" fell through to "enabled" for the
    // public runner, which is backwards (looked like public dispatch was on when
    // it was actually just unloaded).
    const defaults = [
      { key: "public_runner", label: "Public runner", status: snap && snap.public_runner_enabled ? "enabled" : "disabled" },
      { key: "private_runner", label: "Private runner", status: snap && snap.private_runner_enabled ? "controlled" : "disabled" },
      { key: "shell_input", label: "Shell access", status: snap && snap.arbitrary_shell_input ? "enabled" : "disabled" },
    ];
    const items = (snap && snap.items && snap.items.length) ? snap.items.filter((item) => ["public_runner", "private_runner", "arbitrary_shell_input", "shell_input"].includes(String(item.key || ""))) : defaults;
    const rows = items.length ? items : defaults;
    host.innerHTML = rows.slice(0, 3).map((item) => `
      <div class="rail-safety-row" data-testid="rail-safety-row">
        <span>${escapeHtml(safetyRowLabel(item.key, item.label))}</span>
        <span class="status-pill ${statusChipClass(item.severity || item.status)}">${escapeHtml(safetyRowValue(item))}</span>
      </div>
    `).join("") || '<div class="muted">Unavailable</div>';
  }

  function renderRailNextMove() {
    const host = document.getElementById("rail-next-move");
    if (!host) return;
    const nm = (crState.snapshot && crState.snapshot.next_move) || {};
    host.innerHTML = `
      <div class="rail-next-label">${escapeHtml(nm.label || "Awaiting mission")}</div>
      <div class="rail-next-desc">${escapeHtml(nm.description || "Start a Captain plan.")}</div>
    `;
  }

  function renderRunnerSessionsView() {
    const summary = document.getElementById("runner-sessions-summary");
    const table = document.getElementById("runner-sessions-table");
    const result = document.getElementById("runner-sessions-result");
    const rs = crState.runnerSessions || {};
    if (summary) {
      summary.innerHTML = `
        <div class="summary-stat"><strong>${Number(rs.active_runner_sessions || 0)}</strong><span>Active</span></div>
        <div class="summary-stat"><strong>${Number(rs.stale_runner_sessions || 0)}</strong><span>Stale</span></div>
        <div class="summary-stat"><strong>${Number(rs.total_runner_sessions || 0)}</strong><span>Total</span></div>
        <div class="summary-stat"><strong>${Number(rs.max_active_runner_sessions || 4)}</strong><span>Max</span></div>
      `;
    }
    const items = rs.items || [];
    if (table) {
      if (!items.length) {
        table.innerHTML = '<div class="empty-state-card"><h3>No sessions</h3></div>';
      } else {
        table.innerHTML = `
          <table class="runner-table">
            <thead><tr><th>Session</th><th>Command</th><th>Title</th><th>Age</th><th>Stale</th><th>Linked run</th><th>Safe</th></tr></thead>
            <tbody>${items.map((row) => `
              <tr data-testid="runner-session-row">
                <td class="mono">${escapeHtml(row.session_name)}</td>
                <td>${escapeHtml(row.command || "—")}</td>
                <td>${escapeHtml(row.title || "—")}</td>
                <td>${row.age_seconds != null ? `${row.age_seconds}s` : "—"}</td>
                <td>${row.stale ? "Yes" : "No"}</td>
                <td>${escapeHtml(row.linked_run_id || "—")}</td>
                <td>${row.safe_to_manage ? "Yes" : "No"}</td>
              </tr>
            `).join("")}</tbody>
          </table>
        `;
      }
    }
    const canCleanup = !crState.demoMode && crState.registryWriteEnabled;
    const disabledNote = document.getElementById("runner-sessions-disabled-note");
    if (disabledNote) disabledNote.style.display = canCleanup ? "none" : "";
    const dryBtn = document.getElementById("runner-view-dry-run");
    const confirmBtn = document.getElementById("runner-view-confirm");
    if (dryBtn) dryBtn.disabled = !canCleanup;
    if (confirmBtn) confirmBtn.disabled = !canCleanup || !crState.dryRunResult;
    if (result && crState.lastCleanupResult) {
      const r = crState.lastCleanupResult;
      result.innerHTML = `<pre class="cleanup-result-pre">${escapeHtml(JSON.stringify({ dry_run: r.dry_run, candidates: r.candidates, killed: r.killed, skipped: r.skipped, errors: r.errors }, null, 2))}</pre>`;
    }
  }

  function renderProofGatesView() {
    const host = document.getElementById("proof-gates-view-content");
    if (!host) return;
    const pg = (crState.snapshot && crState.snapshot.proof_gates) || {};
    const items = pg.items || [];
    if (!items.length) {
      host.innerHTML = '<div class="empty-state-card"><h3>No gates yet</h3></div>';
      return;
    }
    host.innerHTML = items.map((gate) => `
      <div class="proof-gate-card" data-testid="proof-gate-view-card">
        <div class="proof-gate-card-top">
          <strong>${escapeHtml(gate.title || gate.gate_id)}</strong>
          <span class="status-pill ${statusChipClass(gate.status)}">${escapeHtml(String(gate.status || "pending").toUpperCase())}</span>
        </div>
        <div class="muted">${escapeHtml(gate.step_id || "—")}</div>
      </div>
    `).join("");
  }

  function renderEvidenceViewPolish() {
    const lead = document.getElementById("evidence-section-lead");
    if (lead) lead.textContent = "Transcripts, diffs, and artifacts.";
  }

  function markReady() {
    const shell = document.querySelector("[data-testid='warden-shell']");
    if (shell) shell.setAttribute("data-control-room-ready", "1");
  }

  function renderAll() {
    renderDemoBanner();
    renderTopBar();
    renderHero();
    renderTabs();
    renderRailGates();
    renderRailAgents();
    renderRailRunner();
    renderRailSafety();
    renderRailNextMove();
    renderRunnerSessionsView();
    renderProofGatesView();
    renderEvidenceViewPolish();
    syncLegacyMissionPanel();
    markReady();
  }

  function syncLegacyMissionPanel() {
    const status = document.getElementById("current-mission-status");
    const empty = document.getElementById("current-mission-empty");
    const plan = document.getElementById("current-mission-plan");
    const mission = (crState.snapshot && crState.snapshot.mission) || {};
    if (status) {
      if (missionActive(crState.snapshot)) {
        status.textContent = `${mission.title || "Active mission"} · ${mission.status || "running"}`;
        if (empty) empty.style.display = "none";
        if (plan) plan.style.display = "";
      } else {
        status.textContent = "No active mission. Start a Captain plan.";
        if (empty) empty.style.display = "";
        if (plan) plan.style.display = "none";
      }
    }
    const timelineEmpty = document.getElementById("mission-timeline-empty");
    const timelineList = document.getElementById("mission-worklog-list");
    const items = (crState.snapshot && crState.snapshot.timeline && crState.snapshot.timeline.items) || [];
    if (timelineList && timelineEmpty) {
      if (!items.length) {
        return;
      } else {
        timelineEmpty.style.display = "none";
        timelineList.style.display = "flex";
        timelineList.innerHTML = items.slice(0, 8).map((item) => `
          <div class="worklog-event-card">
            <div class="worklog-event-top"><span class="worklog-event-label">${escapeHtml(item.label || item.kind)}</span></div>
            <p class="worklog-event-title">${escapeHtml(item.title || "")}</p>
            <p class="worklog-event-summary">${escapeHtml(item.summary || "")}</p>
          </div>
        `).join("");
      }
    }
  }

  async function refreshAll({ quiet = false } = {}) {
    if (!crState.demoMode && crState.loadStatus !== "ok") {
      crState.loadStatus = "connecting";
      renderTopBar();
    }
    let snapshotOk = false;
    let runnerOk = false;
    try {
      await loadSnapshot();
      snapshotOk = true;
    } catch (e) {
      crState.loadError = e.message || String(e);
      if (!crState.demoMode) crState.snapshot = crState.snapshot || null;
    }
    try {
      await loadRunnerSessions();
      runnerOk = true;
    } catch (e) {
      crState.loadError = crState.loadError || e.message || String(e);
      crState.runnerSessions = crState.runnerSessions || null;
    }
    if (crState.demoMode || snapshotOk || runnerOk) {
      crState.loadStatus = "ok";
      crState.loadError = null;
      crState.lastRefresh = new Date().toISOString();
    } else if (!crState.lastRefresh) {
      crState.loadStatus = "degraded";
    } else {
      crState.loadStatus = "degraded";
    }
    renderAll();
    if (!quiet) showToast(crState.demoMode ? "Demo preview refreshed" : "Control Room refreshed");
  }

  async function runDryRunCleanup() {
    if (crState.demoMode) {
      showToast("Demo mode — cleanup disabled", "warn");
      return;
    }
    if (!crState.registryWriteEnabled) {
      showToast("Cleanup requires private write-enabled service", "warn");
      return;
    }
    const result = await requestJson(`${MCH}/runner/sessions/cleanup`, {
      method: "POST",
      body: { confirm: false, stale_after_seconds: 7200 },
    });
    crState.dryRunResult = result;
    crState.lastCleanupResult = result;
    const body = document.getElementById("cleanup-dryrun-body");
    if (body) {
      body.innerHTML = `<pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
    }
    openModal("cleanup-dryrun-modal");
    renderRailRunner();
    renderRunnerSessionsView();
    showToast(`Dry-run: ${(result.candidates || []).length} candidate(s), 0 killed`);
  }

  async function runConfirmCleanup() {
    if (crState.demoMode || !crState.registryWriteEnabled || !crState.dryRunResult) return;
    const result = await requestJson(`${MCH}/runner/sessions/cleanup`, {
      method: "POST",
      body: { confirm: true, stale_after_seconds: 7200 },
    });
    crState.dryRunResult = null;
    crState.lastCleanupResult = result;
    closeModal("cleanup-confirm-modal");
    await refreshAll({ quiet: true });
    showToast(`Cleanup complete: ${(result.killed || []).length} session(s) removed`, "good");
  }

  async function pauseMission() {
    if (crState.demoMode || !crState.registryWriteEnabled) return;
    const missionId = crState.snapshot && crState.snapshot.mission && crState.snapshot.mission.mission_id;
    if (!missionId) return;
    await requestJson(`${MCH}/missions/${encodeURIComponent(missionId)}/pause`, { method: "POST", body: {} });
    closeModal("pause-mission-modal");
    await refreshAll({ quiet: true });
    showToast("Mission paused", "good");
  }

  async function adjustPlan() {
    if (crState.demoMode || !crState.registryWriteEnabled) return;
    const missionId = crState.snapshot && crState.snapshot.mission && crState.snapshot.mission.mission_id;
    const noteEl = document.getElementById("adjust-plan-note");
    const note = noteEl ? noteEl.value.trim() : "";
    if (!missionId || !note) return;
    const result = await requestJson(`${MCH}/missions/${encodeURIComponent(missionId)}/adjust-plan`, {
      method: "POST",
      body: { note, adjustments: {} },
    });
    closeModal("adjust-plan-modal");
    showToast(result.human_review_required ? "Plan adjustment requested — human review required" : "Plan adjustment recorded", "good");
    await refreshAll({ quiet: true });
  }

  function openCommandPalette() {
    const el = document.getElementById("command-palette");
    if (el) {
      el.style.display = "flex";
      const input = document.getElementById("command-palette-input");
      if (input) { input.value = ""; input.focus(); }
      filterCommandPalette("");
    }
  }

  function closeCommandPalette() {
    closeModal("command-palette");
  }

  const COMMANDS = [
    { id: "refresh", label: "Refresh snapshot", run: () => refreshAll() },
    { id: "captain", label: "Open Captain / Develop Plan", run: () => document.querySelector("[data-action='develop-plan']") && document.querySelector("[data-action='develop-plan']").click() },
    { id: "agents", label: "Open Agents", run: () => window.WardenApp && window.WardenApp.setActiveSection("agents") },
    { id: "runs", label: "Open Runs", run: () => window.WardenApp && window.WardenApp.setActiveSection("runs") },
    { id: "evidence", label: "Open Evidence", run: () => window.WardenApp && window.WardenApp.setActiveSection("evidence") },
    { id: "gates", label: "Open Proof Gates", run: () => window.WardenApp && window.WardenApp.setActiveSection("proof-gates") },
    { id: "runner", label: "Open Runner Sessions", run: () => window.WardenApp && window.WardenApp.setActiveSection("runner-sessions") },
    { id: "dryrun", label: "Dry-run runner cleanup", run: () => runDryRunCleanup() },
    { id: "settings", label: "Open Settings", run: () => window.WardenApp && window.WardenApp.setActiveSection("settings") },
    { id: "copy", label: "Copy current mission summary", run: () => {
      const m = crState.snapshot && crState.snapshot.mission;
      if (!m || !m.mission_id) { showToast("No mission to copy", "warn"); return; }
      const text = `Warden Mission: ${m.title || m.mission_id} · ${m.status} · ${m.progress_pct || 0}%`;
      navigator.clipboard.writeText(text).then(() => showToast("Mission summary copied")).catch(() => showToast("Copy failed", "warn"));
    }},
  ];

  function filterCommandPalette(query) {
    const list = document.getElementById("command-palette-list");
    if (!list) return;
    const q = String(query || "").toLowerCase();
    const filtered = COMMANDS.filter((c) => c.label.toLowerCase().includes(q));
    list.innerHTML = filtered.map((cmd) => `<button type="button" class="command-item" data-command-id="${cmd.id}">${escapeHtml(cmd.label)}</button>`).join("");
    list.querySelectorAll("[data-command-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cmd = COMMANDS.find((c) => c.id === btn.getAttribute("data-command-id"));
        closeCommandPalette();
        if (cmd) cmd.run();
      });
    });
  }

  function wireEvents() {
    document.getElementById("topbar-refresh")?.addEventListener("click", () => refreshAll());
    document.getElementById("topbar-command")?.addEventListener("click", openCommandPalette);
    document.getElementById("command-palette-close")?.addEventListener("click", closeCommandPalette);
    document.getElementById("command-palette")?.addEventListener("click", (e) => { if (e.target.id === "command-palette") closeCommandPalette(); });
    document.getElementById("command-palette-input")?.addEventListener("input", (e) => filterCommandPalette(e.target.value));
    document.querySelectorAll("[data-cr-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        crState.activeTab = btn.getAttribute("data-cr-tab") || "timeline";
        renderTabs();
      });
    });
    document.querySelectorAll("[data-cr-timeline-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        crState.timelineFilter = btn.getAttribute("data-cr-timeline-filter") || "all";
        renderTimelineTab();
      });
    });
    document.getElementById("cr-pause-mission")?.addEventListener("click", () => openModal("pause-mission-modal"));
    document.getElementById("cr-adjust-plan")?.addEventListener("click", () => openModal("adjust-plan-modal"));
    document.getElementById("pause-mission-confirm")?.addEventListener("click", () => pauseMission().catch((e) => showToast(e.message, "warn")));
    document.getElementById("pause-mission-cancel")?.addEventListener("click", () => closeModal("pause-mission-modal"));
    document.getElementById("adjust-plan-submit")?.addEventListener("click", () => adjustPlan().catch((e) => showToast(e.message, "warn")));
    document.getElementById("adjust-plan-cancel")?.addEventListener("click", () => closeModal("adjust-plan-modal"));
    document.getElementById("rail-runner-dry-run")?.addEventListener("click", () => runDryRunCleanup().catch((e) => showToast(e.message, "warn")));
    document.getElementById("rail-runner-confirm")?.addEventListener("click", () => openModal("cleanup-confirm-modal"));
    document.getElementById("runner-view-dry-run")?.addEventListener("click", () => runDryRunCleanup().catch((e) => showToast(e.message, "warn")));
    document.getElementById("runner-view-confirm")?.addEventListener("click", () => openModal("cleanup-confirm-modal"));
    document.getElementById("cleanup-dryrun-close")?.addEventListener("click", () => closeModal("cleanup-dryrun-modal"));
    document.getElementById("cleanup-confirm-cancel")?.addEventListener("click", () => closeModal("cleanup-confirm-modal"));
    document.getElementById("cleanup-confirm-submit")?.addEventListener("click", () => runConfirmCleanup().catch((e) => showToast(e.message, "warn")));
    document.getElementById("rail-review-gates")?.addEventListener("click", () => window.WardenApp && window.WardenApp.setActiveSection("proof-gates"));
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openCommandPalette();
      }
      if (e.key === "Escape") closeCommandPalette();
    });
  }

  function init() {
    if (crState.initialized) {
      refreshAll({ quiet: true }).catch(() => renderAll());
      return;
    }
    crState.initialized = true;
    crState.demoMode = new URLSearchParams(window.location.search).get("demo") === "1";
    wireEvents();
    if (crState.demoMode) {
      crState.loadStatus = "ok";
      refreshAll({ quiet: true }).catch(() => renderAll());
    } else {
      refreshAll({ quiet: true }).catch(() => renderAll());
    }
    setPolling(true);
  }

  window.WardenControlRoom = {
    init,
    refresh: refreshAll,
    isDemoMode,
    isInitialized: () => crState.initialized,
    getSnapshot: () => crState.snapshot,
    onSectionChange(section) {
      if (section === "mission" || section === "control-room") setPolling(true);
      else setPolling(false);
      if (section === "runner-sessions" || section === "proof-gates") renderAll();
    },
  };
})();