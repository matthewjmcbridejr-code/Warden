/* Runner Sessions section for the canonical Command Center (app.html).
   Read-only port of the Control Room panel (v2.3 UI consolidation) —
   cleanup actions stay on the private service. */
(function () {
  const MCH = "/api/mcharness";

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadRunnerSessions() {
    const summary = document.getElementById("runners-summary");
    const table = document.getElementById("runners-table");
    if (!summary || !table) return;
    summary.innerHTML = '<span class="muted">Loading…</span>';
    let rs = {};
    try {
      const resp = await fetch(`${MCH}/runner/sessions`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      rs = await resp.json();
    } catch (err) {
      summary.innerHTML = "";
      table.innerHTML = `<div class="empty-state-card"><h3>Runner sessions unavailable</h3><p class="muted">${esc(err.message || err)}</p></div>`;
      return;
    }
    summary.innerHTML = `
      <div class="summary-stat"><strong>${Number(rs.active_runner_sessions || 0)}</strong><span>Active</span></div>
      <div class="summary-stat"><strong>${Number(rs.stale_runner_sessions || 0)}</strong><span>Stale</span></div>
      <div class="summary-stat"><strong>${Number(rs.total_runner_sessions || 0)}</strong><span>Total</span></div>
      <div class="summary-stat"><strong>${Number(rs.max_active_runner_sessions || 4)}</strong><span>Max</span></div>
    `;
    const items = rs.items || [];
    if (!items.length) {
      table.innerHTML = '<div class="empty-state-card"><h3>No runner sessions</h3><p class="muted">Dispatch a Captain step or skill on the private service to start one.</p></div>';
      return;
    }
    table.innerHTML = `
      <table class="runner-table">
        <thead><tr><th>Session</th><th>Command</th><th>Title</th><th>Age</th><th>Stale</th><th>Linked run</th></tr></thead>
        <tbody>${items.map((row) => `
          <tr data-testid="runners-session-row">
            <td class="mono">${esc(row.session_name)}</td>
            <td>${esc(row.command || "—")}</td>
            <td>${esc(row.title || "—")}</td>
            <td>${row.age_seconds != null ? `${row.age_seconds}s` : "—"}</td>
            <td>${row.stale ? "Yes" : "No"}</td>
            <td>${esc(row.linked_run_id || "—")}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    `;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const nav = document.querySelector('[data-section="runners"]');
    if (nav) nav.addEventListener("click", () => loadRunnerSessions().catch((e) => console.error(e)));
    const refresh = document.getElementById("runners-refresh");
    if (refresh) refresh.addEventListener("click", () => loadRunnerSessions().catch((e) => console.error(e)));
  });
})();
