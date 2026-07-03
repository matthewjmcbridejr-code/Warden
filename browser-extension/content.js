// Warden Memory Collector — content script (runs on every page)
// Captures: typed text, selected text, copy/paste, page reading time,
// AI conversation turns, search queries, form submissions, page content summary.

const SEND = (payload) => chrome.runtime.sendMessage({ type: "warden_event", payload });

const host = location.hostname.replace(/^www\./, "");
const url = location.href;

// ── 1. Page visit with reading metrics ───────────────────────────────────────

let pageEnterTime = Date.now();
let maxScrollPct = 0;
let focused = true;
let focusedMs = 0;
let lastFocusTime = Date.now();

function scrollPct() {
  const el = document.documentElement;
  const scrolled = el.scrollTop;
  const total = el.scrollHeight - el.clientHeight;
  return total > 0 ? Math.round((scrolled / total) * 100) : 0;
}

document.addEventListener("scroll", () => {
  maxScrollPct = Math.max(maxScrollPct, scrollPct());
}, { passive: true });

window.addEventListener("focus", () => {
  focused = true;
  lastFocusTime = Date.now();
});

window.addEventListener("blur", () => {
  if (focused) focusedMs += Date.now() - lastFocusTime;
  focused = false;
});

// Send page summary on unload
window.addEventListener("beforeunload", () => {
  if (focused) focusedMs += Date.now() - lastFocusTime;
  const dwell = Math.round((Date.now() - pageEnterTime) / 1000);
  const focusSec = Math.round(focusedMs / 1000);
  if (dwell < 3) return; // skip instant bounces
  SEND({
    source: "page_dwell",
    url,
    title: document.title,
    dwell_sec: dwell,
    focused_sec: focusSec,
    scroll_pct: maxScrollPct,
    kind: "browse",
  });
});

// ── 2. Text selection (what you read and highlight) ───────────────────────────

let selectionTimer = null;
document.addEventListener("mouseup", () => {
  clearTimeout(selectionTimer);
  selectionTimer = setTimeout(() => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 20 && sel.length < 2000) {
      SEND({
        source: "text_selection",
        url,
        title: document.title,
        selected_text: sel,
        kind: "selection",
      });
    }
  }, 400);
});

// ── 3. Copy events ────────────────────────────────────────────────────────────

document.addEventListener("copy", () => {
  setTimeout(() => {
    navigator.clipboard.readText().then((text) => {
      if (text && text.length > 10 && text.length < 3000) {
        SEND({ source: "clipboard_copy", url, title: document.title, text, kind: "copy" });
      }
    }).catch(() => {});
  }, 50);
});

// ── 4. Typed text in inputs/textareas (debounced, non-password) ──────────────

const typingBuffers = new WeakMap();
const typingTimers = new WeakMap();

function onInput(e) {
  const el = e.target;
  if (!el || el.type === "password" || el.type === "hidden") return;
  const tag = el.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea" && !el.isContentEditable) return;

  clearTimeout(typingTimers.get(el));
  typingTimers.set(el, setTimeout(() => {
    const text = (el.value || el.textContent || "").trim();
    if (text.length < 10) return;
    SEND({
      source: "typed_input",
      url,
      title: document.title,
      text: text.slice(0, 1000),
      input_type: el.type || tag,
      kind: "input",
    });
  }, 1500)); // 1.5s after you stop typing
}

document.addEventListener("input", onInput, { capture: true, passive: true });

// ── 5. Form submissions ───────────────────────────────────────────────────────

document.addEventListener("submit", (e) => {
  const form = e.target;
  const fields = {};
  for (const el of form.elements) {
    if (!el.name || el.type === "password" || el.type === "hidden" || el.type === "submit") continue;
    const val = (el.value || "").trim();
    if (val) fields[el.name] = val.slice(0, 200);
  }
  if (Object.keys(fields).length) {
    SEND({
      source: "form_submit",
      url,
      title: document.title,
      fields,
      kind: "input",
    });
  }
}, { capture: true });

// ── 6. Google search query ─────────────────────────────────────────────────────

if (host === "google.com" || host === "bing.com" || host === "duckduckgo.com") {
  const q = new URLSearchParams(location.search).get("q") || "";
  if (q) {
    SEND({
      source: "search_query",
      url,
      title: document.title,
      query: q,
      engine: host.split(".")[0],
      kind: "search",
    });
  }
}

// ── 7. YouTube — what you watch ───────────────────────────────────────────────

