from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WARDEN_APP = ROOT / "web" / "warden" / "index.html"
COMMAND_DECK_APP = ROOT / "web" / "warden" / "command-deck.html"
COMMAND_DECK_JS = ROOT / "web" / "warden" / "command-deck.js"


def test_warden_app_static_asset_exists():
    assert WARDEN_APP.is_file(), "web/warden/index.html must exist"


def test_warden_app_contains_branding_copy():
    content = WARDEN_APP.read_text(encoding="utf-8")
    assert "Warden" in content
    assert "by Marius Systems" in content
    assert "Powered by McHarness" in content


def test_warden_app_has_control_room_sections():
    content = WARDEN_APP.read_text(encoding="utf-8")
    required_snippets = [
        "Warden",
        "by Marius Systems",
        "Supervise missions, runs, and proof gates.",
        "Control Room",
        "Agents",
        "agent-group-captain",
        "captain-create-plan-btn",
        "codex-open-monitor",
        "CLI Agents",
        "agent-group-remote",
        "captain-profile-panel",
        "Executes approved CLI tasks",
        "captain-deck-modal",
        "Develop Plan",
        "Deploy Current Step",
        "current-mission-plan",
        "cr-command-center",
        "rail-proof-gates",
        "runner-sessions-table",
        "control-room.js",
        "runs-list",
        "evidence-list",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"Missing Warden UI snippet: {snippet}"

    banned_snippets = [
        "Legacy Cockpit",
        "Marius Desktop",
        "McTable Studio",
        "SERVER CONTROL PLANE",
    ]
    for snippet in banned_snippets:
        assert snippet not in content, f"Legacy product copy found: {snippet}"


def test_command_deck_static_assets_exist_and_are_linked():
    assert COMMAND_DECK_APP.is_file(), "web/warden/command-deck.html must exist"
    assert COMMAND_DECK_JS.is_file(), "web/warden/command-deck.js must exist"

    shell = WARDEN_APP.read_text(encoding="utf-8")
    assert "command-deck.html" in shell


def test_command_deck_static_html_has_hero_copy():
    content = COMMAND_DECK_APP.read_text(encoding="utf-8")
    assert "Warden Command Deck" in content
    assert "Local-first AI workforce control plane" in content


def test_command_deck_contains_required_portfolio_panels():
    content = COMMAND_DECK_APP.read_text(encoding="utf-8")
    script = COMMAND_DECK_JS.read_text(encoding="utf-8")
    required_snippets = [
        "Warden Command Deck",
        "Run Demo Mission",
        "agent-grid",
        "mission-board",
        "proof-ledger",
        "relay-timeline",
        "memory-chat-log",
        "notion-sync-panel",
        "Preview Sync",
        "command-deck.js",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"Missing Command Deck snippet: {snippet}"

    for snippet in [
        "/api/mcharness/warden/command-deck",
        "/api/mcharness/warden/notion/sync",
        "previewNotionSync",
        "proof_needed",
        "Verified",
        "Proof Needed",
    ]:
        assert snippet in script, f"Missing Command Deck script snippet: {snippet}"


def test_command_deck_workspace_authority_panel_exists():
    content = COMMAND_DECK_APP.read_text(encoding="utf-8")
    required = [
        "workspace-authority-panel",
        "Workspace Authority",
        "ws-canonical",
        "ws-scratch-list",
        "ws-proof-cmds",
        "Refuse edits from non-canonical worktrees",
    ]
    for snippet in required:
        assert snippet in content, f"Missing Workspace Authority panel snippet: {snippet}"


def test_command_deck_js_calls_workspace_authority_api():
    script = COMMAND_DECK_JS.read_text(encoding="utf-8")
    assert "/warden/workspaces/warden" in script, "JS must call workspace authority API"
    assert "loadWorkspaceAuthority" in script, "JS must have loadWorkspaceAuthority function"


def test_command_deck_has_notion_sync_panel():
    content = COMMAND_DECK_APP.read_text(encoding="utf-8")
    script = COMMAND_DECK_JS.read_text(encoding="utf-8")
    for snippet in [
        "notion-sync-panel",
        "Notion Sync",
        "Dry-run Candidate Preview",
        "preview-notion-sync",
    ]:
        assert snippet in content, f"Missing Notion sync panel snippet: {snippet}"
    for snippet in [
        "NOTION_SYNC_BASE",
        "/api/mcharness/warden/notion/sync",
        "previewNotionSync",
        "renderNotionSyncPreview",
    ]:
        assert snippet in script, f"Missing Notion sync script snippet: {snippet}"
