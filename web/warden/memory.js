/* Warden Memory — PiecesOS-style knowledge hub */
(function () {
  "use strict";

  const MCH = "/api/mcharness";

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  let _allMemories = [];
  let _filteredMemories = [];
  let _activeKind = "";
  let _activeProject = "";
  let _activeMemoryId = null;
  let _searchQuery = "";
  let _sortBy = "recent";

  /* Chat state */
  let _chatHistory = [];
  let _chatBusy = false;

  /* ------------------------------------------------------------------ */
  /* Utilities                                                            */
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

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const t = await res.text().catch(() => res.statusText);
      throw new Error(t);
    }
    return res.json();
  }

  function toast(msg, type = "good") {
    const host = document.getElementById("warden-toast-host");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `warden-toast warden-toast-${type}`;
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  const KIND_LABEL = {
    decision: "Decision", proof: "Proof", failure: "Failure",
    handoff: "Handoff", constraint: "Constraint", user_note: "Note",
    agent_prompt: "Prompt", claim: "Claim", test_result: "Test",
  };

  function kindChip(kind) {
    const label = KIND_LABEL[kind] || kind;
    return `<span class="mem-kind-chip mem-kind-${kind}">${label}</span>`;
  }

  /* ------------------------------------------------------------------ */
  /* Load health + stats                                                  */
  /* ------------------------------------------------------------------ */
  async function loadStats() {
    try {
      const h = await api(`${MCH}/memory/health`);
      document.getElementById("mem-stat-total").textContent = h.memory_count ?? "—";
      document.getElementById("mem-stat-vectors").textContent = h.vector_count ?? "—";
      const kinds = h.kinds || {};
      document.getElementById("mem-stat-decisions").textContent = kinds.decision ?? 0;
      document.getElementById("mem-stat-proofs").textContent = kinds.proof ?? 0;
      document.getElementById("mem-stat-failures").textContent = kinds.failure ?? 0;
      document.getElementById("mem-stat-handoffs").textContent = kinds.handoff ?? 0;
    } catch {
      document.getElementById("mem-stat-total").textContent = "—";
    }
  }

  /* ------------------------------------------------------------------ */
  /* Personal profile (PiecesOS identity card)                           */
  /* ------------------------------------------------------------------ */
  async function loadIdentity() {
    // Call the warden_me-equivalent via MCP recall on personal_memory
    // We expose it via the warden_me tool data stored in personal_profile.json
    // For now read it from the workstream endpoint which has profile data
    try {
      const data = await api(`${MCH}/projects/`);
      // Check for a profile memory without assuming the repository author's identity.
      const profileData = await api(`${MCH}/memories/recall?q=operator+profile&limit=1`).catch(() => null);

      // Default profile (from the seed we know exists)
      const profile = {
        name: "Warden operator",
        bio: "Personalize this profile so agents receive your context.",
        projects: data.map(p => p.name).filter(Boolean),
      };

      // Enrich from workbench if we got a profile memory
      if (profileData?.memories?.length) {
        const m = profileData.memories[0];
        // use as bio hint
      }

      document.getElementById("mem-identity-name").textContent = profile.name;
      document.getElementById("mem-identity-bio").textContent = profile.bio;

      const projsEl = document.getElementById("mem-identity-projects");
      if (projsEl) {
        const tags = profile.projects.length
          ? profile.projects
          : ["Add your first project"];
        projsEl.innerHTML = tags.slice(0, 6)
          .map(t => `<span class="mem-identity-project-tag">${t}</span>`)
          .join("");
      }
    } catch {
      document.getElementById("mem-identity-name").textContent = "Warden operator";
    }
  }

  /* ------------------------------------------------------------------ */
  /* Load memories                                                        */
  /* ------------------------------------------------------------------ */
  async function loadMemories() {
    try {
      const data = await api(`${MCH}/memories?limit=200`);
      _allMemories = data.memories || [];
      populateProjectFilter();
      applyFilters();
    } catch (e) {
      document.getElementById("mem-list").innerHTML =
        `<div class="mem-empty">Could not load memories: ${e.message}</div>`;
    }
  }

  function populateProjectFilter() {
    const sel = document.getElementById("mem-project-filter");
    if (!sel) return;
    const projects = new Set();
    _allMemories.forEach(m => {
      const p = m.project_id || m.scope;
      if (p) projects.add(p);
    });
    const cur = sel.value;
    sel.innerHTML = `<option value="">All projects</option>` +
      Array.from(projects).sort().map(p => `<option value="${p}">${p}</option>`).join("");
    sel.value = cur;
  }

  function applyFilters() {
    let list = [..._allMemories];

    // Kind filter
    if (_activeKind) list = list.filter(m => m.kind === _activeKind);

    // Project filter
    if (_activeProject) list = list.filter(m =>
      (m.project_id || m.scope || "").toLowerCase() === _activeProject.toLowerCase()
    );

    // Search filter
    if (_searchQuery) {
      const q = _searchQuery.toLowerCase();
      list = list.filter(m =>
        (m.title || "").toLowerCase().includes(q) ||
        (m.summary || "").toLowerCase().includes(q) ||
        (m.tags || []).some(t => t.toLowerCase().includes(q))
      );
    }

    // Sort
    if (_sortBy === "kind") list.sort((a, b) => (a.kind || "").localeCompare(b.kind || ""));
    else if (_sortBy === "project") list.sort((a, b) => ((a.project_id || a.scope) || "").localeCompare((b.project_id || b.scope) || ""));
    else list.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));

    _filteredMemories = list;
    renderList();
    renderWorkstream();
  }

  /* ------------------------------------------------------------------ */
  /* Render list                                                          */
  /* ------------------------------------------------------------------ */
  function renderList() {
    const el = document.getElementById("mem-list");
    const countEl = document.getElementById("mem-list-count");
    if (!el) return;

    if (countEl) countEl.textContent = `${_filteredMemories.length} ${_filteredMemories.length === 1 ? "memory" : "memories"}`;

    if (!_filteredMemories.length) {
      el.innerHTML = `<div class="mem-empty">${_searchQuery || _activeKind || _activeProject ? "No results for this filter." : "No memories yet. Save your first one above."}</div>`;
      return;
    }

    el.innerHTML = _filteredMemories
      .map(m => {
        const project = m.project_id || m.scope || "";
        const summary = (m.summary || m.content || "").slice(0, 120);
        return `
        <div class="mem-card${_activeMemoryId === m.memory_id ? " active" : ""}"
          data-id="${m.memory_id}" tabindex="0" role="button">
          <div class="mem-card-top">
            <h4 class="mem-card-title">${m.title || summary.slice(0, 60) || m.memory_id}</h4>
            ${kindChip(m.kind)}
          </div>
          <p class="mem-card-summary">${summary || "<em class='muted'>No content</em>"}</p>
          <div class="mem-card-footer">
            ${project ? `<span class="memory-chip" style="font-size:0.65rem;">${project}</span>` : ""}
            ${(m.tags || []).slice(0, 2).map(t => `<span class="memory-chip" style="font-size:0.65rem;">${t}</span>`).join("")}
            <span class="mem-card-time">${relTime(m.updated_at)}</span>
          </div>
        </div>`;
      })
      .join("");

    el.querySelectorAll(".mem-card").forEach(card => {
      card.addEventListener("click", () => selectMemory(card.dataset.id));
      card.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") selectMemory(card.dataset.id);
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Workstream (recent cross-project activity)                           */
  /* ------------------------------------------------------------------ */
  function renderWorkstream() {
    const el = document.getElementById("mem-workstream-list");
    if (!el) return;
    const recent = [..._allMemories]
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
      .slice(0, 5);
    if (!recent.length) {
      el.innerHTML = `<span class="muted" style="font-size:0.78rem;">No recent activity.</span>`;
      return;
    }
    el.innerHTML = recent.map(m => `
      <div class="mem-workstream-item">
        <strong>${m.title || (m.summary || "").slice(0, 40) || m.memory_id}</strong>
        <span>${KIND_LABEL[m.kind] || m.kind} · ${relTime(m.updated_at)}</span>
      </div>`).join("");
  }

  /* ------------------------------------------------------------------ */
  /* Detail panel                                                         */
  /* ------------------------------------------------------------------ */
  function selectMemory(id) {
    _activeMemoryId = id;
    const m = _allMemories.find(x => x.memory_id === id);
    if (!m) return;

    // Update active card
    document.querySelectorAll(".mem-card").forEach(c => {
      c.classList.toggle("active", c.dataset.id === id);
    });

    const detail = document.getElementById("mem-detail");
    if (!detail) return;
    detail.style.display = "";

    document.getElementById("mem-detail-kind-chip").outerHTML; // no-op; just reference
    const kindEl = document.getElementById("mem-detail-kind-chip");
    if (kindEl) {
      kindEl.className = `mem-kind-chip mem-kind-${m.kind}`;
      kindEl.textContent = KIND_LABEL[m.kind] || m.kind;
    }

    document.getElementById("mem-detail-title").textContent = m.title || m.memory_id;

    const project = m.project_id || m.scope || "";
    const agent = m.agent_id || "";
    document.getElementById("mem-detail-meta").innerHTML = [
      project && `<span>Project: <strong>${project}</strong></span>`,
      agent && `<span>Agent: <strong>${agent}</strong></span>`,
      `<span>Created: ${new Date(m.created_at).toLocaleString()}</span>`,
      `<span>Updated: ${relTime(m.updated_at)}</span>`,
    ].filter(Boolean).join(" &nbsp;·&nbsp; ");

    document.getElementById("mem-detail-body").textContent = m.summary || m.content || "(no content)";

    const tagsEl = document.getElementById("mem-detail-tags");
    tagsEl.innerHTML = (m.tags || []).map(t => `<span class="memory-chip">${t}</span>`).join("");

    const forgetBtn = document.getElementById("mem-forget-btn");
    if (forgetBtn) forgetBtn.dataset.id = id;
  }

  function closeDetail() {
    _activeMemoryId = null;
    document.getElementById("mem-detail").style.display = "none";
    document.querySelectorAll(".mem-card").forEach(c => c.classList.remove("active"));
  }

  /* ------------------------------------------------------------------ */
  /* Search (server-side)                                                 */
  /* ------------------------------------------------------------------ */
  async function runSearch(query) {
    _searchQuery = query;
    if (!query) {
      applyFilters();
      return;
    }
    try {
      const data = await api(`${MCH}/memories/recall?q=${encodeURIComponent(query)}&limit=40${_activeProject ? `&scope=${encodeURIComponent(_activeProject)}` : ""}`);
      _filteredMemories = data.memories || [];
      document.getElementById("mem-list-count").textContent = `${_filteredMemories.length} results`;
      renderList();
    } catch {
      applyFilters(); // fall back to client-side
    }
  }

  /* ------------------------------------------------------------------ */
  /* New memory modal                                                     */
  /* ------------------------------------------------------------------ */
  function openNewModal() {
    const modal = document.getElementById("mem-new-modal");
    if (modal) { modal.style.display = "flex"; document.getElementById("mem-new-title")?.focus(); }
  }

  function closeNewModal() {
    const modal = document.getElementById("mem-new-modal");
    if (modal) modal.style.display = "none";
  }

  async function submitNewMemory() {
    const title = document.getElementById("mem-new-title")?.value?.trim();
    const kind = document.getElementById("mem-new-kind")?.value || "user_note";
    const project = document.getElementById("mem-new-project")?.value?.trim();
    const tags = (document.getElementById("mem-new-tags")?.value || "").split(",").map(t => t.trim()).filter(Boolean);
    const content = document.getElementById("mem-new-content")?.value?.trim();
    const errEl = document.getElementById("mem-new-error");

    if (!content) {
      if (errEl) errEl.textContent = "Content is required.";
      return;
    }

    const btn = document.getElementById("mem-new-submit");
    if (btn) btn.disabled = true;
    try {
      const data = await api(`${MCH}/memory/remember`, {
        method: "POST",
        body: JSON.stringify({ title, kind, project_id: project, tags, content, summary: content }),
      });
      if (data.ok) {
        closeNewModal();
        toast("Memory saved");
        // Clear form
        ["mem-new-title","mem-new-project","mem-new-tags","mem-new-content"].forEach(id => {
          const el = document.getElementById(id); if (el) el.value = "";
        });
        if (errEl) errEl.textContent = "";
        await refresh();
      } else {
        if (errEl) errEl.textContent = data.error || "Save failed.";
      }
    } catch (e) {
      if (errEl) errEl.textContent = `Error: ${e.message}`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Forget (soft delete)                                                 */
  /* ------------------------------------------------------------------ */
  async function forgetMemory(id) {
    if (!confirm("Mark this memory as forgotten? It will be excluded from recall.")) return;
    try {
      // Use the update endpoint to set status=forgotten
      await api(`${MCH}/memories/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "forgotten" }),
      });
      toast("Memory forgotten");
      closeDetail();
      await refresh();
    } catch (e) {
      toast(`Could not forget: ${e.message}`, "warn");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Memory Agent Chat                                                    */
  /* ------------------------------------------------------------------ */
  const SOURCE_META = {
    git:      { label: "Git", icon: "⎇" },
    shell:    { label: "Shell", icon: "❯" },
    chrome:   { label: "Browser", icon: "○" },
    board:    { label: "Board", icon: "▤" },
    memories: { label: "Memories", icon: "⧉" },
  };

  function renderChatThread() {
    const thread = document.getElementById("mem-chat-thread");
    const welcome = document.getElementById("mem-chat-welcome");
    if (!thread) return;

    if (!_chatHistory.length) {
      thread.style.display = "none";
      if (welcome) welcome.style.display = "";
      return;
    }

    if (welcome) welcome.style.display = "none";
    thread.style.display = "";

    thread.innerHTML = _chatHistory.map((msg, i) => {
      if (msg.role === "user") {
        return `<div class="mem-msg mem-msg-user" data-idx="${i}">
          <div class="mem-msg-bubble mem-msg-bubble-user">${escapeHtml(msg.content)}</div>
        </div>`;
      }
      // assistant
      const sources = msg.sources || [];
      const snap = msg.snapshot || {};
      const offlineChip = msg.fallback ? `<span class="mem-source-chip mem-source-fallback" title="Ollama not available — raw context shown">⚠ offline</span>` : "";
      const modelLabel = msg.model && !msg.fallback ? `<span class="mem-chat-msg-model">${msg.model}</span>` : "";
      const sourceChips = sources.map(s => {
        const m = SOURCE_META[s] || { label: s, icon: "·" };
        const detail = snap[s] ? ` (${Array.isArray(snap[s]) ? snap[s].length : snap[s]})` : "";
        return `<span class="mem-source-chip mem-source-${s}" title="${m.label}${detail}">${m.icon} ${m.label}${detail}</span>`;
      }).join("");
      const sourceBar = (sources.length || msg.fallback)
        ? `<div class="mem-msg-sources">${sourceChips}${offlineChip}${modelLabel}</div>`
        : "";

      // When Ollama is offline the reply IS the raw snapshot — collapse it
      const isRawSnapshot = msg.fallback && msg.content.includes("Warden Memory Snapshot");
      let bubbleContent;
      if (isRawSnapshot) {
        bubbleContent = `<p class="mem-msg-offline-note">Memory agent is offline. Raw context collected:</p>
          <details class="mem-raw-context">
            <summary>View raw context</summary>
            <pre class="mem-raw-context-body">${escapeHtml(msg.content)}</pre>
          </details>`;
      } else {
        // Normal conversational reply — append collapsible raw context if snapshot exists
        const hasSnap = Object.keys(snap).length > 0;
        const rawContextToggle = hasSnap ? `
          <details class="mem-raw-context">
            <summary>View raw context</summary>
            <pre class="mem-raw-context-body">${escapeHtml(buildSnapshotText(snap))}</pre>
          </details>` : "";
        bubbleContent = `<div class="mem-reply-text">${formatReply(msg.content)}</div>${rawContextToggle}`;
      }

      return `<div class="mem-msg mem-msg-agent" data-idx="${i}">
        <div class="mem-msg-avatar">⧉</div>
        <div class="mem-msg-body">
          <div class="mem-msg-bubble mem-msg-bubble-agent">${bubbleContent}</div>
          ${sourceBar}
        </div>
      </div>`;
    }).join("");

    // Scroll to bottom
    thread.scrollTop = thread.scrollHeight;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatReply(text) {
    // Light markdown: bold, code spans, line breaks
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  }

  function buildSnapshotText(snap) {
    const lines = [];
    if (snap.branch)   lines.push(`branch: ${snap.branch}`);
    if (snap.git)      lines.push(`commits: ${snap.git}`);
    if (snap.shell)    lines.push(`shell commands: ${snap.shell}`);
    if (snap.chrome)   lines.push(`browser visits: ${snap.chrome}`);
    if (snap.board)    lines.push(`board tasks: ${snap.board}`);
    if (snap.memories) lines.push(`stored memories: ${snap.memories}`);
    return lines.join("\n") || "(no context captured)";
  }

  function setChatStatus(msg, isError = false) {
    const el = document.getElementById("mem-chat-status");
    if (!el) return;
    if (!msg) { el.style.display = "none"; el.textContent = ""; return; }
    el.style.display = "";
    el.textContent = msg;
    el.className = "mem-chat-status" + (isError ? " mem-chat-status-error" : "");
  }

  async function sendMemoryAgentMessage(text) {
    const msg = (text || "").trim();
    if (!msg || _chatBusy) return;
    _chatBusy = true;

    _chatHistory.push({ role: "user", content: msg });
    renderChatThread();
    setChatStatus("Memory agent thinking…");

    const sendBtn = document.getElementById("mem-chat-send-btn");
    const input = document.getElementById("mem-chat-input");
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.value = ""; input.style.height = ""; }

    try {
      // Build history for API (exclude source/snapshot metadata)
      const apiHistory = _chatHistory
        .filter(m => m.role === "user" || m.role === "assistant")
        .slice(-10)
        .map(m => ({ role: m.role, content: m.content }));

      const data = await api(`${MCH}/warden/memory-agent/chat`, {
        method: "POST",
        body: JSON.stringify({ message: msg, history: apiHistory.slice(0, -1) }),
      });

      // Build snapshot summary for source chips (cs keys match memory_agent.py ChatResponse)
      const snap = {};
      const cs = data.context_snapshot || {};
      if (cs.commits)        snap.git      = cs.commits;
      if (cs.shell_commands) snap.shell    = cs.shell_commands;
      if (cs.browser_visits) snap.chrome   = cs.browser_visits;
      if (cs.board_tasks)    snap.board    = cs.board_tasks;
      if (cs.memories)       snap.memories = cs.memories;
      if (cs.branch)         snap.branch   = cs.branch;

      _chatHistory.push({
        role: "assistant",
        content: data.reply || "(no reply)",
        sources: data.sources || [],
        model: data.model_used || "",
        snapshot: snap,
        fallback: data.fallback || false,
        trace: data.trace || null,
      });

      // Render trace inspector if trace present
      if (data.trace) renderMemoryTrace(data.trace);

      // Update model label
      const modelLabelEl = document.getElementById("mem-chat-model-label");
      if (modelLabelEl && data.model_used) modelLabelEl.textContent = `local · ${data.model_used}`;

      setChatStatus(null);
    } catch (e) {
      _chatHistory.push({
        role: "assistant",
        content: `Error: ${e.message}`,
        sources: [],
        fallback: true,
      });
      setChatStatus(`Request failed: ${e.message}`, true);
      setTimeout(() => setChatStatus(null), 4000);
    } finally {
      _chatBusy = false;
      if (sendBtn) sendBtn.disabled = false;
      renderChatThread();
    }
  }

  /* ── Trace Inspector ── */
  const MEM_TRACE_ICONS = {
    context_read: "◎", memory_read: "⧉", memory_write: "✦",
    tool_action: "⬡", proof: "✓", blocked: "⊗", note: "·",
  };

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderMemoryTrace(trace) {
    const pane = document.getElementById("mem-trace-inspector-pane");
    const list = document.getElementById("mem-trace-inspector-list");
    if (!pane || !list) return;

    if (!trace || !trace.steps || !trace.steps.length) {
      list.innerHTML = '<div class="mem-trace-empty">No trace steps.</div>';
      return;
    }

    // Filter: only show user-visible steps (hide debug by default)
    const userSteps = trace.steps.filter((s) => !s.visibility || s.visibility === "user");

    list.innerHTML = [
      `<div class="mem-trace-agent-label">${escHtml(trace.agent || "Memory Agent")} · ${escHtml(trace.trace_id || "")}</div>`,
      ...userSteps.map((s) => {
        const icon = MEM_TRACE_ICONS[s.type] || "·";
        const cls = s.status === "blocked" ? "wa-trace-blocked"
                  : s.status === "skipped" ? "wa-trace-skipped"
                  : s.status === "error"   ? "wa-trace-error" : "";
        return `<div class="wa-trace-item ${cls}">
          <div class="wa-trace-tool-name">${icon} ${escHtml(s.label)}</div>
          ${s.detail ? `<div class="wa-trace-preview">${escHtml(s.detail.slice(0, 120))}</div>` : ""}
          ${s.ref ? `<div class="wa-trace-ref">${escHtml(s.ref)}</div>` : ""}
        </div>`;
      }),
    ].join("");

    pane.style.display = "";
  }

  async function loadChatContext() {
    const panel = document.getElementById("mem-chat-context-panel");
    const body = document.getElementById("mem-chat-context-body");
    if (!panel || !body) return;
    panel.style.display = "";
    body.textContent = "Loading…";
    try {
      const data = await api(`${MCH}/warden/memory-agent/context`);
      body.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
      body.textContent = `Error: ${e.message}`;
    }
  }

  function clearChat() {
    _chatHistory = [];
    renderChatThread();
    const welcome = document.getElementById("mem-chat-welcome");
    if (welcome) welcome.style.display = "";
    const thread = document.getElementById("mem-chat-thread");
    if (thread) thread.style.display = "none";
    setChatStatus(null);
  }

  /* ------------------------------------------------------------------ */
  /* Context pack                                                         */
  /* ------------------------------------------------------------------ */
  async function buildContextPack() {
    const prompt = document.getElementById("mem-context-prompt")?.value?.trim() || "";
    const agent = document.getElementById("mem-context-agent")?.value || "codex_cli";
    const project = _activeProject || "";
    const statusEl = document.getElementById("mem-context-status");
    const previewEl = document.getElementById("mem-context-preview");

    if (statusEl) statusEl.textContent = "Building…";
    if (previewEl) previewEl.style.display = "none";

    try {
      const data = await api(`${MCH}/memory/context-pack`, {
        method: "POST",
        body: JSON.stringify({ prompt, agent, project_id: project || undefined }),
      });
      if (previewEl) {
        previewEl.textContent = JSON.stringify(data, null, 2);
        previewEl.style.display = "";
      }
      if (statusEl) statusEl.textContent = "";
    } catch (e) {
      if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.style.color = "var(--bad)"; }
    }
  }

  /* ------------------------------------------------------------------ */
  /* Full refresh                                                         */
  /* ------------------------------------------------------------------ */
  async function refresh() {
    await Promise.all([loadStats(), loadMemories(), loadIdentity()]);
  }

  /* ------------------------------------------------------------------ */
  /* Bind events                                                          */
  /* ------------------------------------------------------------------ */
  function bindEvents() {
    // Refresh
    document.getElementById("mem-refresh-btn")?.addEventListener("click", refresh);
    // Legacy compat
    document.getElementById("memory-refresh")?.addEventListener("click", refresh);

    // New modal
    document.getElementById("mem-new-btn")?.addEventListener("click", openNewModal);
    document.getElementById("mem-new-submit")?.addEventListener("click", submitNewMemory);
    document.getElementById("mem-new-cancel")?.addEventListener("click", closeNewModal);
    document.getElementById("mem-new-modal")?.addEventListener("click", e => {
      if (e.target === e.currentTarget) closeNewModal();
    });

    // Kind filters
    document.getElementById("mem-filter-chips")?.addEventListener("click", e => {
      const chip = e.target.closest(".mem-filter-chip");
      if (!chip) return;
      document.querySelectorAll(".mem-filter-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      _activeKind = chip.dataset.kind || "";
      _searchQuery = "";
      document.getElementById("mem-search-input").value = "";
      applyFilters();
    });

    // Project filter
    document.getElementById("mem-project-filter")?.addEventListener("change", e => {
      _activeProject = e.target.value;
      applyFilters();
    });

    // Sort
    document.getElementById("mem-sort-select")?.addEventListener("change", e => {
      _sortBy = e.target.value;
      applyFilters();
    });

    // Search
    const searchInput = document.getElementById("mem-search-input");
    const searchBtn = document.getElementById("mem-search-btn");

    let debounceTimer;
    searchInput?.addEventListener("input", e => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => runSearch(e.target.value.trim()), 280);
    });
    searchInput?.addEventListener("keydown", e => {
      if (e.key === "Enter") runSearch(searchInput.value.trim());
    });
    searchBtn?.addEventListener("click", () => runSearch(searchInput?.value?.trim() || ""));

    // Close detail
    document.getElementById("mem-detail-close")?.addEventListener("click", closeDetail);

    // Forget
    document.getElementById("mem-forget-btn")?.addEventListener("click", e => {
      const id = e.target.dataset.id;
      if (id) forgetMemory(id);
    });

    // Context pack
    document.getElementById("mem-context-build-btn")?.addEventListener("click", buildContextPack);

    // Edit identity (placeholder — opens new memory as profile update)
    document.getElementById("mem-edit-identity-btn")?.addEventListener("click", () => {
      document.getElementById("mem-new-kind").value = "user_note";
      document.getElementById("mem-new-project").value = "personal";
      document.getElementById("mem-new-title").value = "Profile update";
      openNewModal();
    });

    // ── Chat ──
    const chatInput = document.getElementById("mem-chat-input");
    const chatSendBtn = document.getElementById("mem-chat-send-btn");

    chatSendBtn?.addEventListener("click", () => sendMemoryAgentMessage(chatInput?.value));

    chatInput?.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMemoryAgentMessage(chatInput.value);
      }
    });

    // Auto-resize textarea
    chatInput?.addEventListener("input", () => {
      chatInput.style.height = "auto";
      chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
    });

    // Starter prompts
    document.querySelectorAll(".mem-starter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        sendMemoryAgentMessage(btn.dataset.msg || btn.textContent);
      });
    });

    // Clear chat
    document.getElementById("mem-chat-clear-btn")?.addEventListener("click", clearChat);

    // Trace inspector toggle
    document.getElementById("mem-trace-toggle")?.addEventListener("click", () => {
      const pane = document.getElementById("mem-trace-inspector-pane");
      const btn = document.getElementById("mem-trace-toggle");
      if (!pane) return;
      const hidden = pane.classList.toggle("mem-trace-hidden");
      if (btn) btn.textContent = hidden ? "▶" : "◀";
    });

    // Context snapshot panel
    document.getElementById("mem-chat-context-btn")?.addEventListener("click", () => {
      const panel = document.getElementById("mem-chat-context-panel");
      if (!panel) return;
      if (panel.style.display === "none" || !panel.style.display) {
        loadChatContext();
      } else {
        panel.style.display = "none";
      }
    });
    document.getElementById("mem-chat-context-close")?.addEventListener("click", () => {
      const panel = document.getElementById("mem-chat-context-panel");
      if (panel) panel.style.display = "none";
    });

    // Keyboard
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") {
        closeNewModal();
        closeDetail();
        const panel = document.getElementById("mem-chat-context-panel");
        if (panel) panel.style.display = "none";
      }
    });

    // Legacy search form compatibility (old HTML)
    document.getElementById("memory-search-form")?.addEventListener("submit", e => {
      e.preventDefault();
      const q = document.getElementById("memory-search-query")?.value?.trim() || "";
      runSearch(q);
    });

    // Legacy remember form
    document.getElementById("memory-remember-form")?.addEventListener("submit", async e => {
      e.preventDefault();
      const title = document.getElementById("memory-note-title")?.value?.trim();
      const kind = document.getElementById("memory-note-kind")?.value || "user_note";
      const tags = (document.getElementById("memory-note-tags")?.value || "").split(",").map(t => t.trim()).filter(Boolean);
      const content = document.getElementById("memory-note-content")?.value?.trim();
      const statusEl = document.getElementById("memory-remember-status");
      if (!content) { if (statusEl) statusEl.textContent = "Content required."; return; }
      try {
        await api(`${MCH}/memory/remember`, {
          method: "POST",
          body: JSON.stringify({ title, kind, tags, content, summary: content }),
        });
        if (statusEl) { statusEl.textContent = "Saved!"; statusEl.className = "memory-form-status success"; }
        setTimeout(() => { if (statusEl) statusEl.textContent = ""; }, 2000);
        await refresh();
      } catch (err) {
        if (statusEl) { statusEl.textContent = `Error: ${err.message}`; statusEl.className = "memory-form-status error"; }
      }
    });

    // Legacy context pack build
    document.getElementById("memory-context-build")?.addEventListener("click", buildContextPack);
  }

  /* ------------------------------------------------------------------ */
  /* Section lifecycle                                                    */
  /* ------------------------------------------------------------------ */
  function onActivate() {
    refresh();
  }

  /* ------------------------------------------------------------------ */
  /* Patch app.js nav                                                     */
  /* ------------------------------------------------------------------ */
  function patchNav() {
    const origNav = window.navigateTo;
    if (typeof origNav === "function") {
      window.navigateTo = function (section) {
        if (section === "memory") onActivate();
        return origNav.apply(this, arguments);
      };
    }
  }

  /* ------------------------------------------------------------------ */
  /* Init                                                                 */
  /* ------------------------------------------------------------------ */
  function init() {
    bindEvents();
    patchNav();
    if (document.querySelector('.workspace-section[data-section="memory"].active')) {
      onActivate();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
