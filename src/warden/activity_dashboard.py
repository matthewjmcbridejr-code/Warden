"""Operator activity dashboard on the MCP edge.

The stable page is ``/dash`` on the same host that serves ``/mcp``.
Cloud Run stays private. When ``MCP_OAUTH_OWNER_PASSPHRASE`` is set, the page
requires that passphrase once and then keeps an HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

_PATHS = {"/dash", "/dash/", "/dash/activity", "/dash/login"}
_COOKIE = "warden_dash"


def dashboard_public_url() -> str:
    return os.getenv("WARDEN_DASH_PUBLIC_URL", "https://mcp.mctable.online/dash")


def _passphrase() -> str:
    return os.getenv("MCP_OAUTH_OWNER_PASSPHRASE", "")


def _cookie_value(secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), b"warden-dash-v1", hashlib.sha256).hexdigest()


def _authorized(request: Request) -> bool:
    secret = _passphrase()
    if not secret:
        return True
    presented = request.cookies.get(_COOKIE, "")
    return hmac.compare_digest(presented, _cookie_value(secret))


def _login_html(error: str = "") -> str:
    message = f"<p class=\"err\">{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Warden activity</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ margin: 0; font: 15px/1.45 ui-sans-serif, system-ui, sans-serif; background: #10141a; color: #e7eef6; }}
main {{ max-width: 420px; margin: 12vh auto; padding: 24px; }}
input, button {{ font: inherit; }}
input {{ width: 100%; box-sizing: border-box; margin: 8px 0 12px; padding: 8px; }}
.err {{ color: #f07178; }}
</style></head><body><main>
<h1>Warden activity</h1>
<p>This dashboard uses the same owner passphrase as the MCP consent screen.</p>
{message}
<form method="post" action="/dash/login">
<label>Passphrase <input type="password" name="passphrase" autocomplete="current-password" required></label>
<button type="submit">Open dashboard</button>
</form>
</main></body></html>"""


def _page_html() -> str:
    public = dashboard_public_url()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Warden activity</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ margin: 0; font: 15px/1.45 ui-sans-serif, system-ui, sans-serif; background: #10141a; color: #e7eef6; }}
main {{ max-width: 960px; margin: 0 auto; padding: 20px; }}
.row {{ display: grid; grid-template-columns: 168px 92px minmax(0,1fr); gap: 10px; padding: 10px 0; border-bottom: 1px solid #243041; }}
.muted {{ color: #9cacbf; font-size: 13px; }}
.where {{ color: #8b7cff; text-transform: uppercase; font-size: 12px; font-weight: 650; }}
button {{ font: inherit; margin-right: 6px; }}
@media (max-width: 720px) {{ .row {{ grid-template-columns: 1fr; }} }}
</style></head><body><main>
<h1>Activity</h1>
<p class="muted" id="status">Loading…</p>
<p class="muted">Stable page: {public}. MCP stays at /mcp on this host. Cloud Run is not the public dashboard.</p>
<div id="filters">
<button type="button" data-dest="">All</button>
<button type="button" data-dest="memory">Memory</button>
<button type="button" data-dest="mcp">MCP</button>
<button type="button" data-dest="brain">Brain</button>
<button type="button" data-dest="board">Missions</button>
<button type="button" data-dest="artifact">Artifacts</button>
</div>
<div id="list"></div>
<script>
const list = document.getElementById("list");
const status = document.getElementById("status");
let dest = "";
function render(payload) {{
  const events = (payload.events || []).filter(row => !dest || row.destination === dest || row.landed === dest);
  status.textContent = (payload.placement && payload.placement.control_plane ? payload.placement.control_plane + " · " : "") + events.length + " shown · " + (payload.generated_at || "");
  list.replaceChildren();
  if (!events.length) {{
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No writes in this view yet.";
    list.appendChild(empty);
    return;
  }}
  for (const row of events) {{
    const item = document.createElement("div");
    item.className = "row";
    const when = document.createElement("div");
    when.className = "muted";
    when.textContent = row.at || "";
    const where = document.createElement("div");
    where.className = "where";
    where.textContent = row.destination || "";
    const body = document.createElement("div");
    const title = document.createElement("div");
    title.textContent = (row.agent ? row.agent + " · " : "") + (row.title || row.tool || "write");
    const meta = document.createElement("div");
    meta.className = "muted";
    meta.textContent = [row.tool, row.ref, row.project].filter(Boolean).join(" · ");
    body.append(title, meta);
    item.append(when, where, body);
    list.appendChild(item);
  }}
}}
async function load() {{
  const response = await fetch("/dash/activity" + (dest ? "?destination=" + encodeURIComponent(dest) : ""), {{ credentials: "same-origin" }});
  if (response.status === 401) {{ location.href = "/dash"; return; }}
  render(await response.json());
}}
document.getElementById("filters").addEventListener("click", (event) => {{
  const button = event.target.closest("button");
  if (!button) return;
  dest = button.dataset.dest || "";
  load();
}});
load();
setInterval(load, 8000);
</script>
</main></body></html>"""


def _set_cookie(response: Response, request: Request, secret: str) -> Response:
    response.set_cookie(
        _COOKIE,
        _cookie_value(secret),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/dash",
        max_age=60 * 60 * 12,
    )
    return response


async def handle_dashboard(scope: dict[str, Any], receive: Any, send: Any) -> bool:
    """Serve /dash. Returns False when the path belongs to the MCP app."""
    if scope.get("type") != "http" or scope.get("path") not in _PATHS:
        return False
    request = Request(scope, receive)
    path = request.url.path
    if path == "/dash/":
        await RedirectResponse("/dash", status_code=307)(scope, receive, send)
        return True
    if path == "/dash/login" and request.method == "POST":
        form = await request.form()
        given = str(form.get("passphrase") or "")
        secret = _passphrase()
        if secret and hmac.compare_digest(given, secret):
            response = _set_cookie(RedirectResponse("/dash", status_code=303), request, secret)
        else:
            response = HTMLResponse(_login_html("That passphrase was not accepted."), status_code=401)
        await response(scope, receive, send)
        return True
    if not _authorized(request):
        await HTMLResponse(_login_html(), status_code=401)(scope, receive, send)
        return True
    if path == "/dash/activity":
        from src.warden.activity_feed import build_activity_feed
        destination = request.query_params.get("destination", "")
        payload = build_activity_feed(limit=80, destination=destination)
        await JSONResponse(payload)(scope, receive, send)
        return True
    await HTMLResponse(_page_html())(scope, receive, send)
    return True
