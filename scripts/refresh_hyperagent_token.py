#!/usr/bin/env python3
"""Refresh the private Hyperagent OAuth token used by the Warden hub.

The token file is an operator-managed system file and is never checked in.
This helper intentionally logs only success/failure metadata, never tokens.
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


ENV_PATH = Path(os.getenv("HYPERAGENT_ENV_PATH", "/etc/warden-hyperagent.env"))


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env(path: Path, values: dict[str, str]) -> None:
    content = "".join(f"{key}={value}\n" for key, value in values.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    if not ENV_PATH.exists():
        print("hyperagent refresh skipped: credential file is absent")
        return 0
    values = _read_env(ENV_PATH)
    refresh = values.get("HYPERAGENT_REFRESH_TOKEN", "")
    client_id = values.get("HYPERAGENT_CLIENT_ID", "")
    token_url = values.get("HYPERAGENT_TOKEN_URL", "https://hyperagent.com/api/oauth/token")
    resource = values.get("HYPERAGENT_RESOURCE", "https://hyperagent.com/api/mcp")
    if not refresh or not client_id:
        print("hyperagent refresh skipped: refresh credentials are incomplete")
        return 0

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh,
        "resource": resource,
    }).encode("ascii")
    request = urllib.request.Request(
        token_url,
        data=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            import json

            token_response = json.load(response)
    except Exception as exc:  # pragma: no cover - exercised by the systemd job
        print(f"hyperagent refresh failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    access_token = str(token_response.get("access_token", "")).strip()
    if not access_token:
        print("hyperagent refresh failed: provider returned no access token", file=sys.stderr)
        return 1
    values["HYPERAGENT_AUTHORIZATION"] = f"Bearer {access_token}"
    rotated_refresh = str(token_response.get("refresh_token", "")).strip()
    if rotated_refresh:
        values["HYPERAGENT_REFRESH_TOKEN"] = rotated_refresh
    _write_env(ENV_PATH, values)
    print("hyperagent refresh succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
