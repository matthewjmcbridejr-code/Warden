(function () {
  const MCH = "/api/mcharness";
  const JULES_VIEW_URL = "https://jules.google.com/session";
  const CAPTAIN_PROFILE_BASE = "/web/warden/agent_profiles";
  const CAPTAIN_PROFILE_STORAGE_KEY = "warden.captain.instructionProfile";
  const CAPTAIN_PROFILES = [
    { id: "captain-default", label: "Default Captain", file: "captain-default.md" },
    { id: "captain-code-review", label: "Code Review Captain", file: "captain-code-review.md" },
    { id: "captain-release-manager", label: "Release Manager Captain", file: "captain-release-manager.md" },
  ];
  // Minimal state for Agents page + Codex flow + Live Monitor
  const state = {
    repos: [],
    lanes: [],
    agents: [],
    agentTemplates: [],
    registryWriteEnabled: false,
    addAgent: {
      step: "choose",
      mode: "create",
      editingAgentId: "",
      templateAdapter: "",
      saving: false,
      testing: false,
      lastTestStatus: "",
      error: "",
    },
    health: {},
    selectedThreadId: "",
    selectedQueueItemId: "",
    promptSubmittedAt: 0,
    liveMonitorExpanded: false,
    liveAutoScroll: true,
    lastMonitorTranscriptText: "",
    activeSection: "mission",
    recentRuns: [],
    recentEvidence: [],
    activeWardenRunId: "",
    activeCaptainPlan: null,
    missionWorklog: [],
    missionTimelineFilter: "all",
    captainDeck: {
      configured: false,
      planningEnabled: false,
      privateKeySetupEnabled: false,
      keySource: "missing",
      model: "openrouter/auto",
      notes: [],
      repoId: "",
      repoPath: "",
      laneId: "codex_cli",
      goal: "",
      plan: null,
      loading: false,
      error: "",
      keyFormVisible: false,
      keySaving: false,
      keyError: "",
      keyModel: "openrouter/auto",
    },
    captainProfile: {
      selectedId: localStorage.getItem(CAPTAIN_PROFILE_STORAGE_KEY) || "captain-default",
      cache: {},
      loading: false,
      error: "",
    },
    memory: {
      available: false,
      privateOnly: true,
      loading: false,
      memories: [],
      searchResults: [],
      lastContext: null,
      error: "",
    },
  };

  // Helper for API calls (minimal)
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

  function setQuickReplyStatus(message, isError = false) {
    const el = document.getElementById("quick-reply-status");
    if (!el) return;
    el.textContent = message || "";
    el.style.color = isError ? "var(--bad, #ff7e91)" : "var(--muted, #9cacbf)";
  }

  function scrollModalTranscriptToBottom() {
    const pre = document.getElementById("modal-transcript");
    if (!pre) return;
    state.liveScrollProgrammatic = true;
    requestAnimationFrame(() => {
      pre.scrollTop = pre.scrollHeight;
      requestAnimationFrame(() => {
        state.liveScrollProgrammatic = false;
      });
    });
  }

  function isModalTranscriptNearBottom(pre) {
    if (!pre) return true;
    return (pre.scrollHeight - pre.scrollTop - pre.clientHeight) < 80;
  }

  function updateLiveMonitorChrome() {
    const modal = document.getElementById("live-cli-modal");
    const expandBtn = document.getElementById("modal-expand");
    const scrollIndicator = document.getElementById("modal-autoscroll-indicator");
    if (modal) {
      modal.classList.toggle("monitor-expanded", !!state.liveMonitorExpanded);
    }
    if (expandBtn) {
      expandBtn.textContent = state.liveMonitorExpanded ? "Normal View" : "Bigger View";
    }
    if (scrollIndicator) {
      scrollIndicator.textContent = state.liveAutoScroll ? "" : "Scrolled up — updates paused here";
      scrollIndicator.style.display = state.liveAutoScroll ? "none" : "block";
    }
  }

  function pauseLiveAutoScroll() {
    if (!state.liveAutoScroll) return;
    state.liveAutoScroll = false;
    updateLiveMonitorChrome();
  }

  function resumeLiveAutoScroll() {
    state.liveAutoScroll = true;
    updateLiveMonitorChrome();
    scrollModalTranscriptToBottom();
  }

  function escapeHtml(v) {
    return String(v || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function redactVisibleMemory(value) {
    let text = String(value || "");
    text = text.replace(
      /-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----/gi,
      "[REDACTED PRIVATE KEY BLOCK]",
    );
    text = text.replace(/\b(Authorization\s*:\s*Bearer)\s+[^\s]+/gi, "$1 [REDACTED]");
    text = text.replace(
      /\b((?:OPENAI|ANTHROPIC|GEMINI|GOOGLE|GROQ|GITHUB|OPENROUTER)[A-Z0-9_]*(?:KEY|TOKEN|SECRET)|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|PASSWORD|PASSWD|COOKIE)\s*=\s*['"]?[^\s'"]+['"]?/gi,
      "$1=[REDACTED]",
    );
    text = text.replace(/\b(password|passwd|pwd|cookie|sessionid)\s*[:=]\s*['"]?[^\s'"]+['"]?/gi, "$1=[REDACTED]");
    return text.replace(/\b(?:sk-(?:ant-|or-)?[A-Za-z0-9._-]{6,}|gsk_[A-Za-z0-9._-]{6,}|gh[pousr]_[A-Za-z0-9_]{6,})\b/g, "[REDACTED]");
  }

  function currentMemoryProject() {
    const selectedRepo = (state.repos || []).find((repo) => {
      return repo.repo_id === state.captainDeck.repoId || repo.path === state.captainDeck.repoPath;
    });
    const projectId = state.captainDeck.repoId
      || (selectedRepo && selectedRepo.repo_id)
      || "mcharness-public-export";
    const repoPath = state.captainDeck.repoPath
      || (selectedRepo && selectedRepo.path)
      || "";
    return { projectId, repoPath };
  }

  function memoryMatchesProject(memory, project) {
    const scope = String(memory.scope || "").toLowerCase();
    const projectId = String(memory.project_id || "").toLowerCase();
    const wanted = String(project.projectId || "").toLowerCase();
    return scope === wanted
      || projectId === wanted
      || (!!project.repoPath && memory.repo_path === project.repoPath);
  }

  function memoryTimestamp(value) {
    if (!value) return "";
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(value));
    } catch (_error) {
      return "";
    }
  }

  function memoryCardHtml(memory) {
    const title = redactVisibleMemory(memory.title || memory.kind || "Memory");
    const summary = redactVisibleMemory(memory.summary || memory.content || "");
    const kind = redactVisibleMemory(memory.kind || "note");
    const tags = Array.isArray(memory.tags)
      ? memory.tags.filter((tag) => String(tag).toLowerCase() !== String(kind).toLowerCase()).slice(0, 6)
      : [];
    const chips = [kind, ...tags].filter(Boolean).map((tag, index) => {
      const kindClass = index === 0 ? ` kind-${String(kind).replace(/[^a-z0-9_-]/gi, "")}` : "";
      return `<span class="memory-chip${kindClass}">${escapeHtml(redactVisibleMemory(tag))}</span>`;
    }).join("");
    const source = redactVisibleMemory(memory.source || "");
    const sourceRef = redactVisibleMemory(memory.source_ref || "");
    const created = memoryTimestamp(memory.created_at || memory.updated_at);
    return `
      <article class="memory-card" data-memory-id="${escapeHtml(memory.memory_id || "")}">
        <div class="memory-card-top">
          <h4 class="memory-card-title">${escapeHtml(title)}</h4>
          <div class="memory-chip-row">${chips}</div>
        </div>
        <p class="memory-card-summary">${escapeHtml(summary)}</p>
        <div class="memory-card-meta">
          ${source ? `<span>${escapeHtml(source)}</span>` : ""}
          ${sourceRef ? `<span>${escapeHtml(sourceRef)}</span>` : ""}
          ${created ? `<span>${escapeHtml(created)}</span>` : ""}
        </div>
        <span class="memory-card-id">${escapeHtml(memory.memory_id || "")}</span>
      </article>
    `;
  }

  function renderMemoryList(targetId, memories, emptyCopy) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!memories.length) {
      target.innerHTML = `<div class="memory-empty">${escapeHtml(emptyCopy)}</div>`;
      return;
    }
    target.innerHTML = memories.map(memoryCardHtml).join("");
  }

  function setMemoryControlsEnabled(enabled) {
    [
      "memory-search-query",
      "memory-note-title",
      "memory-note-tags",
      "memory-note-content",
      "memory-note-kind",
      "memory-context-agent",
      "memory-context-prompt",
      "memory-context-build",
      "memory-refresh",
    ].forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.disabled = !enabled;
    });
    document.querySelectorAll("#memory-search-form button, #memory-remember-form button").forEach((button) => {
      button.disabled = !enabled;
    });
  }

  function renderMemoryStatus() {
    const memoryState = state.memory;
    const project = currentMemoryProject();
    const status = document.getElementById("memory-status-value");
    const detail = document.getElementById("memory-status-detail");
    const count = document.getElementById("memory-count-value");
    const projectValue = document.getElementById("memory-project-value");
    const updated = document.getElementById("memory-updated-value");
    const notice = document.getElementById("memory-private-notice");
    if (status) status.textContent = memoryState.loading
      ? "Checking…"
      : memoryState.available
        ? "Memory ready"
        : memoryState.error
          ? "Memory unavailable"
          : "Private runner only";
    if (detail) detail.textContent = memoryState.available ? "Private · available" : "Private runner only";
    if (count) count.textContent = memoryState.available ? String(memoryState.memories.length) : "—";
    if (projectValue) projectValue.textContent = redactVisibleMemory(project.projectId);
    const newest = memoryState.memories[0];
    if (updated) updated.textContent = newest
      ? `Updated ${memoryTimestamp(newest.updated_at || newest.created_at)}`
      : "No memories yet";
    if (notice) notice.style.display = memoryState.available ? "none" : "block";
    setMemoryControlsEnabled(memoryState.available && !memoryState.loading);
  }

  async function loadMemory() {
    const memoryState = state.memory;
    memoryState.loading = true;
    memoryState.error = "";
    renderMemoryStatus();
    try {
      const [health, listing] = await Promise.all([
        requestJson(`${MCH}/memory/health`),
        requestJson(`${MCH}/memories`),
      ]);
      memoryState.available = !!health.ok;
      memoryState.privateOnly = health.private_only !== false;
      const project = currentMemoryProject();
      memoryState.memories = (listing.memories || [])
        .filter((memory) => memoryMatchesProject(memory, project))
        .slice(0, 20);
      renderMemoryList("memory-recent-list", memoryState.memories, "No memories yet.");
    } catch (error) {
      memoryState.available = false;
      memoryState.memories = [];
      memoryState.error = error.message || "Memory unavailable.";
      renderMemoryList("memory-recent-list", [], "Memory is private-runner-only.");
      renderMemoryList("memory-search-results", [], "Memory is unavailable on this service.");
    } finally {
      memoryState.loading = false;
      renderMemoryStatus();
    }
  }

  async function searchMemory(query) {
    const status = document.getElementById("memory-search-status");
    const project = currentMemoryProject();
    const cleanQuery = String(query || "").trim().slice(0, 500);
    if (!cleanQuery) {
      state.memory.searchResults = state.memory.memories.slice();
      renderMemoryList("memory-search-results", state.memory.searchResults, "No memories yet.");
      if (status) status.textContent = "";
      return;
    }
    if (status) {
      status.className = "memory-form-status";
      status.textContent = "Searching…";
    }
    try {
      const data = await requestJson(
        `${MCH}/memories/search?q=${encodeURIComponent(cleanQuery)}&scope=${encodeURIComponent(project.projectId)}&limit=20`,
      );
      state.memory.searchResults = (data.memories || []).slice(0, 20);
      renderMemoryList("memory-search-results", state.memory.searchResults, "No matching memories.");
      if (status) status.textContent = `${state.memory.searchResults.length} result${state.memory.searchResults.length === 1 ? "" : "s"}`;
    } catch (error) {
      renderMemoryList("memory-search-results", [], "Memory search unavailable.");
      if (status) {
        status.className = "memory-form-status error";
        status.textContent = "Memory search unavailable.";
      }
    }
  }

  function parseMemoryTags(value) {
    return String(value || "")
      .split(",")
      .map((tag) => tag.trim().toLowerCase())
      .filter(Boolean)
      .filter((tag, index, tags) => tags.indexOf(tag) === index)
      .slice(0, 10);
  }

  async function rememberMemoryNote() {
    const titleInput = document.getElementById("memory-note-title");
    const kindInput = document.getElementById("memory-note-kind");
    const tagsInput = document.getElementById("memory-note-tags");
    const contentInput = document.getElementById("memory-note-content");
    const status = document.getElementById("memory-remember-status");
    const content = String(contentInput && contentInput.value || "").trim().slice(0, 5000);
    if (!content) {
      if (status) {
        status.className = "memory-form-status error";
        status.textContent = "Add a note first.";
      }
      return;
    }
    const project = currentMemoryProject();
    if (status) {
      status.className = "memory-form-status";
      status.textContent = "Remembering…";
    }
    try {
      const data = await requestJson(`${MCH}/memory/remember`, {
        method: "POST",
        body: {
          scope: project.projectId,
          project_id: project.projectId,
          repo_path: project.repoPath || null,
          title: String(titleInput && titleInput.value || "").trim().slice(0, 160) || null,
          content,
          kind: String(kindInput && kindInput.value || "user_note"),
          tags: parseMemoryTags(tagsInput && tagsInput.value),
          source: "manual",
        },
      });
      if (!data.ok) throw new Error(data.error || "Memory was not saved.");
      const returned = data.memory || {};
      if (status) {
        status.className = "memory-form-status success";
        status.textContent = `Remembered ${redactVisibleMemory(returned.title || returned.memory_id || "note")}.`;
      }
      if (titleInput) titleInput.value = "";
      if (tagsInput) tagsInput.value = "";
      if (contentInput) contentInput.value = "";
      await loadMemory();
    } catch (error) {
      if (status) {
        status.className = "memory-form-status error";
        status.textContent = "Memory could not be saved.";
      }
    }
  }

  async function buildMemoryContextPreview() {
    const agent = document.getElementById("memory-context-agent");
    const prompt = document.getElementById("memory-context-prompt");
    const preview = document.getElementById("memory-context-preview");
    const meta = document.getElementById("memory-context-meta");
    const sources = document.getElementById("memory-context-sources");
    const status = document.getElementById("memory-context-status");
    const project = currentMemoryProject();
    if (status) {
      status.className = "memory-form-status";
      status.textContent = "Building context…";
    }
    try {
      const data = await requestJson(`${MCH}/memory/context-pack`, {
        method: "POST",
        body: {
          project_id: project.projectId,
          repo_path: project.repoPath || null,
          agent: String(agent && agent.value || "codex_cli"),
          prompt: String(prompt && prompt.value || "").trim().slice(0, 5000),
          max_memories: 8,
          max_chars: 6000,
        },
      });
      state.memory.lastContext = data;
      if (preview) preview.textContent = redactVisibleMemory(data.context || "No relevant memory for this task.");
      if (meta) meta.textContent = `${data.memory_count || 0} memories${data.truncated ? " · truncated" : ""}`;
      if (sources) {
        const ids = Array.isArray(data.memory_ids) ? data.memory_ids : [];
        sources.textContent = ids.length ? `Sources: ${redactVisibleMemory(ids.join(", "))}` : "No source memories.";
      }
      if (status) status.textContent = "";
    } catch (error) {
      if (preview) preview.textContent = "Context preview unavailable.";
      if (meta) meta.textContent = "Unavailable";
      if (sources) sources.textContent = "";
      if (status) {
        status.className = "memory-form-status error";
        status.textContent = "Memory is private-runner-only.";
      }
    }
  }

  async function loadCaptainDeckStatus() {
    try {
      const status = await requestJson(`${MCH}/captain/status`);
      const deck = state.captainDeck;
      deck.configured = !!status.configured;
      deck.planningEnabled = !!status.planning_enabled;
      deck.privateKeySetupEnabled = !!status.private_key_setup_enabled;
      deck.keySource = status.key_source || "missing";
      deck.model = status.model || "openrouter/auto";
      if (!deck.keyFormVisible) {
        deck.keyModel = deck.model || "openrouter/auto";
      }
      deck.notes = Array.isArray(status.notes) ? status.notes : [];
      renderCaptainDeck();
      renderSettingsPanel();
      return status;
    } catch (e) {
      const deck = state.captainDeck;
      deck.configured = false;
      deck.planningEnabled = false;
      deck.privateKeySetupEnabled = false;
      deck.keySource = "missing";
      deck.notes = ["Captain status unavailable."];
      renderCaptainDeck();
      renderSettingsPanel();
      return null;
    }
  }

  async function populateCaptainDeckRepos() {
    const sel = document.getElementById("captain-repo-select");
    if (!sel) return;
    sel.innerHTML = '<option value="">Loading repos...</option>';
    try {
      const data = await requestJson(`${MCH}/repos`);
      const repos = data.repos || [];
      state.repos = repos;
      sel.innerHTML = "";
      const fallback = repos.length ? repos : [
        { repo_id: "hybrid-agent-os", label: "hybrid-agent-os", path: "/root/hybrid-agent-os" },
        { repo_id: "mcharness-public-export", label: "mcharness-public-export", path: "/root/mcharness-public-export" },
      ];
      fallback.forEach((repo) => {
        const opt = document.createElement("option");
        opt.value = repo.repo_id || repo.path;
        opt.dataset.repoPath = repo.path || "";
        opt.textContent = repo.label || repo.repo_id || repo.path;
        sel.appendChild(opt);
      });
      if (fallback.length) {
        const current = state.captainDeck.repoId || fallback[0].repo_id || fallback[0].path;
        sel.value = current;
        const selected = sel.selectedOptions[0];
        state.captainDeck.repoId = selected ? selected.value : current;
        state.captainDeck.repoPath = (selected && selected.dataset.repoPath) || fallback[0].path || "";
      }
    } catch (e) {
      sel.innerHTML = '<option value="/root/mcharness-public-export">mcharness-public-export (fallback)</option>';
      sel.value = "/root/mcharness-public-export";
      state.captainDeck.repoId = "mcharness-public-export";
      state.captainDeck.repoPath = "/root/mcharness-public-export";
    }
  }

  function renderCaptainDeck() {
    const deck = state.captainDeck;
    const noteEl = document.getElementById("captain-config-note");
    const settingsStatusEl = document.getElementById("captain-settings-status");
    const settingsNoteEl = document.getElementById("captain-settings-note");
    const keyFormEl = document.getElementById("captain-key-form");
    const setKeyBtn = document.getElementById("captain-set-key");
    const removeKeyBtn = document.getElementById("captain-remove-key");
    const saveKeyBtn = document.getElementById("captain-save-key");
    const cancelKeyBtn = document.getElementById("captain-cancel-key");
    const keyInput = document.getElementById("captain-openrouter-key");
    const modelInput = document.getElementById("captain-openrouter-model");
    const keyFormNoteEl = document.getElementById("captain-key-form-note");
    const statusEl = document.getElementById("captain-plan-status");
    const createBtn = document.getElementById("captain-create-plan");
    const deployBtn = document.getElementById("captain-deploy-first");
    const copyBtn = document.getElementById("captain-copy-plan");
    const planBody = document.getElementById("captain-plan-body");
    const goalEl = document.getElementById("captain-goal");
    const repoSel = document.getElementById("captain-repo-select");
    const laneSel = document.getElementById("captain-agent-select");

    if (goalEl && goalEl.value !== deck.goal) goalEl.value = deck.goal || "";
    if (repoSel && deck.repoId && repoSel.value !== deck.repoId) repoSel.value = deck.repoId;
    if (laneSel && deck.laneId && laneSel.value !== deck.laneId) laneSel.value = deck.laneId;

    if (noteEl) {
      if (deck.configured) {
        noteEl.textContent = "";
        noteEl.style.display = "none";
      } else {
        noteEl.textContent = "Not configured. Set OpenRouter key on the private service.";
        noteEl.style.display = "block";
      }
    }
    if (settingsStatusEl) {
      settingsStatusEl.textContent = `Status: ${deck.configured ? "Configured" : "Not configured"} • Key source: ${deck.keySource || "missing"} • Model: ${deck.model || "openrouter/auto"}`;
    }
    if (settingsNoteEl) {
      if (!deck.privateKeySetupEnabled && !deck.configured) {
        settingsNoteEl.textContent = "Key setup is private-service only.";
        settingsNoteEl.style.display = "block";
      } else if (deck.keySource === "env") {
        settingsNoteEl.textContent = "";
        settingsNoteEl.style.display = "none";
      } else if (!deck.configured && deck.privateKeySetupEnabled) {
        settingsNoteEl.textContent = "Set an OpenRouter key to enable planning.";
        settingsNoteEl.style.display = "block";
      } else {
        settingsNoteEl.textContent = "";
        settingsNoteEl.style.display = "none";
      }
    }
    if (keyFormEl) {
      keyFormEl.style.display = deck.keyFormVisible ? "block" : "none";
    }
    if (setKeyBtn) {
      setKeyBtn.style.display = deck.privateKeySetupEnabled ? "inline-flex" : "inline-flex";
      setKeyBtn.disabled = !deck.privateKeySetupEnabled || deck.keySource === "env" || deck.keySaving;
      setKeyBtn.textContent = deck.keySource === "env" ? "OpenRouter Key in Environment" : "Set OpenRouter Key";
    }
    if (removeKeyBtn) {
      removeKeyBtn.style.display = deck.privateKeySetupEnabled && deck.keySource === "saved" ? "inline-flex" : "none";
      removeKeyBtn.disabled = !deck.privateKeySetupEnabled || deck.keySaving;
    }
    if (saveKeyBtn) {
      saveKeyBtn.disabled = !deck.privateKeySetupEnabled || deck.keySource === "env" || deck.keySaving;
      saveKeyBtn.textContent = deck.keySaving ? "Saving..." : "Save Key";
    }
    if (cancelKeyBtn) {
      cancelKeyBtn.disabled = !!deck.keySaving;
    }
    if (keyInput && keyInput.value && !deck.keyFormVisible) {
      keyInput.value = "";
    }
    if (modelInput) {
      modelInput.value = deck.keyModel || deck.model || "openrouter/auto";
      modelInput.disabled = !deck.privateKeySetupEnabled || deck.keySource === "env" || deck.keySaving;
    }
    if (keyFormNoteEl) {
      if (deck.keyError) {
        keyFormNoteEl.textContent = deck.keyError;
        keyFormNoteEl.style.color = "var(--bad, #ff7e91)";
      } else if (deck.keySaving) {
        keyFormNoteEl.textContent = "Saving OpenRouter key on the private service...";
        keyFormNoteEl.style.color = "var(--muted, #9cacbf)";
      } else if (deck.keySource === "env") {
        keyFormNoteEl.textContent = "Environment key is already active on this service. Saved keys are disabled here.";
        keyFormNoteEl.style.color = "var(--warn, #f0c66a)";
      } else if (!deck.privateKeySetupEnabled) {
        keyFormNoteEl.textContent = "Captain key setup is available only on the private service.";
        keyFormNoteEl.style.color = "var(--warn, #f0c66a)";
      } else {
        keyFormNoteEl.textContent = "The key is stored server-side only for the private service.";
        keyFormNoteEl.style.color = "var(--muted, #9cacbf)";
      }
    }

    if (createBtn) {
      // Planning works locally even without cloud key — only block while loading
      const hasGoal = !!(deck.goal && deck.goal.trim());
      createBtn.disabled = !!deck.loading;
      createBtn.textContent = deck.loading ? "Building plan…" : "Create Plan";
    }
    if (deployBtn) {
      const selectedAgent = (state.agents || []).find((agent) => agent.id === deck.laneId) || {};
      const agentRunnable = selectedAgent.runnable !== false && selectedAgent.adapter === "codex_cli";
      deployBtn.disabled = !deck.plan || !agentRunnable;
    }
    const captainAgentNote = document.getElementById("captain-agent-note");
    if (captainAgentNote) {
      const selectedAgent = (state.agents || []).find((agent) => agent.id === deck.laneId) || {};
      if (selectedAgent.adapter === "jules_remote") {
        captainAgentNote.textContent = "Jules Remote: planning available, execution coming soon.";
        captainAgentNote.style.display = "block";
      } else if (selectedAgent.id && !selectedAgent.runnable) {
        captainAgentNote.textContent = "Planning enabled. Agent execution requires private runner.";
        captainAgentNote.style.display = "block";
      } else {
        captainAgentNote.textContent = "";
        captainAgentNote.style.display = "none";
      }
    }
    if (copyBtn) {
      copyBtn.disabled = !deck.plan;
    }
    if (statusEl) {
      if (deck.error) {
        statusEl.textContent = deck.error;
        statusEl.style.color = "var(--bad, #ff7e91)";
      } else if (deck.loading) {
        statusEl.textContent = deck.configured ? "Captain is building the plan…" : "Building local preview plan…";
        statusEl.style.color = "var(--muted, #9cacbf)";
      } else if (deck.plan) {
        const src = deck.plan.source === "local_preview" ? " · Local preview" : "";
        statusEl.textContent = `Plan ready: ${deck.plan.title}${src}`;
        statusEl.style.color = deck.plan.source === "local_preview" ? "var(--warn, #f0c66a)" : "var(--good, #63db9d)";
      } else if (!deck.configured) {
        statusEl.textContent = "No cloud key — will use local preview planner. Enter a goal and click Create Plan.";
        statusEl.style.color = "var(--muted, #9cacbf)";
      } else {
        statusEl.textContent = "";
      }
    }
    if (planBody) {
      if (!deck.plan) {
        planBody.innerHTML = '<div class="muted" style="font-size:0.82em;">Enter a goal and click Create Plan.</div>';
      } else {
        const steps = deck.plan.steps || [];
        const isLocal = deck.plan.source === "local_preview";
        const sourceBadge = isLocal
          ? '<span style="display:inline-block;margin-left:8px;padding:1px 7px;border-radius:10px;font-size:0.72em;background:rgba(240,198,106,0.15);color:var(--warn,#f0c66a);border:1px solid var(--warn,#f0c66a);">Local Preview</span>'
          : '<span style="display:inline-block;margin-left:8px;padding:1px 7px;border-radius:10px;font-size:0.72em;background:rgba(99,219,157,0.12);color:var(--good,#63db9d);border:1px solid var(--good,#63db9d);">AI Plan</span>';
        const stepsHtml = steps.map((step, i) => `
          <details class="captain-step" style="margin-bottom:6px;">
            <summary style="cursor:pointer;padding:6px 0;">
              <strong style="margin-right:6px;">${i + 1}.</strong>
              <strong>${escapeHtml(step.title || step.id || "Step")}</strong>
              <span class="muted" style="margin-left:8px;font-size:0.8em;">${escapeHtml(step.agent || step.recommended_agent || "codex_cli")}</span>
              <span class="muted" style="margin-left:8px;font-size:0.78em;">${escapeHtml(step.status || "queued")}</span>
            </summary>
            <pre class="captain-step-prompt" style="margin:6px 0 4px;font-size:0.78em;white-space:pre-wrap;word-break:break-word;">${escapeHtml(step.prompt || "")}</pre>
            <div style="margin-top:4px;">
              <button class="btn" style="font-size:0.75em;padding:3px 10px;opacity:0.5;cursor:default;" disabled title="Agent dispatch coming in next sprint">Dispatch Step — Coming Next</button>
            </div>
          </details>
        `).join("");
        planBody.innerHTML = `
          <div style="margin-bottom:6px;">${sourceBadge}<strong style="margin-left:6px;">${escapeHtml(deck.plan.title || "Captain Plan")}</strong></div>
          <div class="muted" style="font-size:0.82em;margin-bottom:10px;">${escapeHtml(deck.plan.summary || deck.plan.goal || "")}</div>
          <div class="captain-plan-steps">${stepsHtml}</div>
        `;
      }
    }
    renderCaptainAgentCard();
  }

  function currentCaptainProfile() {
    return CAPTAIN_PROFILES.find((profile) => profile.id === state.captainProfile.selectedId) || CAPTAIN_PROFILES[0];
  }

  function profilePreviewText(markdown) {
    const lines = String(markdown || "").split("\n").filter((line) => line.trim());
    const body = lines.filter((line) => !line.startsWith("#")).join(" ").trim();
    return body.slice(0, 180) + (body.length > 180 ? "…" : "");
  }

  async function fetchCaptainProfileMarkdown(profile) {
    if (!profile) return "";
    if (state.captainProfile.cache[profile.id]) return state.captainProfile.cache[profile.id];
    const url = `${CAPTAIN_PROFILE_BASE}/${profile.file}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Profile unavailable");
    const text = await res.text();
    state.captainProfile.cache[profile.id] = text;
    return text;
  }

  function populateCaptainProfileSelect() {
    const sel = document.getElementById("captain-profile-select");
    if (!sel) return;
    sel.innerHTML = CAPTAIN_PROFILES.map((profile) => (
      `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.label)}</option>`
    )).join("");
    sel.value = currentCaptainProfile().id;
  }

  async function renderCaptainProfilePanel() {
    const preview = document.getElementById("captain-profile-preview");
    const profileLabel = document.getElementById("captain-agent-profile-label");
    const profile = currentCaptainProfile();
    if (profileLabel) {
      profileLabel.textContent = profile ? `Profile: ${profile.label}` : "";
    }
    if (!preview) return;
    preview.textContent = "Loading profile preview…";
    try {
      const markdown = await fetchCaptainProfileMarkdown(profile);
      preview.textContent = profilePreviewText(markdown) || "No preview available.";
      state.captainProfile.error = "";
    } catch (e) {
      preview.textContent = "Profile preview unavailable.";
      state.captainProfile.error = e.message || "Profile unavailable";
    }
  }

  function renderCaptainAgentCard() {
    const deck = state.captainDeck;
    const pill = document.getElementById("captain-agent-status-pill");
    const modelEl = document.getElementById("captain-agent-model");
    if (pill) {
      const label = deck.configured ? "CONFIGURED" : "NOT CONFIGURED";
      pill.textContent = label;
      pill.className = `status-pill ${deck.configured ? "status-ready" : "status-coming"}`;
    }
    if (modelEl) {
      modelEl.textContent = deck.configured || deck.model
        ? `Model: ${deck.model || "openrouter/auto"}`
        : "Model: —";
    }
    populateCaptainProfileSelect();
    renderCaptainProfilePanel().catch((e) => console.error(e));
  }

  function navigateToCaptainAgents({ highlightProfile = false } = {}) {
    setActiveSection("agents");
    const card = document.getElementById("captain-agent-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
    if (highlightProfile) {
      const panel = document.getElementById("captain-profile-panel");
      if (panel) {
        panel.classList.add("captain-profile-highlight");
        setTimeout(() => panel.classList.remove("captain-profile-highlight"), 1800);
      }
      const sel = document.getElementById("captain-profile-select");
      if (sel) sel.focus();
    }
  }

  async function openCaptainProfileModal() {
    const modal = document.getElementById("captain-profile-modal");
    const pre = document.getElementById("captain-profile-markdown");
    const nameEl = document.getElementById("captain-profile-modal-name");
    const profile = currentCaptainProfile();
    if (!modal || !pre) return;
    if (nameEl) nameEl.textContent = profile ? profile.label : "";
    pre.textContent = "Loading…";
    modal.style.display = "flex";
    try {
      pre.textContent = await fetchCaptainProfileMarkdown(profile);
    } catch (e) {
      pre.textContent = "Unable to load instruction profile.";
    }
  }

  function closeCaptainProfileModal() {
    const modal = document.getElementById("captain-profile-modal");
    if (modal) modal.style.display = "none";
  }

  async function copyCaptainProfileInstructions() {
    const profile = currentCaptainProfile();
    try {
      const markdown = await fetchCaptainProfileMarkdown(profile);
      await navigator.clipboard.writeText(markdown);
    } catch (e) {
      try {
        const markdown = await fetchCaptainProfileMarkdown(profile);
        prompt("Copy instructions:", markdown);
      } catch (err) {
        alert("Unable to copy instruction profile.");
      }
    }
  }

  function useCaptainProfileSelection() {
    const sel = document.getElementById("captain-profile-select");
    const profileId = (sel && sel.value) || currentCaptainProfile().id;
    state.captainProfile.selectedId = profileId;
    localStorage.setItem(CAPTAIN_PROFILE_STORAGE_KEY, profileId);
    renderCaptainAgentCard();
  }

  async function loadLatestCaptainPlan() {
    try {
      const data = await requestJson(`${MCH}/captain/plans/recent`);
      const plans = data.plans || [];
      if (plans.length && !state.captainDeck.plan) {
        const latest = plans[0];
        state.captainDeck.plan = latest;
        if (latest.goal) state.captainDeck.goal = latest.goal;
        const goalEl = document.getElementById("captain-goal");
        if (goalEl && latest.goal && !goalEl.value) goalEl.value = latest.goal;
      }
    } catch (e) { /* non-fatal */ }
  }

  async function openCaptainDeckModal() {
    const modal = document.getElementById("captain-deck-modal");
    if (!modal) return;
    modal.style.display = "flex";
    state.captainDeck.error = "";
    state.captainDeck.keyError = "";
    state.captainDeck.keyFormVisible = false;
    renderCaptainDeck();
    await Promise.all([populateCaptainDeckRepos(), loadCaptainDeckStatus(), loadAgents()]);
    populateCaptainAgents();
    await loadLatestCaptainPlan();
    renderCaptainDeck();
  }

  function closeCaptainDeckModal() {
    const modal = document.getElementById("captain-deck-modal");
    if (modal) modal.style.display = "none";
  }

  function openCaptainKeyForm() {
    const deck = state.captainDeck;
    if (!deck.privateKeySetupEnabled || deck.keySource === "env") return;
    deck.keyError = "";
    deck.keyFormVisible = true;
    deck.keyModel = deck.keyModel || deck.model || "openrouter/auto";
    renderCaptainDeck();
    const keyInput = document.getElementById("captain-openrouter-key");
    if (keyInput) {
      keyInput.value = "";
      keyInput.focus();
    }
  }

  function closeCaptainKeyForm() {
    const deck = state.captainDeck;
    deck.keyError = "";
    deck.keyFormVisible = false;
    renderCaptainDeck();
  }

  async function saveCaptainKey() {
    const deck = state.captainDeck;
    const keyInput = document.getElementById("captain-openrouter-key");
    const modelInput = document.getElementById("captain-openrouter-model");
    if (!deck.privateKeySetupEnabled || deck.keySource === "env") {
      deck.keyError = "Captain key setup is available only on the private service.";
      renderCaptainDeck();
      return;
    }
    const apiKey = (keyInput && keyInput.value ? keyInput.value : "").trim();
    const model = (modelInput && modelInput.value ? modelInput.value : "").trim() || "openrouter/auto";
    if (!apiKey) {
      deck.keyError = "Enter an OpenRouter API key first.";
      renderCaptainDeck();
      return;
    }
    deck.keySaving = true;
    deck.keyError = "";
    renderCaptainDeck();
    try {
      await requestJson(`${MCH}/captain/key`, {
        method: "POST",
        body: {
          api_key: apiKey,
          model,
        },
      });
      if (keyInput) keyInput.value = "";
      deck.keyFormVisible = false;
      await loadCaptainDeckStatus();
      deck.keyError = "";
      renderCaptainDeck();
    } catch (e) {
      deck.keyError = e.message || String(e);
      renderCaptainDeck();
    } finally {
      deck.keySaving = false;
      renderCaptainDeck();
    }
  }

  async function removeCaptainKey() {
    const deck = state.captainDeck;
    if (!deck.privateKeySetupEnabled || deck.keySource !== "saved") return;
    deck.keySaving = true;
    deck.keyError = "";
    renderCaptainDeck();
    try {
      await requestJson(`${MCH}/captain/key`, {
        method: "DELETE",
      });
      deck.keyFormVisible = false;
      await loadCaptainDeckStatus();
      renderCaptainDeck();
    } catch (e) {
      deck.keyError = e.message || String(e);
      renderCaptainDeck();
    } finally {
      deck.keySaving = false;
      renderCaptainDeck();
    }
  }

  async function createCaptainPlan() {
    const deck = state.captainDeck;
    const goalEl = document.getElementById("captain-goal");
    const repoSel = document.getElementById("captain-repo-select");
    const laneSel = document.getElementById("captain-agent-select");
    if (!goalEl || !repoSel || !laneSel) return;
    const goal = (goalEl.value || "").trim();
    const repoId = repoSel.value;
    const repoPath = (repoSel.selectedOptions[0] && repoSel.selectedOptions[0].dataset.repoPath) || "";
    const laneId = laneSel.value || "codex_cli";
    if (!goal) {
      deck.error = "Describe the goal first.";
      renderCaptainDeck();
      return;
    }
    deck.loading = true;
    deck.error = "";
    deck.goal = goal;
    deck.repoId = repoId;
    deck.repoPath = repoPath;
    deck.laneId = laneId;
    renderCaptainDeck();
    try {
      const plan = await requestJson(`${MCH}/captain/plan`, {
        method: "POST",
        body: {
          goal,
          repo_id: repoId,
          lane_id: laneId,
        },
      });
      deck.plan = plan;
      setActiveCaptainPlan(plan);
      deck.error = "";
      deck.loading = false;
      renderCaptainDeck();
    } catch (e) {
      deck.loading = false;
      deck.error = e.message || String(e);
      renderCaptainDeck();
    }
  }

  async function copyCaptainPlan() {
    const plan = state.captainDeck.plan;
    if (!plan) return;
    const text = JSON.stringify(plan, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      const status = document.getElementById("captain-plan-status");
      if (status) status.textContent = "Plan copied to clipboard.";
    } catch (e) {
      prompt("Copy plan:", text);
    }
  }

  async function deployCaptainFirstPrompt() {
    const plan = state.activeCaptainPlan || state.captainDeck.plan;
    if (!plan || !plan.steps || !plan.steps.length) return;
    const current = currentCaptainStep(normalizeCaptainPlan(plan));
    if (!current) return;
    await dispatchCaptainStep(current.id || current.step_id);
  }

  async function loadAgents() {
    try {
      const data = await requestJson(`${MCH}/agents`);
      state.agents = data.agents || [];
      state.registryWriteEnabled = !!data.registry_write_enabled;
      renderRemoteAgentCards();
      populateCaptainAgents();
      renderSettingsPanel();
      return data;
    } catch (e) {
      state.agents = [];
      state.registryWriteEnabled = false;
      renderRemoteAgentCards();
      renderSettingsPanel();
      return null;
    }
  }

  async function refreshAgentStatuses() {
    const data = await requestJson(`${MCH}/agents/refresh-status`, { method: "POST" });
    state.agents = data.agents || [];
    state.agentStatusLastChecked = data.last_checked_at || null;
    state.registryWriteEnabled = !!data.registry_write_enabled;
    renderRemoteAgentCards();
    populateCaptainAgents();
    renderSettingsPanel();
    return data;
  }

  async function loadAgentTemplates() {
    try {
      const data = await requestJson(`${MCH}/agents/templates`);
      state.agentTemplates = data.templates || [];
      return data;
    } catch (e) {
      state.agentTemplates = [];
      return null;
    }
  }

  function agentTypeLabel(agent) {
    if (!agent) return "Unknown";
    return agent.kind === "remote" ? "Remote" : "CLI";
  }

  function agentStatusLabel(agent) {
    if (!agent) return "unknown";
    if (agent.connection_status === "connected" && agent.status === "ready") return "connected";
    if (agent.status === "unverified" || agent.connection_status === "unverified") return "unverified";
    return agent.status || agent.connection_status || "unknown";
  }

  function setCodexStatusPill({ ready, disabled, label }) {
    const pill = document.getElementById("codex-status-pill");
    if (!pill) return;
    const text = label || (ready ? "READY" : disabled ? "DISABLED" : "COMING NEXT");
    pill.textContent = String(text).toUpperCase();
    pill.className = `status-pill ${ready ? "status-ready" : disabled ? "status-disabled" : "status-coming"}`;
  }

  function julesWorkspaceStatus() {
    const jules = (state.agents || []).find((agent) => agent.adapter === "jules_remote" && agent.user_created);
    if (!jules) return "Planning only";
    if (jules.connection_status === "connected" && jules.status === "ready") return "Connected";
    return "Setup needed";
  }

  function julesHeroStatus() {
    const jules = (state.agents || []).find((agent) => agent.adapter === "jules_remote" && agent.user_created);
    if (jules && jules.connection_status === "connected" && jules.status === "ready") return "Connected";
    return "Planning only";
  }

  function julesInspectorStatus() {
    const jules = (state.agents || []).find((agent) => agent.adapter === "jules_remote" && agent.user_created);
    if (jules && jules.connection_status === "connected" && jules.status === "ready") {
      return "Connected, planning only";
    }
    return "Setup needed";
  }

  function renderCodexCapabilityChips(codex) {
    const capsEl = document.getElementById("codex-capabilities");
    if (!capsEl) return;
    const caps = (codex && codex.capabilities) || [];
    if (!caps.length) {
      capsEl.style.display = "none";
      capsEl.innerHTML = "";
      return;
    }
    capsEl.style.display = "flex";
    capsEl.innerHTML = caps.slice(0, 4).map((cap) => `<span class="cap-chip">${escapeHtml(cap)}</span>`).join("");
  }

  function updateRunsEvidenceActions() {
    const hasSession = !!state.selectedThreadId;
    ["runs-open-monitor", "evidence-open-output"].forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) btn.style.display = hasSession ? "" : "none";
    });
  }

  function formatHistoryTimestamp(value) {
    if (!value) return "—";
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    } catch (e) {
      return value;
    }
  }

  function stepCompletionAllowed(step) {
    const gateStatus = step && step.gate_status;
    return !gateStatus || gateStatus === "approved";
  }

  function gateBannerCopy(step, { isCurrent = false } = {}) {
    if (!isCurrent || !step || !step.gate_status) return "";
    const label = step.gate_label || step.gate_status;
    if (step.gate_status === "blocked") {
      return `Hard stop — ${label}. Resolve the gate before continuing.`;
    }
    if (step.gate_status === "needs_more_evidence") {
      return "More evidence is required before this step can be marked done.";
    }
    if (step.gate_status === "pending") {
      return "Proof gate pending. Review and decide before marking the step done.";
    }
    if (step.gate_status === "approved") {
      return `Proof gate approved. You may mark the step done manually when ready.`;
    }
    return `Proof gate: ${label}`;
  }

  const TIMELINE_FILTER_KINDS = {
    plans: new Set(["plan_created", "step_dispatched", "step_completed", "step_revised", "plan_stopped"]),
    runs: new Set(["run_created"]),
    evidence: new Set(["evidence_saved"]),
    gates: new Set(["gate_created", "gate_approved", "gate_blocked", "gate_needs_more_evidence"]),
  };

  function worklogStatusClass(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "running" || normalized === "dispatched") return "status-ready";
    if (normalized === "completed" || normalized === "saved" || normalized === "approved") return "status-connected";
    if (normalized === "stopped" || normalized === "blocked" || normalized === "failed") return "status-disabled";
    return "status-coming";
  }

  function filteredMissionTimelineItems() {
    const items = state.missionWorklog || [];
    const filter = state.missionTimelineFilter || "all";
    if (filter === "all") return items;
    const allowed = TIMELINE_FILTER_KINDS[filter];
    if (!allowed) return items;
    return items.filter((item) => allowed.has(String(item.kind || "")));
  }

  function missionTimelineEmptyMessage() {
    const filter = state.missionTimelineFilter || "all";
    const hasAny = (state.missionWorklog || []).length > 0;
    if (!hasAny) return "No mission activity yet. Create a plan to start the timeline.";
    if (filter === "plans") return "No plan events yet. Captain plan activity will appear here.";
    if (filter === "runs") return "No run events yet. Dispatched agent runs will appear here.";
    if (filter === "evidence") return "No evidence events yet. Saved outputs will appear here.";
    if (filter === "gates") return "No gate events yet. Proof gate decisions will appear here.";
    return "No timeline events match this filter.";
  }

  function renderMissionTimelineFilter() {
    const bar = document.getElementById("mission-timeline-filter");
    if (!bar) return;
    bar.querySelectorAll("[data-timeline-filter]").forEach((button) => {
      const value = button.getAttribute("data-timeline-filter") || "all";
      button.classList.toggle("active", value === (state.missionTimelineFilter || "all"));
    });
  }

  function controlRoomHandlesMissionTimeline() {
    return !!document.getElementById("cr-command-center");
  }

  function renderMissionWorklog() {
    const list = document.getElementById("mission-worklog-list");
    const empty = document.getElementById("mission-worklog-empty");
    if (!list || !empty) return;
    if (controlRoomHandlesMissionTimeline()) {
      list.innerHTML = "";
      list.style.display = "none";
      empty.style.display = "none";
      return;
    }
    const allItems = state.missionWorklog || [];
    const items = filteredMissionTimelineItems();
    renderMissionTimelineFilter();
    if (!allItems.length) {
      list.innerHTML = "";
      list.style.display = "none";
      empty.style.display = "";
      empty.textContent = missionTimelineEmptyMessage();
      return;
    }
    if (!items.length) {
      list.innerHTML = "";
      list.style.display = "none";
      empty.style.display = "";
      empty.textContent = missionTimelineEmptyMessage();
      return;
    }
    empty.style.display = "none";
    list.style.display = "flex";
    list.innerHTML = items.map((item) => {
      const links = item.links || {};
      const linkBits = [];
      if (links.run_id) linkBits.push(`<button type="button" class="btn" data-worklog-run-id="${escapeHtml(links.run_id)}">Run</button>`);
      if (links.evidence_id) linkBits.push(`<button type="button" class="btn" data-worklog-evidence-id="${escapeHtml(links.evidence_id)}">Evidence</button>`);
      return `
        <div class="worklog-event-card" data-testid="worklog-event-${escapeHtml(item.kind || "event")}">
          <div class="worklog-event-top">
            <span class="worklog-event-label">${escapeHtml(item.label || item.kind || "event")}</span>
            <span class="status-pill ${worklogStatusClass(item.status)}">${escapeHtml(String(item.status || "saved").toUpperCase())}</span>
          </div>
          <p class="worklog-event-title">${escapeHtml(item.title || "Mission activity")}</p>
          <p class="worklog-event-summary">${escapeHtml(item.summary || "")}</p>
          <p class="worklog-event-time">${escapeHtml(formatHistoryTimestamp(item.created_at))}</p>
          ${linkBits.length ? `<div class="worklog-event-links">${linkBits.join("")}</div>` : ""}
        </div>
      `;
    }).join("");
    list.querySelectorAll("[data-worklog-run-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const runId = button.getAttribute("data-worklog-run-id");
        if (runId) openRunDetailModal(runId).catch((e) => console.error(e));
      });
    });
    list.querySelectorAll("[data-worklog-evidence-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const evidenceId = button.getAttribute("data-worklog-evidence-id");
        if (evidenceId) openEvidenceDetailModal(evidenceId).catch((e) => console.error(e));
      });
    });
  }

  async function loadMissionWorklog() {
    try {
      const data = await requestJson(`${MCH}/worklog/recent`);
      state.missionWorklog = data.items || [];
      renderMissionWorklog();
      return data;
    } catch (e) {
      state.missionWorklog = [];
      renderMissionWorklog();
      return null;
    }
  }

  function renderRunsPanel() {
    const list = document.getElementById("runs-list");
    const empty = document.querySelector("[data-testid='runs-empty-state']");
    const runs = state.recentRuns || [];
    if (!list || !empty) return;
    if (!runs.length) {
      list.style.display = "none";
      list.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";
    list.style.display = "grid";
    list.innerHTML = runs.map((run) => `
      <div class="history-card" data-run-id="${escapeHtml(run.run_id)}">
        <div class="history-card-top">
          <h3 class="history-card-title">${escapeHtml(run.title || run.run_id)}</h3>
          <span class="status-pill ${run.status === "running" || run.status === "dispatched" ? "status-ready" : "status-connected"}">${escapeHtml((run.status || "unknown").toUpperCase())}</span>
        </div>
        <p class="history-card-meta">${escapeHtml(run.agent_id || "agent")} · ${escapeHtml(run.repo_id || "repo")} · ${escapeHtml(formatHistoryTimestamp(run.started_at))}${run.plan_id ? ` · Plan ${escapeHtml(run.plan_id)}` : ""}</p>
        <p class="history-card-copy">${escapeHtml(run.prompt_excerpt || "No prompt excerpt saved.")}</p>
        <p class="history-card-meta">Evidence: ${Number(run.evidence_count || 0)}${run.gate_status ? ` · Gate: ${escapeHtml(run.gate_status)}` : ""}</p>
        <button type="button" class="btn" data-view-run-id="${escapeHtml(run.run_id)}">View Run</button>
      </div>
    `).join("");
    list.querySelectorAll("[data-view-run-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const runId = button.getAttribute("data-view-run-id");
        if (runId) openRunDetailModal(runId).catch((e) => console.error(e));
      });
    });
  }

  function filteredEvidenceItems() {
    const evidence = state.recentEvidence || [];
    const filter = state.evidenceTypeFilter || "all";
    if (filter === "all") return evidence;
    return evidence.filter((item) => String(item.type || "") === filter);
  }

  function renderEvidenceTypeFilter() {
    const bar = document.getElementById("evidence-type-filter");
    if (!bar) return;
    const hasEvidence = (state.recentEvidence || []).length > 0;
    bar.style.display = hasEvidence ? "flex" : "none";
    bar.querySelectorAll("[data-evidence-filter]").forEach((button) => {
      const value = button.getAttribute("data-evidence-filter") || "all";
      button.classList.toggle("active", value === (state.evidenceTypeFilter || "all"));
    });
  }

  function renderEvidencePanel() {
    const list = document.getElementById("evidence-list");
    const empty = document.querySelector("[data-testid='evidence-empty-state']");
    const evidence = filteredEvidenceItems();
    if (!list || !empty) return;
    renderEvidenceTypeFilter();
    if (!evidence.length) {
      list.style.display = "none";
      list.innerHTML = "";
      empty.style.display = (state.recentEvidence || []).length ? "none" : "";
      if ((state.recentEvidence || []).length) {
        list.style.display = "grid";
        list.innerHTML = "<p class=\"history-card-copy\">No evidence matches this filter.</p>";
      }
      return;
    }
    empty.style.display = "none";
    list.style.display = "grid";
    list.innerHTML = evidence.map((item) => `
      <div class="history-card" data-evidence-id="${escapeHtml(item.evidence_id)}">
        <div class="history-card-top">
          <h3 class="history-card-title">${escapeHtml(item.title || item.evidence_id)}</h3>
          <span class="status-pill status-connected">${escapeHtml((item.type || "evidence").toUpperCase())}</span>
        </div>
        <p class="history-card-meta">${escapeHtml(formatHistoryTimestamp(item.created_at))}${item.agent_id ? ` · ${escapeHtml(item.agent_id)}` : ""}${item.run_id ? ` · Run ${escapeHtml(item.run_id)}` : ""}</p>
        <p class="history-card-copy">${escapeHtml(item.summary || item.content_excerpt || "Saved evidence excerpt.")}</p>
        <button type="button" class="btn" data-view-evidence-id="${escapeHtml(item.evidence_id)}">View Evidence</button>
      </div>
    `).join("");
    list.querySelectorAll("[data-view-evidence-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const evidenceId = button.getAttribute("data-view-evidence-id");
        if (evidenceId) openEvidenceDetailModal(evidenceId).catch((e) => console.error(e));
      });
    });
  }

  async function loadRecentRuns() {
    try {
      const data = await requestJson(`${MCH}/runs/recent`);
      state.recentRuns = data.runs || [];
      renderRunsPanel();
      return data;
    } catch (e) {
      state.recentRuns = [];
      renderRunsPanel();
      return null;
    }
  }

  async function loadRecentEvidence() {
    try {
      const data = await requestJson(`${MCH}/evidence/recent`);
      state.recentEvidence = data.evidence || [];
      renderEvidencePanel();
      return data;
    } catch (e) {
      state.recentEvidence = [];
      renderEvidencePanel();
      return null;
    }
  }

  async function exportRunReport(runId) {
    const data = await requestJson(`${MCH}/runs/${encodeURIComponent(runId)}/report`);
    const markdown = data.markdown || "";
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `warden-run-${runId}.md`;
    link.click();
    URL.revokeObjectURL(url);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(markdown);
      } catch (e) {
        /* clipboard optional */
      }
    }
  }

  function proofGateStatusClass(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "approved") return "status-connected";
    if (normalized === "pending") return "status-coming";
    return "status-disabled";
  }

  function renderProofGateCard(gate, { interactive = false } = {}) {
    const status = gate.status || "pending";
    const actions = interactive && status === "pending"
      ? `
        <div class="proof-gate-actions">
          <button type="button" class="btn good" data-gate-approve="${escapeHtml(gate.gate_id)}">Approve</button>
          <button type="button" class="btn bad" data-gate-block="${escapeHtml(gate.gate_id)}">Block</button>
          <button type="button" class="btn" data-gate-more-evidence="${escapeHtml(gate.gate_id)}">Request More Evidence</button>
        </div>
      `
      : gate.decision_reason
        ? `<p class="history-card-meta">Decision: ${escapeHtml(gate.decision_reason)}</p>`
        : "";
    return `
      <div class="proof-gate-card" data-gate-id="${escapeHtml(gate.gate_id)}">
        <div class="history-card-top">
          <h4 class="history-card-title">${escapeHtml(gate.title || gate.gate_id)}</h4>
          <span class="status-pill ${proofGateStatusClass(status)}">${escapeHtml(String(status).toUpperCase())}</span>
        </div>
        <p class="history-card-meta">${escapeHtml(gate.gate_type || "manual_review")} · ${escapeHtml(formatHistoryTimestamp(gate.created_at))}</p>
        <p class="history-card-copy">${escapeHtml(gate.summary || "Manual proof gate.")}</p>
        ${actions}
      </div>
    `;
  }

  function bindProofGateActions(container, runId) {
    if (!container) return;
    container.querySelectorAll("[data-gate-approve]").forEach((button) => {
      button.addEventListener("click", () => {
        const gateId = button.getAttribute("data-gate-approve");
        if (gateId) decideProofGate(gateId, "approve", runId).catch((e) => console.error(e));
      });
    });
    container.querySelectorAll("[data-gate-block]").forEach((button) => {
      button.addEventListener("click", () => {
        const gateId = button.getAttribute("data-gate-block");
        if (gateId) decideProofGate(gateId, "block", runId).catch((e) => console.error(e));
      });
    });
    container.querySelectorAll("[data-gate-more-evidence]").forEach((button) => {
      button.addEventListener("click", () => {
        const gateId = button.getAttribute("data-gate-more-evidence");
        if (gateId) decideProofGate(gateId, "request_more_evidence", runId).catch((e) => console.error(e));
      });
    });
  }

  async function decideProofGate(gateId, decision, runId) {
    let decisionReason = null;
    if (decision === "block" || decision === "request_more_evidence") {
      decisionReason = window.prompt("Enter a short reason for this decision:");
      if (!decisionReason || !decisionReason.trim()) return;
    }
    await requestJson(`${MCH}/gates/${encodeURIComponent(gateId)}/decision`, {
      method: "POST",
      body: {
        decision,
        decided_by: "operator",
        decision_reason: decisionReason,
      },
    });
    if (runId) await openRunDetailModal(runId);
    await Promise.all([loadRecentGates(), loadMissionWorklog(), loadActiveCaptainPlan()]);
  }

  async function createProofGateForRun(runId, evidenceIds) {
    const title = window.prompt("Proof gate title:", "Manual review gate");
    if (!title || !title.trim()) return;
    await requestJson(`${MCH}/runs/${encodeURIComponent(runId)}/gates`, {
      method: "POST",
      body: {
        title: title.trim(),
        summary: "Operator-created manual proof gate.",
        evidence_ids: evidenceIds || [],
      },
    });
    await openRunDetailModal(runId);
    await Promise.all([loadRecentGates(), loadMissionWorklog(), loadActiveCaptainPlan()]);
  }

  function renderInspectorGatesSummary() {
    const summary = document.getElementById("inspector-gates-summary");
    if (!summary) return;
    const gates = state.recentGates || [];
    if (!gates.length) {
      summary.textContent = "No proof gates yet.";
      return;
    }
    const pending = gates.filter((gate) => gate.status === "pending").length;
    const latest = gates[0];
    summary.innerHTML = `
      <div>${pending} pending · ${gates.length} total</div>
      <div class="history-card-meta">Latest: ${escapeHtml(latest.title || latest.gate_id)} (${escapeHtml(latest.status || "pending")})</div>
    `;
  }

  async function loadRecentGates() {
    try {
      const data = await requestJson(`${MCH}/gates/recent`);
      state.recentGates = data.gates || [];
      renderInspectorGatesSummary();
      return data;
    } catch (e) {
      state.recentGates = [];
      renderInspectorGatesSummary();
      return null;
    }
  }

  function runDetailDecisionLabel(decision) {
    const labels = {
      approve: "Approved",
      block: "Blocked",
      request_more_evidence: "Requested more evidence",
    };
    return labels[decision] || String(decision || "decision").replace(/_/g, " ");
  }

  function linkedCaptainStepForRun(run) {
    const plan = state.activeCaptainPlan;
    if (!plan || !run) return null;
    const runId = String(run.run_id || "");
    if (!runId) return null;
    return (plan.steps || []).find((step) => String(step.run_id || "") === runId) || null;
  }

  function renderRunDetailDecisions(gates) {
    const decisionsEl = document.getElementById("run-detail-decisions");
    if (!decisionsEl) return;
    const entries = [];
    gates.forEach((gate) => {
      (gate.decision_log || []).forEach((entry) => {
        entries.push({
          at: entry.at,
          gateTitle: gate.title || gate.gate_id,
          decision: entry.decision,
          decidedBy: entry.decided_by,
          reason: entry.reason,
        });
      });
    });
    entries.sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
    if (!entries.length) {
      decisionsEl.innerHTML = "<li>No gate decisions recorded yet.</li>";
      return;
    }
    decisionsEl.innerHTML = entries.map((entry) => {
      const reason = entry.reason ? ` — ${entry.reason}` : "";
      return `<li>${escapeHtml(runDetailDecisionLabel(entry.decision))} · ${escapeHtml(entry.gateTitle)} · ${escapeHtml(entry.decidedBy || "operator")}${escapeHtml(reason)} · ${escapeHtml(formatHistoryTimestamp(entry.at))}</li>`;
    }).join("");
  }

  function renderRunDetailNextActions(run, gates, evidenceItems, { canWrite = false } = {}) {
    const actionsEl = document.getElementById("run-detail-next-actions");
    if (!actionsEl) return;
    const gateStatus = run.gate_status || (gates.length ? gates[0].status : null);
    const pendingGate = gates.find((gate) => gate.status === "pending");
    const linkedStep = linkedCaptainStepForRun(run);
    const evidenceIds = evidenceItems.map((item) => item.evidence_id).filter(Boolean);
    const bits = [];

    if (!canWrite) {
      bits.push('<p class="run-detail-action-note">Manual review actions require the private runner service.</p>');
    } else if (gateStatus === "blocked") {
      bits.push('<p class="run-detail-action-note">Hard stop — gate is blocked. Revise the step or resolve the gate before continuing.</p>');
    } else if (!gates.length) {
      bits.push('<button type="button" class="btn primary" data-testid="run-detail-create-gate" id="run-detail-create-gate">Create Proof Gate</button>');
    } else if (pendingGate) {
      bits.push(`
        <button type="button" class="btn good" data-testid="run-detail-approve-gate" data-gate-approve="${escapeHtml(pendingGate.gate_id)}">Approve Gate</button>
        <button type="button" class="btn bad" data-testid="run-detail-block-gate" data-gate-block="${escapeHtml(pendingGate.gate_id)}">Block Gate</button>
        <button type="button" class="btn" data-testid="run-detail-more-evidence" data-gate-more-evidence="${escapeHtml(pendingGate.gate_id)}">Request More Evidence</button>
      `);
    } else if (gateStatus === "needs_more_evidence") {
      bits.push('<p class="run-detail-action-note">Save more evidence, then approve the gate when ready.</p>');
      bits.push('<button type="button" class="btn" data-testid="run-detail-create-gate" id="run-detail-create-gate">Create Proof Gate</button>');
    } else if (gateStatus === "approved") {
      bits.push('<p class="run-detail-action-note">Gate approved. Mark the linked Captain step done manually when ready — no auto-dispatch.</p>');
      if (linkedStep && stepCompletionAllowed(linkedStep)) {
        bits.push(`<button type="button" class="btn good" data-testid="run-detail-complete-step" data-complete-step-id="${escapeHtml(linkedStep.id || linkedStep.step_id)}">Mark Step Complete</button>`);
      }
    } else {
      bits.push('<button type="button" class="btn primary" data-testid="run-detail-create-gate" id="run-detail-create-gate">Create Proof Gate</button>');
    }

    actionsEl.innerHTML = bits.join("");
    actionsEl.dataset.gateStatus = gateStatus || "none";

    const createGateBtn = actionsEl.querySelector("#run-detail-create-gate");
    if (createGateBtn) {
      createGateBtn.addEventListener("click", () => {
        createProofGateForRun(run.run_id, evidenceIds).catch((e) => console.error(e));
      });
    }
    bindProofGateActions(actionsEl, run.run_id);
    actionsEl.querySelectorAll("[data-complete-step-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const stepId = button.getAttribute("data-complete-step-id");
        if (stepId) completeCaptainStep(stepId).catch((e) => console.error(e));
      });
    });
  }

  async function openRunDetailModal(runId) {
    const modal = document.getElementById("run-detail-modal");
    if (!modal) return;
    const [data, gateData] = await Promise.all([
      requestJson(`${MCH}/runs/${encodeURIComponent(runId)}`),
      requestJson(`${MCH}/runs/${encodeURIComponent(runId)}/gates`).catch(() => ({ gates: [] })),
    ]);
    const run = data.run || {};
    const gates = gateData.gates || data.gates || [];
    state.activeRunDetailId = runId;
    const title = document.getElementById("run-detail-title");
    const meta = document.getElementById("run-detail-meta");
    const prompt = document.getElementById("run-detail-prompt");
    const transcript = document.getElementById("run-detail-transcript");
    const evidence = document.getElementById("run-detail-evidence");
    const gatesEl = document.getElementById("run-detail-gates");
    const health = state.health || {};
    const canWrite = !!health.tmux_runner_enabled && !!health.codex_runner_enabled;
    if (title) title.textContent = run.title || run.run_id || "Run Detail";
    if (meta) {
      const gateLabel = run.gate_label || (run.gate_status ? String(run.gate_status).replace(/_/g, " ") : "No gate");
      meta.textContent = `${run.agent_id || "agent"} · ${run.status || "unknown"} · ${formatHistoryTimestamp(run.started_at)} · Evidence: ${Number(run.evidence_count || (data.evidence || []).length || 0)} · Gate: ${gateLabel}`;
    }
    const gateStateEl = document.getElementById("run-detail-gate-state");
    if (gateStateEl) {
      const gateStatus = run.gate_status || (gates.length ? gates[0].status : null);
      const gateLabel = run.gate_label || (gateStatus ? String(gateStatus).replace(/_/g, " ") : "No gate");
      let copy = `Proof gate state: ${gateLabel}`;
      if (gateStatus === "blocked") copy = `Hard stop — ${gateLabel}. This run cannot advance until the gate is resolved.`;
      if (gateStatus === "needs_more_evidence") copy = "This run needs more evidence before the step can be marked done.";
      if (gateStatus === "pending") copy = "Proof gate pending. Review evidence and decide before marking the step done.";
      gateStateEl.textContent = copy;
      gateStateEl.dataset.gateStatus = gateStatus || "none";
    }
    if (prompt) prompt.textContent = run.prompt || run.prompt_excerpt || "(no prompt saved)";
    if (transcript) transcript.textContent = run.transcript_excerpt || "(no transcript saved yet)";
    const evidenceItems = data.evidence || [];
    if (evidence) {
      evidence.innerHTML = evidenceItems.length
        ? evidenceItems.map((item) => `<li>${escapeHtml(item.title || item.evidence_id)} · ${escapeHtml(item.type || "evidence")}</li>`).join("")
        : "<li>No saved evidence linked to this run yet.</li>";
    }
    if (gatesEl) {
      gatesEl.innerHTML = gates.length
        ? gates.map((gate) => renderProofGateCard(gate, { interactive: false })).join("")
        : "<p class=\"history-card-copy\">No proof gate created for this run yet.</p>";
    }
    renderRunDetailDecisions(gates);
    renderRunDetailNextActions(run, gates, evidenceItems, { canWrite });
    const exportBtn = document.getElementById("run-detail-export");
    if (exportBtn) {
      exportBtn.onclick = () => exportRunReport(runId).catch((e) => console.error(e));
    }
    modal.style.display = "flex";
  }

  function closeRunDetailModal() {
    const modal = document.getElementById("run-detail-modal");
    if (modal) modal.style.display = "none";
  }

  async function openEvidenceDetailModal(evidenceId) {
    const modal = document.getElementById("evidence-detail-modal");
    if (!modal) return;
    const data = await requestJson(`${MCH}/evidence/${encodeURIComponent(evidenceId)}`);
    const item = data.evidence || {};
    const linkedRun = data.linked_run;
    const title = document.getElementById("evidence-detail-title");
    const meta = document.getElementById("evidence-detail-meta");
    const content = document.getElementById("evidence-detail-content");
    const runMeta = document.getElementById("evidence-detail-run");
    if (title) title.textContent = item.title || item.evidence_id || "Evidence Detail";
    if (meta) {
      meta.textContent = `${item.type || "evidence"} · ${formatHistoryTimestamp(item.created_at)} · ${item.source || "operator"}`;
    }
    if (content) content.textContent = item.content || item.content_excerpt || item.summary || "(no content saved)";
    if (runMeta) {
      runMeta.textContent = linkedRun
        ? `Linked run: ${linkedRun.title || linkedRun.run_id} (${linkedRun.status || "unknown"})`
        : "No linked run.";
    }
    modal.style.display = "flex";
  }

  function closeEvidenceDetailModal() {
    const modal = document.getElementById("evidence-detail-modal");
    if (modal) modal.style.display = "none";
  }

  function normalizeCaptainPlan(plan) {
    if (!plan) return null;
    const steps = (plan.steps || []).map((step, index) => ({
      id: step.id || step.step_id || `step_${index + 1}`,
      step_id: step.step_id || step.id || `step_${index + 1}`,
      title: step.title,
      agent: step.agent || step.agent_id || "codex_cli",
      agent_id: step.agent_id || step.agent || "codex_cli",
      prompt: step.prompt || step.prompt_preview || "",
      status: step.status || "queued",
      run_id: step.run_id || null,
      evidence_ids: step.evidence_ids || [],
      order: step.order || index + 1,
    }));
    return {
      ...plan,
      plan_id: plan.plan_id || plan.id,
      current_step_id: plan.current_step_id || (steps[0] && steps[0].id),
      steps,
    };
  }

  function setActiveCaptainPlan(plan) {
    state.activeCaptainPlan = normalizeCaptainPlan(plan);
    if (state.captainDeck && state.activeCaptainPlan) {
      state.captainDeck.plan = state.activeCaptainPlan;
    }
    renderMissionPlanPanel();
    renderCaptainDeck();
  }

  function currentCaptainStep(plan) {
    if (!plan || !plan.steps || !plan.steps.length) return null;
    const currentId = plan.current_step_id;
    return plan.steps.find((step) => step.id === currentId || step.step_id === currentId) || plan.steps[0];
  }

  function isControlRoomDemoMode() {
    return !!(window.WardenControlRoom && window.WardenControlRoom.isDemoMode && window.WardenControlRoom.isDemoMode());
  }

  function renderMissionPlanPanel() {
    const empty = document.getElementById("current-mission-empty");
    const panel = document.getElementById("current-mission-plan");
    const header = document.getElementById("current-plan-header");
    const stepsEl = document.getElementById("captain-plan-steps");
    const controls = document.getElementById("captain-plan-controls");
    const plan = state.activeCaptainPlan;
    if (!empty || !panel || !header || !stepsEl || !controls) return;

    if (isControlRoomDemoMode()) {
      empty.style.display = "none";
      panel.style.display = "none";
      return;
    }

    const crEmpty = document.getElementById("cr-mission-empty");
    const crActive = document.getElementById("cr-mission-active");
    if (!plan || plan.status === "stopped") {
      empty.style.display = "";
      panel.style.display = "none";
      if (crEmpty) crEmpty.style.display = "";
      if (crActive) crActive.style.display = "none";
      return;
    }

    empty.style.display = "none";
    panel.style.display = "";
    if (crEmpty) crEmpty.style.display = "none";
    if (crActive) crActive.style.display = "none";
    const current = currentCaptainStep(plan);
    const currentGateBanner = gateBannerCopy(current, { isCurrent: true });
    header.innerHTML = `
      <strong>${escapeHtml(plan.title || "Captain plan")}</strong>
      <div>${escapeHtml(plan.summary || "")}</div>
      <div>Status: ${escapeHtml(plan.status || "active")} · Repo: ${escapeHtml(plan.repo_id || "n/a")}</div>
      ${current && current.gate_label ? `<div data-testid="current-step-gate-label">Gate: ${escapeHtml(current.gate_label)}</div>` : ""}
      ${currentGateBanner ? `<p class="captain-gate-banner" data-testid="captain-step-gate-banner">${escapeHtml(currentGateBanner)}</p>` : ""}
    `;

    stepsEl.innerHTML = (plan.steps || []).map((step) => {
      const isCurrent = current && (step.id === current.id || step.step_id === current.step_id);
      const status = step.status || "queued";
      const classes = ["captain-plan-step-card", isCurrent ? "current" : "", status === "passed" ? "passed" : ""].filter(Boolean).join(" ");
      const links = [];
      if (step.run_id) links.push(`<button type="button" class="btn" data-view-step-run="${escapeHtml(step.run_id)}">View Run</button>`);
      if ((step.evidence_ids || []).length) {
        links.push(`<button type="button" class="btn" data-view-step-evidence="${escapeHtml(step.evidence_ids[0])}">View Evidence</button>`);
      }
      const canComplete = stepCompletionAllowed(step);
      const actionRow = isCurrent && plan.status === "active" ? `
        <div class="captain-plan-step-actions" data-testid="captain-step-actions-${escapeHtml(step.id)}">
          <button type="button" class="btn primary" data-deploy-step-id="${escapeHtml(step.id)}">${escapeHtml(deployStepButtonLabel(plan, step))}</button>
          <button type="button" class="btn good" data-complete-step-id="${escapeHtml(step.id)}" ${canComplete ? "" : "disabled"}>Mark Step Done</button>
          <button type="button" class="btn" data-revise-step-id="${escapeHtml(step.id)}">Revise Step</button>
        </div>
      ` : links.join("");
      const stepGateBanner = gateBannerCopy(step, { isCurrent });
      return `
        <div class="${classes}" data-step-id="${escapeHtml(step.id)}">
          <div class="captain-plan-step-top">
            <h4 class="captain-plan-step-title">${escapeHtml(step.title || step.id)}</h4>
            <span class="status-pill ${status === "passed" ? "status-ready" : isCurrent ? "status-connected" : "status-coming"}">${escapeHtml(status.toUpperCase())}</span>
          </div>
          <p class="captain-plan-step-meta">${escapeHtml(step.agent || "codex_cli")}${step.run_id ? ` · Run ${escapeHtml(step.run_id)}` : ""}${step.gate_label ? ` · ${escapeHtml(step.gate_label)}` : ""}</p>
          ${stepGateBanner && !isCurrent ? `<p class="captain-gate-banner">${escapeHtml(stepGateBanner)}</p>` : ""}
          <p class="captain-plan-step-prompt-preview">${escapeHtml((step.prompt || "").slice(0, 220))}${(step.prompt || "").length > 220 ? "..." : ""}</p>
          ${actionRow}
        </div>
      `;
    }).join("");

    controls.innerHTML = plan.status === "active"
      ? `<button type="button" class="btn bad" id="captain-stop-plan" data-testid="captain-stop-plan">Stop Plan</button>`
      : "";

    stepsEl.querySelectorAll("[data-deploy-step-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const stepId = button.getAttribute("data-deploy-step-id");
        if (stepId) dispatchCaptainStep(stepId).catch((e) => console.error(e));
      });
    });
    stepsEl.querySelectorAll("[data-complete-step-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const stepId = button.getAttribute("data-complete-step-id");
        if (stepId) completeCaptainStep(stepId).catch((e) => console.error(e));
      });
    });
    stepsEl.querySelectorAll("[data-revise-step-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const stepId = button.getAttribute("data-revise-step-id");
        if (stepId) reviseCaptainStep(stepId).catch((e) => console.error(e));
      });
    });
    stepsEl.querySelectorAll("[data-view-step-run]").forEach((button) => {
      button.addEventListener("click", () => {
        const runId = button.getAttribute("data-view-step-run");
        if (runId) openRunDetailModal(runId).catch((e) => console.error(e));
      });
    });
    stepsEl.querySelectorAll("[data-view-step-evidence]").forEach((button) => {
      button.addEventListener("click", () => {
        const evidenceId = button.getAttribute("data-view-step-evidence");
        if (evidenceId) openEvidenceDetailModal(evidenceId).catch((e) => console.error(e));
      });
    });
    const stopBtn = document.getElementById("captain-stop-plan");
    if (stopBtn) {
      stopBtn.addEventListener("click", () => stopCaptainPlan().catch((e) => console.error(e)));
    }

  }

  function deployStepButtonLabel(plan, step) {
    const steps = plan.steps || [];
    const index = steps.findIndex((item) => item.id === step.id);
    const priorPassed = index > 0 && steps.slice(0, index).every((item) => item.status === "passed");
    if (priorPassed && (step.status === "queued" || step.status === "revised")) return "Deploy Next Step";
    return "Deploy Current Step";
  }

  async function loadActiveCaptainPlan() {
    try {
      const data = await requestJson(`${MCH}/captain/plans/recent`);
      const plans = (data.plans || []).map(normalizeCaptainPlan);
      const active = plans.find((plan) => plan.status === "active") || plans[0] || null;
      if (active && active.plan_id) {
        const detail = await requestJson(`${MCH}/captain/plans/${encodeURIComponent(active.plan_id)}`);
        setActiveCaptainPlan(detail.plan || active);
      } else {
        setActiveCaptainPlan(null);
      }
      if (isControlRoomDemoMode() && window.WardenControlRoom && window.WardenControlRoom.refresh) {
        await window.WardenControlRoom.refresh({ quiet: true });
      }
      return active;
    } catch (e) {
      setActiveCaptainPlan(null);
      if (isControlRoomDemoMode() && window.WardenControlRoom && window.WardenControlRoom.refresh) {
        await window.WardenControlRoom.refresh({ quiet: true });
      }
      return null;
    }
  }

  async function dispatchCaptainStep(stepId) {
    const plan = state.activeCaptainPlan;
    if (!plan || !plan.plan_id) return;
    const step = (plan.steps || []).find((item) => item.id === stepId || item.step_id === stepId);
    if (!step) return;
    const result = await requestJson(`${MCH}/captain/plans/${encodeURIComponent(plan.plan_id)}/steps/${encodeURIComponent(stepId)}/dispatch`, {
      method: "POST",
    });
    if (result.plan) setActiveCaptainPlan(result.plan);

    // Blocked path: runner unavailable — show message, don't open monitor
    if (result.blocked) {
      closeCaptainDeckModal();
      const memId = result.memory_id || "";
      const runId = result.run_id || "";
      const noticeEl = document.getElementById("captain-blocked-notice");
      if (noticeEl) {
        noticeEl.innerHTML = `
          <div class="blocked-notice-body">
            <span class="blocked-notice-icon">⊗</span>
            <div>
              <strong>Runner unavailable</strong> — blocked attempt saved to Memory.
              ${runId ? `<span class="blocked-id-pill" title="Copy run ID" onclick="navigator.clipboard.writeText('${escapeHtml(runId)}')">Run: ${escapeHtml(runId.slice(0,20))}</span>` : ""}
              ${memId ? `<span class="blocked-id-pill" title="Copy memory ID" onclick="navigator.clipboard.writeText('${escapeHtml(memId)}')">Mem: ${escapeHtml(memId.slice(0,24))}</span>` : ""}
            </div>
          </div>
          <div class="blocked-notice-actions">
            <button type="button" class="btn" onclick="document.querySelector('[data-section=\\'memory\\']').click()">Ask Memory what happened</button>
            <button type="button" class="btn" onclick="document.querySelector('[data-section=\\'agent\\']').click()">Ask Marius Agent</button>
            <button type="button" class="onboarding-dismiss-btn" onclick="this.closest('.captain-blocked-notice').style.display='none'" title="Dismiss">✕</button>
          </div>`;
        noticeEl.style.display = "";
      }
      await loadMissionWorklog();
      return;
    }

    // Happy path: runner started
    const dispatch = result.dispatch || {};
    state.selectedThreadId = dispatch.session_id || state.selectedThreadId;
    state.activeWardenRunId = dispatch.runner_id || state.activeWardenRunId;
    await Promise.all([loadRecentRuns(), loadMissionWorklog()]);
    closeCaptainDeckModal();
    openLiveCLIMonitor();
    const prompt = dispatch.prompt || step.prompt;
    if (dispatch.session_id && prompt) {
      setTimeout(async () => {
        try {
          await requestJson(`${MCH}/sessions/${encodeURIComponent(dispatch.session_id)}/runner/send-prompt`, {
            method: "POST",
            body: { prompt },
          });
          setQuickReplyStatus("Prompt sent to Codex.");
          await refreshLiveMonitor();
        } catch (e) {
          await refreshLiveMonitor();
        }
      }, 10000);
    }
  }

  async function completeCaptainStep(stepId) {
    const plan = state.activeCaptainPlan;
    if (!plan || !plan.plan_id) return;
    const evidenceIds = state.activeWardenRunId ? [] : [];
    const result = await requestJson(`${MCH}/captain/plans/${encodeURIComponent(plan.plan_id)}/steps/${encodeURIComponent(stepId)}/complete`, {
      method: "POST",
      body: { evidence_ids: evidenceIds },
    });
    if (result.plan) setActiveCaptainPlan(result.plan);
    await loadMissionWorklog();
  }

  async function reviseCaptainStep(stepId) {
    const plan = state.activeCaptainPlan;
    if (!plan || !plan.plan_id) return;
    const step = (plan.steps || []).find((item) => item.id === stepId || item.step_id === stepId);
    if (!step) return;
    const revisedPrompt = window.prompt("Revise step prompt:", step.prompt || "");
    if (revisedPrompt === null) return;
    const result = await requestJson(`${MCH}/captain/plans/${encodeURIComponent(plan.plan_id)}/steps/${encodeURIComponent(stepId)}/revise`, {
      method: "POST",
      body: { prompt: revisedPrompt, note: "Operator revised the step prompt." },
    });
    if (result.plan) setActiveCaptainPlan(result.plan);
    await loadMissionWorklog();
  }

  async function stopCaptainPlan() {
    const plan = state.activeCaptainPlan;
    if (!plan || !plan.plan_id) return;
    const result = await requestJson(`${MCH}/captain/plans/${encodeURIComponent(plan.plan_id)}/stop`, {
      method: "POST",
      body: { note: "Operator stopped the Captain plan." },
    });
    if (result.plan) setActiveCaptainPlan(result.plan);
    await loadMissionWorklog();
  }

  function renderSettingsPanel() {
    const deck = state.captainDeck;
    const health = state.health || {};
    const captainStatus = document.getElementById("settings-captain-status");
    const captainModel = document.getElementById("settings-captain-model");
    const captainKeySource = document.getElementById("settings-captain-key-source");
    const agentNote = document.getElementById("settings-agent-note");
    const publicRunner = document.getElementById("settings-public-runner");
    const privateRunner = document.getElementById("settings-private-runner");
    const shellInput = document.getElementById("settings-shell-input");
    const agentRegistration = document.getElementById("settings-agent-registration");
    const heroCaptain = document.getElementById("hero-captain-status");
    const heroCodex = document.getElementById("hero-codex-status");
    const heroJules = document.getElementById("hero-jules-status");
    const crPublic = document.getElementById("cr-public-runner");
    const crPrivate = document.getElementById("cr-private-runner");
    const crShell = document.getElementById("cr-shell-input");
    const crAgentReg = document.getElementById("cr-agent-registration");
    const settingsCodex = document.getElementById("settings-codex-status");
    const settingsJules = document.getElementById("settings-jules-status");
    const inspectorNextMove = document.getElementById("inspector-next-move-copy");
    const inspectorCaptain = document.getElementById("inspector-captain-agent");
    const inspectorCodex = document.getElementById("inspector-codex-agent");
    const inspectorJules = document.getElementById("inspector-jules-agent");
    const useCodexDirectly = document.getElementById("use-codex-directly");
    const inspectorViewCodex = document.getElementById("inspector-view-codex");
    const runnerActive = !!health.tmux_runner_enabled && !!health.codex_runner_enabled;
    const shellDisabled = !health.arbitrary_command_execution_enabled;
    const publicRunnerText = "Public runner — Off";
    const privateRunnerText = runnerActive ? "Private runner — On" : "Private runner — Off";
    const shellText = shellDisabled ? "Shell access — Restricted" : "Shell access — Enabled";
    const agentRegText = state.registryWriteEnabled ? "Agent registration — On" : "Agent registration — Private";
    if (captainStatus) {
      captainStatus.textContent = deck.configured
        ? `Captain · Configured · ${deck.model || "openrouter/auto"}`
        : "Captain · Not configured";
    }
    if (captainModel) captainModel.textContent = "";
    if (captainKeySource) {
      captainKeySource.textContent = deck.keySource && deck.keySource !== "missing" ? `Key · ${deck.keySource}` : "";
    }
    if (agentNote) {
      agentNote.textContent = state.registryWriteEnabled ? "Registration enabled." : "Registration on private service.";
    }
    if (publicRunner) publicRunner.textContent = publicRunnerText;
    if (privateRunner) privateRunner.textContent = privateRunnerText;
    if (shellInput) shellInput.textContent = shellText;
    if (agentRegistration) agentRegistration.textContent = agentRegText;
    if (heroCaptain) {
      heroCaptain.textContent = `Captain · ${deck.configured ? "Ready" : "—"}`;
    }
    if (heroCodex) heroCodex.textContent = "";
    if (heroJules) heroJules.textContent = "";
    if (settingsCodex) {
      settingsCodex.textContent = runnerActive ? "Codex · Ready" : "Codex · Off";
    }
    if (settingsJules) {
      const jules = (state.agents || []).find((agent) => agent.adapter === "jules_remote" && agent.user_created);
      if (!jules) settingsJules.textContent = "Jules · —";
      else if (jules.connection_status === "connected" && jules.status === "ready") settingsJules.textContent = "Jules · Connected";
      else settingsJules.textContent = "Jules · Setup";
    }
    if (crPublic) crPublic.textContent = "Public runner — Off";
    if (crPrivate) crPrivate.textContent = runnerActive ? "Private runner — On" : "Private runner — Off";
    if (crShell) crShell.textContent = shellDisabled ? "Shell access — Restricted" : "Shell access — Enabled";
    if (crAgentReg) crAgentReg.textContent = agentRegText;
    const codexAgent = (state.agents || []).find((agent) => agent.id === "codex_cli");
    const codexReady = !!(codexAgent && codexAgent.runnable);
    const codexChecked = codexAgent && codexAgent.last_checked_at
      ? ` · ${formatHistoryTimestamp(codexAgent.last_checked_at)}`
      : state.agentStatusLastChecked
        ? ` · ${formatHistoryTimestamp(state.agentStatusLastChecked)}`
        : "";
    if (inspectorCaptain) {
      inspectorCaptain.textContent = `Captain — Orchestrator · ${deck.configured ? "Configured" : "Not configured"}`;
    }
    if (inspectorCodex) {
      inspectorCodex.textContent = `Codex CLI — CLI Agent · ${codexReady ? "Ready" : "Disabled"}${codexChecked}`;
    }
    if (inspectorJules) {
      const julesChecked = (state.agents || []).find((agent) => agent.adapter === "jules_remote" && agent.user_created);
      const suffix = julesChecked && julesChecked.last_checked_at ? ` · ${formatHistoryTimestamp(julesChecked.last_checked_at)}` : "";
      inspectorJules.textContent = `Jules Remote — Remote · Planning only · ${julesInspectorStatus()}${suffix}`;
    }
    if (useCodexDirectly) useCodexDirectly.style.display = runnerActive ? "" : "none";
    if (inspectorViewCodex) inspectorViewCodex.style.display = runnerActive ? "" : "none";
    if (inspectorNextMove) {
      if (!runnerActive) {
        inspectorNextMove.textContent = "Private runner is unavailable on this service.";
      } else if (!deck.configured) {
        inspectorNextMove.textContent = "Configure Captain before planning work.";
      } else {
        inspectorNextMove.textContent = "Create a plan, then dispatch the first bounded step to Codex.";
      }
    }
    updateRunsEvidenceActions();
  }

  function setActiveSection(sectionId) {
    state.activeSection = sectionId || "mission";
    document.querySelectorAll(".workspace-section").forEach((section) => {
      section.classList.toggle("active", section.dataset.section === state.activeSection);
    });
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.section === state.activeSection);
    });
    const inspector = document.getElementById("operator-inspector");
    const showInspector = (state.activeSection === "mission" || state.activeSection === "agents") && state.activeSection !== "projects";
    if (inspector) inspector.style.display = showInspector ? "" : "none";
    const stage = document.querySelector(".warden-stage");
    if (stage) stage.classList.toggle("inspector-visible", showInspector);
    const titles = {
      mission: "Control Room",
      tasks: "Missions",
      agents: "Agents",
      runs: "Runs",
      evidence: "Evidence",
      memory: "Memory",
      "proof-gates": "Proof Gates",
      "runner-sessions": "Runner Sessions",
      settings: "Settings",
      projects: "Projects",
    };
    const topTitle = document.getElementById("topbar-page-title");
    if (topTitle) topTitle.textContent = titles[state.activeSection] || "Warden";
    if (window.WardenControlRoom && window.WardenControlRoom.onSectionChange) {
      window.WardenControlRoom.onSectionChange(state.activeSection);
    }
    if (state.activeSection === "mission") {
      Promise.all([loadActiveCaptainPlan(), loadMissionWorklog()]).catch((e) => console.error(e));
      if (window.WardenControlRoom && window.WardenControlRoom.isInitialized && window.WardenControlRoom.isInitialized() && window.WardenControlRoom.refresh) {
        window.WardenControlRoom.refresh({ quiet: true }).catch((e) => console.error(e));
      }
    } else if (state.activeSection === "runs") {
      loadRecentRuns().catch((e) => console.error(e));
    } else if (state.activeSection === "evidence") {
      loadRecentEvidence().catch((e) => console.error(e));
    } else if (state.activeSection === "memory") {
      loadMemory().catch((e) => console.error(e));
    } else if (state.activeSection === "settings") {
      loadConnectorsProviders().catch((e) => console.error(e));
      loadMailTestAccountOptions().catch((e) => console.error(e));
    }
  }

  async function loadMailTestAccountOptions() {
    const select = document.getElementById("mail-test-account");
    if (!select) return;
    try {
      const data = await requestJson(`${MCH}/warden/mail/accounts`);
      const accounts = (data && data.accounts) || [];
      select.innerHTML = accounts.length
        ? '<option value="">— select account —</option>' + accounts.map((a) =>
            `<option value="${escapeHtml(a.account_id)}">${escapeHtml(a.display_email || a.account_id)} (${escapeHtml(a.provider)})</option>`
          ).join("")
        : '<option value="">No mail accounts connected</option>';
    } catch (e) {
      select.innerHTML = '<option value="">Could not load accounts</option>';
    }
  }

  async function loadBrainVaultSettings() {
    const statusEl = document.getElementById("brain-vault-status");
    const metaEl = document.getElementById("brain-vault-meta");
    const mirrorEl = document.getElementById("brain-mirror-status");
    if (!statusEl) return;
    try {
      const data = await requestJson(`${MCH}/warden/brain/health`);
      const local = data.local || {};
      if (local.vault_exists) {
        statusEl.innerHTML = `<span class="cc-dot cc-dot-good" style="display:inline-block;margin-right:6px;"></span>Ready — ${local.source_count || 0} source${local.source_count === 1 ? "" : "s"} indexed`;
      } else {
        statusEl.innerHTML = `<span class="cc-dot cc-dot-warn" style="display:inline-block;margin-right:6px;"></span>Not initialized`;
      }
      if (metaEl) metaEl.textContent = local.vault_path ? `Vault: ${local.vault_path}` : "";
      if (mirrorEl) {
        mirrorEl.innerHTML = data.hybrid_enabled
          ? `<span class="cc-dot cc-dot-good" style="display:inline-block;margin-right:6px;"></span>Enabled`
          : `<span class="cc-dot" style="display:inline-block;margin-right:6px;"></span>Not enabled`;
      }
    } catch (e) {
      statusEl.textContent = "Could not reach Brain service.";
    }
  }

  function wireBrainVaultSettings() {
    const initBtn = document.getElementById("brain-vault-init-btn");
    const reindexBtn = document.getElementById("brain-vault-reindex-btn");
    const actionStatus = document.getElementById("brain-vault-action-status");
    if (initBtn) initBtn.addEventListener("click", async () => {
      initBtn.disabled = true;
      if (actionStatus) actionStatus.textContent = "Initializing…";
      try {
        await requestJson(`${MCH}/warden/brain/init-vault`, { method: "POST" });
        if (actionStatus) actionStatus.textContent = "Vault initialized.";
        await loadBrainVaultSettings();
      } catch (e) {
        if (actionStatus) actionStatus.textContent = `Error: ${e.message}`;
      } finally {
        initBtn.disabled = false;
      }
    });
    if (reindexBtn) reindexBtn.addEventListener("click", async () => {
      reindexBtn.disabled = true;
      if (actionStatus) actionStatus.textContent = "Reindexing…";
      try {
        const res = await requestJson(`${MCH}/warden/brain/reindex`, { method: "POST" });
        if (actionStatus) actionStatus.textContent = `Reindexed ${res.indexed || 0} source(s).`;
        await loadBrainVaultSettings();
      } catch (e) {
        if (actionStatus) actionStatus.textContent = `Error: ${e.message}`;
      } finally {
        reindexBtn.disabled = false;
      }
    });
  }

  async function saveMailToBrain(btn, { accountId, messageId, subject, fromAddr, bodyText }) {
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Saving…";
    try {
      await requestJson(`${MCH}/warden/brain/ingest`, {
        method: "POST",
        body: {
          url: `mail://${accountId}/${messageId}`,
          title: subject || "(no subject)",
          source_type: "webpage",
          content_text: bodyText || `From: ${fromAddr || "unknown"}\n\n(subject only — open the message to save its body)`,
          tags: ["mail"],
        },
      });
      btn.textContent = "Saved to Brain ✓";
    } catch (e) {
      btn.textContent = "Save failed";
      setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
      return;
    }
  }

  function wireMailTestPanel() {
    const searchBtn = document.getElementById("mail-test-search-btn");
    if (!searchBtn) return;
    searchBtn.addEventListener("click", async () => {
      const accountId = (document.getElementById("mail-test-account") || {}).value || "";
      const query = ((document.getElementById("mail-test-query") || {}).value || "").trim();
      const resultsEl = document.getElementById("mail-test-results");
      if (!accountId) { if (resultsEl) { resultsEl.style.display = ""; resultsEl.innerHTML = '<p class="connectors-empty">Select an account first.</p>'; } return; }
      searchBtn.disabled = true;
      searchBtn.textContent = "Searching…";
      if (resultsEl) resultsEl.style.display = "none";
      try {
        const params = new URLSearchParams({account_id: accountId, q: query || "ALL", limit: "10"});
        const data = await requestJson(`${MCH}/warden/mail/search?${params}`);
        const messages = data.messages || [];
        if (resultsEl) {
          resultsEl.style.display = "";
          if (!messages.length) {
            resultsEl.innerHTML = '<p class="connectors-empty">No messages found.</p>';
          } else {
            resultsEl.innerHTML = `<p class="connector-provider-note">${messages.length} result${messages.length !== 1 ? "s" : ""}</p>` +
              messages.map((m) => `<div class="mail-result-card" data-message-id="${escapeHtml(m.id)}" data-account-id="${escapeHtml(m.account_id)}">
                <div class="mail-result-top">
                  <strong class="mail-result-subject">${escapeHtml(m.subject || "(no subject)")}</strong>
                  <span class="mail-result-date">${escapeHtml(m.date || "")}</span>
                </div>
                <div class="mail-result-from">From: ${escapeHtml(m.from_addr || "")}</div>
                <div class="mail-result-snippet">${escapeHtml(m.snippet || "")}</div>
                <div class="mail-result-actions" style="display:flex;gap:6px;margin-top:4px;flex-wrap:wrap;">
                  <button type="button" class="btn mail-read-btn" style="font-size:0.75rem;"
                    data-msg-id="${escapeHtml(m.id)}" data-acc-id="${escapeHtml(m.account_id)}">Read</button>
                  <button type="button" class="btn mail-save-brain-btn" style="font-size:0.75rem;"
                    data-msg-id="${escapeHtml(m.id)}" data-acc-id="${escapeHtml(m.account_id)}"
                    data-subject="${escapeHtml(m.subject || "")}" data-from="${escapeHtml(m.from_addr || "")}">Save to Brain</button>
                  <button type="button" class="btn mail-ask-marius-btn" style="font-size:0.75rem;"
                    data-subject="${escapeHtml(m.subject || "")}">Ask Marius</button>
                </div>
                <div class="mail-read-body" style="display:none;"></div>
              </div>`).join("");
            // Wire read buttons
            resultsEl.querySelectorAll(".mail-read-btn").forEach((btn) => {
              btn.addEventListener("click", async () => {
                const msgId = btn.getAttribute("data-msg-id");
                const accId = btn.getAttribute("data-acc-id");
                const bodyEl = btn.closest(".mail-result-card").querySelector(".mail-read-body");
                btn.disabled = true;
                btn.textContent = "Loading…";
                try {
                  const msgData = await requestJson(`${MCH}/warden/mail/messages/${encodeURIComponent(accId)}/${encodeURIComponent(msgId)}`);
                  const body = (msgData.message && msgData.message.body_text) || "(empty body)";
                  if (bodyEl) {
                    bodyEl.style.display = "";
                    bodyEl.textContent = body.slice(0, 2000) + (body.length > 2000 ? "\n…[truncated]" : "");
                    bodyEl.dataset.fullBody = body;
                  }
                  btn.style.display = "none";
                } catch (e) {
                  if (bodyEl) { bodyEl.style.display = ""; bodyEl.textContent = `Error: ${e.message}`; }
                  btn.textContent = "Read";
                  btn.disabled = false;
                }
              });
            });
            // Wire save-to-brain buttons
            resultsEl.querySelectorAll(".mail-save-brain-btn").forEach((btn) => {
              btn.addEventListener("click", () => {
                const card = btn.closest(".mail-result-card");
                const bodyEl = card ? card.querySelector(".mail-read-body") : null;
                saveMailToBrain(btn, {
                  accountId: btn.getAttribute("data-acc-id"),
                  messageId: btn.getAttribute("data-msg-id"),
                  subject: btn.getAttribute("data-subject"),
                  fromAddr: btn.getAttribute("data-from"),
                  bodyText: bodyEl ? bodyEl.dataset.fullBody : "",
                });
              });
            });
            // Wire ask-marius buttons
            resultsEl.querySelectorAll(".mail-ask-marius-btn").forEach((btn) => {
              btn.addEventListener("click", () => {
                setActiveSection("mission");
                ccAskMariusAbout(btn.getAttribute("data-subject") || "this email");
              });
            });
          }
        }
      } catch (e) {
        if (resultsEl) { resultsEl.style.display = ""; resultsEl.innerHTML = `<p class="connectors-empty">Error: ${e.message}</p>`; }
      } finally {
        searchBtn.disabled = false;
        searchBtn.textContent = "Search Mail";
      }
    });
  }

  // Listen for postMessage from OAuth popup — refresh connectors immediately
  window.addEventListener("message", (evt) => {
    if (evt.data && evt.data.type === "warden_connector_connected") {
      loadConnectorsProviders().catch(() => {});
    }
  });

  async function loadConnectorsProviders() {
    const listEl = document.getElementById("connectors-provider-list");
    if (!listEl) return;
    try {
      const [provData, accData] = await Promise.all([
        requestJson(`${MCH}/warden/connectors/providers`),
        requestJson(`${MCH}/warden/connectors/accounts`),
      ]);
      const providers = (provData && provData.providers) || [];
      const accounts = (accData && accData.accounts) || [];

      if (!providers.length) {
        listEl.innerHTML = '<p class="connectors-empty">No connector providers registered.</p>';
        return;
      }

      // Index connected accounts by provider
      const connectedByProvider = {};
      accounts.forEach((a) => {
        if (!connectedByProvider[a.provider]) connectedByProvider[a.provider] = [];
        connectedByProvider[a.provider].push(a);
      });

      listEl.innerHTML = providers.map((p) => {
        const caps = (p.capabilities || []).join(", ") || "—";
        const connected = connectedByProvider[p.provider_id] || [];
        const isConnected = connected.length > 0;
        const configuredClass = isConnected ? "connector-configured" : (p.configured ? "connector-ready" : "connector-unconfigured");
        const statusLabel = isConnected ? `${connected.length} account${connected.length > 1 ? "s" : ""} connected` : (p.configured ? "Ready to connect" : "Setup required");
        const statusPillClass = isConnected ? "status-connected" : (p.configured ? "status-ready" : "status-coming");

        // Connected accounts rows
        const accountsHtml = connected.map((a) => `
          <div class="connector-account-row" data-account-id="${escapeHtml(a.account_id)}">
            <span class="connector-account-email">${escapeHtml(a.display_email || a.account_id)}</span>
            <span class="status-pill status-connected" style="font-size:0.72rem;">Connected</span>
            <button type="button" class="btn connector-disconnect-btn"
              data-disconnect-id="${escapeHtml(a.account_id)}" style="font-size:0.75rem;padding:2px 8px;">Disconnect</button>
          </div>`).join("");

        // Connect action area
        let connectAction = "";
        if (p.provider_id === "gmail" && !isConnected) {
          // Gmail primary path: App Password (IMAP), no OAuth required
          const guideUrl = "https://console.cloud.google.com/apis/credentials";
          const redirectUri = `${location.origin}/api/mcharness/warden/connectors/gmail/callback`;
          connectAction = `
            <div class="connector-icloud-form" data-provider="gmail">
              <p class="connector-provider-note">
                Connect Gmail using a <strong>Google App Password</strong> — no OAuth verification needed.
                <a href="#" class="connector-icloud-help-toggle" style="font-size:.8rem;">How to create one</a>
              </p>
              <div class="connector-icloud-help" style="display:none;">
                <ol style="margin:.5rem 0 .5rem 1.2rem;padding:0;font-size:.85rem;color:var(--text-secondary);">
                  <li>Go to <a href="https://myaccount.google.com/security" target="_blank" rel="noopener">Google Account → Security</a></li>
                  <li>Enable <strong>2-Step Verification</strong> if not already on</li>
                  <li>Search for <strong>App passwords</strong> at the top of Google Account</li>
                  <li>Create a new app password — name it "Warden"</li>
                  <li>Copy the 16-character password (no spaces needed)</li>
                </ol>
                <p style="font-size:.8rem;color:var(--text-secondary);">
                  Note: Some Google Workspace or Advanced Protection accounts may block IMAP or app passwords.
                  Also confirm IMAP is enabled in Gmail → Settings → Forwarding and POP/IMAP.
                </p>
              </div>
              <div class="connector-form-row">
                <label class="connector-label">Gmail Address</label>
                <input type="email" class="connector-input" placeholder="you@gmail.com"
                  id="gmail-imap-email-input" autocomplete="email" />
              </div>
              <div class="connector-form-row">
                <label class="connector-label">Google App Password</label>
                <input type="password" class="connector-input" placeholder="16-character app password"
                  id="gmail-imap-pass-input" autocomplete="off" spellcheck="false" />
              </div>
              <div class="connector-setup-actions">
                <button type="button" class="btn primary connector-gmail-imap-submit-btn">
                  Connect Gmail
                </button>
                <span class="connector-setup-note">App password stored locally only. Never sent anywhere.</span>
              </div>
              <div class="connector-icloud-status" id="gmail-imap-connect-status"></div>
            </div>
            <details class="connector-advanced-details" style="margin-top:.5rem;">
              <summary style="font-size:.8rem;color:var(--text-secondary);cursor:pointer;">Advanced setup / OAuth</summary>
              <div class="connector-advanced-body" style="font-size:.82rem;color:var(--text-secondary);padding:.5rem 0;">
                <p>OAuth is optional and may require Google app verification.<br>App Password is simpler for local/private Warden.</p>
                ${p.configured ? `
                  <button type="button" class="btn primary connector-oauth-btn"
                    data-provider="gmail" style="margin-top:.4rem;">Sign in with Google (OAuth)</button>
                  <a href="#" class="connector-popup-fallback" style="display:none;" data-provider="gmail">Open sign-in page</a>
                  <br><button type="button" class="btn connector-clear-config-btn"
                    data-provider="gmail" style="font-size:.8rem;padding:2px 8px;margin-top:.4rem;">Clear OAuth app config</button>
                ` : `
                  <details class="connector-setup-wizard" data-provider="gmail" style="margin-top:.4rem;">
                    <summary class="connector-setup-summary" style="font-size:.82rem;">Set up OAuth app (advanced)</summary>
                    <div class="connector-setup-body">
                      <p>Create at <a href="${escapeHtml(guideUrl)}" target="_blank" rel="noopener">Google Cloud Console</a></p>
                      <p><strong>Redirect URI:</strong></p>
                      <div class="connector-redirect-row">
                        <code class="connector-redirect-uri">${escapeHtml(redirectUri)}</code>
                        <button type="button" class="btn connector-copy-uri-btn" data-uri="${escapeHtml(redirectUri)}">Copy</button>
                      </div>
                      <div class="connector-form-row">
                        <label class="connector-label">Client ID</label>
                        <input type="text" class="connector-input connector-client-id-input"
                          placeholder="Paste Client ID" autocomplete="off" spellcheck="false" />
                      </div>
                      <div class="connector-form-row">
                        <label class="connector-label">Client Secret</label>
                        <input type="password" class="connector-input connector-client-secret-input"
                          placeholder="Paste Client Secret" autocomplete="off" spellcheck="false" />
                      </div>
                      <div class="connector-setup-actions">
                        <button type="button" class="btn primary connector-save-config-btn"
                          data-provider="gmail">Save OAuth config</button>
                        <span class="connector-setup-note">Saved to local vault only.</span>
                      </div>
                      <div class="connector-setup-status" id="setup-status-gmail"></div>
                    </div>
                  </details>`}
              </div>
            </details>`;
        } else if (p.auth_type === "oauth2_authorization_code" && p.provider_id !== "gmail") {
          const connectBtnLabel = p.display_name.includes("Outlook") ? "Sign in with Microsoft"
            : `Connect ${p.display_name}`;
          const signInNote = "Warden stores read-only access locally. Your Microsoft password is never shared.";

          if (!p.configured) {
            const guideUrl = "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps";
            const redirectUri = `${location.origin}/api/mcharness/warden/connectors/${p.provider_id}/callback`;
            connectAction = `
              <details class="connector-setup-wizard" data-provider="${escapeHtml(p.provider_id)}">
                <summary class="connector-setup-summary">
                  <span class="connector-setup-icon">&#9881;</span> Set up ${escapeHtml(p.display_name)} connection
                </summary>
                <div class="connector-setup-body">
                  <p class="connector-setup-desc">
                    Warden needs a free OAuth app.
                    Register one at <a href="${escapeHtml(guideUrl)}" target="_blank" rel="noopener">Azure App Registrations</a> (free).
                  </p>
                  <p class="connector-setup-step"><strong>Redirect URI</strong> to add in the OAuth app:</p>
                  <div class="connector-redirect-row">
                    <code class="connector-redirect-uri">${escapeHtml(redirectUri)}</code>
                    <button type="button" class="btn connector-copy-uri-btn" data-uri="${escapeHtml(redirectUri)}">Copy</button>
                  </div>
                  <div class="connector-form-row">
                    <label class="connector-label">Client ID</label>
                    <input type="text" class="connector-input connector-client-id-input"
                      placeholder="Paste your Client ID here" autocomplete="off" spellcheck="false" />
                  </div>
                  <div class="connector-form-row">
                    <label class="connector-label">Client Secret</label>
                    <input type="password" class="connector-input connector-client-secret-input"
                      placeholder="Paste your Client Secret here" autocomplete="off" spellcheck="false" />
                  </div>
                  <div class="connector-setup-actions">
                    <button type="button" class="btn primary connector-save-config-btn"
                      data-provider="${escapeHtml(p.provider_id)}">Save and activate</button>
                    <span class="connector-setup-note">Saved to local vault only. Never sent to any server.</span>
                  </div>
                  <div class="connector-setup-status" id="setup-status-${escapeHtml(p.provider_id)}"></div>
                </div>
              </details>`;
          } else {
            connectAction = `
              <p class="connector-signin-note">${escapeHtml(signInNote)}</p>
              <button type="button" class="btn primary connector-oauth-btn"
                data-provider="${escapeHtml(p.provider_id)}">${escapeHtml(connectBtnLabel)}</button>
              <a href="#" class="connector-popup-fallback" style="display:none;"
                data-provider="${escapeHtml(p.provider_id)}">Open sign-in page</a>
              <details class="connector-advanced-details">
                <summary>Advanced setup</summary>
                <div class="connector-advanced-body">
                  <p>OAuth app configured. <button type="button" class="btn connector-clear-config-btn"
                    data-provider="${escapeHtml(p.provider_id)}" style="font-size:.8rem;padding:2px 8px;">Clear app config</button></p>
                </div>
              </details>`;
          }
        } else if (p.auth_type === "app_password") {
          if (!isConnected) {
            connectAction = `
              <div class="connector-icloud-form" data-provider="icloud">
                <p class="connector-provider-note">
                  Enter your iCloud email and an
                  <a href="https://appleid.apple.com/account/manage/section/security" target="_blank" rel="noopener">app-specific password</a>
                  (not your main Apple password).
                  <a href="#" class="connector-icloud-help-toggle" style="font-size:.8rem;">How to create one</a>
                </p>
                <div class="connector-icloud-help" style="display:none;">
                  <ol style="margin:.5rem 0 .5rem 1.2rem;padding:0;font-size:.85rem;color:var(--text-secondary);">
                    <li>Go to <a href="https://appleid.apple.com" target="_blank" rel="noopener">appleid.apple.com</a></li>
                    <li>Sign in → Sign-In and Security → App-Specific Passwords</li>
                    <li>Click + and name it "Warden"</li>
                    <li>Copy the password shown (xxxx-xxxx-xxxx-xxxx)</li>
                  </ol>
                </div>
                <div class="connector-form-row">
                  <label class="connector-label">iCloud Email</label>
                  <input type="email" class="connector-input" placeholder="your@icloud.com or me.com"
                    id="icloud-email-input" autocomplete="email" />
                </div>
                <div class="connector-form-row">
                  <label class="connector-label">App-Specific Password</label>
                  <input type="password" class="connector-input" placeholder="xxxx-xxxx-xxxx-xxxx"
                    id="icloud-pass-input" autocomplete="off" spellcheck="false" />
                </div>
                <div class="connector-setup-actions">
                  <button type="button" class="btn primary connector-icloud-submit-btn">
                    Connect iCloud Mail
                  </button>
                  <span class="connector-setup-note">Password stored locally only. Never sent anywhere.</span>
                </div>
                <div class="connector-icloud-status" id="icloud-connect-status"></div>
              </div>`;
          }
        }

        return `<div class="connector-provider-card ${configuredClass}" data-provider-id="${escapeHtml(p.provider_id)}">
          <div class="connector-provider-top">
            <strong class="connector-provider-name">${escapeHtml(p.display_name)}</strong>
            <span class="connector-status-pill ${statusPillClass}">${escapeHtml(statusLabel)}</span>
          </div>
          <div class="connector-provider-meta">
            <span>Capabilities: ${escapeHtml(caps)}</span>
          </div>
          ${accountsHtml ? `<div class="connector-accounts-list">${accountsHtml}</div>` : ""}
          <div class="connector-action-area">${connectAction}</div>
        </div>`;
      }).join("");

      // Wire "Copy redirect URI" buttons
      listEl.querySelectorAll(".connector-copy-uri-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const uri = btn.getAttribute("data-uri");
          if (uri && navigator.clipboard) {
            navigator.clipboard.writeText(uri).then(() => {
              btn.textContent = "Copied!";
              setTimeout(() => { btn.textContent = "Copy"; }, 2000);
            });
          }
        });
      });

      // Wire "Save and activate" (provider OAuth config) buttons
      listEl.querySelectorAll(".connector-save-config-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const provider = btn.getAttribute("data-provider");
          const wizard = btn.closest(".connector-setup-wizard");
          const clientIdInput = wizard ? wizard.querySelector(".connector-client-id-input") : null;
          const clientSecretInput = wizard ? wizard.querySelector(".connector-client-secret-input") : null;
          const statusEl = document.getElementById(`setup-status-${provider}`);

          const clientId = (clientIdInput && clientIdInput.value.trim()) || "";
          const clientSecret = (clientSecretInput && clientSecretInput.value.trim()) || "";

          if (!clientId || !clientSecret) {
            if (statusEl) statusEl.textContent = "Both Client ID and Client Secret are required.";
            return;
          }
          btn.disabled = true;
          btn.textContent = "Saving…";
          try {
            const result = await requestJson(`${MCH}/warden/connectors/${encodeURIComponent(provider)}/config`, {
              method: "POST",
              body: JSON.stringify({client_id: clientId, client_secret: clientSecret}),
            });
            if (result.ok) {
              if (clientSecretInput) clientSecretInput.value = "";  // clear secret from DOM
              await loadConnectorsProviders();
            } else {
              if (statusEl) statusEl.textContent = result.detail || "Save failed.";
              btn.disabled = false;
              btn.textContent = "Save and activate";
            }
          } catch (e) {
            if (statusEl) statusEl.textContent = `Error: ${e.message}`;
            btn.disabled = false;
            btn.textContent = "Save and activate";
          }
        });
      });

      // Wire "Clear app config" buttons
      listEl.querySelectorAll(".connector-clear-config-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const provider = btn.getAttribute("data-provider");
          if (!confirm(`Remove the saved ${provider} OAuth app config? You will need to re-enter the credentials to reconnect.`)) return;
          btn.disabled = true;
          try {
            await requestJson(`${MCH}/warden/connectors/${encodeURIComponent(provider)}/config`, {method: "DELETE"});
            await loadConnectorsProviders();
          } catch (e) {
            btn.disabled = false;
          }
        });
      });

      // Wire OAuth connect buttons
      listEl.querySelectorAll(".connector-oauth-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const provider = btn.getAttribute("data-provider");
          btn.disabled = true;
          btn.textContent = "Opening…";
          try {
            const result = await requestJson(`${MCH}/warden/connectors/${encodeURIComponent(provider)}/connect/start`, {method: "POST"});
            if (result.auth_url) {
              const popup = window.open(result.auth_url, "warden_oauth", "width=560,height=760");
              // Show fallback link for popup blockers
              const fallbackLink = btn.parentElement.querySelector(".connector-popup-fallback");
              if (fallbackLink) {
                fallbackLink.href = result.auth_url;
                fallbackLink.style.display = "";
              }
              const displayName = provider.charAt(0).toUpperCase() + provider.slice(1);
              btn.textContent = `Sign in with ${displayName}`;
              btn.disabled = false;
              // Poll in case postMessage doesn't fire (popup blocked/cross-origin)
              const pollTimer = setInterval(async () => {
                if (popup && popup.closed) {
                  clearInterval(pollTimer);
                  await loadConnectorsProviders();
                }
              }, 800);
            } else {
              btn.textContent = "Setup required — see above";
              btn.disabled = false;
            }
          } catch (e) {
            btn.textContent = `Error: ${e.message}`;
            btn.disabled = false;
          }
        });
      });

      // Wire iCloud help toggle
      listEl.querySelectorAll(".connector-icloud-help-toggle").forEach((link) => {
        link.addEventListener("click", (e) => {
          e.preventDefault();
          const help = link.closest(".connector-icloud-form").querySelector(".connector-icloud-help");
          if (help) {
            const hidden = help.style.display === "none";
            help.style.display = hidden ? "" : "none";
            link.textContent = hidden ? "Hide instructions" : "How to create one";
          }
        });
      });

      // Wire iCloud submit buttons
      listEl.querySelectorAll(".connector-icloud-submit-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const form = btn.closest(".connector-icloud-form");
          const emailInput = form ? form.querySelector("#icloud-email-input") : null;
          const passInput = form ? form.querySelector("#icloud-pass-input") : null;
          const statusEl = form ? form.querySelector("#icloud-connect-status") : null;

          const email = (emailInput && emailInput.value.trim()) || "";
          const appPassword = (passInput && passInput.value.trim()) || "";

          if (!email || !appPassword) {
            if (statusEl) statusEl.textContent = "Email and app-specific password are required.";
            return;
          }
          btn.disabled = true;
          if (statusEl) statusEl.textContent = "Connecting…";
          try {
            const result = await requestJson(`${MCH}/warden/connectors/icloud/connect/app-password`, {
              method: "POST",
              body: JSON.stringify({email, app_password: appPassword}),
            });
            if (result.ok) {
              if (passInput) passInput.value = "";  // clear password from DOM immediately
              if (statusEl) statusEl.textContent = "";
              await loadConnectorsProviders();
            } else {
              if (statusEl) statusEl.textContent = result.detail || "Connection failed.";
              btn.disabled = false;
            }
          } catch (e) {
            if (statusEl) statusEl.textContent = `Error: ${e.message}`;
            btn.disabled = false;
          }
        });
      });

      // Wire Gmail IMAP submit buttons
      listEl.querySelectorAll(".connector-gmail-imap-submit-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const form = btn.closest(".connector-icloud-form[data-provider='gmail']");
          const emailInput = form ? form.querySelector("#gmail-imap-email-input") : null;
          const passInput = form ? form.querySelector("#gmail-imap-pass-input") : null;
          const statusEl = form ? form.querySelector("#gmail-imap-connect-status") : null;

          const email = (emailInput && emailInput.value.trim()) || "";
          const appPassword = (passInput && passInput.value.trim()) || "";

          if (!email || !appPassword) {
            if (statusEl) statusEl.textContent = "Gmail address and app password are required.";
            return;
          }
          btn.disabled = true;
          if (statusEl) statusEl.textContent = "Connecting…";
          try {
            const result = await requestJson(`${MCH}/warden/connectors/gmail/connect/app-password`, {
              method: "POST",
              body: JSON.stringify({email, app_password: appPassword}),
            });
            if (passInput) passInput.value = "";  // clear app password from DOM immediately
            if (result.ok) {
              if (statusEl) statusEl.textContent = "";
              await loadConnectorsProviders();
            } else {
              if (statusEl) statusEl.textContent = result.detail || result.note || "Connection failed.";
              btn.disabled = false;
            }
          } catch (e) {
            if (passInput) passInput.value = "";  // clear even on error
            if (statusEl) statusEl.textContent = `Error: ${e.message}`;
            btn.disabled = false;
          }
        });
      });

      // Wire disconnect buttons
      listEl.querySelectorAll(".connector-disconnect-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const accountId = btn.getAttribute("data-disconnect-id");
          if (!accountId) return;
          btn.disabled = true;
          btn.textContent = "Disconnecting…";
          try {
            await requestJson(`${MCH}/warden/connectors/accounts/${encodeURIComponent(accountId)}/disconnect`, {method: "POST"});
            await loadConnectorsProviders();
          } catch (e) {
            btn.textContent = "Error";
            btn.disabled = false;
          }
        });
      });

    } catch (e) {
      listEl.innerHTML = '<p class="connectors-empty">Could not load connector providers.</p>';
    }
  }

  function remoteAgentCardCopy(agent) {
    if (agent.adapter === "jules_remote") {
      const connected = agent.connection_status === "connected" && agent.status === "ready";
      const disabled = agent.status === "disabled" || agent.enabled === false;
      return {
        pillLabel: disabled ? "DISABLED" : connected ? "CONNECTED" : "PLANNING ONLY",
        pillClass: disabled ? "status-disabled" : connected ? "status-connected" : "status-coming",
        mode: "Not executable",
      };
    }
    const status = agentStatusLabel(agent);
    return {
      pillLabel: status === "connected" ? "CONNECTED" : "PLANNING ONLY",
      pillClass: status === "connected" ? "status-connected" : "status-coming",
      mode: "Not executable",
    };
  }

  function captainAgentOptionLabel(agent) {
    if (!agent) return "Unknown";
    if (agent.runnable || agent.id === "codex_cli") {
      return `${agent.name || agent.id} — Ready`;
    }
    if (agent.adapter === "jules_remote") {
      const connected = agent.connection_status === "connected";
      return `${agent.name || agent.id} — ${connected ? "Connected, execution coming next" : "Setup incomplete"}`;
    }
    return `${agent.name || agent.id} — Not runnable`;
  }

  function renderRemoteAgentCards() {
    const container = document.getElementById("remote-agent-cards");
    const empty = document.getElementById("remote-agents-empty");
    if (!container) return;
    const registered = (state.agents || []).filter((agent) => agent.user_created && (agent.kind === "remote" || agent.adapter === "jules_remote"));
    if (!registered.length) {
      container.innerHTML = "";
      if (empty) empty.style.display = "";
      return;
    }
    if (empty) empty.style.display = "none";
    container.innerHTML = registered.map((agent) => {
      const copy = remoteAgentCardCopy(agent);
      const displayName = agent.adapter === "jules_remote" ? "Jules Remote" : (agent.name || agent.id);
      const showConfig = agent.adapter === "jules_remote";
      return `
        <div class="agent-card registered-agent-card remote-agent-card" data-agent-id="${escapeHtml(agent.id)}">
          <div class="agent-card-top">
            <h3 class="agent-card-title">${escapeHtml(displayName)}</h3>
            <span class="status-pill ${copy.pillClass}">${escapeHtml(copy.pillLabel)}</span>
          </div>
          <div class="agent-card-meta-row">
            <span class="agent-type-label">Type: Remote Agent</span>
            <span class="agent-mode-label">Mode: ${escapeHtml(copy.mode)}</span>
          </div>
          <p class="agent-card-copy">Planning and status only.</p>
          <div class="agent-card-actions">
            ${showConfig ? `<button class="btn" type="button" data-edit-agent-id="${escapeHtml(agent.id)}" data-testid="view-config-jules">View Config</button>` : ""}
            <button class="btn bad" type="button" data-remove-agent-id="${escapeHtml(agent.id)}">Remove</button>
          </div>
        </div>
      `;
    }).join("");
    container.querySelectorAll("[data-remove-agent-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const agentId = button.getAttribute("data-remove-agent-id");
        if (agentId) removeRegisteredAgent(agentId).catch((e) => console.error(e));
      });
    });
    container.querySelectorAll("[data-edit-agent-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const agentId = button.getAttribute("data-edit-agent-id");
        if (agentId) openEditAgentModal(agentId).catch((e) => console.error(e));
      });
    });
    renderSettingsPanel();
  }

  function populateCaptainAgents() {
    const sel = document.getElementById("captain-agent-select");
    if (!sel) return;
    const agents = state.agents || [];
    sel.innerHTML = "";
    agents.forEach((agent) => {
      const opt = document.createElement("option");
      opt.value = agent.id;
      opt.textContent = captainAgentOptionLabel(agent);
      opt.dataset.runnable = agent.runnable ? "1" : "0";
      sel.appendChild(opt);
    });
    if (agents.length) {
      const preferred = agents.find((agent) => agent.id === state.captainDeck.laneId) || agents.find((agent) => agent.runnable) || agents[0];
      sel.value = preferred.id;
      state.captainDeck.laneId = preferred.id;
    }
  }

  function resetAddAgentFormFields({ keepName = false, keepRepo = false } = {}) {
    const nameEl = document.getElementById("add-agent-name");
    const keyEl = document.getElementById("add-agent-api-key");
    const branchEl = document.getElementById("add-agent-branch");
    const approvalEl = document.getElementById("add-agent-require-plan-approval");
    const unverifiedEl = document.getElementById("add-agent-allow-unverified");
    if (nameEl && !keepName) nameEl.value = "";
    if (keyEl) keyEl.value = "";
    if (branchEl && !keepRepo) branchEl.value = "";
    if (approvalEl) approvalEl.checked = true;
    if (unverifiedEl) unverifiedEl.checked = false;
    state.addAgent.lastTestStatus = "";
    const testStatus = document.getElementById("add-agent-test-status");
    if (testStatus) {
      testStatus.style.display = "none";
      testStatus.textContent = "";
    }
  }

  function renderAddAgentCategoryList() {
    const list = document.getElementById("add-agent-category-list");
    const templateList = document.getElementById("add-agent-template-list");
    if (!list) return;
    const templates = state.agentTemplates || [];
    const julesTemplate = templates.find((template) => template.adapter === "jules_remote");
    const remoteRegisterable = !!(julesTemplate && julesTemplate.registerable);
    list.innerHTML = `
      <button class="btn" type="button" data-add-category="captain_profile" style="justify-content:flex-start; text-align:left; width:100%;">
        Captain profile
      </button>
      <button class="btn" type="button" data-add-category="cli_agent" disabled style="justify-content:flex-start; text-align:left; width:100%;">
        CLI agent — Planned
      </button>
      <div class="add-agent-category-block">
        <div class="add-agent-category-label">Remote agent</div>
        <div id="add-agent-remote-options" data-testid="add-agent-remote-options" style="display:flex; flex-direction:column; gap:8px;"></div>
      </div>
      <button class="btn" type="button" data-add-category="research_agent" disabled style="justify-content:flex-start; text-align:left; width:100%;">
        Research agent — Planned
      </button>
    `;
    const remoteOptions = document.getElementById("add-agent-remote-options");
    if (remoteOptions) {
      remoteOptions.innerHTML = templates.filter((template) => template.kind === "remote" || template.adapter === "jules_remote").map((template) => {
        const suffix = template.registerable ? "" : " — Planned";
        const disabled = !template.registerable;
        return `
          <button
            class="btn ${template.registerable ? "primary" : ""}"
            type="button"
            data-template-adapter="${escapeHtml(template.adapter)}"
            data-template-registerable="${template.registerable ? "1" : "0"}"
            data-template-builtin="${template.builtin ? "1" : "0"}"
            ${disabled ? "disabled" : ""}
            style="justify-content:flex-start; text-align:left; width:100%;"
          >
            ${escapeHtml(template.label || template.adapter)}${escapeHtml(suffix)}
          </button>
        `;
      }).join("") || `<button class="btn" type="button" disabled style="width:100%;">No remote adapters available</button>`;
      remoteOptions.querySelectorAll("[data-template-adapter]").forEach((button) => {
        button.addEventListener("click", () => {
          const adapter = button.getAttribute("data-template-adapter") || "";
          const registerable = button.getAttribute("data-template-registerable") === "1";
          if (!registerable) return;
          state.addAgent.templateAdapter = adapter;
          showAddAgentConfigStep();
        });
      });
    }
    if (templateList) templateList.innerHTML = "";
    list.querySelectorAll("[data-add-category]").forEach((button) => {
      button.addEventListener("click", () => {
        const category = button.getAttribute("data-add-category");
        if (category === "captain_profile") {
          closeAddAgentModal();
          navigateToCaptainAgents({ highlightProfile: true });
        }
      });
    });
  }

  function renderAddAgentTemplateList() {
    renderAddAgentCategoryList();
  }

  function showAddAgentChooseStep() {
    state.addAgent.step = "choose";
    const choose = document.getElementById("add-agent-step-choose");
    const config = document.getElementById("add-agent-step-config");
    const backBtn = document.getElementById("add-agent-back");
    const testBtn = document.getElementById("add-agent-test");
    const saveBtn = document.getElementById("add-agent-save");
    const title = document.getElementById("add-agent-title");
    if (choose) choose.style.display = "block";
    if (config) config.style.display = "none";
    if (backBtn) backBtn.style.display = "none";
    if (testBtn) testBtn.style.display = "none";
    if (saveBtn) saveBtn.style.display = "none";
    if (title) title.textContent = state.addAgent.mode === "edit" ? "Edit Agent Config" : "Add Agent";
    renderAddAgentTemplateList();
    updateAddAgentActions();
  }

  function showAddAgentConfigStep() {
    state.addAgent.step = "config";
    const choose = document.getElementById("add-agent-step-choose");
    const config = document.getElementById("add-agent-step-config");
    const backBtn = document.getElementById("add-agent-back");
    const testBtn = document.getElementById("add-agent-test");
    const saveBtn = document.getElementById("add-agent-save");
    const title = document.getElementById("add-agent-title");
    if (choose) choose.style.display = "none";
    if (config) config.style.display = "block";
    if (backBtn) backBtn.style.display = state.addAgent.mode === "create" ? "inline-flex" : "none";
    if (testBtn) testBtn.style.display = "inline-flex";
    if (saveBtn) saveBtn.style.display = "inline-flex";
    if (title) title.textContent = state.addAgent.templateAdapter === "jules_remote" ? "Configure Jules Remote" : "Configure Agent";
    updateAddAgentActions();
  }

  function updateAddAgentActions() {
    const saveBtn = document.getElementById("add-agent-save");
    const testBtn = document.getElementById("add-agent-test");
    const allowUnverified = document.getElementById("add-agent-allow-unverified");
    const keyEl = document.getElementById("add-agent-api-key");
    const editingMetadataOnly = state.addAgent.mode === "edit" && !(keyEl && keyEl.value ? keyEl.value : "").trim();
    const canSave = editingMetadataOnly
      || state.addAgent.lastTestStatus === "connected"
      || (allowUnverified && allowUnverified.checked && ["not_verified", "error"].includes(state.addAgent.lastTestStatus));
    if (saveBtn) {
      saveBtn.disabled = state.addAgent.step !== "config"
        || !state.registryWriteEnabled
        || !!state.addAgent.saving
        || !!state.addAgent.testing
        || !canSave;
    }
    if (testBtn) {
      testBtn.disabled = state.addAgent.step !== "config"
        || !state.registryWriteEnabled
        || !!state.addAgent.saving
        || !!state.addAgent.testing;
      testBtn.textContent = state.addAgent.testing ? "Testing..." : "Test Connection";
    }
    if (saveBtn) saveBtn.textContent = state.addAgent.saving ? "Saving..." : "Save Agent";
  }

  async function populateAddAgentRepos() {
    const sel = document.getElementById("add-agent-repo");
    if (!sel) return;
    sel.innerHTML = '<option value="">No default repo</option>';
    const repos = state.repos.length ? state.repos : [];
    if (!repos.length) {
      try {
        const data = await requestJson(`${MCH}/repos`);
        state.repos = data.repos || [];
      } catch (e) {
        state.repos = [];
      }
    }
    (state.repos || []).forEach((repo) => {
      const opt = document.createElement("option");
      opt.value = repo.repo_id || repo.path;
      opt.textContent = repo.label || repo.repo_id || repo.path;
      sel.appendChild(opt);
    });
  }

  function collectJulesConfigPayload() {
    const nameEl = document.getElementById("add-agent-name");
    const keyEl = document.getElementById("add-agent-api-key");
    const repoEl = document.getElementById("add-agent-repo");
    const branchEl = document.getElementById("add-agent-branch");
    const approvalEl = document.getElementById("add-agent-require-plan-approval");
    const unverifiedEl = document.getElementById("add-agent-allow-unverified");
    return {
      name: (nameEl && nameEl.value ? nameEl.value : "").trim(),
      api_key: (keyEl && keyEl.value ? keyEl.value : "").trim(),
      default_repo_id: repoEl && repoEl.value ? repoEl.value : null,
      default_branch: (branchEl && branchEl.value ? branchEl.value : "").trim() || null,
      require_plan_approval: !!(approvalEl && approvalEl.checked),
      allow_unverified: !!(unverifiedEl && unverifiedEl.checked),
    };
  }

  async function openAddAgentModal() {
    const modal = document.getElementById("add-agent-modal");
    if (!modal) return;
    state.addAgent.mode = "create";
    state.addAgent.editingAgentId = "";
    state.addAgent.error = "";
    state.addAgent.saving = false;
    state.addAgent.testing = false;
    state.addAgent.templateAdapter = "";
    resetAddAgentFormFields();
    modal.style.display = "flex";
    await Promise.all([loadAgentTemplates(), loadAgents(), populateAddAgentRepos()]);
    const err = document.getElementById("add-agent-error");
    if (err) {
      err.style.display = "none";
      err.textContent = "";
    }
    if (!state.registryWriteEnabled && err) {
      err.textContent = "Agent configuration is available only on the private runner service.";
      err.style.display = "block";
    }
    showAddAgentChooseStep();
  }

  async function openEditAgentModal(agentId) {
    const agent = (state.agents || []).find((item) => item.id === agentId);
    if (!agent) return;
    const modal = document.getElementById("add-agent-modal");
    if (!modal) return;
    state.addAgent.mode = "edit";
    state.addAgent.editingAgentId = agentId;
    state.addAgent.templateAdapter = agent.adapter || "jules_remote";
    state.addAgent.error = "";
    state.addAgent.saving = false;
    state.addAgent.testing = false;
    state.addAgent.lastTestStatus = "";
    resetAddAgentFormFields({ keepName: true, keepRepo: true });
    const nameEl = document.getElementById("add-agent-name");
    const branchEl = document.getElementById("add-agent-branch");
    const approvalEl = document.getElementById("add-agent-require-plan-approval");
    if (nameEl) nameEl.value = agent.name || "";
    if (branchEl) branchEl.value = agent.default_branch || "";
    if (approvalEl) approvalEl.checked = agent.require_plan_approval !== false;
    await populateAddAgentRepos();
    const repoEl = document.getElementById("add-agent-repo");
    if (repoEl && agent.default_repo_id) repoEl.value = agent.default_repo_id;
    modal.style.display = "flex";
    const err = document.getElementById("add-agent-error");
    if (err) {
      err.style.display = "none";
      err.textContent = "";
    }
    showAddAgentConfigStep();
  }

  function closeAddAgentModal() {
    const modal = document.getElementById("add-agent-modal");
    if (modal) modal.style.display = "none";
    resetAddAgentFormFields();
    state.addAgent.step = "choose";
    state.addAgent.mode = "create";
    state.addAgent.editingAgentId = "";
    state.addAgent.templateAdapter = "";
    state.addAgent.lastTestStatus = "";
  }

  async function testAddAgentConnection() {
    const err = document.getElementById("add-agent-error");
    const testStatus = document.getElementById("add-agent-test-status");
    const payload = collectJulesConfigPayload();
    if (!payload.api_key) {
      if (err) {
        err.textContent = "Enter a Jules API key before testing the connection.";
        err.style.display = "block";
      }
      return;
    }
    if (!state.registryWriteEnabled) {
      if (err) {
        err.textContent = "Agent configuration is available only on the private runner service.";
        err.style.display = "block";
      }
      return;
    }
    state.addAgent.testing = true;
    if (err) err.style.display = "none";
    updateAddAgentActions();
    try {
      const result = await requestJson(`${MCH}/agents/test-config`, {
        method: "POST",
        body: {
          adapter: "jules_remote",
          api_key: payload.api_key,
          default_repo_id: payload.default_repo_id,
          default_branch: payload.default_branch,
        },
      });
      state.addAgent.lastTestStatus = result.status || "";
      if (testStatus) {
        testStatus.textContent = result.message || `Connection status: ${result.status || "unknown"}`;
        testStatus.style.display = "block";
        testStatus.style.color = result.status === "connected"
          ? "var(--good, #63db9d)"
          : (result.status === "invalid_key" ? "var(--bad, #ff7e91)" : "var(--warn, #f0c66a)");
      }
    } catch (e) {
      state.addAgent.lastTestStatus = "";
      if (err) {
        err.textContent = e.message || String(e);
        err.style.display = "block";
      }
    } finally {
      state.addAgent.testing = false;
      updateAddAgentActions();
    }
  }

  async function saveAddAgent() {
    const err = document.getElementById("add-agent-error");
    const payload = collectJulesConfigPayload();
    const template = (state.agentTemplates || []).find((item) => item.adapter === state.addAgent.templateAdapter);
    if (!payload.name) {
      if (err) {
        err.textContent = "Display name is required.";
        err.style.display = "block";
      }
      return;
    }
    if (!state.registryWriteEnabled) {
      if (err) {
        err.textContent = "Agent configuration is available only on the private runner service.";
        err.style.display = "block";
      }
      return;
    }
    if (state.addAgent.mode === "edit" && state.addAgent.editingAgentId && !payload.api_key) {
      state.addAgent.saving = true;
      updateAddAgentActions();
      try {
        await requestJson(`${MCH}/agents/${encodeURIComponent(state.addAgent.editingAgentId)}/config`, {
          method: "PATCH",
          body: {
            default_repo_id: payload.default_repo_id,
            default_branch: payload.default_branch,
            require_plan_approval: payload.require_plan_approval,
          },
        });
        resetAddAgentFormFields();
        if (err) err.style.display = "none";
        await loadAgents();
        closeAddAgentModal();
      } catch (e) {
        if (err) {
          err.textContent = e.message || String(e);
          err.style.display = "block";
        }
      } finally {
        state.addAgent.saving = false;
        updateAddAgentActions();
      }
      return;
    }
    if (!payload.api_key) {
      if (err) {
        err.textContent = "Jules API key is required to save this agent.";
        err.style.display = "block";
      }
      return;
    }
    const canSave = state.addAgent.lastTestStatus === "connected"
      || (payload.allow_unverified && ["not_verified", "error"].includes(state.addAgent.lastTestStatus));
    if (!canSave) {
      if (err) {
        err.textContent = "Test the Jules connection first, or allow saving as an unverified profile.";
        err.style.display = "block";
      }
      return;
    }
    state.addAgent.saving = true;
    updateAddAgentActions();
    try {
      if (state.addAgent.mode === "edit" && state.addAgent.editingAgentId) {
        await requestJson(`${MCH}/agents/${encodeURIComponent(state.addAgent.editingAgentId)}/config`, {
          method: "PATCH",
          body: {
            api_key: payload.api_key,
            default_repo_id: payload.default_repo_id,
            default_branch: payload.default_branch,
            require_plan_approval: payload.require_plan_approval,
            allow_unverified: payload.allow_unverified,
          },
        });
      } else {
        await requestJson(`${MCH}/agents`, {
          method: "POST",
          body: {
            name: payload.name,
            kind: template ? template.kind : "remote",
            adapter: "jules_remote",
            default_repo_id: payload.default_repo_id,
            default_branch: payload.default_branch,
            require_plan_approval: payload.require_plan_approval,
            enabled: true,
            description: template ? template.description : "",
            api_key: payload.api_key,
            allow_unverified: payload.allow_unverified,
          },
        });
      }
      resetAddAgentFormFields();
      if (err) err.style.display = "none";
      await loadAgents();
      closeAddAgentModal();
    } catch (e) {
      if (err) {
        err.textContent = e.message || String(e);
        err.style.display = "block";
      }
    } finally {
      state.addAgent.saving = false;
      updateAddAgentActions();
    }
  }

  async function removeRegisteredAgent(agentId) {
    if (!state.registryWriteEnabled) {
      alert("Agent registration is available only on the private runner service.");
      return;
    }
    try {
      await requestJson(`${MCH}/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
      await loadAgents();
    } catch (e) {
      alert("Remove failed: " + (e.message || e));
    }
  }

  // Load for library card status (from lanes + health + registry)
  async function loadLibraryStatus() {
    try {
      const [lanesData, health] = await Promise.all([
        requestJson(`${MCH}/agent-lanes`),
        requestJson(`${MCH}/health`),
      ]);
      state.lanes = lanesData.lanes || [];
      state.health = health || {};
      await loadAgents();
      const codex = (state.agents || []).find((agent) => agent.id === "codex_cli")
        || state.lanes.find((l) => l.lane_id === "codex_cli")
        || {};
      const installed = !!codex.installed || codex.status === "ready" || codex.status === "disabled";
      const tmuxF = !!state.health.tmux_runner_enabled;
      const codexF = !!state.health.codex_runner_enabled;
      const working = codex.status === "working";
      if (working) {
        setCodexStatusPill({ ready: true, label: "WORKING" });
      } else if (codex.status === "ready" || (installed && tmuxF && codexF)) {
        setCodexStatusPill({ ready: true, label: "READY" });
      } else if (codex.status === "error") {
        setCodexStatusPill({ disabled: true, label: "ERROR" });
      } else if (installed) {
        setCodexStatusPill({ disabled: true, label: "DISABLED" });
      } else {
        setCodexStatusPill({ disabled: true, label: "DISABLED" });
      }
      renderCodexCapabilityChips(codex);
      const statusLine = document.getElementById("codex-status-line");
      if (statusLine) {
        const checkedAt = codex.last_checked_at || state.agentStatusLastChecked;
        if (checkedAt) {
          statusLine.style.display = "";
          statusLine.textContent = `Last checked ${formatHistoryTimestamp(checkedAt)}`;
        } else {
          statusLine.style.display = "none";
          statusLine.textContent = "";
        }
      }
      renderSettingsPanel();
    } catch (e) {
      setCodexStatusPill({ disabled: true, label: "Disabled" });
      renderSettingsPanel();
    }
  }

  // Populate repo select in use-agent modal (from /repos)
  async function populateModalRepos() {
    const sel = document.getElementById("modal-repo-select");
    if (!sel) return;
    sel.innerHTML = '<option value="">Loading repos...</option>';
    try {
      const data = await requestJson(`${MCH}/repos`);
      const repos = data.repos || [];
      sel.innerHTML = "";
      repos.forEach((r) => {
        const opt = document.createElement("option");
        opt.value = r.path || r.repo_id; // path for session, id for runner
        opt.dataset.repoId = r.repo_id;
        opt.textContent = r.label || r.path;
        sel.appendChild(opt);
      });
      if (repos.length) sel.value = repos[0].path || repos[0].repo_id;
    } catch (e) {
      sel.innerHTML = '<option value="/root/mcharness-public-export">mcharness-public-export (fallback)</option>';
    }
  }

  // Use Agent modal open
  function openUseAgentModal() {
    const modal = document.getElementById("use-agent-modal");
    if (!modal) return;
    modal.style.display = "flex";
    populateModalRepos();
    // clear fields
    const t = document.getElementById("modal-task-title");
    const p = document.getElementById("modal-prompt");
    if (t) t.value = "";
    if (p) p.value = "";
    const note = document.getElementById("deploy-disabled-note");
    if (note) note.style.display = "none";
  }

  function closeUseAgentModal() {
    const modal = document.getElementById("use-agent-modal");
    if (modal) modal.style.display = "none";
  }

  function closeSetupModals() {
    closeUseAgentModal();
    closeCaptainDeckModal();
    closeCaptainProfileModal();
    closeAddAgentModal();
  }

  async function deployRunnerPrompt({ title, prompt, repoPath, repoId, planId = null, closeCurrentModal = null, noteId = "deploy-disabled-note" }) {
    const note = noteId ? document.getElementById(noteId) : null;
    const health = state.health || {};
    const canRunReal = !!(health.tmux_runner_enabled && health.codex_runner_enabled);
    if (!canRunReal && note) {
      note.textContent = "Codex runner is disabled. Start private runner mode (8125 + both MCHARNESS_TMUX_RUNNER_ENABLED=true and MCHARNESS_CODEX_RUNNER_ENABLED=true) to use Deploy Prompt for real Codex.";
      note.style.display = "block";
    }

    try {
      const sess = await requestJson(`${MCH}/sessions`, {
        method: "POST",
        body: {
          title,
          objective: title,
          plan_instruction: prompt,
          repo_path: repoPath,
          agent_lane: "codex_cli",
        },
      });
      const sid = sess.session_id || sess.id;
      state.selectedThreadId = sid;
      updateRunsEvidenceActions();

      const qres = await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/queue`, {
        method: "POST",
        body: { title: "Task prompt", prompt },
      });
      const qid = qres.queue_item_id || qres.id;

      try {
        await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/prompt-export`, {
          method: "POST",
          body: { queue_item_id: qid, mark_sent: false },
        });
      } catch (e) { /* non fatal */ }

      const runnerState = await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/start`, {
        method: "POST",
        body: {
          lane_id: "codex_cli",
          repo_id: repoId,
          queue_item_id: qid,
          title,
          prompt,
          plan_id: planId,
          agent_id: "codex_cli",
          created_by: planId ? "captain_deck" : "use_agent",
        },
      });
      state.activeWardenRunId = (runnerState && (runnerState.runner_id || (runnerState.warden_run && runnerState.warden_run.run_id))) || "";
      await Promise.all([loadRecentRuns(), loadRecentEvidence(), loadMissionWorklog()]);

      if (typeof closeCurrentModal === "function") closeCurrentModal();
      closeSetupModals();
      openLiveCLIMonitor();

      setTimeout(async () => {
        try {
          const result = await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/send-prompt`, {
            method: "POST",
            body: { prompt },
          });
          state.promptSubmittedAt = Date.now();
          if (result && result.status) {
            state.health.runner_status = result.status;
          }
          setQuickReplyStatus("Prompt sent to Codex.");
          if (typeof refreshLiveMonitor === "function") await refreshLiveMonitor();
        } catch (e) {
          if (typeof refreshLiveMonitor === "function") await refreshLiveMonitor();
        }
      }, 10000);

      return sid;
    } catch (err) {
      if (typeof closeCurrentModal === "function") closeCurrentModal();
      alert("Deploy failed: " + (err.message || err));
      if (state.selectedThreadId) openLiveCLIMonitor();
      throw err;
    }
  }

  // Deploy Prompt flow (create, queue, export, start, open monitor, delayed send)
  async function deployPrompt() {
    const repoSel = document.getElementById("modal-repo-select");
    const titleEl = document.getElementById("modal-task-title");
    const promptEl = document.getElementById("modal-prompt");
    if (!repoSel || !titleEl || !promptEl) return;

    const repoPath = repoSel.value || "/root/mcharness-public-export";
    const repoId = (repoSel.selectedOptions[0] && repoSel.selectedOptions[0].dataset.repoId) || "mcharness-public-export";
    const title = (titleEl.value || "Untitled task").trim();
    const prompt = (promptEl.value || "Perform the task described.").trim();

    if (!title || !prompt) {
      alert("Title and prompt are required.");
      return;
    }

    await deployRunnerPrompt({
      title,
      prompt,
      repoPath,
      repoId,
      closeCurrentModal: closeUseAgentModal,
    });
  }

  // Live CLI Monitor (adapted from previous implementation, read-only, polls while open)
  let liveMonitorInterval = null;
  let liveAutoRefresh = true;

  function openLiveCLIMonitor() {
    closeSetupModals();
    const modal = document.getElementById("live-cli-modal");
    if (!modal) return;
    modal.style.display = "flex";
    state.promptSubmittedAt = state.promptSubmittedAt || 0;
    state.liveAutoScroll = true;
    state.lastMonitorTranscriptText = "";
    setQuickReplyStatus("");
    updateLiveMonitorChrome();
    refreshLiveMonitor();
    if (liveAutoRefresh) startMonitorPolling();
  }

  function closeLiveCLIMonitor() {
    const modal = document.getElementById("live-cli-modal");
    if (modal) modal.style.display = "none";
    setQuickReplyStatus("");
    stopMonitorPolling();
  }

  function startMonitorPolling() {
    stopMonitorPolling();
    liveMonitorInterval = setInterval(() => {
      const modal = document.getElementById("live-cli-modal");
      if (modal && modal.style.display !== "none" && liveAutoRefresh) {
        refreshLiveMonitor();
      }
    }, 1500);
  }

  function stopMonitorPolling() {
    if (liveMonitorInterval) {
      clearInterval(liveMonitorInterval);
      liveMonitorInterval = null;
    }
  }

  async function refreshLiveMonitor() {
    const sid = state.selectedThreadId;
    if (!sid) {
      const empty = document.getElementById("modal-empty");
      if (empty) empty.style.display = "";
      return;
    }
    try {
      const [status, trans] = await Promise.all([
        requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/status`),
        requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/transcript`),
      ]);
      // update UI elements (ids from the modal in html)
      const laneEl = document.getElementById("modal-lane-name");
      if (laneEl) laneEl.textContent = "";
      const infoEl = document.getElementById("modal-info");
      const statusText = status.status || "n/a";
      const txt = (trans && trans.transcript) ? trans.transcript : (status.transcript || "");
      const hasTranscriptOutput = !!String(txt || "").trim();
      const monitorStatusLabel = (() => {
        if (statusText === "failed") return "Failed";
        if (statusText === "exited") return "Finished";
        if (statusText === "stopped") return "Stopped";
        if (statusText === "starting") return "Starting Codex...";
        if (statusText === "waiting_for_codex") return hasTranscriptOutput ? "Running" : "Opening Codex...";
        if (statusText === "prompt_sent") return "Running";
        if (statusText === "awaiting_response") return "Running";
        if (statusText === "running") return "Running";
        return statusText;
      })();
      const sessionName = status.tmux_session_name || "n/a";
      if (infoEl) {
        infoEl.innerHTML = `
          <div><strong>Repo:</strong> ${status.repo_id || "n/a"}</div>
          <div><strong>Status:</strong> ${monitorStatusLabel}</div>
          <div><strong>Session:</strong> ${sessionName}</div>
        `;
      }
      const pre = document.getElementById("modal-transcript");
      let displayTxt = txt || "Waiting for CLI output...";
      if (pre) {
        const shouldStick = state.liveAutoScroll && isModalTranscriptNearBottom(pre);
        const previousScrollTop = pre.scrollTop;
        pre.textContent = displayTxt;
        if (shouldStick) {
          scrollModalTranscriptToBottom();
        } else {
          pre.scrollTop = previousScrollTop;
        }
        // warning if only exit code visible (means launch didn't keep interactive or capture missed TUI)
        if (displayTxt.trim() === "MCH_EXIT_CODE:0" || (displayTxt.trim().length < 30 && displayTxt.includes("EXIT"))) {
          pre.textContent = displayTxt + "\n\n[Warning] Runner exited before producing visible CLI output. Check flags, codex auth, or tmux attach manually.";
          if (shouldStick) scrollModalTranscriptToBottom();
        }
      }
      const elapsed = state.promptSubmittedAt ? Date.now() - state.promptSubmittedAt : 0;
      const transcriptTrimmed = String(txt || "").trim();
      if (elapsed > 10000 && statusText !== "running" && !transcriptTrimmed) {
        setQuickReplyStatus("Transcript is not updating yet. Use the buttons below if Codex is waiting for input.");
      }
      state.lastMonitorTranscriptText = transcriptTrimmed;
      const ts = document.getElementById("modal-timestamp");
      if (ts) ts.textContent = `Last refreshed: ${new Date().toLocaleTimeString()}`;

      // store for buttons
      const modal = document.getElementById("live-cli-modal");
      if (modal) {
        modal.dataset.attach = status.attach_command || (status.tmux_session_name ? `tmux attach -t ${status.tmux_session_name}` : "");
        modal.dataset.transcript = txt;
      }

      // hide states
      const e = document.getElementById("modal-empty");
      const d = document.getElementById("modal-disabled");
      if (e) e.style.display = "none";
      if (d) d.style.display = "none";
    } catch (e) {
      const empty = document.getElementById("modal-empty");
      if (empty) {
        empty.style.display = "";
        empty.textContent = "No active runner or error fetching status. (Runner disabled in public mode?)";
      }
    }
  }

  async function sendQuickReply(key) {
    const sid = state.selectedThreadId;
    if (!sid) {
      setQuickReplyStatus("Failed: no active runner", true);
      return;
    }
    if (key === "Submit / Continue") {
      setQuickReplyStatus("Sending: Submit / Continue");
    } else {
      setQuickReplyStatus(`Sending: ${key}`);
    }
    try {
      const result = await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/send-key`, {
        method: "POST",
        body: { key },
      });
      if (key === "Submit / Continue") {
        setQuickReplyStatus((result && result.status_note) || "Prompt sent to Codex.");
      } else {
        setQuickReplyStatus(`Sent: ${key}`);
      }
      const pre = document.getElementById("modal-transcript");
      if (pre && result && result.transcript_excerpt) {
        const shouldStick = state.liveAutoScroll && isModalTranscriptNearBottom(pre);
        pre.textContent = result.transcript_excerpt;
        if (shouldStick) scrollModalTranscriptToBottom();
      }
      await refreshLiveMonitor();
    } catch (e) {
      setQuickReplyStatus(`Failed: ${e.message || e}`, true);
    }
  }

  function wireDevelopPlanButtons() {
    const openCaptain = () => openCaptainDeckModal().catch((e) => console.error(e));
    document.querySelectorAll("[data-action='develop-plan']").forEach((btn) => {
      btn.addEventListener("click", openCaptain);
    });
  }

  function wireWorkspaceNav() {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const section = btn.dataset.section;
        if (section) setActiveSection(section);
      });
    });
    const configureCaptain = document.getElementById("configure-captain-btn");
    if (configureCaptain) {
      configureCaptain.addEventListener("click", () => {
        openCaptainDeckModal().catch((e) => console.error(e));
      });
    }
    const settingsCaptainAgentsLink = document.getElementById("settings-captain-agents-link");
    if (settingsCaptainAgentsLink) {
      settingsCaptainAgentsLink.addEventListener("click", () => navigateToCaptainAgents());
    }
    const captainConfigureBtn = document.getElementById("captain-configure-btn");
    if (captainConfigureBtn) {
      captainConfigureBtn.addEventListener("click", () => {
        openCaptainDeckModal().catch((e) => console.error(e));
      });
    }
    const captainInstructionsBtn = document.getElementById("captain-instructions-btn");
    if (captainInstructionsBtn) {
      captainInstructionsBtn.addEventListener("click", () => {
        openCaptainProfileModal().catch((e) => console.error(e));
      });
    }
    const captainProfileSelect = document.getElementById("captain-profile-select");
    if (captainProfileSelect) {
      captainProfileSelect.addEventListener("change", () => {
        state.captainProfile.selectedId = captainProfileSelect.value || "captain-default";
        renderCaptainProfilePanel().catch((e) => console.error(e));
      });
    }
    const captainViewProfileMd = document.getElementById("captain-view-profile-md");
    if (captainViewProfileMd) {
      captainViewProfileMd.addEventListener("click", () => {
        openCaptainProfileModal().catch((e) => console.error(e));
      });
    }
    const captainCopyProfile = document.getElementById("captain-copy-profile");
    if (captainCopyProfile) {
      captainCopyProfile.addEventListener("click", () => {
        copyCaptainProfileInstructions().catch((e) => console.error(e));
      });
    }
    const captainUseProfile = document.getElementById("captain-use-profile");
    if (captainUseProfile) {
      captainUseProfile.addEventListener("click", useCaptainProfileSelection);
    }
    const captainProfileModalClose = document.getElementById("captain-profile-modal-close");
    if (captainProfileModalClose) {
      captainProfileModalClose.addEventListener("click", closeCaptainProfileModal);
    }
    const captainProfileModal = document.getElementById("captain-profile-modal");
    if (captainProfileModal) {
      captainProfileModal.addEventListener("click", (e) => {
        if (e.target === captainProfileModal) closeCaptainProfileModal();
      });
    }
    const runDetailClose = document.getElementById("run-detail-close");
    if (runDetailClose) runDetailClose.addEventListener("click", closeRunDetailModal);
    document.querySelectorAll("[data-evidence-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.evidenceTypeFilter = button.getAttribute("data-evidence-filter") || "all";
        renderEvidencePanel();
      });
    });
    document.querySelectorAll("[data-timeline-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.missionTimelineFilter = button.getAttribute("data-timeline-filter") || "all";
        renderMissionWorklog();
      });
    });
    document.querySelectorAll("[data-section-jump]").forEach((button) => {
      button.addEventListener("click", () => {
        const section = button.getAttribute("data-section-jump");
        if (section) setActiveSection(section);
      });
    });
    const evidenceDetailClose = document.getElementById("evidence-detail-close");
    if (evidenceDetailClose) evidenceDetailClose.addEventListener("click", closeEvidenceDetailModal);
    const runDetailModal = document.getElementById("run-detail-modal");
    if (runDetailModal) runDetailModal.addEventListener("click", (e) => { if (e.target === runDetailModal) closeRunDetailModal(); });
    const evidenceDetailModal = document.getElementById("evidence-detail-modal");
    if (evidenceDetailModal) evidenceDetailModal.addEventListener("click", (e) => { if (e.target === evidenceDetailModal) closeEvidenceDetailModal(); });
    ["runs-open-monitor", "evidence-open-output"].forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) btn.addEventListener("click", openLiveCLIMonitor);
    });
  }

  // Wire simple UI events
  function wireSimpleUI() {
    wireDevelopPlanButtons();
    wireWorkspaceNav();

    const memoryRefresh = document.getElementById("memory-refresh");
    if (memoryRefresh) memoryRefresh.addEventListener("click", () => {
      loadMemory().catch((e) => console.error(e));
    });
    const memorySearchForm = document.getElementById("memory-search-form");
    if (memorySearchForm) memorySearchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const query = document.getElementById("memory-search-query");
      searchMemory(query && query.value).catch((e) => console.error(e));
    });
    const memoryRememberForm = document.getElementById("memory-remember-form");
    if (memoryRememberForm) memoryRememberForm.addEventListener("submit", (event) => {
      event.preventDefault();
      rememberMemoryNote().catch((e) => console.error(e));
    });
    const memoryContextBuild = document.getElementById("memory-context-build");
    if (memoryContextBuild) memoryContextBuild.addEventListener("click", () => {
      buildMemoryContextPreview().catch((e) => console.error(e));
    });

    const useCodexDirectly = document.getElementById("use-codex-directly");
    if (useCodexDirectly) useCodexDirectly.addEventListener("click", openUseAgentModal);

    const inspectorViewCodex = document.getElementById("inspector-view-codex");
    if (inspectorViewCodex) inspectorViewCodex.addEventListener("click", openLiveCLIMonitor);

    const codexOpenMonitor = document.getElementById("codex-open-monitor-btn");
    if (codexOpenMonitor) codexOpenMonitor.addEventListener("click", openLiveCLIMonitor);

    const codexConfigure = document.getElementById("codex-configure-btn");
    if (codexConfigure) codexConfigure.addEventListener("click", () => setActiveSection("settings"));

    const codexViewRuns = document.getElementById("codex-view-runs-btn");
    if (codexViewRuns) {
      codexViewRuns.addEventListener("click", () => {
        setActiveSection("runs");
        loadRecentRuns().catch((e) => console.error(e));
      });
    }

    const captainCreatePlanBtn = document.getElementById("captain-create-plan-btn");
    if (captainCreatePlanBtn) {
      captainCreatePlanBtn.addEventListener("click", () => {
        openCaptainDeckModal().catch((e) => console.error(e));
      });
    }

    const refreshAgentStatus = document.getElementById("refresh-agent-status");
    if (refreshAgentStatus) {
      refreshAgentStatus.addEventListener("click", () => {
        refreshAgentStatuses().catch((e) => console.error(e));
      });
    }
    const inspectorRefreshAgents = document.getElementById("inspector-refresh-agents");
    if (inspectorRefreshAgents) {
      inspectorRefreshAgents.addEventListener("click", () => {
        refreshAgentStatuses().catch((e) => console.error(e));
      });
    }

    const cancel = document.getElementById("cancel-use-agent");
    if (cancel) cancel.addEventListener("click", closeUseAgentModal);

    const deploy = document.getElementById("deploy-prompt-btn");
    if (deploy) deploy.addEventListener("click", () => {
      // run deploy (async but fire)
      deployPrompt().catch((e) => console.error(e));
    });

    const captainClose = document.getElementById("captain-close");
    if (captainClose) captainClose.addEventListener("click", closeCaptainDeckModal);
    const captainCreate = document.getElementById("captain-create-plan");
    if (captainCreate) captainCreate.addEventListener("click", () => {
      createCaptainPlan().catch((e) => console.error(e));
    });
    const captainDeploy = document.getElementById("captain-deploy-first");
    if (captainDeploy) captainDeploy.addEventListener("click", () => {
      deployCaptainFirstPrompt().catch((e) => console.error(e));
    });
    const captainCopy = document.getElementById("captain-copy-plan");
    if (captainCopy) captainCopy.addEventListener("click", () => {
      copyCaptainPlan().catch((e) => console.error(e));
    });
    const captainSetKey = document.getElementById("captain-set-key");
    if (captainSetKey) captainSetKey.addEventListener("click", () => {
      openCaptainKeyForm();
    });
    const captainSaveKey = document.getElementById("captain-save-key");
    if (captainSaveKey) captainSaveKey.addEventListener("click", () => {
      saveCaptainKey().catch((e) => console.error(e));
    });
    const captainCancelKey = document.getElementById("captain-cancel-key");
    if (captainCancelKey) captainCancelKey.addEventListener("click", () => {
      closeCaptainKeyForm();
    });
    const captainRemoveKey = document.getElementById("captain-remove-key");
    if (captainRemoveKey) captainRemoveKey.addEventListener("click", () => {
      removeCaptainKey().catch((e) => console.error(e));
    });
    const captainGoal = document.getElementById("captain-goal");
    if (captainGoal) captainGoal.addEventListener("input", () => {
      state.captainDeck.goal = captainGoal.value || "";
    });
    const captainOpenrouterModel = document.getElementById("captain-openrouter-model");
    if (captainOpenrouterModel) captainOpenrouterModel.addEventListener("input", () => {
      state.captainDeck.keyModel = captainOpenrouterModel.value || "openrouter/auto";
    });
    const captainRepo = document.getElementById("captain-repo-select");
    if (captainRepo) captainRepo.addEventListener("change", () => {
      const selected = captainRepo.selectedOptions[0];
      state.captainDeck.repoId = captainRepo.value;
      state.captainDeck.repoPath = (selected && selected.dataset.repoPath) || "";
    });
    const captainLane = document.getElementById("captain-agent-select");
    if (captainLane) captainLane.addEventListener("change", () => {
      state.captainDeck.laneId = captainLane.value || "codex_cli";
      renderCaptainDeck();
    });

    const addAgentBtn = document.getElementById("add-agent-btn");
    if (addAgentBtn) addAgentBtn.addEventListener("click", () => {
      openAddAgentModal().catch((e) => console.error(e));
    });
    const addAgentClose = document.getElementById("add-agent-close");
    if (addAgentClose) addAgentClose.addEventListener("click", closeAddAgentModal);
    const addAgentSave = document.getElementById("add-agent-save");
    if (addAgentSave) addAgentSave.addEventListener("click", () => {
      saveAddAgent().catch((e) => console.error(e));
    });
    const addAgentTest = document.getElementById("add-agent-test");
    if (addAgentTest) addAgentTest.addEventListener("click", () => {
      testAddAgentConnection().catch((e) => console.error(e));
    });
    const addAgentBack = document.getElementById("add-agent-back");
    if (addAgentBack) addAgentBack.addEventListener("click", () => {
      showAddAgentChooseStep();
    });
    const addAgentAllowUnverified = document.getElementById("add-agent-allow-unverified");
    if (addAgentAllowUnverified) addAgentAllowUnverified.addEventListener("change", updateAddAgentActions);
    const addAgentApiKey = document.getElementById("add-agent-api-key");
    if (addAgentApiKey) addAgentApiKey.addEventListener("input", () => {
      state.addAgent.lastTestStatus = "";
      updateAddAgentActions();
    });
    const addAgentModal = document.getElementById("add-agent-modal");
    if (addAgentModal) addAgentModal.addEventListener("click", (e) => {
      if (e.target === addAgentModal) closeAddAgentModal();
    });

    // Monitor buttons (if elements exist from the modal HTML)
    const mRefresh = document.getElementById("modal-refresh");
    if (mRefresh) mRefresh.addEventListener("click", refreshLiveMonitor);
    const mAuto = document.getElementById("modal-autorefresh");
    if (mAuto) mAuto.addEventListener("click", () => {
      liveAutoRefresh = !liveAutoRefresh;
      mAuto.textContent = `Auto-refresh: ${liveAutoRefresh ? "ON" : "OFF"}`;
      if (liveAutoRefresh) startMonitorPolling();
      else stopMonitorPolling();
    });
    const mJump = document.getElementById("modal-jump-latest");
    if (mJump) mJump.addEventListener("click", resumeLiveAutoScroll);
    const mExpand = document.getElementById("modal-expand");
    if (mExpand) mExpand.addEventListener("click", () => {
      state.liveMonitorExpanded = !state.liveMonitorExpanded;
      updateLiveMonitorChrome();
    });
    const mCopy = document.getElementById("modal-copy-attach");
    if (mCopy) mCopy.addEventListener("click", () => {
      const modal = document.getElementById("live-cli-modal");
      const cmd = modal ? modal.dataset.attach : "";
      if (cmd) navigator.clipboard.writeText(cmd).catch(() => prompt("Copy:", cmd));
    });
    const mSave = document.getElementById("modal-save-evidence");
    if (mSave) mSave.addEventListener("click", async () => {
      const sid = state.selectedThreadId;
      if (!sid) return;
      try {
        const result = await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/transcript-to-evidence`, { method: "POST" });
        if (result && result.warden_evidence && result.warden_evidence.evidence_id) {
          state.activeWardenRunId = result.warden_evidence.run_id || state.activeWardenRunId;
        }
        await Promise.all([loadRecentRuns(), loadRecentEvidence(), loadMissionWorklog()]);
        setQuickReplyStatus("Transcript saved as evidence.");
      } catch (e) { setQuickReplyStatus(`Save failed: ${e.message || e}`, true); }
    });
    const mStop = document.getElementById("modal-stop");
    if (mStop) mStop.addEventListener("click", async () => {
      const sid = state.selectedThreadId;
      if (!sid) return;
      try { await requestJson(`${MCH}/sessions/${encodeURIComponent(sid)}/runner/stop`, { method: "POST" }); } catch (e) {}
      refreshLiveMonitor();
    });
    const mClose = document.getElementById("modal-close");
    if (mClose) mClose.addEventListener("click", closeLiveCLIMonitor);

    document.querySelectorAll("[data-quick-reply]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-quick-reply");
        if (key) sendQuickReply(key);
      });
    });

    // close monitor on backdrop
    const mon = document.getElementById("live-cli-modal");
    if (mon) mon.addEventListener("click", (e) => { if (e.target === mon) closeLiveCLIMonitor(); });

    const transcript = document.getElementById("modal-transcript");
    if (transcript && !transcript.dataset.scrollBound) {
      transcript.dataset.scrollBound = "1";
      transcript.addEventListener("scroll", () => {
        if (state.liveScrollProgrammatic) {
          state.liveScrollProgrammatic = false;
          return;
        }
        if (!isModalTranscriptNearBottom(transcript)) {
          pauseLiveAutoScroll();
        }
      });
    }

    updateLiveMonitorChrome();
  }

  // --- Marius Local Agent Integration ---

  async function refreshMariusStatus() {
    try {
      const res = await requestJson(`${MCH}/agents/marius/models`);
      if (res && res.data) {
        const pLabel = document.getElementById('marius-provider-label');
        if (pLabel) pLabel.textContent = 'Ollama';
        const mLabel = document.getElementById('marius-model-label');
        if (mLabel) mLabel.textContent = res.data.forced_model || 'auto';
        const prLabel = document.getElementById('marius-profile-label');
        if (prLabel) prLabel.textContent = res.data.current_profile || 'fast';
        
        // Update modals if open
        const statusMode = document.getElementById('marius-model-status-mode');
        if (statusMode) statusMode.textContent = "local";
        const statusProfile = document.getElementById('marius-model-status-profile');
        if (statusProfile) statusProfile.textContent = res.data.current_profile || 'fast';
        const statusForced = document.getElementById('marius-model-status-forced');
        if (statusForced) statusForced.textContent = res.data.forced_model || 'None (Auto)';
        
        const available = res.data.available_ollama || [];
        const availList = document.getElementById('marius-model-available-list');
        if (availList) availList.innerHTML = available.join('<br>') || 'None';

        // Update chat dropdowns
        const profSel = document.getElementById('marius-chat-profile-select');
        if (profSel) profSel.value = res.data.current_profile || 'fast';
        
        const modSel = document.getElementById('marius-chat-model-select');
        if (modSel) {
          modSel.innerHTML = '<option value="auto">Auto-select</option>' + available.map(m => `<option value="${m}">${m}</option>`).join('');
          modSel.value = res.data.forced_model || 'auto';
        }
      }

      const missingRes = await requestJson(`${MCH}/model/missing`);
      if (missingRes && missingRes.missing) {
        const mList = document.getElementById('marius-model-missing-list');
        if (mList) mList.innerHTML = missingRes.missing.map(m => `ollama pull ${m}`).join('<br>') || 'None missing';
      }
    } catch (e) {
      console.warn("Marius API unavailable", e);
    }
  }

  async function openMariusChat() {
    const modal = document.getElementById("marius-chat-modal");
    if (modal) modal.style.display = "flex";
    
    // Refresh to get latest state
    await refreshMariusStatus();
    
    // Check for router-only model lockout
    const mLabel = document.getElementById('marius-model-label');
    const currentModel = mLabel ? mLabel.textContent : '';
    
    if (currentModel === 'marius-fast') {
      const availListEl = document.getElementById('marius-model-available-list');
      const availText = availListEl ? availListEl.innerHTML : '';
      const available = availText.split('<br>').map(m => m.trim());
      
      const chatPriorities = ['llama3.2:1b', 'gemma3:1b', 'qwen3:0.6b', 'llama3.2:3b'];
      let targetModel = null;
      for (const m of chatPriorities) {
        if (available.includes(m) || available.includes(m + ':latest')) {
          targetModel = m;
          break;
        }
      }
      
      if (targetModel) {
        try {
          await requestJson(`${MCH}/agents/marius/model/set`, { method: "POST", body: { model: targetModel } });
          const messagesEl = document.getElementById("marius-chat-messages");
          if (messagesEl) {
            messagesEl.innerHTML += `<div style="align-self:center; font-size:12px; color:var(--warn, #f0c66a); margin:8px 0;">Warning: marius-fast is router-only. Switched chat model to ${targetModel}.</div>`;
            messagesEl.scrollTop = messagesEl.scrollHeight;
          }
          await refreshMariusStatus();
        } catch (e) {
          console.error("Failed to auto-switch router model", e);
        }
      }
    }
    
    setTimeout(() => document.getElementById("marius-chat-input")?.focus(), 100);
  }

  function closeMariusChat() {
    const modal = document.getElementById("marius-chat-modal");
    if (modal) modal.style.display = "none";
  }

  function openMariusModels() {
    const modal = document.getElementById("marius-model-modal");
    if (modal) {
      modal.style.display = "flex";
      document.getElementById('marius-model-modal-title').textContent = "Marius Models & Benchmarks";
    }
    refreshMariusStatus();
  }

  function closeMariusModels() {
    const modal = document.getElementById("marius-model-modal");
    if (modal) modal.style.display = "none";
  }

  async function sendMariusChat() {
    const input = document.getElementById("marius-chat-input");
    const msg = input.value.trim();
    if (!msg) return;

    input.value = "";
    
    const messagesEl = document.getElementById("marius-chat-messages");
    const progEl = document.getElementById("marius-chat-progress");
    const errEl = document.getElementById("marius-chat-error");
    
    messagesEl.innerHTML += `<div style="align-self:flex-end; background:var(--bg-2); padding:10px 14px; border-radius:14px 14px 2px 14px; max-width:85%; border:1px solid var(--line);">${escapeHtml(msg)}</div>`;
    messagesEl.scrollTop = messagesEl.scrollHeight;
    
    progEl.style.display = "block";
    errEl.style.display = "none";
    
    try {
      // Gather workspace context safely
      const repoPath = (state && state.captainDeck && state.captainDeck.repoPath) || "";
      const runnerEnabled = !!(state && state.snapshot && state.snapshot.safety && state.snapshot.safety.private_runner_enabled);
      const workspaceCtx = repoPath ? {
        repo_path: repoPath,
        branch: "unknown",
        dirty: "unknown",
        runner_enabled: runnerEnabled
      } : null;

      const res = await requestJson(`${MCH}/agents/marius/chat`, {
        method: "POST",
        body: { 
          message: msg,
          workspace: workspaceCtx
        }
      });
      
      if (res && res.ok && res.data) {
        const reply = res.data.response;
        const footer = `provider: ${res.data.provider} | model: ${res.data.model} | profile: ${res.data.profile || 'fast'} | ${res.data.elapsed}s`;
        
        messagesEl.innerHTML += `
          <div style="align-self:flex-start; background:var(--bg-1); padding:10px 14px; border-radius:14px 14px 14px 2px; max-width:85%; border:1px solid var(--line);">
            <div style="line-height:1.5; white-space:pre-wrap;">${escapeHtml(reply)}</div>
            <div style="font-size:11px; color:var(--muted); margin-top:8px;">[${escapeHtml(footer)}]</div>
          </div>
        `;
      } else {
        errEl.textContent = "Error: " + (res.error || "Unknown API error");
        errEl.style.display = "block";
      }
    } catch (e) {
      errEl.textContent = "Error: " + e.message;
      errEl.style.display = "block";
    } finally {
      progEl.style.display = "none";
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  async function runMariusBench() {
    const progEl = document.getElementById("marius-bench-progress");
    const resEl = document.getElementById("marius-bench-results");
    const tableEl = document.getElementById("marius-bench-table-container");
    
    progEl.style.display = "block";
    resEl.style.display = "none";
    
    try {
      const res = await requestJson(`${MCH}/agents/marius/model/bench`, {
        method: "POST",
        body: { quick: true }
      });
      
      if (res && res.ok && res.data) {
        const d = res.data;
        let table = "Model                Time     Overall  Safety   Preview\n";
        table += "----------------------------------------------------------------------\n";
        (d.results || []).forEach(r => {
          const m = r.model.padEnd(20);
          const t = String(r.elapsed_seconds).padEnd(8);
          const o = String(r.overall_score || 0).padEnd(8);
          const s = String(r.safety_score || 0).padEnd(8);
          table += `${m} ${t}s ${o} ${s} ${r.response_preview}\n`;
        });
        tableEl.textContent = table;
        
        const bestEl = document.getElementById("marius-bench-rec-best");
        if (bestEl) bestEl.textContent = d.recommendations.best_terminal_default || "None";
        const fastestEl = document.getElementById("marius-bench-rec-fastest");
        if (fastestEl) fastestEl.textContent = d.recommendations.fastest_safe_terminal_model || "None";
        const codeEl = document.getElementById("marius-bench-rec-code");
        if (codeEl) codeEl.textContent = d.recommendations.best_code_local || "None";
        
        resEl.style.display = "block";
      }
    } catch (e) {
      alert("Benchmark failed: " + e.message);
    } finally {
      progEl.style.display = "none";
    }
  }

  async function applyMariusRec() {
    const bestEl = document.getElementById("marius-bench-rec-best");
    const best = bestEl ? bestEl.textContent : "";
    if (best && best !== "None") {
      try {
        await requestJson(`${MCH}/agents/marius/model/set`, {
          method: "POST",
          body: { model: best }
        });
        alert("Applied " + best);
        refreshMariusStatus();
      } catch (e) { alert("Failed: " + e.message); }
    }
  }

  async function showMariusContext() {
    try {
      const res = await requestJson(`${MCH}/agents/marius/context`);
      if (res && res.ok && res.data) {
        const modal = document.getElementById("marius-model-modal");
        if (modal) {
          modal.style.display = "flex";
          const title = document.getElementById('marius-model-modal-title');
          if (title) title.textContent = "Marius Grounding Context";
        }
        const availList = document.getElementById('marius-model-available-list');
        if (availList) availList.innerHTML = `<pre style="white-space:pre-wrap; color:var(--fg);">${escapeHtml(res.data.facts)}</pre>`;
      }
    } catch(e) { alert("Error fetching context"); }
  }

  function wireMariusEvents() {
    const btnChat = document.getElementById("open-marius-chat-btn");
    if (btnChat) btnChat.addEventListener("click", openMariusChat);
    const btnTest = document.getElementById("marius-test-drive-btn");
    if (btnTest) btnTest.addEventListener("click", openMariusModels);
    const btnChatTest = document.getElementById("marius-chat-test-drive-btn");
    if (btnChatTest) btnChatTest.addEventListener("click", openMariusModels);
    const btnCloseChat = document.getElementById("marius-chat-close-btn");
    if (btnCloseChat) btnCloseChat.addEventListener("click", closeMariusChat);
    const btnCloseModels = document.getElementById("marius-model-close-btn");
    if (btnCloseModels) btnCloseModels.addEventListener("click", closeMariusModels);
    const btnSend = document.getElementById("marius-chat-send-btn");
    if (btnSend) btnSend.addEventListener("click", sendMariusChat);
    const btnBench = document.getElementById("marius-model-run-bench-btn");
    if (btnBench) btnBench.addEventListener("click", runMariusBench);
    const btnApply = document.getElementById("marius-model-apply-rec-btn");
    if (btnApply) btnApply.addEventListener("click", applyMariusRec);
    const btnCtx = document.getElementById("marius-context-btn");
    if (btnCtx) btnCtx.addEventListener("click", showMariusContext);
    const btnChatCtx = document.getElementById("marius-chat-context-btn");
    if (btnChatCtx) btnChatCtx.addEventListener("click", showMariusContext);
    
    const input = document.getElementById("marius-chat-input");
    if (input) {
      input.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMariusChat();
        }
      });
    }

    const selProf = document.getElementById("marius-chat-profile-select");
    if (selProf) {
      selProf.addEventListener("change", async (e) => {
        await requestJson(`${MCH}/agents/marius/model/profile`, { method: "POST", body: { profile: e.target.value } });
        refreshMariusStatus();
      });
    }
    
    const selMod = document.getElementById("marius-chat-model-select");
    if (selMod) {
      selMod.addEventListener("change", async (e) => {
        await requestJson(`${MCH}/agents/marius/model/set`, { method: "POST", body: { model: e.target.value } });
        refreshMariusStatus();
      });
    }

    // Attempt initial status refresh
    refreshMariusStatus();
  }

  // Init
  // ─── Command Center dashboard ────────────────────────────────────────────

  function timeAgo(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (diffSec < 60) return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 30) return `${diffDay}d ago`;
    return new Date(iso).toLocaleDateString();
  }

  const CC_TYPE_BADGE = {
    webpage: { label: "Webpage", cls: "cc-badge-web" },
    selection: { label: "Selection", cls: "cc-badge-selection" },
    youtube: { label: "YouTube", cls: "cc-badge-youtube" },
    pdf: { label: "PDF", cls: "cc-badge-pdf" },
    mail: { label: "Mail", cls: "cc-badge-mail" },
  };

  function ccSourceTypeOf(source) {
    let tags = source.tags;
    if (typeof tags === "string") {
      try {
        const parsed = JSON.parse(tags);
        tags = Array.isArray(parsed) ? parsed : String(tags).split(/[\s,]+/);
      } catch (_) {
        tags = tags.split(/[\s,]+/);
      }
    }
    tags = Array.isArray(tags) ? tags : [];
    if (tags.includes("video")) return "youtube";
    const found = tags.find((t) => CC_TYPE_BADGE[t]);
    return found || "webpage";
  }

  function ccAskMariusAbout(label) {
    const input = document.getElementById("cc-ask-input");
    if (input) {
      input.value = `Tell me about "${label}"`;
      input.focus();
    }
    document.querySelector(".cc-ask-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function loadCommandCenterCaptures() {
    const el = document.getElementById("cc-captures-list");
    if (!el) return;
    try {
      const data = await requestJson(`${MCH}/warden/brain/sources?limit=6`);
      const sources = data.sources || [];
      if (!sources.length) {
        el.innerHTML = `<div class="cc-empty">
          <p>No captures yet.</p>
          <p class="muted">Install <strong>Warden Watcher</strong> and save a page, selection, or video — it'll show up here.</p>
        </div>`;
        return;
      }
      el.innerHTML = sources.map((s) => {
        const type = ccSourceTypeOf(s);
        const badge = CC_TYPE_BADGE[type] || CC_TYPE_BADGE.webpage;
        const title = escapeHtml(s.title || s.path || "Untitled");
        return `<div class="cc-row">
          <div class="cc-row-main">
            <span class="cc-type-badge ${badge.cls}">${badge.label}</span>
            <span class="cc-row-title" title="${title}">${title}</span>
          </div>
          <div class="cc-row-meta">
            <span class="muted">${escapeHtml(timeAgo(s.indexed_at))}</span>
            <button type="button" class="btn cc-mini-btn" data-cc-ask="${title}">Ask Marius</button>
          </div>
        </div>`;
      }).join("");
      el.querySelectorAll("[data-cc-ask]").forEach((btn) => {
        btn.addEventListener("click", () => ccAskMariusAbout(btn.getAttribute("data-cc-ask")));
      });
    } catch (e) {
      el.innerHTML = `<div class="cc-empty"><p class="muted">Brain vault isn't reachable yet.</p></div>`;
    }
  }

  async function loadCommandCenterConnections() {
    const el = document.getElementById("cc-connections-list");
    const strip = document.getElementById("cc-status-strip");
    if (!el) return;
    try {
      const [accountsRes, brainRes] = await Promise.all([
        requestJson(`${MCH}/warden/connectors/accounts`).catch(() => ({ accounts: [] })),
        requestJson(`${MCH}/warden/brain/health`).catch(() => null),
      ]);
      const accounts = accountsRes.accounts || [];
      const rows = [];
      const vaultOk = !!(brainRes && brainRes.local && brainRes.local.vault_exists);
      rows.push({
        label: "Local Brain vault",
        ok: !!vaultOk,
        detail: vaultOk ? "Indexed & ready" : "Not initialized",
      });
      if (brainRes && brainRes.hybrid_enabled) {
        rows.push({ label: "Google Brain mirror", ok: true, detail: "Enabled" });
      }
      if (!accounts.length) {
        rows.push({ label: "Mail accounts", ok: false, detail: "None connected — add in Settings" });
      } else {
        accounts.forEach((a) => {
          rows.push({
            label: `${a.provider || "account"} · ${a.display_email || a.account_id || ""}`,
            ok: a.status === "connected" || a.status === "active",
            detail: a.status || "unknown",
          });
        });
      }
      el.innerHTML = rows.map((r) => `<div class="cc-row">
        <div class="cc-row-main">
          <span class="cc-dot ${r.ok ? "cc-dot-good" : "cc-dot-warn"}"></span>
          <span class="cc-row-title">${escapeHtml(r.label)}</span>
        </div>
        <span class="muted cc-row-meta">${escapeHtml(r.detail)}</span>
      </div>`).join("");

      if (strip) {
        const connectedCount = accounts.filter((a) => a.status === "connected" || a.status === "active").length;
        strip.innerHTML = [
          `<span class="cc-strip-item ${vaultOk ? "good" : "warn"}">● Brain ${vaultOk ? "ready" : "not set up"}</span>`,
          `<span class="cc-strip-item ${connectedCount ? "good" : "muted"}">● ${connectedCount} mail account${connectedCount === 1 ? "" : "s"} connected</span>`,
        ].join("");
      }
    } catch (e) {
      el.innerHTML = `<p class="muted">Could not load connection status.</p>`;
    }
  }

  function renderCommandCenterTrace() {
    const el = document.getElementById("cc-trace-list");
    if (!el) return;
    const items = (state.recentEvidence || []).slice(0, 5);
    if (!items.length) {
      el.innerHTML = `<div class="cc-empty"><p class="muted">No proof recorded yet. Once an agent runs or a capture is saved, it shows up here.</p></div>`;
      return;
    }
    el.innerHTML = items.map((ev) => {
      const label = ev.title || ev.kind || ev.evidence_type || "Run artifact";
      const ok = ev.status ? ev.status !== "failed" && ev.status !== "error" : true;
      return `<div class="cc-row">
        <div class="cc-row-main">
          <span class="cc-dot ${ok ? "cc-dot-good" : "cc-dot-bad"}"></span>
          <span class="cc-row-title">${escapeHtml(label)}</span>
        </div>
        <span class="muted cc-row-meta">${escapeHtml(timeAgo(ev.created_at || ev.timestamp))}</span>
      </div>`;
    }).join("");
  }

  function renderCommandCenterNextAction() {
    const el = document.getElementById("cc-next-action");
    if (!el) return;
    const accounts = (state.cc && state.cc.accounts) || [];
    let suggestion;
    if (!accounts.length) {
      suggestion = { text: "Connect Gmail or iCloud so Marius can search your mail.", cta: "Open Settings", section: "settings" };
    } else if (!(state.recentEvidence || []).length) {
      suggestion = { text: "Save your first page with Warden Watcher to build up Brain memory.", cta: "Open Settings", section: "settings" };
    } else {
      suggestion = { text: "Ask Marius what changed recently, or open the plan builder for multi-step work.", cta: "Ask Marius", section: null };
    }
    el.innerHTML = `<div class="cc-next">
      <p>${escapeHtml(suggestion.text)}</p>
      <button type="button" class="btn primary" id="cc-next-cta">${escapeHtml(suggestion.cta)}</button>
    </div>`;
    document.getElementById("cc-next-cta")?.addEventListener("click", () => {
      if (suggestion.section) setActiveSection(suggestion.section);
      else document.getElementById("cc-ask-input")?.focus();
    });
  }

  async function loadCommandCenter() {
    state.cc = state.cc || {};
    await Promise.all([loadCommandCenterCaptures(), loadCommandCenterConnections()]);
    renderCommandCenterTrace();
    try {
      const accountsRes = await requestJson(`${MCH}/warden/connectors/accounts`);
      state.cc.accounts = accountsRes.accounts || [];
    } catch (e) {
      state.cc.accounts = [];
    }
    renderCommandCenterNextAction();
  }

  function wireCommandCenter() {
    const form = document.getElementById("cc-ask-form");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.getElementById("cc-ask-input");
      const replyEl = document.getElementById("cc-ask-reply");
      const msg = (input.value || "").trim();
      if (!msg) return;
      const submitBtn = form.querySelector(".cc-ask-submit");
      if (submitBtn) submitBtn.disabled = true;
      replyEl.style.display = "block";
      replyEl.innerHTML = `<p class="muted">Marius is thinking…</p>`;
      try {
        const res = await requestJson(`${MCH}/agents/marius/chat`, {
          method: "POST",
          body: { message: msg, workspace: null },
        });
        if (res && res.ok && res.data) {
          replyEl.innerHTML = `<div class="cc-ask-answer">${escapeHtml(res.data.response)}</div>
            <div class="cc-ask-footer muted">${escapeHtml(res.data.model || "")}</div>`;
        } else {
          replyEl.innerHTML = `<p class="cc-ask-error">Marius couldn't answer that: ${escapeHtml((res && res.error) || "unknown error")}</p>`;
        }
      } catch (e) {
        replyEl.innerHTML = `<p class="cc-ask-error">Marius is offline right now. Try again in a moment.</p>`;
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  async function init() {
    // Hide any remaining old complex UI elements (from previous full cockpit) - force SIMPLE MODE
    const oldSelectors = [".rail", ".panel", "#sessions-list", "#queue-list", "#artifact-list", "#evidence-list", "#gate-list", "#safety-list", "#log-hint", "section.layout-stack", "main.panel"];
    oldSelectors.forEach((sel) => {
      document.querySelectorAll(sel).forEach((el) => {
        if (el.id && (el.id.includes("modal") || el.id === "codex-card" || el.id === "marius-card" || el.id.includes("use-agent"))) return;
        el.style.display = "none";
      });
    });
    document.querySelectorAll("body > section.layout-stack, body > div.layout-stack").forEach((el) => {
      el.style.display = "none";
    });

    // Onboarding card dismiss
    const onboardingCard = document.getElementById("warden-onboarding-card");
    const onboardingDismiss = document.getElementById("onboarding-dismiss-btn");
    if (onboardingDismiss && onboardingCard) {
      if (sessionStorage.getItem("warden-onboarding-dismissed")) {
        onboardingCard.style.display = "none";
      }
      onboardingDismiss.addEventListener("click", () => {
        onboardingCard.style.display = "none";
        sessionStorage.setItem("warden-onboarding-dismissed", "1");
      });
    }

    wireSimpleUI();
    wireMariusEvents(); // Initialize Marius UI bindings
    wireMailTestPanel();
    wireBrainVaultSettings();
    wireCommandCenter();
    if (window.WardenControlRoom && window.WardenControlRoom.init) {
      window.WardenControlRoom.init();
    }
    setActiveSection("mission");
    await Promise.all([loadLibraryStatus(), loadCaptainDeckStatus(), loadRecentRuns(), loadRecentEvidence(), loadActiveCaptainPlan(), loadMissionWorklog(), loadRecentGates()]);
    if (window.WardenControlRoom && window.WardenControlRoom.refresh) {
      await window.WardenControlRoom.refresh({ quiet: true });
    }
    loadCommandCenter().catch((e) => console.error("command center load error", e));
    loadBrainVaultSettings().catch((e) => console.error("brain vault settings load error", e));

    // initial status check for disabled note etc is handled in deploy
    // If user has runner flags in this process (e.g. private), card will reflect Ready
  }

  // expose a couple for console/manual if needed
  window.McHarnessSimple = { deployPrompt, openUseAgentModal, openLiveCLIMonitor, refreshLiveMonitor };
  window.WardenApp = { setActiveSection, openCaptainDeckModal, openLiveCLIMonitor };

  // boot
  init().catch((e) => console.error("init error", e));
})();
