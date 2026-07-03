/* Warden Projects — Command Center module */
(function () {
  "use strict";

  const API = "/api/mcharness";

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  let _currentProject = null;
  let _projects = [];
  let _worktrees = [];
  let _refreshTimer = null;

  /* ------------------------------------------------------------------ */
  /* Utility                                                              */
  /* ------------------------------------------------------------------ */
  function relTime(iso) {
    if (!iso) return "";
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function csvToArray(s) {
    return s.split(",").map((x) => x.trim()).filter(Boolean);
  }

  function toast(msg, type = "good") {
    if (window.wardenToast) { window.wardenToast(msg, type); return; }
    const host = document.getElementById("warden-toast-host");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `warden-toast warden-toast-${type}`;
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  async function apiFetch(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(text);
    }
    return res.json();
  }

  /* ------------------------------------------------------------------ */
  /* Status helpers                                                       */
  /* ------------------------------------------------------------------ */
  const STATUS_LABELS = {
    idle: "Idle",
    running: "Running",
    waiting_proof: "Needs proof",
    merged: "Merged",
    abandoned: "Abandoned",
  };

  function statusBadge(status) {
    const label = STATUS_LABELS[status] || status;
    return `<span class="wt-status-badge wt-status-${status}">${label}</span>`;
  }

  /* ------------------------------------------------------------------ */
  /* Render — overview                                                    */
  /* ------------------------------------------------------------------ */
  function renderOverview() {
    const grid = document.getElementById("projects-grid");
    const empty = document.getElementById("projects-empty");
    if (!grid) return;

    if (_projects.length === 0) {
      grid.innerHTML = "";
      empty && grid.appendChild(empty);
      empty && (empty.style.display = "");
      return;
    }

    empty && (empty.style.display = "none");
    grid.innerHTML = _projects
      .map((p) => {
        const agents = p.agent_ids || [];
        const tags = p.brain_tags || [];
        return `
        <div class="project-card" data-project-id="${p.project_id}" tabindex="0" role="button" aria-label="Open ${p.name}">
          <div class="project-card-top">
            <h3 class="project-card-name">${p.name}</h3>
            <span class="project-stat-chip ${p.status === 'active' ? 'active' : ''}">${p.status}</span>
          </div>
          <div class="project-card-repo">${p.repo_path}</div>
          <div class="project-card-stats">
            <span class="project-stat-chip">${agents.length} agent${agents.length !== 1 ? "s" : ""}</span>
            ${p.worktree_root ? `<span class="project-stat-chip">Worktrees enabled</span>` : ""}
            <span class="project-stat-chip">${relTime(p.updated_at)}</span>
          </div>
          ${tags.length ? `<div class="project-card-tags">${tags.map((t) => `<span class="memory-chip">${t}</span>`).join("")}</div>` : ""}
        </div>`;
      })
      .join("");

    grid.querySelectorAll(".project-card").forEach((card) => {
      card.addEventListener("click", () => openProject(card.dataset.projectId));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") openProject(card.dataset.projectId);
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Render — detail                                                      */
  /* ------------------------------------------------------------------ */
  function renderDetail(project) {
    // Context strip
    const nameEl = document.getElementById("project-context-name");
    const repoEl = document.getElementById("project-context-repo");
    const chipsEl = document.getElementById("project-context-chips");
    if (nameEl) nameEl.textContent = project.name;
    if (repoEl) repoEl.textContent = project.repo_path;
    if (chipsEl) {
      chipsEl.innerHTML = (project.brain_tags || [])
        .map((t) => `<span class="memory-chip">${t}</span>`)
        .join("");
    }

    // Agent cards
    renderAgentCards(project);

    // Templates (brain memories tagged with project) — load async
    loadTemplates(project);

    // Worktrees
    loadWorktrees(project);

    // Proof ledger
    loadProofLedger(project);

    // Bootstrap / next action
    loadBootstrap(project);

    // Runs
    loadRuns(project);
  }

  function renderAgentCards(project) {
    const el = document.getElementById("project-agent-cards");
    if (!el) return;
    const agents = project.agent_ids || [];
    if (!agents.length) {
      el.innerHTML = `<p class="muted" style="font-size:0.82rem;">No agents configured.</p>`;
      return;
    }
    el.innerHTML = agents
      .map(
        (id) => `
      <div class="project-agent-card">
        <div>
          <div class="project-agent-name">${id.replace(/_/g, " ")}</div>
          <div class="project-agent-id">${id}</div>
        </div>
        <button type="button" class="btn" style="font-size:0.72rem;padding:4px 8px;"
          onclick="window._wardenProjects.launchFor('${project.project_id}', '${id}')">Launch</button>
      </div>`
      )
      .join("");
  }

  async function loadTemplates(project) {
    const el = document.getElementById("project-templates");
    if (!el) return;
    el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Loading…</span>`;
    try {
      const data = await apiFetch(
        `${API}/projects/${project.project_id}/recall?query=&kind=agent_prompt&limit=8`
      );
      const memories = data.memories || data.results || [];
      if (!memories.length) {
        el.innerHTML = `<span class="muted" style="font-size:0.78rem;">No templates yet.</span>`;
        return;
      }
      el.innerHTML = memories
        .map(
          (m) => `
        <div class="project-template-item" data-prompt="${encodeURIComponent(m.summary || m.content || "")}"
          title="${m.title || m.summary || ""}">
          ${m.title || m.summary?.slice(0, 60) || m.memory_id}
        </div>`
        )
        .join("");
      el.querySelectorAll(".project-template-item").forEach((item) => {
        item.addEventListener("click", () => {
          const prompt = decodeURIComponent(item.dataset.prompt || "");
          openLaunchDrawer(project.project_id, "", prompt);
        });
      });
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Could not load templates.</span>`;
    }
  }

  async function loadWorktrees(project) {
    const tbody = document.getElementById("worktrees-tbody");
    const empty = document.getElementById("worktrees-empty");
    const countEl = document.getElementById("worktrees-count");
    if (!tbody) return;
    try {
      _worktrees = await apiFetch(`${API}/projects/${project.project_id}/worktrees`);
      const visible = _worktrees.filter((w) => w.branch !== "main" && w.branch !== (project.default_branch || "main"));
      if (countEl) countEl.textContent = `${visible.length}`;
      if (!visible.length) {
        tbody.innerHTML = "";
        empty && (empty.style.display = "");
        return;
      }
      empty && (empty.style.display = "none");
      tbody.innerHTML = visible
        .map(
          (w) => `
        <tr>
          <td><span class="wt-branch">${w.branch}</span></td>
          <td>${w.agent_id || '<span class="muted">—</span>'}</td>
          <td>${statusBadge(w.status || "idle")}</td>
          <td>
            <div class="wt-actions">
              <button type="button" class="btn" onclick="window._wardenProjects.setWtStatus('${project.project_id}','${w.worktree_id || w.branch}','waiting_proof')">Proof</button>
              <button type="button" class="btn warn" onclick="window._wardenProjects.setWtStatus('${project.project_id}','${w.worktree_id || w.branch}','abandoned')">Abandon</button>
            </div>
          </td>
        </tr>`
        )
        .join("");
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" class="muted" style="font-size:0.82rem;">Could not load worktrees.</td></tr>`;
    }
  }

  async function loadProofLedger(project) {
    const el = document.getElementById("project-proof-ledger");
    if (!el) return;
    el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Loading…</span>`;
    try {
      const data = await apiFetch(
        `${API}/projects/${project.project_id}/recall?query=&kind=proof&limit=10`
      );
      const items = data.memories || data.results || [];
      if (!items.length) {
        el.innerHTML = `<span class="muted" style="font-size:0.78rem;">No proofs yet.</span>`;
        return;
      }
      el.innerHTML = items
        .map(
          (m) => `
        <div class="proof-ledger-item">
          <div class="proof-ledger-top">
            <span class="proof-ledger-title">${m.title || "Proof"}</span>
            <span class="memory-chip kind-proof">${m.kind || "proof"}</span>
          </div>
          <div class="proof-ledger-summary">${(m.summary || "").slice(0, 120)}</div>
          <div style="font-size:0.7rem;color:var(--muted);margin-top:4px;">${relTime(m.updated_at)}</div>
        </div>`
        )
        .join("");
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Could not load ledger.</span>`;
    }
  }

  async function loadBootstrap(project) {
    const el = document.getElementById("project-next-action");
    if (!el) return;
    try {
      const data = await apiFetch(`${API}/projects/${project.project_id}/bootstrap?task=`);
      const next = data?.recommended_next_action || data?.next_action;
      if (next) {
        el.innerHTML = `<div class="project-next-chip">${next}</div>`;
      } else {
        el.innerHTML = `<span class="muted" style="font-size:0.84rem;">No recommendation yet. Add memories to get one.</span>`;
      }
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.84rem;">Could not load bootstrap.</span>`;
    }
  }

  async function loadRuns(project) {
    const el = document.getElementById("project-runs-list");
    if (!el) return;
    el.innerHTML = `<span class="muted" style="font-size:0.82rem;">Loading…</span>`;
    try {
      const data = await apiFetch(`${API}/runs/recent`).catch(() => null);
      const runs = (data?.runs || []).slice(0, 8);
      if (!runs.length) {
        el.innerHTML = `<span class="muted" style="font-size:0.82rem;">No runs yet.</span>`;
        return;
      }
      el.innerHTML = runs
        .map(
          (r) => `
        <div class="project-run-row">
          <span class="${r.status === 'success' ? 'chip-good' : r.status === 'failed' ? 'chip-bad' : 'chip-muted'}" style="font-size:0.72rem;">${r.status}</span>
          <span class="mono">${r.run_id?.slice(0, 12) || "—"}</span>
          <span style="font-size:0.72rem;color:var(--muted);">${relTime(r.started_at)}</span>
        </div>`
        )
        .join("");
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.82rem;">Could not load runs.</span>`;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Navigation                                                           */
  /* ------------------------------------------------------------------ */
  function showOverview() {
    _currentProject = null;
    clearInterval(_refreshTimer);
    const ov = document.getElementById("projects-overview");
    const dt = document.getElementById("projects-detail");
    if (ov) ov.style.display = "";
    if (dt) dt.style.display = "none";
  }

  async function openProject(projectId) {
    const project = _projects.find((p) => p.project_id === projectId);
    if (!project) return;
    _currentProject = project;

    const ov = document.getElementById("projects-overview");
    const dt = document.getElementById("projects-detail");
    if (ov) ov.style.display = "none";
    if (dt) dt.style.display = "";

    renderDetail(project);

    // Auto-refresh worktrees every 15s while in detail view
    clearInterval(_refreshTimer);
    _refreshTimer = setInterval(() => {
      if (_currentProject) loadWorktrees(_currentProject);
    }, 15000);
  }

  /* ------------------------------------------------------------------ */
  /* Create project modal                                                 */
  /* ------------------------------------------------------------------ */
  function openNewProjectModal() {
    const modal = document.getElementById("new-project-modal");
    if (modal) { modal.style.display = "flex"; document.getElementById("np-name")?.focus(); }
  }

  function closeNewProjectModal() {
    const modal = document.getElementById("new-project-modal");
    if (modal) modal.style.display = "none";
  }

  async function submitNewProject() {
    const name = document.getElementById("np-name")?.value?.trim();
    const repo = document.getElementById("np-repo")?.value?.trim();
    const wroot = document.getElementById("np-worktrees")?.value?.trim();
    const agents = csvToArray(document.getElementById("np-agents")?.value || "");
    const tags = csvToArray(document.getElementById("np-tags")?.value || "");
    const errEl = document.getElementById("np-error");

    if (!name || !repo) {
      if (errEl) errEl.textContent = "Name and repo path are required.";
      return;
    }

    const btn = document.getElementById("np-submit-btn");
    if (btn) btn.disabled = true;
    try {
      const project = await apiFetch(`${API}/projects/`, {
        method: "POST",
        body: JSON.stringify({
          name,
          repo_path: repo,
          worktree_root: wroot || undefined,
          agent_ids: agents,
          brain_tags: tags,
        }),
      });
      _projects.unshift(project);
      renderOverview();
      closeNewProjectModal();
      toast(`Project "${project.name}" created`);
      // Clear form
      ["np-name", "np-repo", "np-worktrees", "np-agents", "np-tags"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = "";
      });
      if (errEl) errEl.textContent = "";
    } catch (e) {
      if (errEl) errEl.textContent = `Error: ${e.message}`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Launch agent drawer                                                  */
  /* ------------------------------------------------------------------ */
  function openLaunchDrawer(projectId, agentId = "", prompt = "") {
    const modal = document.getElementById("launch-agent-modal");
    if (!modal) return;

    const project = _projects.find((p) => p.project_id === projectId);
    if (!project) return;

    // Populate agent select
    const sel = document.getElementById("la-agent");
    if (sel) {
      const agents = project.agent_ids?.length ? project.agent_ids : ["claude_code"];
      sel.innerHTML = agents.map((a) => `<option value="${a}" ${a === agentId ? "selected" : ""}>${a}</option>`).join("");
    }

    // Pre-fill prompt if provided
    const promptEl = document.getElementById("la-prompt");
    if (promptEl) promptEl.value = prompt;

    // Suggest branch name from first words of prompt
    const branchEl = document.getElementById("la-branch");
    if (branchEl && !branchEl.value && prompt) {
      const words = slugify(prompt.split(" ").slice(0, 4).join("-"));
      branchEl.value = `feat-${words.slice(0, 30)}`;
    }

    // Store project id on submit button
    const submitBtn = document.getElementById("la-submit-btn");
    if (submitBtn) submitBtn.dataset.projectId = projectId;

    const errEl = document.getElementById("la-error");
    if (errEl) errEl.textContent = "";

    // Load bootstrap preview
    const preview = document.getElementById("la-bootstrap-preview");
    if (preview) {
      preview.textContent = "Loading…";
      apiFetch(`${API}/projects/${projectId}/bootstrap?task=${encodeURIComponent(prompt || "")}`)
        .then((d) => { preview.textContent = JSON.stringify(d, null, 2); })
        .catch(() => { preview.textContent = "Could not load bootstrap context."; });
    }

    modal.style.display = "flex";
    branchEl?.focus();
  }

  function closeLaunchDrawer() {
    const modal = document.getElementById("launch-agent-modal");
    if (modal) modal.style.display = "none";
    const branchEl = document.getElementById("la-branch");
    if (branchEl) branchEl.value = "";
  }

  async function submitLaunchAgent() {
    const submitBtn = document.getElementById("la-submit-btn");
    const projectId = submitBtn?.dataset?.projectId;
    const agent = document.getElementById("la-agent")?.value;
    const branch = document.getElementById("la-branch")?.value?.trim();
    const prompt = document.getElementById("la-prompt")?.value?.trim();
    const errEl = document.getElementById("la-error");

    if (!branch) {
      if (errEl) errEl.textContent = "Branch name is required.";
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    try {
      await apiFetch(`${API}/projects/${projectId}/worktrees`, {
        method: "POST",
        body: JSON.stringify({ branch, agent_id: agent, prompt }),
      });
      closeLaunchDrawer();
      toast(`Worktree "${branch}" created`);
      if (_currentProject) loadWorktrees(_currentProject);
    } catch (e) {
      if (errEl) errEl.textContent = `Error: ${e.message}`;
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Worktree actions                                                     */
  /* ------------------------------------------------------------------ */
  async function setWtStatus(projectId, worktreeId, status) {
    try {
      await apiFetch(`${API}/projects/${projectId}/worktrees/${worktreeId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      if (_currentProject) loadWorktrees(_currentProject);
      toast(`Status → ${status}`);
    } catch (e) {
      toast(`Failed: ${e.message}`, "warn");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Brain search                                                         */
  /* ------------------------------------------------------------------ */
  async function runBrainSearch() {
    const query = document.getElementById("brain-search-input")?.value?.trim();
    const el = document.getElementById("brain-search-results");
    if (!el || !query) return;
    el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Searching…</span>`;
    try {
      const project = _currentProject;
      const url = project
        ? `${API}/projects/${project.project_id}/recall?query=${encodeURIComponent(query)}&limit=5`
        : `${API}/memories/recall?q=${encodeURIComponent(query)}&limit=5`;
      const data = await apiFetch(url);
      const items = data.memories || data.results || [];
      if (!items.length) {
        el.innerHTML = `<span class="muted" style="font-size:0.78rem;">No results.</span>`;
        return;
      }
      el.innerHTML = items
        .map(
          (m) => `
        <div class="brain-result-item">
          <div class="brain-result-title">${m.title || m.kind || "Memory"}</div>
          <div class="brain-result-summary">${(m.summary || "").slice(0, 140)}</div>
        </div>`
        )
        .join("");
    } catch {
      el.innerHTML = `<span class="muted" style="font-size:0.78rem;">Search failed.</span>`;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Load projects                                                        */
  /* ------------------------------------------------------------------ */
  async function loadProjects() {
    try {
      _projects = await apiFetch(`${API}/projects/`);
      renderOverview();
    } catch {
      _projects = [];
      renderOverview();
    }
  }

  /* ------------------------------------------------------------------ */
  /* Section lifecycle                                                    */
  /* ------------------------------------------------------------------ */
  function onSectionActivate() {
    loadProjects();
    showOverview();
  }

  function onSectionDeactivate() {
    clearInterval(_refreshTimer);
  }

  /* ------------------------------------------------------------------ */
  /* Wire up app.js navigation hook                                       */
  /* ------------------------------------------------------------------ */
  function patchAppNav() {
    // Wait for app.js to define navigateTo, then monkey-patch
    const origNav = window.navigateTo;
    if (typeof origNav === "function") {
      window.navigateTo = function (section) {
        if (section === "projects") onSectionActivate();
        else onSectionDeactivate();
        return origNav.apply(this, arguments);
      };
    }

    // Also update titles map if needed
    const topTitle = document.getElementById("topbar-page-title");
    const origSection = document.querySelector('.nav-item[data-section="projects"]');
    if (origSection && topTitle) {
      origSection.addEventListener("click", () => {
        topTitle.textContent = "Projects";
      });
    }
  }

  /* ------------------------------------------------------------------ */
  /* Event listeners                                                      */
  /* ------------------------------------------------------------------ */
  function bindEvents() {
    // New project
    document.getElementById("new-project-btn")?.addEventListener("click", openNewProjectModal);
    document.querySelector("[data-action='new-project']")?.addEventListener("click", openNewProjectModal);
    document.getElementById("np-submit-btn")?.addEventListener("click", submitNewProject);
    document.getElementById("np-cancel-btn")?.addEventListener("click", closeNewProjectModal);
    document.getElementById("new-project-modal")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeNewProjectModal();
    });

    // Launch agent
    document.getElementById("launch-agent-btn")?.addEventListener("click", () => {
      if (_currentProject) openLaunchDrawer(_currentProject.project_id);
    });
    document.getElementById("la-submit-btn")?.addEventListener("click", submitLaunchAgent);
    document.getElementById("la-cancel-btn")?.addEventListener("click", closeLaunchDrawer);
    document.getElementById("launch-agent-modal")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeLaunchDrawer();
    });

    // Back
    document.getElementById("projects-back-btn")?.addEventListener("click", () => {
      showOverview();
      clearInterval(_refreshTimer);
    });

    // Brain search
    document.getElementById("brain-search-btn")?.addEventListener("click", runBrainSearch);
    document.getElementById("brain-search-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runBrainSearch();
    });

    // Bootstrap
    document.getElementById("bootstrap-btn")?.addEventListener("click", () => {
        if (_currentProject) loadBootstrap(_currentProject);
    });

    // Prompt auto-suggest branch name
    document.getElementById("la-prompt")?.addEventListener("input", () => {
      const branchEl = document.getElementById("la-branch");
      const prompt = document.getElementById("la-prompt")?.value || "";
      if (branchEl && !branchEl.dataset.manuallySet) {
        const words = slugify(prompt.split(" ").slice(0, 4).join("-"));
        branchEl.value = words ? `feat-${words.slice(0, 30)}` : "";
      }
    });
    document.getElementById("la-branch")?.addEventListener("input", (e) => {
      e.target.dataset.manuallySet = "1";
    });

    // Modal keyboard close
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeNewProjectModal();
        closeLaunchDrawer();
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* Public API (for inline onclick handlers)                             */
  /* ------------------------------------------------------------------ */
  window._wardenProjects = {
    launchFor: (projectId, agentId) => openLaunchDrawer(projectId, agentId),
    setWtStatus,
    openProject,
  };

  /* ------------------------------------------------------------------ */
  /* Init                                                                 */
  /* ------------------------------------------------------------------ */
  function init() {
    bindEvents();
    patchAppNav();

    // If projects section is already active on load
    if (document.querySelector('.workspace-section[data-section="projects"].active')) {
      onSectionActivate();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
