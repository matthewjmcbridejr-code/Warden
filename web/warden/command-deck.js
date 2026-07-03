const API_BASE = "/api/mcharness/warden/command-deck";
const NOTION_SYNC_BASE = "/api/mcharness/warden/notion/sync";
const COLUMNS = [
  ["posted", "Posted"],
  ["claimed", "Claimed"],
  ["working", "Working"],
  ["proof_needed", "Proof Needed"],
  ["verified", "Verified"],
  ["blocked", "Blocked"],
];
const DEFAULT_AGENTS = [
  { id: "claude", name: "Claude", role: "Planning", status: "standby", summary: "Turns messy goals into scoped missions and handoffs." },
  { id: "codex", name: "Codex", role: "Coding", status: "standby", summary: "Implements repo changes, runs checks, and records proof." },
  { id: "gemini", name: "Gemini", role: "Review", status: "standby", summary: "Reviews architecture, risk, and second-pass reasoning." },
  { id: "local", name: "Local Agents", role: "Server/Ops", status: "standby", summary: "Handles local models, ingest, services, and safe automation." },
];

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function list(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function safePath(value) {
  const text = String(value ?? "");
  return text.replace(/\/home\/[^/\s]+/g, "~").replace(/\/root/g, "~");
}

function taskStatus(task) {
  if (task.proof_gate === "proof_needed") return "proof_needed";
  if (task.proof_gate === "verified" || task.proof || task.proof_id) return "verified";
  if (task.failure || task.status === "failed") return "blocked";
  if (task.status === "claimed") return "claimed";
  if (task.status === "running") return "working";
  if (task.status === "needs_review") return "proof_needed";
  if (task.status === "completed" || task.status === "done") return "proof_needed";
  return "posted";
}

function normalizeState(state = {}, proofPayload = {}, relayPayload = {}) {
  const columns = Object.fromEntries(COLUMNS.map(([key]) => [key, []]));
  let missions = [];
  if (state.columns) {
    for (const [key] of COLUMNS) {
      columns[key] = list(state.columns[key]);
      missions = missions.concat(columns[key]);
    }
  } else {
    missions = list(state.tasks).map((task) => ({
      id: task.id || task.task_id,
      title: task.title || "Untitled mission",
      summary: task.description || task.summary || task.project || "No summary recorded.",
      status: taskStatus(task),
      assigned_agent: task.assigned_agent || task.agent || "Unassigned",
      source: task.source || "Warden board",
      branch: task.branch || "",
      repo: task.repo || task.project || "Warden",
      files_changed: list(task.files_changed || task.proof?.files_changed),
      files_inspected: list(task.files_inspected),
      risk_level: task.risk_level || task.risk || "read_only",
      proof_required: task.proof_required !== false,
      proof_gate: task.proof_gate,
      demo: list(task.tags).includes("demo"),
    }));
    for (const mission of missions) columns[mission.status]?.push(mission);
  }
  const proofs = list(state.proofs).concat(list(proofPayload.proofs));
  const relay = list(state.relay).concat(list(state.events), list(relayPayload.relay), list(relayPayload.events));
  const summary = state.summary || {};
  return {
    ...state,
    agents: list(state.agents).length ? state.agents : DEFAULT_AGENTS,
    columns,
    missions,
    proofs,
    relay,
    demo_mode: Boolean(state.demo_mode || missions.some((item) => item.demo)),
    stats: state.stats || {
      active_missions: missions.filter((item) => !["verified", "blocked"].includes(item.status)).length,
      agents_online: DEFAULT_AGENTS.length,
      proofs_recorded: proofs.length,
      blocked_tasks: summary.failed ?? columns.blocked.length,
    },
    brain_panel: state.brain_panel || {
      summary: "Command Deck reads Warden board tasks, proof closeouts, and relay events. Seed a demo mission to verify the loop.",
      context_sources: ["Warden Board", "Proof Ledger", "Relay Timeline"],
    },
  };
}

function renderStats(stats = {}) {
  $("stat-active").textContent = stats.active_missions ?? 0;
  $("stat-agents").textContent = stats.agents_online ?? DEFAULT_AGENTS.length;
  $("stat-proofs").textContent = stats.proofs_recorded ?? 0;
  $("stat-blocked").textContent = stats.blocked_tasks ?? 0;
}

function renderAgents(agents = []) {
  $("agent-grid").innerHTML = agents.map((agent) => `
    <article class="agent-card">
      <span class="agent-status">${esc(agent.status || "standby")}</span>
      <h3>${esc(agent.name)}</h3>
      <div class="agent-role">${esc(agent.role)}</div>
      <p>${esc(agent.summary)}</p>
    </article>
  `).join("");
}

function renderMission(mission) {
  const files = [...list(mission.files_changed), ...list(mission.files_inspected)].slice(0, 3).map(safePath);
  return `
    <article class="mission-card">
      <div class="card-meta">
        <span class="chip ${esc(mission.status)}">${esc(String(mission.status || "").replaceAll("_", " "))}</span>
        <span class="chip">${esc(mission.assigned_agent || "Unassigned")}</span>
      </div>
      <h3>${esc(mission.title)}</h3>
      <p>${esc(mission.summary || mission.project || "No summary recorded.")}</p>
      <div class="card-meta">
        <span class="chip">${esc(mission.risk_level || "read_only")}</span>
        <span class="chip">${esc(mission.branch || "no branch")}</span>
      </div>
      ${files.length ? `<p>${files.map(esc).join(" · ")}</p>` : ""}
    </article>
  `;
}

function renderBoard(columns = {}) {
  $("mission-board").innerHTML = COLUMNS.map(([key, label]) => {
    const missions = columns[key] || [];
    return `
      <section class="mission-column">
        <div class="column-title"><span>${label}</span><span>${missions.length}</span></div>
        ${missions.length ? missions.map(renderMission).join("") : `<div class="empty-card">No missions</div>`}
      </section>
    `;
  }).join("");
}

function renderProofs(proofs = []) {
  $("proof-ledger").innerHTML = proofs.length ? proofs.map((proof) => `
    <article class="proof-card">
      <div class="card-meta">
        <span class="chip verified">${esc(proof.kind || proof.type || "proof")}</span>
        <span class="chip">${esc(proof.agent || proof.agent_id || "Warden")}</span>
      </div>
      <h3>${esc(proof.title || proof.summary || "Proof recorded")}</h3>
      <p>${esc(proof.summary || proof.notes || proof.content || "Proof closeout recorded.")}</p>
      ${list(proof.tests_run).length ? `<p>Tests: ${list(proof.tests_run).map(esc).join(" · ")}</p>` : ""}
    </article>
  `).join("") : `<div class="empty-card">No proof recorded yet. Missions stay in Proof Needed until evidence exists.</div>`;
}

function renderRelay(relay = []) {
  $("relay-timeline").innerHTML = relay.length ? relay.map((item) => `
    <article class="relay-card">
      <div class="card-meta">
        <span class="chip">${esc(item.from_agent || item.agent || "Warden")}</span>
        <span class="chip">${esc(item.to_agent || item.target_agent || "Agent")}</span>
      </div>
      <h3>${esc(item.reason || item.title || item.event || "Relay event")}</h3>
      <p>${esc(item.context_summary || item.summary || item.note || item.message || "Agent handoff recorded.")}</p>
      <p>Proof required: ${esc(item.proof_required || "Not specified")}</p>
    </article>
  `).join("") : `<div class="empty-card">No handoffs recorded yet.</div>`;
}

function renderBrain(panel = {}, state = {}) {
  // Legacy: no-op — chat panel owns brain display now
}

// ---------------------------------------------------------------------------
// Memory Chat Agent
// ---------------------------------------------------------------------------

const MEMORY_AGENT_BASE = "/api/mcharness/warden/memory-agent";
let _chatHistory = [];  // {role, content}[]

function appendChatBubble(role, text, isThinking = false) {
  const log = $("memory-chat-log");
  const empty = log.querySelector(".chat-empty");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = `chat-bubble ${isThinking ? "thinking" : role}`;
  div.dataset.role = role;
  // Render newlines and simple markdown-ish formatting
  div.innerHTML = isThinking
    ? esc(text)
    : formatChatText(text);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function formatChatText(text) {
  // Basic: escape HTML, then restore newlines and bold
  return esc(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

function updateContextBar(snapshot = {}) {
  const bar = $("memory-chat-context");
  if (!bar) return;
  const chips = [
    { key: "commits", label: `git (${snapshot.commits || 0})`, field: "commits" },
    { key: "shell_commands", label: `shell (${snapshot.shell_commands || 0})`, field: "shell_commands" },
    { key: "browser_visits", label: `chrome (${snapshot.browser_visits || 0})`, field: "browser_visits" },
    { key: "board_tasks", label: `board (${snapshot.board_tasks || 0})`, field: "board_tasks" },
    { key: "memories", label: `memories (${snapshot.memory_count || snapshot.memories || 0})`, field: "memories" },
  ];
  bar.innerHTML = chips.map(c =>
    `<span class="ctx-chip ${(snapshot[c.field] || 0) > 0 ? "has-data" : ""}">${esc(c.label)}</span>`
  ).join("");
  if (snapshot.branch) {
    bar.innerHTML += `<span class="ctx-chip has-data">${esc(snapshot.branch)}</span>`;
  }
}

async function sendMemoryChat(message) {
  if (!message.trim()) return;

  appendChatBubble("user", message);
  _chatHistory.push({ role: "user", content: message });

  const thinking = appendChatBubble("assistant", "Analyzing your memory sources…", true);
  const sendBtn = $("brain-send");
  if (sendBtn) sendBtn.disabled = true;

  try {
    const resp = await fetch(`${MEMORY_AGENT_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        history: _chatHistory.slice(0, -1),  // exclude current message (already sent as `message`)
        model: null,
      }),
    });
    const data = await resp.json();
    thinking.remove();

    if (data.ok) {
      const reply = data.reply || "No answer returned.";
      appendChatBubble("assistant", reply);
      _chatHistory.push({ role: "assistant", content: reply });

      // Update status badges
      const modelBadge = $("brain-model");
      const srcBadge = $("brain-sources");
      if (modelBadge) modelBadge.textContent = data.fallback ? "fallback" : (data.model_used || "?");
      if (srcBadge) srcBadge.textContent = (data.sources || []).join(" · ") || "no sources";

      updateContextBar(data.context_snapshot || {});
    } else {
      appendChatBubble("assistant", `Error: ${data.detail || data.error || "Unknown error"}`);
    }
  } catch (err) {
    thinking.remove();
    appendChatBubble("assistant", `Failed to reach Memory Agent: ${err.message}`);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}

async function loadMemoryContext() {
  try {
    const ctx = await fetch(`${MEMORY_AGENT_BASE}/context`).then(r => r.json());
    if (ctx.ok) updateContextBar({
      ...ctx,
      commits: (ctx.recent_commits || []).length,
      shell_commands: (ctx.shell_commands || []).length,
      browser_visits: (ctx.browser_visits || []).length,
      board_tasks: (ctx.board_tasks || []).length,
      memories: ctx.memory_count || 0,
    });
  } catch (_) {}
}

function initMemoryChat() {
  const log = $("memory-chat-log");
  if (log && log.children.length === 0) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.innerHTML = "Ask me anything about your work.<br><small>I can see your git history, shell commands, browser activity, tasks, and stored memories.</small>";
    log.appendChild(empty);
  }

  const form = $("memory-chat-form");
  const input = $("brain-query");

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const msg = input?.value?.trim();
      if (!msg) return;
      if (input) input.value = "";
      sendMemoryChat(msg);
    });
  }

  // Prompt chips
  document.querySelectorAll(".prompt-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.q;
      if (input) input.value = "";
      sendMemoryChat(q);
    });
  });
}


async function fetchJson(path, options = {}) {
  const { base, ...fetchOpts } = options;
  const url = `${base || API_BASE}${path}`;
  const response = await fetch(url, { headers: { "Accept": "application/json", "Content-Type": "application/json" }, ...fetchOpts });
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`);
  return response.json();
}

async function loadDeck() {
  const [rawState, proofs, relay] = await Promise.all([
    fetchJson("/state"),
    fetchJson("/proofs").catch(() => ({ proofs: [] })),
    fetchJson("/relay").catch(() => ({ events: [] })),
  ]);
  const state = normalizeState(rawState, proofs, relay);
  renderStats(state.stats);
  renderAgents(state.agents);
  renderBoard(state.columns);
  renderProofs(state.proofs);
  renderRelay(state.relay);
  renderBrain(state.brain_panel, state);
  $("deck-mode").textContent = state.demo_mode ? "Demo Data" : "Live";
  $("last-refresh").textContent = `Last refresh ${new Date().toLocaleTimeString()}`;
}

async function seedDemo() {
  $("seed-demo").disabled = true;
  try {
    await fetchJson("/demo-seed", { method: "POST", body: JSON.stringify({ title: "Demo Mission", description: "Demonstrate Warden Command Deck dispatch loop.", agent: "codex", priority: "medium" }) });
    await loadDeck();
    await previewNotionSync();
  } finally {
    $("seed-demo").disabled = false;
  }
}

function renderNotionSyncPreview(result = {}) {
  const summary = $("notion-sync-summary");
  const results = $("notion-sync-results");
  if (!summary || !results) return;
  setText("notion-sync-mode", result.write_enabled ? "Writes Enabled" : "Dry Run");
  summary.innerHTML = `
    <div class="sync-stat"><span>Found</span><strong>${esc(result.candidates_found ?? 0)}</strong></div>
    <div class="sync-stat"><span>Would Create</span><strong>${esc(result.would_create_count ?? 0)}</strong></div>
    <div class="sync-stat"><span>Would Skip</span><strong>${esc(result.would_skip_count ?? 0)}</strong></div>
  `;
  const candidates = list(result.would_create).slice(0, 6);
  results.innerHTML = candidates.length ? candidates.map((candidate) => `
    <article class="proof-card notion-candidate">
      <div class="card-meta">
        <span class="chip ${esc(candidate.proof_status || "proof_needed")}">${esc(String(candidate.proof_status || "proof_needed").replaceAll("_", " "))}</span>
        <span class="chip">${esc(candidate.agent || "unassigned")}</span>
        <span class="chip">${esc(candidate.priority || "medium")}</span>
      </div>
      <h3>${esc(candidate.title || "Untitled candidate")}</h3>
      <p>${esc(candidate.ai_summary || "No summary recorded.")}</p>
      <p>${esc(safePath(candidate.repo_path || candidate.project || "Warden"))}</p>
    </article>
  `).join("") : `<div class="empty-card">No candidate tasks. Command Deck will preview Notion inbox rows after local board tasks exist.</div>`;
}

async function loadNotionSyncStatus() {
  try {
    const status = await fetchJson("/status", { base: NOTION_SYNC_BASE });
    setText("notion-sync-mode", status.write_enabled ? "Writes Enabled" : "Dry Run");
  } catch (err) {
    setText("notion-sync-mode", "Unavailable");
  }
}

async function previewNotionSync() {
  const button = $("preview-notion-sync");
  if (button) button.disabled = true;
  try {
    const result = await fetchJson("/dry-run", { base: NOTION_SYNC_BASE, method: "POST", body: JSON.stringify({ existing_candidates: [] }) });
    renderNotionSyncPreview(result);
  } catch (err) {
    const results = $("notion-sync-results");
    if (results) results.innerHTML = `<div class="empty-card">${esc(err.message)}</div>`;
  } finally {
    if (button) button.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Workspace Authority panel
// ---------------------------------------------------------------------------

async function loadWorkspaceAuthority() {
  try {
    const data = await fetchJson("/warden/workspaces/warden", { base: "/api/mcharness" });
    const p = data.project || {};
    const canonical = p.canonical_repo || "—";
    const service = (p.live_services || [])[0];
    const scratchWts = (p.known_worktrees || []).filter(w => !w.safe_to_edit);
    const proofCmds = p.proof_commands || [];

    setText("ws-canonical", canonical);
    setText("ws-service", service ? `${service.name} — ${service.url}` : "—");
    setText("ws-safe", "✓ Yes");
    setText("ws-drift", "None");
    setText("workspace-status-pill", "Canonical");
    $("workspace-status-pill").style.background = "#1a4731";
    $("workspace-status-pill").style.color = "#4ade80";

    const scratchList = $("ws-scratch-list");
    scratchList.innerHTML = scratchWts.length
      ? scratchWts.map(w => `<li><code>${esc(w.path)}</code> <span class="ws-tag">${esc(w.role)}</span></li>`).join("")
      : "<li>None registered.</li>";

    const cmdList = $("ws-proof-cmds");
    cmdList.innerHTML = proofCmds.length
      ? proofCmds.map(c => `<li><code>${esc(c)}</code></li>`).join("")
      : "<li>None configured.</li>";
  } catch (err) {
    setText("workspace-status-pill", "Error");
    setText("ws-canonical", err.message || "Could not load");
  }
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

$("refresh-deck").addEventListener("click", () => { loadDeck(); loadWorkspaceAuthority(); previewNotionSync(); loadMemoryContext(); });
$("seed-demo").addEventListener("click", seedDemo);
$("preview-notion-sync").addEventListener("click", previewNotionSync);

loadDeck().catch((error) => {
  $("mission-board").innerHTML = `<div class="empty-card">${esc(error.message)}</div>`;
});
loadWorkspaceAuthority().catch(() => {});
loadNotionSyncStatus().catch(() => {});
previewNotionSync().catch(() => {});
initMemoryChat();
loadMemoryContext().catch(() => {});

setInterval(() => {
  loadDeck().catch(() => {});
}, 5000);
