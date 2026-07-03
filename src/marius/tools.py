import subprocess
import os
import re
from pathlib import Path
from typing import Dict, Any, List

REPO_ROOT = Path(__file__).resolve().parents[2]

def redact_secrets(text: str) -> str:
    # Basic redaction for common secret patterns
    # API Keys: typical 32-64 chars hex or base64
    # Improved regex to handle "key is ...", "key: ...", "key=...", etc.
    text = re.sub(r'(?i)(api[_-]?key|secret|token|password|auth|credential)(?:\s+|[:=]["\s]*|["\s]+is\s+)["\']?([a-zA-Z0-9_\-\.]{16,})["\']?', r'\1: [REDACTED]', text)
    # Common prefixes like sk- or gpt-
    text = re.sub(r'\b(sk|gpt|ghp|gho|ghu|ghs|ghr)-[a-zA-Z0-9]{20,}\b', r'[REDACTED]', text)
    # URLs with credentials
    text = re.sub(r'([a-z]+://)([^:]+):([^@]+)@', r'\1[USER]:[PASSWORD]@', text)
    return text

def get_git_status() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--short"],
            capture_output=True,
            text=True,
            check=False
        )
        if proc.returncode != 0:
            return f"Error running git status: {proc.stderr}"
        return proc.stdout.strip() or "Clean"
    except Exception as e:
        return f"Failed to get git status: {str(e)}"

def get_service_status() -> List[Dict[str, str]]:
    services = ["mcharness-cockpit", "mcharness-cockpit-private"]
    status_list = []
    for svc in services:
        try:
            # Check if systemctl is available and if we can use it
            proc = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True,
                text=True,
                check=False
            )
            state = proc.stdout.strip()
            status_list.append({"service": svc, "status": state})
        except Exception:
            status_list.append({"service": svc, "status": "unknown (systemctl failed)"})
    return status_list

def get_recent_logs(service: str, lines: int = 20) -> str:
    try:
        # Try journalctl first
        proc = subprocess.run(
            ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            check=False
        )
        if proc.returncode == 0 and proc.stdout:
            return redact_secrets(proc.stdout)
        
        # Fallback to checking common log locations if needed, 
        # but for now we'll stick to systemd logs as requested
        return f"No logs found for {service} via journalctl"
    except Exception as e:
        return f"Failed to get logs: {str(e)}"

def get_system_status() -> Dict[str, Any]:
    return {
        "git": get_git_status(),
        "services": get_service_status(),
        "load": os.getloadavg() if hasattr(os, 'getloadavg') else "N/A"
    }
