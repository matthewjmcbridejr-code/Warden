"""Warden CLI — the one command a new user needs.

    warden up        start Warden and open it in your browser
    warden mcp       run the Warden Brain MCP server on stdio (for agent clients)
    warden status    check whether Warden is running

Installed via [project.scripts] in pyproject.toml. Internal imports use the
src.* layout, so this module resolves the repo root from its own location
and runs uvicorn against the same import string the docs use.
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_HOST = os.getenv("WARDEN_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("WARDEN_PORT", "4242"))


def _ensure_src_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def cmd_up(args: argparse.Namespace) -> int:
    _ensure_src_on_path()
    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print(f"Warden starting — opening {url}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(
        "src.warden.app:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


def cmd_mcp(_args: argparse.Namespace) -> int:
    _ensure_src_on_path()
    from src.warden.brain_mcp_server import main as mcp_main

    sys.argv = ["warden-brain-mcp"]
    mcp_main()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import httpx

    url = f"http://{args.host}:{args.port}/api/mcharness/health"
    try:
        r = httpx.get(url, timeout=3.0)
        print(f"Warden is up at http://{args.host}:{args.port} (status {r.status_code})")
        return 0
    except Exception:
        print(f"Warden is not responding at http://{args.host}:{args.port} — try: warden up")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="warden", description="Local-first control room for AI coding agents.")
    sub = parser.add_subparsers(dest="command")

    p_up = sub.add_parser("up", help="Start Warden and open it in your browser")
    p_up.add_argument("--host", default=DEFAULT_HOST)
    p_up.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_up.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    p_up.set_defaults(fn=cmd_up)

    p_mcp = sub.add_parser("mcp", help="Run the Warden Brain MCP server on stdio")
    p_mcp.set_defaults(fn=cmd_mcp)

    p_status = sub.add_parser("status", help="Check whether Warden is running")
    p_status.add_argument("--host", default=DEFAULT_HOST)
    p_status.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_status.set_defaults(fn=cmd_status)

    args = parser.parse_args()
    if not getattr(args, "fn", None):
        parser.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