if (host === "youtube.com") {
  const sendYT = () => {
    const titleEl = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title");
    const channelEl = document.querySelector("#channel-name a, #owner-name a");
    const title = titleEl?.textContent?.trim();
    const channel = channelEl?.textContent?.trim();
    if (title) {
      SEND({ source: "youtube_watch", url, title, channel: channel || "", kind: "media" });
    }
  };
  // YT is a SPA — wait for DOM
  setTimeout(sendYT, 2000);
  document.addEventListener("yt-navigate-finish", () => setTimeout(sendYT, 1500));
}

// ── 8. ChatGPT conversation capture ───────────────────────────────────────────

if (host === "chat.openai.com" || host === "chatgpt.com") {
  let lastTurnCount = 0;

  function scrapeGPT() {
    const turns = document.querySelectorAll("[data-message-author-role]");
    if (turns.length <= lastTurnCount) return;
    const newTurns = Array.from(turns).slice(lastTurnCount);
    lastTurnCount = turns.length;
    const messages = newTurns.map((el) => ({
      role: el.getAttribute("data-message-author-role"),
      text: el.innerText?.trim().slice(0, 1500) || "",
    })).filter((m) => m.text.length > 0);
    if (messages.length) {
      SEND({ source: "chatgpt_turn", url, title: document.title, messages, kind: "ai_conversation" });
    }
  }

  const gpObs = new MutationObserver(() => setTimeout(scrapeGPT, 800));
  gpObs.observe(document.body, { childList: true, subtree: true });
  setTimeout(scrapeGPT, 2000);
}

// ── 9. Claude.ai conversation capture ─────────────────────────────────────────

if (host === "claude.ai") {
  let lastClaudeCount = 0;

  function scrapeClaude() {
    // Human turns
    const humanTurns = document.querySelectorAll('[data-testid="human-turn"], .human-turn');
    // Assistant turns
    const assistantTurns = document.querySelectorAll('[data-testid="assistant-turn"], .assistant-turn');

    const allTurns = [];
    document.querySelectorAll(".font-claude-message, [data-is-streaming]").forEach((el) => {
      allTurns.push({ role: "assistant", text: el.innerText?.trim().slice(0, 1500) || "" });
    });
    humanTurns.forEach((el) => {
      allTurns.push({ role: "human", text: el.innerText?.trim().slice(0, 1500) || "" });
    });

    if (allTurns.length > lastClaudeCount) {
      const newTurns = allTurns.slice(lastClaudeCount);
      lastClaudeCount = allTurns.length;
      const messages = newTurns.filter((m) => m.text.length > 0);
      if (messages.length) {
        SEND({ source: "claude_turn", url, title: document.title, messages, kind: "ai_conversation" });
      }
    }
  }

  const clObs = new MutationObserver(() => setTimeout(scrapeClaude, 800));
  clObs.observe(document.body, { childList: true, subtree: true });
  setTimeout(scrapeClaude, 2000);
}

// ── 10. GitHub — what repo/PR/issue you look at ───────────────────────────────

if (host === "github.com") {
  const parts = location.pathname.split("/").filter(Boolean);
  if (parts.length >= 2) {
    const meta = { owner: parts[0], repo: parts[1] };
    if (parts[2] === "pull") meta.pr = parts[3];
    else if (parts[2] === "issues") meta.issue = parts[3];
    else if (parts[2] === "commit") meta.commit = parts[3];
    else if (parts[2] === "tree" || parts[2] === "blob") meta.path = parts.slice(4).join("/");
    SEND({ source: "github_visit", url, title: document.title, ...meta, kind: "github" });
  }
}

// ── 11. Notion, Linear, Jira — what docs/tickets you open ────────────────────

if (host.includes("notion.so") || host.includes("linear.app") || host.includes("atlassian.net")) {
  setTimeout(() => {
    const title = document.title.trim();
    const h1 = document.querySelector("h1")?.innerText?.trim();
    SEND({
      source: "productivity_tool",
      url,
      title: h1 || title,
      site: host,
      kind: "reference",
    });
  }, 2000);
}

// ── 12. Stack Overflow / MDN / docs — what answers you read ──────────────────

if (host.includes("stackoverflow.com") || host.includes("developer.mozilla.org") ||
    host.includes("docs.") || location.pathname.includes("/docs/")) {
  setTimeout(() => {
    const title = document.title.trim();
    const h1 = document.querySelector("h1")?.innerText?.trim();
    // Grab accepted answer on SO
    const answer = document.querySelector(".accepted-answer .js-post-body, .answer--accepted .s-prose");
    const snippet = answer?.innerText?.trim().slice(0, 500) || "";
    SEND({
      source: "docs_reference",
      url,
      title: h1 || title,
      snippet,
      kind: "reference",
    });
  }, 1500);
}
