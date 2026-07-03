/* Warden Model Gateway — productized cockpit */
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

  /* ── Summary strip ─────────────────────────────────────────────────────── */
  function updateSummary(providers, lastRoute) {
    const statusEl = qs("#gw-stat-status-val");
    const routeEl  = qs("#gw-stat-route-val");
    const savingsEl = qs("#gw-stat-savings-val");
    if (!statusEl) return;

    if (providers) {
      const reachable = providers.filter(p =>
        p.status === "reachable" || p.status === "configured"
      ).length;
      const total = providers.length;
      if (reachable === total) {
        statusEl.textContent = "Online";
        statusEl.style.color = "#5a9a5a";
      } else if (reachable > 0) {
        statusEl.textContent = `Degraded (${reachable}/${total})`;
        statusEl.style.color = "#9a8a20";
      } else {
        statusEl.textContent = "Offline";
        statusEl.style.color = "#9a4040";
      }
    }

    if (lastRoute && routeEl) {
      const alias = lastRoute.alias || "—";
      const prov  = lastRoute.primary_provider || "";
      routeEl.textContent = prov ? `${alias} → ${prov}` : alias;
    }

    if (savingsEl) {
      savingsEl.textContent = "—";  // updated after route preview runs
    }
  }

  /* ── Provider Health (compact table) ───────────────────────────────────── */
  const PROVIDER_ROLES = {
    "Ollama":          "Local inference",
    "Groq":            "Cloud fast",
    "Cerebras":        "Cloud fast",
    "OpenRouter":      "Cloud free demos",
    "HuggingFace":     "Embeddings",
    "Tavily":          "Web search",
    "Crawl4AI":        "Web crawl",
    "LiteLLM Gateway": "Proxy / aliases",
  };

  function dotHtml(status) {
    const cls = status === "reachable" || status === "configured" ? "gw-dot-ok"
              : status === "no-key"    || status === "degraded"   ? "gw-dot-warn"
              : status === "unreachable"                          ? "gw-dot-err"
              : "gw-dot-off";
    return `<span class="gw-dot ${cls}"></span>`;
  }

  async function loadProviders() {
    const el = qs("#gw-providers");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/status`);
      const providers = d.providers || [];
      updateSummary(providers, null);

      el.innerHTML = `
        <table class="gw-htable">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Role</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            ${providers.map(p => {
              const status = p.status || "unknown";
              const label  = status === "reachable"   ? "Online"
                           : status === "configured"  ? "Configured"
                           : status === "no-key"      ? "No key"
                           : status === "unreachable" ? "Offline"
                           : status;
              const latency = p.latency_ms != null ? ` · ${p.latency_ms}ms` : "";
              return `<tr>
                <td>${escHtml(p.provider)}</td>
                <td class="gw-td-status">${dotHtml(status)}${escHtml(label)}${escHtml(latency)}</td>
                <td class="gw-td-muted">${escHtml(PROVIDER_ROLES[p.provider] || "—")}</td>
                <td class="gw-td-muted">${escHtml(p.note || "")}</td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>`;
    } catch(e) {
      el.innerHTML = `<div class="gw-err">Provider check failed: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── Model Aliases (compact table, expandable rows) ─────────────────────── */
  const PRIVACY_LABELS = {
    "private":         "Private",
    "public-safe-only":"Public-safe only",
  };

  async function loadAliases() {
    const el = qs("#gw-aliases");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/aliases`);
      const entries = Object.entries(d.aliases || {});

      el.innerHTML = `
        <table class="gw-htable" id="gw-alias-table">
          <thead>
            <tr>
              <th>Alias</th>
              <th>Purpose</th>
              <th>Primary</th>
              <th>Fallback</th>
              <th>Privacy</th>
            </tr>
          </thead>
          <tbody>
            ${entries.map(([name, def]) => {
              const privLabel = PRIVACY_LABELS[def.privacy] || def.privacy;
              const privDot   = def.privacy === "private" ? "gw-dot-ok" : "gw-dot-warn";
              return `
                <tr class="gw-alias-row" data-alias="${escHtml(name)}">
                  <td>${escHtml(name)}</td>
                  <td class="gw-td-muted">${escHtml(def.description || "")}</td>
                  <td class="gw-td-muted">${escHtml(def.primary_provider || "—")}</td>
                  <td class="gw-td-muted">${escHtml(def.fallback_provider || "—")}</td>
                  <td class="gw-td-status"><span class="gw-dot ${privDot}"></span>${escHtml(privLabel)}</td>
                </tr>
                <tr class="gw-alias-detail" id="gw-alias-detail-${escHtml(name)}" hidden>
                  <td colspan="5">
                    <div class="gw-alias-detail-inner">
                      <div class="gw-ad-field">
                        <span class="gw-ad-label">Context budget</span>
                        <span class="gw-ad-value">${(def.max_context_tokens||0).toLocaleString()} tokens</span>
                      </div>
                      <div class="gw-ad-field">
                        <span class="gw-ad-label">Cloud allowed</span>
                        <span class="gw-ad-value">${def.cloud_allowed ? "Yes" : "No"}</span>
                      </div>
                      <div class="gw-ad-field">
                        <span class="gw-ad-label">OpenRouter free</span>
                        <span class="gw-ad-value">${def.openrouter_free_allowed ? "Allowed" : "Blocked"}</span>
                      </div>
                      <div class="gw-ad-field gw-ad-uses">
                        <span class="gw-ad-label">Use cases</span>
                        <span class="gw-ad-value">${(def.use_cases||[]).join(", ") || "—"}</span>
                      </div>
                      ${def.warning ? `<div class="gw-ad-warning">Free routes are blocked for private context.</div>` : ""}
                    </div>
                  </td>
                </tr>`;
            }).join("")}
          </tbody>
        </table>`;

      // Toggle expansion on row click
      el.querySelectorAll(".gw-alias-row").forEach(row => {
        row.addEventListener("click", () => {
          const name   = row.dataset.alias;
          const detail = qs(`#gw-alias-detail-${name}`, el);
          if (detail) detail.hidden = !detail.hidden;
        });
      });

    } catch(e) {
      el.innerHTML = `<div class="gw-err">Failed to load aliases: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── Routing Simulator ──────────────────────────────────────────────────── */
  async function runSimulator() {
    const input  = qs("#gw-sim-input");
    const result = qs("#gw-sim-result");
    const btn    = qs("#gw-sim-btn");
    if (!input || !result) return;
    const task = input.value.trim();
    if (!task) return;

    btn.disabled = true;
    btn.textContent = "Routing…";
    result.innerHTML = `<span class="gw-sim-hint">Routing…</span>`;

    try {
      const d = await api(`${MCH}/warden/model-gateway/route-preview`, {
        method: "POST",
        body: JSON.stringify({ task }),
      });

      const tokBefore = (d.estimated_input_tokens || 0).toLocaleString();
      const tokAfter  = (d.estimated_tokens_after_budget || 0).toLocaleString();
      const saved     = d.pct_saved || 0;
      const savedHtml = saved > 0
        ? ` → ${tokAfter} tok <span class="gw-res-saved">−${saved}%</span>`
        : ` (within budget)`;

      const warnings = (d.warnings||[]).map(w =>
        `<div class="gw-res-warn">${escHtml(w)}</div>`
      ).join("");

      const tools = (d.likely_tools||[]).join(", ") || "None predicted";

      result.innerHTML = `
        <div class="gw-res-alias">${escHtml(d.alias || "—")}</div>
        <div class="gw-res-reason">${escHtml(d.reason || "")}</div>
        <div class="gw-res-fields">
          <div class="gw-res-field">
            <span>Privacy</span>
            <span>${escHtml(d.privacy || "—")}</span>
          </div>
          <div class="gw-res-field">
            <span>Provider</span>
            <span>${escHtml(d.primary_provider || "—")}</span>
          </div>
          <div class="gw-res-field">
            <span>Fallback</span>
            <span>${escHtml(d.fallback_provider || "—")}</span>
          </div>
        </div>
        <div class="gw-res-tokens">${tokBefore} tok${savedHtml}</div>
        ${warnings}
        <details class="gw-res-diag">
          <summary>Show diagnostics</summary>
          <div class="gw-res-diag-body">
            <div class="gw-res-diag-row"><span>Confidence</span><span>${Math.round((d.confidence||0)*100)}%</span></div>
            <div class="gw-res-diag-row"><span>Classifier</span><span>${escHtml(d.classifier_used||"—")}</span></div>
            <div class="gw-res-diag-row"><span>Token budget</span><span>${(d.token_budget||0).toLocaleString()}</span></div>
            <div class="gw-res-diag-row"><span>Likely tools</span><span>${escHtml(tools)}</span></div>
            <div class="gw-res-diag-row"><span>OpenRouter free</span><span>${d.openrouter_free_blocked ? "Blocked" : "Allowed"}</span></div>
          </div>
        </details>`;

      // Update summary strip with last route
      const routeEl = qs("#gw-stat-route-val");
      if (routeEl) routeEl.textContent = d.primary_provider
        ? `${d.alias} → ${d.primary_provider}` : d.alias;
      const savingsEl = qs("#gw-stat-savings-val");
      if (savingsEl) savingsEl.textContent = saved > 0 ? `${saved}% saved` : "Within budget";

    } catch(e) {
      result.innerHTML = `<div class="gw-err">Error: ${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Preview Route";
    }
  }

  /* ── Context Budget Inspector ───────────────────────────────────────────── */
  async function runContextInspector() {
    const input   = qs("#gw-ctx-input");
    const aliasEl = qs("#gw-ctx-alias");
    const result  = qs("#gw-ctx-result");
    const btn     = qs("#gw-ctx-btn");
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
            { summary: "qwen3:0.6b is available locally for classification.", kind: "proof" },
          ],
          git_context: "feat/marius-resident-core\nace35c3 feat(warden): WardenAgent tool-calling loop",
        }),
      });

      const items   = d.items || [];
      const kept    = items.filter(i => i.status === "kept").length;
      const dropped = items.filter(i => i.status === "dropped").length;
      const compr   = items.filter(i => i.status === "compressed").length;
      const saved   = d.pct_saved || 0;

      result.innerHTML = `
        <div class="gw-ctx-summary">
          <div class="gw-ctx-stat"><b>Kept</b><span>${kept}</span></div>
          <div class="gw-ctx-stat"><b>Compressed</b><span>${compr}</span></div>
          <div class="gw-ctx-stat"><b>Dropped</b><span>${dropped}</span></div>
          <div class="gw-ctx-stat"><b>Saved</b><span>${saved}%</span></div>
        </div>
        <details>
          <summary class="gw-link-btn" style="display:inline;cursor:pointer;">View context decisions</summary>
          <div class="gw-ctx-table-wrap" style="margin-top:8px;">
            <table class="gw-ctx-table">
              <thead><tr>
                <th>Source</th><th>Status</th><th>Tokens</th><th>Reason</th><th>Preview</th>
              </tr></thead>
              <tbody>
                ${items.map(item => `
                  <tr class="gw-ctx-${escHtml(item.status)}">
                    <td class="gw-td-mono">${escHtml(item.source)}</td>
                    <td>${escHtml(item.status)}</td>
                    <td>${item.tokens}</td>
                    <td class="gw-td-muted">${escHtml(item.reason || "—")}</td>
                    <td class="gw-ctx-preview">${escHtml((item.preview||"").slice(0,80))}</td>
                  </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </details>`;
      result.style.display = "";

    } catch(e) {
      result.innerHTML = `<div class="gw-err">Error: ${escHtml(e.message)}</div>`;
      result.style.display = "";
    } finally {
      btn.disabled = false;
      btn.textContent = "Inspect";
    }
  }

  /* ── Trace Timeline (compact, last 10) ─────────────────────────────────── */
  async function loadTraces() {
    const el = qs("#gw-trace-timeline");
    if (!el) return;
    try {
      const d = await api(`${MCH}/warden/model-gateway/traces?limit=10`);
      const traces = d.traces || [];
      if (!traces.length) {
        el.innerHTML = '<div class="gw-trace-empty">No traces yet. Send a message via the Agent panel.</div>';
        return;
      }
      el.innerHTML = traces.map(t => {
        const saved = t.tokens_before > 0
          ? Math.round((t.tokens_before - t.tokens_after) / t.tokens_before * 100) : 0;
        const statusCls = t.status === "ok" ? "gw-tr-ok"
          : t.status === "error" ? "gw-tr-err" : "gw-tr-warn";
        const statusDot = t.status === "ok" ? "gw-dot-ok"
          : t.status === "error" ? "gw-dot-err" : "gw-dot-warn";
        return `
          <div class="gw-trace-row">
            <span class="gw-dot ${statusDot}"></span>
            <span class="gw-tr-task">${escHtml((t.task_preview||"").slice(0,90))}</span>
            <span class="gw-tr-alias">${escHtml(t.alias||"?")}</span>
            <span class="gw-tr-provider">${escHtml(t.provider||"")}</span>
            ${saved > 0 ? `<span class="gw-tr-saved-pct">−${saved}%</span>` : ""}
          </div>`;
      }).join("");
    } catch(e) {
      el.innerHTML = `<div class="gw-err">Failed to load traces: ${escHtml(e.message)}</div>`;
    }
  }

  /* ── Diagnostics toggle ────────────────────────────────────────────────── */
  function initDiagToggle() {
    const btn  = qs("#gw-diag-toggle");
    const body = qs("#gw-diag-body");
    if (!btn || !body) return;
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!open));
      body.hidden = open;
      if (!open) {
        loadTraces();
      }
    });
  }

  /* ── Init ──────────────────────────────────────────────────────────────── */
  function init() {
    // Refresh button
    const refreshBtn = qs("#gw-refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => {
      loadProviders();
      loadAliases();
    });

    // Simulator
    const simBtn   = qs("#gw-sim-btn");
    const simInput = qs("#gw-sim-input");
    if (simBtn)   simBtn.addEventListener("click", runSimulator);
    if (simInput) simInput.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runSimulator(); }
    });

    // Context inspector
    const ctxBtn = qs("#gw-ctx-btn");
    if (ctxBtn) ctxBtn.addEventListener("click", runContextInspector);

    // Traces refresh
    const traceRefresh = qs("#gw-traces-refresh");
    if (traceRefresh) traceRefresh.addEventListener("click", loadTraces);

    // Diagnostics section toggle
    initDiagToggle();

    // Hook navigation — load data when Gateway tab activates
    const orig = window.navigateTo;
    window.navigateTo = function(section) {
      if (typeof orig === "function") orig(section);
      if (section === "gateway") {
        loadProviders();
        loadAliases();
      }
    };

    document.querySelectorAll('[data-section="gateway"]').forEach(el => {
      el.addEventListener("click", () => {
        loadProviders();
        loadAliases();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
