(function () {
  "use strict";

  function render(status, user) {
    const existing = document.getElementById("warden-cloud-auth");
    if (existing) existing.remove();
    const el = document.createElement("div");
    el.id = "warden-cloud-auth";
    el.style.cssText = "position:fixed;top:10px;right:14px;z-index:10020;padding:7px 10px;border:1px solid var(--line,#394354);border-radius:6px;background:var(--bg-2,#202733);color:var(--muted,#aab6c7);font:12px system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.25)";
    if (status === "authenticated") {
      const label = user.name || user.email || "Vercel user";
      el.innerHTML = `<span>Cloud: ${escapeHtml(label)}</span> <a href="/api/auth/logout" style="margin-left:8px;color:inherit">Sign out</a>`;
    } else if (status === "unauthenticated") {
      el.innerHTML = '<a href="/api/auth/vercel" style="color:inherit">Sign in with Vercel</a>';
    } else {
      el.textContent = "Cloud sign-in is not configured";
    }
    document.body.appendChild(el);
  }

  function escapeHtml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
  }

  async function load() {
    try {
      const response = await fetch("/api/auth/session", { headers: { accept: "application/json" } });
      if (response.ok) return render("authenticated", (await response.json()).user || {});
      if (response.status === 401) return render("unauthenticated");
    } catch (_) {
      // Keep the cockpit usable when the optional auth status endpoint is down.
    }
    render("unconfigured");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
