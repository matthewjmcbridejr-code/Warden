/* Warden Model Gateway Control Room */
(function () {
  "use strict";
  const MCH = "/api/mcharness";

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function escHtml(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }
  async function api(path, opts) {
    const res = await fetch(path, { headers: {"Content-Type":"application/json"}, ...opts });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /* ── Provider status cards ── */
  const PROVIDER_ICONS = {
    "Ollama": "⬡", "Groq": "⚡", "Cerebras": "⬢",
    "OpenRouter": "⊕", "HuggingFace": "🤗", "Tavily": "⊞",
    "Crawl4AI": "⎋", "LiteLLM Gateway": "⬡",
  };
  const STATUS_CLASSES = {
    "reachable": "gw-status-ok", "configured": "gw-status-ok",
    "unreachable": "gw-status-err", "no-key": "gw-status-warn",
    "degraded": "gw-status-warn",
  };

  async function loadProviders() {
    const el = qs("#gw-providers");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/status`);
      el.innerHTML = (d.providers || []).map(p => {
        const sc = STATUS_CLASSES[p.status] || "gw-status-warn";
        const icon = PROVIDER_ICONS[p.provider] || "•";
        const lat = p.latency_ms != null ? `<span class="gw-lat">${p.latency_ms}ms</span>` : "";
        return `
          <div class="gw-provider-card ${sc}">
            <div class="gw-provider-top">
              <span class="gw-provider-icon">${icon}</span>
              <span class="gw-provider-name">${escHtml(p.provider)}</span>
              ${lat}
              <span class="gw-status-dot"></span>
            </div>
            <div class="gw-provider-status">${escHtml(p.status)}</div>
            <div class="gw-provider-note">${escHtml(p.note || "")}</div>
          </div>`;
      }).join("");
    } catch(e) {
      el.innerHTML = `<div class="gw-err">Failed to load providers: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── Alias table ── */
  const ALIAS_COLORS = {
    "warden-local":  "#4a7a4a",
    "warden-fast":   "#4a6a8a",
    "warden-free":   "#7a6a20",
    "warden-code":   "#6a4a8a",
    "warden-deep":   "#8a2a2a",
    "warden-embed":  "#2a6a6a",
  };
  const PRIVACY_CHIPS = {
    "private": "🔒 private",
    "public-safe-only": "⚠ public-safe only",
  };

  async function loadAliases() {
    const el = qs("#gw-aliases");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/aliases`);
      el.innerHTML = Object.entries(d.aliases || {}).map(([name, def]) => {
        const color = ALIAS_COLORS[name] || "#444";
        const privacy = PRIVACY_CHIPS[def.privacy] || def.privacy;
        const orBlocked = !def.openrouter_free_allowed
          ? '<span class="gw-chip gw-chip-block">OR free ✗</span>'
          : '<span class="gw-chip gw-chip-allow">OR free ✓</span>';
        const cloud = def.cloud_allowed
          ? '<span class="gw-chip gw-chip-allow">cloud ✓</span>'
          : '<span class="gw-chip gw-chip-block">cloud ✗</span>';
        const tier = def.cost_tier === "free" ? "🟢 free"
          : def.cost_tier === "free-tier" ? "🟡 free tier"
          : "🔴 paid";
        return `
          <div class="gw-alias-card" style="border-left-color:${color}">
            <div class="gw-alias-top">
              <span class="gw-alias-name" style="color:${color}">${escHtml(name)}</span>
              <span class="gw-alias-label">${escHtml(def.label)}</span>
              <span class="gw-alias-tier">${tier}</span>
            </div>
            <div class="gw-alias-desc">${escHtml(def.description)}</div>
            <div class="gw-alias-row">
              <span class="gw-alias-field"><b>Primary:</b> ${escHtml(def.primary_provider)}</span>
              <span class="gw-alias-field"><b>Fallback:</b> ${escHtml(def.fallback_provider)}</span>
              <span class="gw-alias-field"><b>Context:</b> ${(def.max_context_tokens||0).toLocaleString()} tok</span>
            </div>
            <div class="gw-alias-chips">
              <span class="gw-chip gw-chip-privacy">${privacy}</span>
              ${cloud}
              ${orBlocked}
            </div>
            <div class="gw-alias-uses">${(def.use_cases||[]).map(u=>`<span class="gw-use-chip">${escHtml(u)}</span>`).join("")}</div>
            ${def.warning ? `<div class="gw-alias-warning">⚠ ${escHtml(def.warning)}</div>` : ""}
          </div>`;
      }).join("");
    } catch(e) {
      el.innerHTML = `<div class="gw-err">Failed to load aliases: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── Routing Simulator ── */
  const CONF_BARS = (c) => {
    const pct = Math.round(c * 100);
    const color = pct >= 80 ? "#4a7a4a" : pct >= 60 ? "#7a6a20" : "#7a4a2a";
    return `<div class="gw-conf-bar"><div class="gw-conf-fill" style="width:${pct}%;background:${color}"></div></div>`;
  };

  async function runSimulator() {
    const input = qs("#gw-sim-input");
    const result = qs("#gw-sim-result");
    const btn = qs("#gw-sim-btn");
    if (!input || !result) return;
    const task = input.value.trim();
    if (!task) return;
    btn.disabled = true;
    btn.textContent = "Routing…";
    result.style.display = "none";
    try {
      const d = await api(`${MCH}/warden/model-gateway/route-preview`, {
        method: "POST",
        body: JSON.stringify({ task }),
      });
      const aliasColor = ALIAS_COLORS[d.alias] || "#555";
      const privacyIcon = d.privacy === "private" ? "🔒" : "⚠";
      const orBlock = d.openrouter_free_blocked
        ? '<span class="gw-chip gw-chip-block">OR free blocked</span>' : "";
      const warnings = (d.warnings||[]).map(w => `<div class="gw-sim-warn">⚠ ${escHtml(w)}</div>`).join("");
      const tools = (d.likely_tools||[]).map(t=>`<span class="gw-use-chip">${escHtml(t)}</span>`).join("") || "—";
      result.innerHTML = `
        <div class="gw-sim-alias" style="color:${aliasColor}">${escHtml(d.alias)}</div>
        <div class="gw-sim-reason">${escHtml(d.reason)}</div>
        ${CONF_BARS(d.confidence)}
        <div class="gw-sim-grid">
          <div><b>Confidence</b><br>${Math.round(d.confidence*100)}%</div>
          <div><b>Classifier</b><br>${escHtml(d.classifier_used)}</div>
          <div><b>Privacy</b><br>${privacyIcon} ${escHtml(d.privacy)}</div>
          <div><b>Est. tokens in</b><br>${(d.estimated_input_tokens||0).toLocaleString()}</div>
          <div><b>Token budget</b><br>${(d.token_budget||0).toLocaleString()}</div>
          <div><b>Tokens after budget</b><br>${(d.estimated_tokens_after_budget||0).toLocaleString()}</div>
          <div><b>Saved</b><br>${d.pct_saved||0}%</div>
          <div><b>Primary</b><br>${escHtml(d.primary_provider||"—")}</div>
          <div><b>Fallback</b><br>${escHtml(d.fallback_provider||"—")}</div>
        </div>
        <div class="gw-sim-tools-row"><b>Likely tools:</b> ${tools}</div>
        ${orBlock}
        ${warnings}
      `;
      result.style.display = "";
    } catch(e) {
      result.innerHTML = `<div class="gw-err">Error: ${escHtml(e.message)}</div>`;
      result.style.display = "";
    } finally {
      btn.disabled = false;
      btn.textContent = "Preview Route";
    }
  }

  /* ── Context Budget Inspector ── */
  const STATUS_ICONS = { kept: "✓", dropped: "✗", compressed: "⟳", pending: "?" };
  const SOURCE_COLORS = {
    memory: "#7a4d7a", git: "#4d7a4d", github: "#5a5aad",
    tool: "#7a6a20", message: "#4a6a8a", system: "#555",
  };

  async function runContextInspector() {
    const input = qs("#gw-ctx-input");
    const aliasEl = qs("#gw-ctx-alias");
    const result = qs("#gw-ctx-result");
    const btn = qs("#gw-ctx-btn");
    if (!input || !result) return;
    const query = input.value.trim();
    if (!query) return;
    btn.disabled = true;
    btn.textContent = "Inspecting…";
    result.style.display = "none";
    try {
      const d = await api(`${MCH}/warden/model-gateway/context-preview`, {
        method: "POST",
        body: JSON.stringify({
          query,
          alias: aliasEl?.value || null,
          system_prompt: "You are Warden, a senior engineering assistant.",
          memories: [
            { summary: "Decided to use LiteLLM as the unified gateway layer.", kind: "decision" },
            { summary: "Memory agent context dump causes token bloat on every turn.", kind: "failure" },
            { summary: "qwen3:0.6b is available locally and works for classification.", kind: "proof" },
          ],
          git_context: "feat/marius-resident-core\nace35c3 feat(warden): WardenAgent tool-calling loop\n193c4e2 feat(memory): add Pieces OS-style memory panel",
        }),
      });
      const saved = d.pct_saved || 0;
      const savedColor = saved > 30 ? "#4a7a4a" : saved > 0 ? "#7a6a20" : "#555";
      const items = d.items || [];
      const kept = items.filter(i=>i.status==="kept").length;
      const dropped = items.filter(i=>i.status==="dropped").length;
      const compressed = items.filter(i=>i.status==="compressed").length;

      result.innerHTML = `
        <div class="gw-ctx-summary">
          <span class="gw-ctx-stat"><b>Budget</b> ${(d.token_budget||0).toLocaleString()} tok</span>
          <span class="gw-ctx-stat"><b>Before</b> ${(d.tokens_before||0).toLocaleString()} tok</span>
          <span class="gw-ctx-stat"><b>After</b> ${(d.tokens_after||0).toLocaleString()} tok</span>
          <span class="gw-ctx-stat" style="color:${savedColor}"><b>Saved</b> ${saved}%</span>
          <span class="gw-ctx-stat">✓ ${kept} kept &nbsp; ✗ ${dropped} dropped &nbsp; ⟳ ${compressed} compressed</span>
        </div>
        <div class="gw-ctx-table">
          <div class="gw-ctx-thead">
            <span>Source</span><span>Status</span><span>Tokens</span><span>Reason</span><span>Preview</span>
          </div>
          ${items.map(item => {
            const sc = SOURCE_COLORS[item.source] || "#555";
            const icon = STATUS_ICONS[item.status] || "?";
            const rowCls = item.status === "kept" ? "gw-ctx-kept"
              : item.status === "dropped" ? "gw-ctx-dropped" : "gw-ctx-compressed";
            return `<div class="gw-ctx-row ${rowCls}">
              <span style="color:${sc}">${escHtml(item.source)}</span>
              <span>${icon} ${escHtml(item.status)}</span>
              <span>${item.tokens}</span>
              <span>${escHtml(item.reason||"—")}</span>
              <span class="gw-ctx-preview">${escHtml((item.preview||"").slice(0,80))}</span>
            </div>`;
          }).join("")}
        </div>`;
      result.style.display = "";
    } catch(e) {
      result.innerHTML = `<div class="gw-err">Error: ${escHtml(e.message)}</div>`;
      result.style.display = "";
    } finally {
      btn.disabled = false;
      btn.textContent = "Inspect";
    }
  }

  /* ── Trace Timeline ── */
  async function loadTraces() {
    const el = qs("#gw-trace-timeline");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/traces?limit=30`);
      const traces = d.traces || [];
      if (!traces.length) {
        el.innerHTML = '<div class="gw-trace-empty">No traces yet — send a message via the Agent panel.</div>';
        return;
      }
      el.innerHTML = traces.map(t => {
        const aliasColor = ALIAS_COLORS[t.alias] || "#555";
        const statusIcon = t.status === "ok" ? "✓" : t.status === "error" ? "✗" : "⚡";
        const statusCls = t.status === "ok" ? "gw-tr-ok" : t.status === "error" ? "gw-tr-err" : "gw-tr-warn";
        const saved = t.tokens_before > 0
          ? Math.round((t.tokens_before - t.tokens_after) / t.tokens_before * 100)
          : 0;
        const tools = (t.tools_called||[]).map(t=>`<span class="gw-use-chip">${escHtml(t)}</span>`).join("") || "—";
        const ts = t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "";
        const privBlock = t.privacy_block_reason
          ? `<div class="gw-tr-privblock">🔒 ${escHtml(t.privacy_block_reason)}</div>` : "";
        return `
          <div class="gw-trace-row ${statusCls}">
            <div class="gw-tr-left">
              <span class="gw-tr-status">${statusIcon}</span>
              <div class="gw-tr-main">
                <div class="gw-tr-task">${escHtml((t.task_preview||"").slice(0,100))}</div>
                <div class="gw-tr-meta">
                  <span class="gw-alias-name" style="color:${aliasColor}">${escHtml(t.alias||"?")}</span>
                  <span class="gw-tr-model">${escHtml(t.provider||"")} / ${escHtml(t.model||"")}</span>
                  <span class="gw-tr-cls">${escHtml(t.classifier_used||"")}</span>
                  ${t.fallback_used ? '<span class="gw-chip gw-chip-warn">fallback</span>' : ""}
                </div>
                <div class="gw-tr-tools">${tools}</div>
                ${privBlock}
              </div>
            </div>
            <div class="gw-tr-right">
              <div class="gw-tr-tokens">
                <span title="tokens before">${(t.tokens_before||0).toLocaleString()}</span>
                <span class="gw-tr-arrow">→</span>
                <span title="tokens after">${(t.tokens_after||0).toLocaleString()}</span>
                ${saved > 0 ? `<span class="gw-tr-saved">-${saved}%</span>` : ""}
              </div>
              <div class="gw-tr-time">${ts} · ${t.elapsed_ms||0}ms</div>
            </div>
          </div>`;
      }).join("");
    } catch(e) {
      el.innerHTML = `<div class="gw-err">Failed to load traces: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── init ── */
  function init() {
    const refreshBtn = qs("#gw-refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => { loadProviders(); loadAliases(); loadTraces(); });

    const simBtn = qs("#gw-sim-btn");
    if (simBtn) simBtn.addEventListener("click", runSimulator);
    const simInput = qs("#gw-sim-input");
    if (simInput) simInput.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runSimulator(); }
    });

    const ctxBtn = qs("#gw-ctx-btn");
    if (ctxBtn) ctxBtn.addEventListener("click", runContextInspector);

    const tracesRefresh = qs("#gw-traces-refresh");
    if (tracesRefresh) tracesRefresh.addEventListener("click", loadTraces);

    // Hook into navigation — load data when Gateway section becomes active
    const orig = window.navigateTo;
    window.navigateTo = function(section) {
      if (typeof orig === "function") orig(section);
      if (section === "gateway") {
        loadProviders();
        loadAliases();
        loadTraces();
      }
    };

    // Also handle nav clicks directly
    document.querySelectorAll('[data-section="gateway"]').forEach(btn => {
      btn.addEventListener("click", () => {
        loadProviders();
        loadAliases();
        loadTraces();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
