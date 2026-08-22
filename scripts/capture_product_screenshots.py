import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_HTML = REPO_ROOT / "desktop" / "dist" / "index.html"
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Mock Desktop API to run in headless browser
MOCK_PRELOAD_JS = """
window.wardenDesk = {
  app: {
    info: async () => ({ name: 'Warden AI Desk', version: '0.6.0-rc.1', platform: 'linux', arch: 'x64' }),
  },
  state: {
    get: async () => ({
      state: {
        workspace: 'team-chat',
        selectedPlatformId: 'p1',
        activeProjectId: 'proj_1',
        recentProjects: ['/home/matt/workspaces/warden'],
        browserProfiles: [{ id: 'prof_1', name: 'Personal' }, { id: 'prof_2', name: 'Startup' }],
        platforms: [
          { id: 'p1', name: 'Gemini', startUrl: 'https://gemini.google.com', category: 'Chat', enabled: true, pinned: true, order: 0, icon: { kind: 'text', value: 'G' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['google.com'], trustedAuthDomains: ['accounts.google.com'] },
          { id: 'p2', name: 'OpenAI Codex', startUrl: 'https://chatgpt.com', category: 'Build', enabled: true, pinned: true, order: 1, icon: { kind: 'text', value: 'C' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['openai.com'], trustedAuthDomains: ['auth0.openai.com'] },
          { id: 'p3', name: 'Anthropic Claude', startUrl: 'https://claude.ai', category: 'Chat', enabled: true, pinned: false, order: 2, icon: { kind: 'text', value: 'C' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['claude.ai'], trustedAuthDomains: ['accounts.anthropic.com'] },
          { id: 'p4', name: 'xAI Grok', startUrl: 'https://grok.com', category: 'Chat', enabled: true, pinned: false, order: 3, icon: { kind: 'text', value: 'X' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['grok.com'], trustedAuthDomains: ['x.com'] }
        ],
        removedPlatforms: [],
        projects: [
          { id: 'proj_1', name: 'Warden', cwd: '/home/matt/workspaces/warden', branch: 'master', executionMode: 'local', workspace: 'team-chat' },
          { id: 'proj_2', name: 'GradeMy', cwd: '/home/matt/workspaces/grademy', branch: 'main', executionMode: 'local', workspace: 'team-chat' }
        ],
        terminals: [],
        windowBounds: { x: 0, y: 0, width: 1200, height: 800 },
        mode: 'simple',
        onboardingComplete: true
      },
      warning: null
    }),
    update: async () => ({})
  },
  project: {
    list: async () => ([
      { id: 'proj_1', name: 'Warden', cwd: '/home/matt/workspaces/warden', branch: 'master', executionMode: 'local', workspace: 'team-chat' },
      { id: 'proj_2', name: 'GradeMy', cwd: '/home/matt/workspaces/grademy', branch: 'main', executionMode: 'local', workspace: 'team-chat' }
    ]),
    create: async ({ cwd }) => ({ id: 'proj_new', name: 'New Project', cwd, branch: 'master', executionMode: 'local', workspace: 'team-chat' }),
    activate: async (id) => ({ id, name: id === 'proj_1' ? 'Warden' : 'GradeMy', cwd: '/home/matt/workspaces/warden', branch: 'master', executionMode: 'local', workspace: 'team-chat' }),
    update: async () => ({})
  },
  platform: {
    list: async () => ([
      { id: 'p1', name: 'Gemini', startUrl: 'https://gemini.google.com', category: 'Chat', enabled: true, pinned: true, order: 0, icon: { kind: 'text', value: 'G' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['google.com'], trustedAuthDomains: ['accounts.google.com'] },
      { id: 'p2', name: 'OpenAI Codex', startUrl: 'https://chatgpt.com', category: 'Build', enabled: true, pinned: true, order: 1, icon: { kind: 'text', value: 'C' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['openai.com'], trustedAuthDomains: ['auth0.openai.com'] },
      { id: 'p3', name: 'Anthropic Claude', startUrl: 'https://claude.ai', category: 'Chat', enabled: true, pinned: false, order: 2, icon: { kind: 'text', value: 'C' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['claude.ai'], trustedAuthDomains: ['accounts.anthropic.com'] },
      { id: 'p4', name: 'xAI Grok', startUrl: 'https://grok.com', category: 'Chat', enabled: true, pinned: false, order: 3, icon: { kind: 'text', value: 'X' }, browserProfileId: 'prof_1', allowMainView: true, allowSplitView: true, trustedFirstPartyDomains: ['grok.com'], trustedAuthDomains: ['x.com'] }
    ]),
    presets: async () => ([]),
    profiles: async () => ([{ id: 'prof_1', name: 'Personal' }, { id: 'prof_2', name: 'Startup' }]),
    show: async () => ({}),
    hide: async () => ({}),
    setBounds: () => ({}),
    action: async () => ({}),
    onStatus: () => () => {},
    onMenuAction: () => () => {}
  },
  terminal: {
    list: async () => ([]),
    create: async ({ name, cwd }) => ({ id: 'term_1', name, cwd, status: 'running', history: [] }),
    write: () => {},
    resize: () => {},
    kill: async () => {},
    clearHistory: async () => {},
    recordCommand: async () => {},
    onData: () => () => {},
    onState: () => () => {}
  },
  runs: {
    providers: async () => ([
      { provider: 'codex', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'codex', version: '0.6.0', entitlement: 'plus', detail: 'Subscription authenticated', canStart: true, apiFallbackAvailable: false },
      { provider: 'gemini', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'gemini', version: '0.6.0', entitlement: 'pro', detail: 'Google Cloud ADC ready', canStart: true, apiFallbackAvailable: true }
    ]),
    checkProject: async () => ({ isGit: true, clean: true }),
    list: async () => ([]),
    get: async () => null,
    start: async () => ({ id: 'run_123', status: 'completed', prompt: 'Warden Mission', cwd: '/home/matt/workspaces/warden', safeWorkspace: { status: 'active' }, events: [], approvals: [], evidence: { changedFiles: ['index.html'], tests: [{ name: 'Visual match', exitCode: 0, stdout: 'OK' }] }, updatedAt: new Date().toISOString() }),
    approve: async () => ({}),
    keep: async () => ({}),
    discard: async () => ({}),
    undoUpdate: async () => ({}),
    previewContext: async () => ({}),
    onChanged: () => () => {}
  },
  warden: {
    serverHealth: async () => true,
    serverStatus: async () => ({ healthy: true, starting: false, error: null }),
    ensureServer: async () => true
  }
};
"""

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        for width, height, suffix in [(1920, 1080, "1920x1080"), (1024, 700, "1024x700")]:
            context = await browser.new_context(viewport={"width": width, "height": height})
            page = await context.new_page()

            await page.add_init_script(MOCK_PRELOAD_JS)
            await page.goto(DIST_HTML.as_uri())
            await page.wait_for_load_state("networkidle")

            # 1. Home Screen
            await page.evaluate("window.selectNav('home')")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT_DIR / f"01_home_{suffix}.png"))
            print(f"Captured 01_home_{suffix}.png")

            # 2. Projects & Nested Missions Rail
            await page.evaluate("window.selectNav('home')")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(OUT_DIR / f"02_projects_rail_{suffix}.png"))
            print(f"Captured 02_projects_rail_{suffix}.png")

            # 3. Active Hybrid Mission
            await page.evaluate("window.openMission('m_sample_1')")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT_DIR / f"03_active_hybrid_mission_{suffix}.png"))
            print(f"Captured 03_active_hybrid_mission_{suffix}.png")

            # 4. Browser Work Expanded
            await page.evaluate("window.selectContextTab('browser')")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(OUT_DIR / f"04_browser_work_expanded_{suffix}.png"))
            print(f"Captured 04_browser_work_expanded_{suffix}.png")

            # 5. Terminal Work Expanded
            await page.evaluate("window.selectContextTab('terminal')")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(OUT_DIR / f"05_terminal_work_expanded_{suffix}.png"))
            print(f"Captured 05_terminal_work_expanded_{suffix}.png")

            # 6. Build Diff & Review
            await page.evaluate("window.selectContextTab('build')")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(OUT_DIR / f"06_build_diff_review_{suffix}.png"))
            print(f"Captured 06_build_diff_review_{suffix}.png")

            # 7. Needs You with Real Actions
            await page.evaluate("window.selectNav('needs-you')")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT_DIR / f"07_needs_you_{suffix}.png"))
            print(f"Captured 07_needs_you_{suffix}.png")

            # 8. Connected AIs Screen
            await page.evaluate("window.selectNav('connected-ais')")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT_DIR / f"08_connected_ais_{suffix}.png"))
            print(f"Captured 08_connected_ais_{suffix}.png")

            # 9. Completed Mission + Proof
            await page.evaluate("window.openMission('m_sample_1'); window.selectContextTab('proof');")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT_DIR / f"09_completed_mission_proof_{suffix}.png"))
            print(f"Captured 09_completed_mission_proof_{suffix}.png")

            # 10/11. Full resolution captures
            await page.evaluate("window.selectNav('home')")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(OUT_DIR / f"10_full_app_{suffix}.png"))
            print(f"Captured 10_full_app_{suffix}.png")

            await context.close()

        await browser.close()
    print("All screenshots successfully captured in docs/screenshots/")

if __name__ == "__main__":
    asyncio.run(capture())
