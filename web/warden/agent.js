/* Warden Agent panel — tool-calling chat UI */
(function () {
  "use strict";

  const MCH = "/api/mcharness";

  /* ── state ── */
  let _history = [];
  let _busy = false;
  let _traceVisible = true;

  /* ── helpers ── */
  function qs(sel, root) { return (root || document).querySelector(sel); }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtReply(text) {
    return escHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  }

  async function api(path, opts) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /* ── tool trace sidebar ── */
  function renderTrace(toolsUsed) {
    const list = qs("#wa-trace-list");
    if (!list) return;
    if (!toolsUsed || !toolsUsed.length) {
      list.innerHTML = '<div class="wa-trace-empty">No tools called.</div>';
      return;
    }
    list.innerHTML = toolsUsed.map((t) => {
      const argsStr = Object.entries(t.args || {})
        .map(([k, v]) => `<span class="wa-trace-arg">${escHtml(k)}=${escHtml(String(v))}</span>`)
        .join(" ");
      return `
        <div class="wa-trace-item">
          <div class="wa-trace-tool-name">${escHtml(t.tool)}</div>
          <div class="wa-trace-args">${argsStr || "<em>no args</em>"}</div>
          <div class="wa-trace-preview">${escHtml(t.result_preview || "")}</div>
        </div>`;
    }).join("");
  }

  /* ── source chips ── */
  const SOURCE_META = {
    git:     { label: "Git",    icon: "⎇" },
    github:  { label: "GitHub", icon: "⬡" },
    memories:{ label: "Memory", icon: "⧉" },
    context: { label: "Context",icon: "◎" },
    web:     { label: "Web",    icon: "⊕" },
  };

  function renderSources(sources) {
    if (!sources || !sources.length) return "";
    return '<div class="wa-msg-sources">' +
      sources.map((s) => {
        const m = SOURCE_META[s] || { label: s, icon: "•" };
        return `<span class="wa-source-chip wa-source-${escHtml(s)}">${m.icon} ${m.label}</span>`;
      }).join("") +
      "</div>";
  }

  /* ── thread rendering ── */
  function renderThread() {
    const thread = qs("#wa-thread");
    const welcome = qs("#wa-welcome");
    if (!thread) return;

    if (!_history.length) {
      if (welcome) welcome.style.display = "";
      thread.style.display = "none";
      return;
    }
    if (welcome) welcome.style.display = "none";
    thread.style.display = "";

    thread.innerHTML = _history.map((msg) => {
      if (msg.role === "user") {
        return `<div class="wa-msg wa-msg-user"><div class="wa-msg-bubble">${fmtReply(msg.content)}</div></div>`;
      }
      const modelBadge = msg.model
        ? `<span class="wa-msg-model">${escHtml(msg.model)}</span>`
        : "";
      const fallbackNote = msg.fallback
        ? '<span class="wa-msg-fallback">⚠ local fallback</span>'
        : "";
      return `
        <div class="wa-msg wa-msg-agent">
          <div class="wa-msg-meta">${modelBadge}${fallbackNote}</div>
          <div class="wa-msg-bubble">${fmtReply(msg.content)}</div>
          ${renderSources(msg.sources)}
        </div>`;
    }).join("");
    thread.scrollTop = thread.scrollHeight;
  }

  /* ── status bar ── */
  function setStatus(text, isErr) {
    const el = qs("#wa-status");
    if (!el) return;
    el.textContent = text;
    el.className = "wa-status" + (isErr ? " wa-status-error" : "");
  }

  /* ── send ── */
  async function send(msg) {
    if (!msg || _busy) return;
    _busy = true;
    _history.push({ role: "user", content: msg });
    renderThread();

    const sendBtn = qs("#wa-send-btn");
    const input = qs("#wa-input");
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.value = ""; input.style.height = ""; }

    setStatus("Thinking… querying tools");

    try {
      const apiHistory = _history
        .slice(0, -1)
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role === "agent" ? "assistant" : m.role, content: m.content }));

      const data = await api(`${MCH}/warden/agent/chat`, {
        method: "POST",
        body: JSON.stringify({ message: msg, history: apiHistory }),
      });

      const agentMsg = {
        role: "agent",
        content: data.reply || "(no response)",
        sources: data.sources || [],
        model: data.model,
        fallback: data.fallback,
        tools_used: data.tools_used || [],
      };
      _history.push(agentMsg);
      renderThread();
      renderTrace(data.tools_used);

      const badge = qs("#wa-model-badge");
      if (badge && data.model) badge.textContent = `${data.provider || ""} / ${data.model}`;

      setStatus("");
    } catch (e) {
      _history.push({ role: "agent", content: `Error: ${e.message}`, sources: [], fallback: true });
      renderThread();
      setStatus(e.message, true);
    } finally {
      _busy = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  /* ── clear ── */
  function clearChat() {
    _history = [];
    renderThread();
    renderTrace([]);
    setStatus("");
    const badge = qs("#wa-model-badge");
    if (badge) badge.textContent = "";
  }

  /* ── init ── */
  function init() {
    /* starter prompts */
    document.querySelectorAll(".wa-starter-btn").forEach((btn) => {
      btn.addEventListener("click", () => send(btn.dataset.prompt));
    });

    /* send button */
    const sendBtn = qs("#wa-send-btn");
    if (sendBtn) sendBtn.addEventListener("click", () => {
      const v = (qs("#wa-input") || {}).value?.trim();
      if (v) send(v);
    });

    /* input enter */
    const input = qs("#wa-input");
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          const v = input.value.trim();
          if (v) send(v);
        }
      });
      input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 160) + "px";
      });
    }

    /* clear */
    const clearBtn = qs("#wa-clear-btn");
    if (clearBtn) clearBtn.addEventListener("click", clearChat);

    /* trace toggle */
    const traceToggle = qs("#wa-trace-toggle");
    const tracePane = qs("#wa-trace-pane");
    if (traceToggle && tracePane) {
      traceToggle.addEventListener("click", () => {
        _traceVisible = !_traceVisible;
        tracePane.classList.toggle("wa-trace-hidden", !_traceVisible);
        traceToggle.textContent = _traceVisible ? "◀" : "▶";
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
