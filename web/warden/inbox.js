/* Brain Inbox (v2.4 / personal_ai_os_plan PR 2): read-only feed of raw captures
   with explicit per-item Promote-to-vault and Discard actions (PR 5). */
(function () {
  const MCH = "/api/mcharness";

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function act(memoryId, action) {
    const resp = await fetch(`${MCH}/warden/memory/${encodeURIComponent(memoryId)}/${action}`, { method: "POST" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function loadInbox() {
    const host = document.getElementById("brain-inbox-list");
    if (!host) return;
    host.innerHTML = '<span class="muted">Loading…</span>';
    let data = {};
    try {
      const resp = await fetch(`${MCH}/warden/brain/inbox?limit=50`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
    } catch (err) {
      host.innerHTML = `<div class="empty-state-card"><h3>Inbox unavailable</h3><p class="muted">${esc(err.message || err)}</p></div>`;
      return;
    }
    const items = data.items || [];
    if (!items.length) {
      host.innerHTML = '<div class="empty-state-card"><h3>No captures yet</h3><p class="muted">Browser, dropzone, and agent captures appear here for review.</p></div>';
      return;
    }
    host.innerHTML = items.map((m) => `
      <div class="inspector-card" data-testid="inbox-item" data-memory-id="${esc(m.memory_id)}">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline;">
          <strong>${esc(m.title || m.summary)}</strong>
          <span class="muted mono" style="font-size:11px;">${esc((m.created_at || "").slice(0, 16))}</span>
        </div>
        <div class="muted" style="font-size:12px;">${esc(m.summary)}</div>
        <div class="muted mono" style="font-size:11px;">
          ${esc(m.source)} · ${esc(m.kind)}${m.url ? ` · <a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.url).slice(0, 60)}</a>` : ""}
          ${m.raw_content_truncated ? " · <em>raw content truncated</em>" : ""}
        </div>
        <div style="margin-top:6px;display:flex;gap:6px;">
          ${m.promoted
            ? `<span class="muted" style="font-size:12px;">Promoted → ${esc(m.source_ref)}</span>`
            : `<button type="button" class="btn" data-inbox-action="promote">Promote to vault</button>
               <button type="button" class="btn" data-inbox-action="discard">Discard</button>`}
        </div>
      </div>
    `).join("");
    host.querySelectorAll("[data-inbox-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const card = btn.closest("[data-memory-id]");
        const id = card && card.getAttribute("data-memory-id");
        if (!id) return;
        btn.disabled = true;
        try {
          await act(id, btn.getAttribute("data-inbox-action"));
          await loadInbox();
        } catch (err) {
          btn.disabled = false;
          console.error(err);
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const nav = document.querySelector('[data-section="inbox"]');
    if (nav) nav.addEventListener("click", () => loadInbox().catch((e) => console.error(e)));
    const refresh = document.getElementById("brain-inbox-refresh");
    if (refresh) refresh.addEventListener("click", () => loadInbox().catch((e) => console.error(e)));
  });
})();
