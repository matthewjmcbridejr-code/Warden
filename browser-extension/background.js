// Warden Memory Collector — background service worker
// Captures all navigation events and queues them for ingest.

const WARDEN_URL = "http://127.0.0.1:6969";
const INGEST_ENDPOINT = `${WARDEN_URL}/api/mcharness/warden/browser/ingest`;
const QUEUE_KEY = "warden_event_queue";
const FLUSH_INTERVAL_MS = 15000; // flush every 15 seconds
const MAX_QUEUE = 200;

// ── Queue helpers ─────────────────────────────────────────────────────────────

async function enqueue(event) {
  const { warden_event_queue: q = [] } = await chrome.storage.local.get(QUEUE_KEY);
  q.push({ ...event, ts: new Date().toISOString() });
  if (q.length > MAX_QUEUE) q.splice(0, q.length - MAX_QUEUE);
  await chrome.storage.local.set({ [QUEUE_KEY]: q });
}

async function flush() {
  const { warden_event_queue: q = [] } = await chrome.storage.local.get(QUEUE_KEY);
  if (!q.length) return;
  await chrome.storage.local.set({ [QUEUE_KEY]: [] });
  try {
    const resp = await fetch(INGEST_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: q }),
    });
    if (!resp.ok) {
      // Put events back on failure
      const { warden_event_queue: current = [] } = await chrome.storage.local.get(QUEUE_KEY);
      await chrome.storage.local.set({ [QUEUE_KEY]: [...q, ...current].slice(-MAX_QUEUE) });
    } else {
      await chrome.storage.local.set({ warden_last_flush: new Date().toISOString(), warden_flushed_count: q.length });
    }
  } catch {
    // API offline — put events back
    const { warden_event_queue: current = [] } = await chrome.storage.local.get(QUEUE_KEY);
    await chrome.storage.local.set({ [QUEUE_KEY]: [...q, ...current].slice(-MAX_QUEUE) });
  }
}

// ── URL classifiers ───────────────────────────────────────────────────────────

function classifyUrl(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");

    if (host === "google.com" && u.pathname === "/search") {
      return { kind: "search", engine: "google", query: u.searchParams.get("q") || "" };
    }
    if (host === "bing.com" && u.pathname === "/search") {
      return { kind: "search", engine: "bing", query: u.searchParams.get("q") || "" };
    }
    if (host === "duckduckgo.com") {
      return { kind: "search", engine: "duckduckgo", query: u.searchParams.get("q") || "" };
    }
    if (host === "chat.openai.com" || host === "chatgpt.com") {
      return { kind: "ai_session", service: "chatgpt" };
    }
    if (host === "claude.ai") {
      return { kind: "ai_session", service: "claude" };
    }
    if (host === "gemini.google.com") {
      return { kind: "ai_session", service: "gemini" };
    }
    if (host === "github.com") {
      return { kind: "github", path: u.pathname };
    }
    if (host.includes("localhost") || host === "127.0.0.1") {
      return { kind: "local_dev", port: u.port || "80" };
    }
    if (host.includes("stackoverflow.com")) {
      return { kind: "reference", site: "stackoverflow" };
    }
    if (host.includes("docs.") || u.pathname.includes("/docs/") || u.pathname.includes("/documentation/")) {
      return { kind: "reference", site: host };
    }
    return { kind: "browse" };
  } catch {
    return { kind: "browse" };
  }
}

// ── Navigation listener ───────────────────────────────────────────────────────

chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (details.frameId !== 0) return; // top frame only
  const { url } = details;
  if (!url || url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("about:")) return;

  let title = "";
  try {
    const tab = await chrome.tabs.get(details.tabId);
    title = tab.title || "";
  } catch { /* tab may be closed */ }

  const meta = classifyUrl(url);
  await enqueue({ source: "navigation", url, title, ...meta });
});

// ── Message receiver (from content scripts) ───────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
  if (msg.type === "warden_event") {
    enqueue(msg.payload).catch(() => {});
  }
});

// ── Periodic flush ────────────────────────────────────────────────────────────

chrome.alarms.create("warden_flush", { periodInMinutes: 0.25 }); // every 15s
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "warden_flush") flush().catch(() => {});
});

// Flush on startup too
flush().catch(() => {});
