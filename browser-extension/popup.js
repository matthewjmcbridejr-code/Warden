const WARDEN_URL = "http://127.0.0.1:6969";
const INGEST_URL = `${WARDEN_URL}/api/mcharness/warden/brain/ingest`;

let currentTab = null;
let pageIsYoutube = false;
let pageIsPdf = false;

async function getTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function setStatus(msg, cls = "online") {
  const el = document.getElementById("status");
  el.className = `status ${cls}`;
  el.textContent = msg;
}

function showSummary(msg) {
  const el = document.getElementById("note-summary");
  el.style.display = "block";
  el.textContent = msg;
}

async function render() {
  currentTab = await getTab();
  if (!currentTab) return;

  const url = currentTab.url || "";
  pageIsYoutube = /youtube\.com\/watch|youtu\.be\//.test(url);
  pageIsPdf = url.endsWith(".pdf") || url.includes("/pdf/") || currentTab.title?.toLowerCase().includes(".pdf");

  const { warden_event_queue: q = [], warden_last_flush, warden_flushed_count } =
    await chrome.storage.local.get(["warden_event_queue", "warden_last_flush", "warden_flushed_count"]);

  const rows = document.getElementById("rows");
  const flush_ago = warden_last_flush
    ? Math.round((Date.now() - new Date(warden_last_flush)) / 1000) + "s ago"
    : "never";

  rows.innerHTML = `
    <div class="row"><span class="label">Queue</span><span class="val">${q.length} events</span></div>
    <div class="row"><span class="label">Last flush</span><span class="val">${flush_ago}</span></div>
    <div class="row"><span class="label">Total flushed</span><span class="val">${warden_flushed_count || 0}</span></div>
  `;

  // Show/hide context-specific buttons
  document.getElementById("save-yt").style.display = pageIsYoutube ? "block" : "none";
  document.getElementById("save-pdf").style.display = pageIsPdf ? "block" : "none";

  try {
    const r = await fetch(`${WARDEN_URL}/api/mcharness/health`, { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      setStatus("Warden Brain online", "online");
    } else {
      throw new Error();
    }
  } catch {
    setStatus("Warden API offline — saves will fail", "offline");
  }

  // Check for active selection in the current tab
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: currentTab.id },
      func: () => window.getSelection()?.toString().trim() || "",
    });
    const sel = results?.[0]?.result || "";
    if (sel && sel.length > 20) {
      document.getElementById("save-selection").style.display = "block";
      document.getElementById("save-selection").dataset.selection = sel;
    }
  } catch {
    // Cannot inject into this tab (e.g. chrome:// pages)
  }
}

async function extractPageText() {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: currentTab.id },
      func: () => {
        // Remove script, style, nav, footer elements for cleaner text
        const clone = document.body.cloneNode(true);
        clone.querySelectorAll("script,style,nav,footer,header,iframe,svg").forEach(el => el.remove());
        return clone.innerText?.trim().slice(0, 8000) || document.title;
      },
    });
    return results?.[0]?.result || "";
  } catch {
    return "";
  }
}

async function ingest(payload) {
  const resp = await fetch(INGEST_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ── Save Page ──────────────────────────────────────────────────────────────────

document.getElementById("save-page").addEventListener("click", async () => {
  const btn = document.getElementById("save-page");
  btn.disabled = true;
  setStatus("Extracting page…", "saving");
  try {
    const content_text = await extractPageText();
    setStatus("Saving to Brain…", "saving");
    const result = await ingest({
      url: currentTab.url,
      title: currentTab.title || currentTab.url,
      source_type: "webpage",
      content_text,
    });
    if (result.ok) {
      setStatus("✓ Saved to Brain!", "saved");
      showSummary(`"${result.title}" — ${result.word_count || 0} words`);
    } else {
      setStatus(`Not saved: ${result.reason || result.error || "unknown"}`, "error-msg");
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error-msg");
  } finally {
    btn.disabled = false;
  }
});

// ── Save Selection ─────────────────────────────────────────────────────────────

document.getElementById("save-selection").addEventListener("click", async () => {
  const btn = document.getElementById("save-selection");
  const selected_text = btn.dataset.selection;
  if (!selected_text) return;
  btn.disabled = true;
  setStatus("Saving selection…", "saving");
  try {
    const result = await ingest({
      url: currentTab.url,
      title: currentTab.title || currentTab.url,
      source_type: "selection",
      selected_text,
    });
    if (result.ok) {
      setStatus("✓ Selection saved!", "saved");
      showSummary(`Selection (${selected_text.length} chars) saved as "${result.title}"`);
    } else {
      setStatus(`Not saved: ${result.reason || result.error}`, "error-msg");
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error-msg");
  } finally {
    btn.disabled = false;
  }
});

// ── Save YouTube ───────────────────────────────────────────────────────────────

document.getElementById("save-yt").addEventListener("click", async () => {
  const btn = document.getElementById("save-yt");
  btn.disabled = true;
  setStatus("Fetching transcript…", "saving");
  try {
    // Get video title and channel from DOM
    const results = await chrome.scripting.executeScript({
      target: { tabId: currentTab.id },
      func: () => ({
        title: document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title")?.textContent?.trim() || document.title,
        channel: document.querySelector("#channel-name a, #owner-name a")?.textContent?.trim() || "",
        description: document.querySelector("#description-text, #snippet-text")?.textContent?.trim().slice(0, 500) || "",
      }),
    });
    const meta = results?.[0]?.result || {};
    setStatus("Saving YouTube to Brain…", "saving");
    const result = await ingest({
      url: currentTab.url,
      title: meta.title || currentTab.title || currentTab.url,
      source_type: "youtube",
      channel: meta.channel || "",
      description: meta.description || "",
      // transcript is fetched server-side via youtube-transcript-api
    });
    if (result.ok) {
      const chars = result.transcript_chars || 0;
      setStatus("✓ YouTube saved!", "saved");
      showSummary(`"${result.title}" — ${chars ? chars + " transcript chars" : "no transcript (no subtitles)"}`);
    } else {
      setStatus(`Not saved: ${result.reason || result.error}`, "error-msg");
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error-msg");
  } finally {
    btn.disabled = false;
  }
});

// ── Save PDF ───────────────────────────────────────────────────────────────────

document.getElementById("save-pdf").addEventListener("click", async () => {
  const btn = document.getElementById("save-pdf");
  btn.disabled = true;
  setStatus("Downloading & extracting PDF…", "saving");
  try {
    const result = await ingest({
      url: currentTab.url,
      title: currentTab.title || "",
      source_type: "pdf",
    });
    if (result.ok) {
      setStatus("✓ PDF saved!", "saved");
      showSummary(`"${result.title}" — ${result.word_count || 0} words extracted`);
    } else {
      setStatus(`Not saved: ${result.reason || result.error}`, "error-msg");
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error-msg");
  } finally {
    btn.disabled = false;
  }
});

// ── Flush memory queue ─────────────────────────────────────────────────────────

document.getElementById("flush").addEventListener("click", async () => {
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
