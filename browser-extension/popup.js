const WARDEN_URL = "http://127.0.0.1:6969";

async function render() {
  const { warden_event_queue: q = [], warden_last_flush, warden_flushed_count } = await chrome.storage.local.get(
    ["warden_event_queue", "warden_last_flush", "warden_flushed_count"]
  );

  const rows = document.getElementById("rows");
  const flush_ago = warden_last_flush
    ? Math.round((Date.now() - new Date(warden_last_flush)) / 1000) + "s ago"
    : "never";

  rows.innerHTML = `
    <div class="row"><span class="label">Queue</span><span class="val">${q.length} events</span></div>
    <div class="row"><span class="label">Last flush</span><span class="val">${flush_ago}</span></div>
    <div class="row"><span class="label">Total flushed</span><span class="val">${warden_flushed_count || 0}</span></div>
  `;

  try {
    const r = await fetch(`${WARDEN_URL}/api/mcharness/health`, { signal: AbortSignal.timeout(2000) });
    const status = document.getElementById("status");
    if (r.ok) {
      status.className = "status online";
      status.textContent = "Warden API online";
    } else {
      throw new Error();
    }
  } catch {
    const status = document.getElementById("status");
    status.className = "status offline";
    status.textContent = "Warden API offline — events queued";
  }
}

document.getElementById("flush").addEventListener("click", async () => {
  // Trigger background flush
  const { warden_event_queue: q = [] } = await chrome.storage.local.get("warden_event_queue");
  if (!q.length) return;
  try {
    await fetch(`${WARDEN_URL}/api/mcharness/warden/browser/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: q }),
    });
    await chrome.storage.local.set({
      warden_event_queue: [],
      warden_last_flush: new Date().toISOString(),
      warden_flushed_count: q.length,
    });
  } catch { /* offline */ }
  render();
});

render();
