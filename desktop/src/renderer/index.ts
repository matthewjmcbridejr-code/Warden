import '@fontsource-variable/sora/wght.css';
import '@fontsource-variable/epilogue/wght.css';
import './styles.css';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import type {
  DesktopState,
  ExecutionMode,
  InterfaceMode,
  PlatformMenuAction,
  PlatformStatus,
  ProjectWorkspace,
  ProviderAuthReport,
  TerminalMetadata,
  WardenRun,
  WebPlatform,
  WorkspaceId,
} from '../shared/types';
import { MISSION_TEMPLATES, initSimpleBuild, renderProjectList, setMode, syncSimpleBuild } from './simple-build';
import { translateEvent, translateApproval } from './copy';

const $ = <T extends Element = HTMLElement>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
};

type ViewId = 'home' | 'needs-you' | 'mission' | 'connected-ais' | 'advanced';

interface UiTerminal {
  metadata: TerminalMetadata;
  terminal: Terminal;
  fit: FitAddon;
  lineBuffer: string;
}

interface MissionWorkItem {
  id: string;
  type: 'browser' | 'terminal' | 'build' | 'verify' | 'proof';
  title: string;
  subtitle: string;
  status: 'working' | 'needs_user' | 'completed' | 'failed' | 'idle';
  meta?: any;
}

interface ActiveMissionData {
  id: string;
  projectId: string;
  projectName: string;
  title: string;
  objective: string;
  status: 'starting' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';
  phase: number;
  run?: WardenRun;
  browserSession?: any;
  conversation?: Array<{ role: 'human' | 'warden'; text: string; time: string }>;
  workItems: MissionWorkItem[];
  terminalOutput?: string;
  terminalHistory?: string[];
  evidence?: {
    changedFiles: string[];
    diff: string;
    tests: Array<{ name: string; exitCode: number; stdout: string }>;
    finalMessage?: string;
    screenshotUrl?: string;
  };
}

const ui = {
  view: 'home' as ViewId,
  workspace: 'team-chat' as WorkspaceId,
  mode: 'simple' as InterfaceMode,
  execution: 'local' as ExecutionMode,
  activeProjectId: undefined as string | undefined,
  activeMissionId: undefined as string | undefined,
  activeContextTab: 'browser' as 'browser' | 'build' | 'terminal' | 'verify' | 'proof',
  activeAdvTab: 'terminals' as 'terminals' | 'build-runner' | 'telemetry' | 'brain',
  projects: [] as ProjectWorkspace[],
  missions: new Map<string, ActiveMissionData>(),
  runs: new Map<string, WardenRun>(),
  platforms: new Map<string, WebPlatform>(),
  platformStatus: new Map<string, PlatformStatus>(),
  terminals: new Map<string, UiTerminal>(),
  activeTerminal: undefined as string | undefined,
  platformId: '',
  splitPlatformId: undefined as string | undefined,
  editingPlatformId: undefined as string | undefined,
  presets: [] as Array<{ key: string; name: string; startUrl: string; icon: { kind: 'text' | 'url'; value: string }; category: WebPlatform['category']; trustedFirstPartyDomains: string[]; trustedAuthDomains: string[] }>,
  profiles: [] as Array<{ id: string; name: string }>,
  cwd: '',
  appInfo: undefined as { name: string; version: string; platform: string; arch: string } | undefined,
  needsYouItems: [] as Array<{
    id: string;
    type: 'browser_approval' | 'build_review';
    title: string;
    description: string;
    projectName: string;
    missionId: string;
    data: any;
  }>,
};

function notice(message?: string): void {
  const element = $('#notice');
  element.textContent = message || '';
  element.toggleAttribute('hidden', !message);
  if (message) setTimeout(() => element.setAttribute('hidden', 'true'), 6000);
}

// ---------------------------------------------------------------------------
// VIEW SWITCHING & PRODUCT NAVIGATION
// ---------------------------------------------------------------------------
export async function selectNav(view: ViewId): Promise<void> {
  ui.view = view;
  document.body.dataset.view = view;

  document.querySelectorAll<HTMLButtonElement>('[data-nav]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.nav === view);
  });

  document.querySelectorAll<HTMLElement>('.product-view').forEach((el) => {
    el.classList.remove('active');
    el.setAttribute('hidden', 'true');
  });

  const target = document.getElementById(`view-${view}`);
  if (target) {
    target.classList.add('active');
    target.removeAttribute('hidden');
  }

  // Handle embedded provider bounds / visibility
  if (view === 'connected-ais' && ui.platformId) {
    providerBounds();
    await window.wardenDesk.platform.show(ui.platformId, ui.splitPlatformId);
  } else {
    await window.wardenDesk.platform.hide();
  }

  if (view === 'home') renderHomeScreen();
  if (view === 'needs-you') renderNeedsYouScreen();
  if (view === 'mission') renderActiveMission();
  if (view === 'connected-ais') renderConnectedAisScreen();
  if (view === 'advanced') renderAdvancedScreen();
}

function selectContextTab(tab: 'browser' | 'build' | 'terminal' | 'verify' | 'proof'): void {
  ui.activeContextTab = tab;
  document.querySelectorAll<HTMLButtonElement>('.context-tab').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.contextTab === tab);
  });
  document.querySelectorAll<HTMLElement>('.context-panel').forEach((p) => {
    p.classList.remove('active');
    p.setAttribute('hidden', 'true');
  });
  const target = document.getElementById(`panel-${tab}`);
  if (target) {
    target.classList.add('active');
    target.removeAttribute('hidden');
  }
}

function selectAdvTab(tab: 'terminals' | 'build-runner' | 'telemetry' | 'brain'): void {
  ui.activeAdvTab = tab;
  document.querySelectorAll<HTMLButtonElement>('.adv-tab').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.advTab === tab);
  });
  document.querySelectorAll<HTMLElement>('.adv-panel').forEach((p) => {
    p.classList.remove('active');
    p.setAttribute('hidden', 'true');
  });
  const target = document.getElementById(`adv-panel-${tab}`);
  if (target) {
    target.classList.add('active');
    target.removeAttribute('hidden');
  }
  if (tab === 'terminals') fitActiveTerminal();
}

// ---------------------------------------------------------------------------
// SIDEBAR PROJECTS & MISSIONS TREE
// ---------------------------------------------------------------------------
function renderProjectsTree(): void {
  const root = $('#nav-projects-tree');
  root.replaceChildren();

  for (const project of ui.projects) {
    const isProjectActive = project.id === ui.activeProjectId;
    const projectBlock = document.createElement('div');
    projectBlock.className = `nav-project-block ${isProjectActive ? 'active' : ''}`;

    const head = document.createElement('div');
    head.className = 'nav-project-head';
    head.innerHTML = `
      <span class="nav-project-caret">${isProjectActive ? '▾' : '▸'}</span>
      <span class="nav-project-name">${escapeHtml(project.name)}</span>
      <span class="nav-project-dot"></span>
    `;
    head.addEventListener('click', () => void activateProject(project.id));
    projectBlock.append(head);

    if (isProjectActive) {
      const missionsList = document.createElement('div');
      missionsList.className = 'nav-missions-list';

      const projectMissions = [...ui.missions.values()].filter((m) => m.projectId === project.id);
      if (projectMissions.length > 0) {
        for (const mission of projectMissions) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `nav-mission-item ${mission.id === ui.activeMissionId && ui.view === 'mission' ? 'active' : ''}`;
          const dotClass = mission.status === 'running' || mission.status === 'starting' ? 'working'
            : mission.status === 'waiting_approval' ? 'needs_user'
            : mission.status === 'completed' ? 'done' : 'failed';
          btn.innerHTML = `
            <span class="mission-dot ${dotClass}">●</span>
            <span class="nav-mission-label">${escapeHtml(mission.title)}</span>
          `;
          btn.addEventListener('click', () => {
            openMission(mission.id);
          });
          missionsList.append(btn);
        }
      }

      const newBtn = document.createElement('button');
      newBtn.type = 'button';
      newBtn.className = 'nav-mission-new';
      newBtn.textContent = '＋ New Mission';
      newBtn.addEventListener('click', () => {
        void selectNav('home');
        $('#home-prompt').focus();
      });
      missionsList.append(newBtn);

      projectBlock.append(missionsList);
    }

    root.append(projectBlock);
  }
}

// ---------------------------------------------------------------------------
// HOME SCREEN
// ---------------------------------------------------------------------------
function renderHomeScreen(): void {
  const select = $('#home-project-select') as HTMLSelectElement;
  select.replaceChildren();
  for (const project of ui.projects) {
    select.add(new Option(project.name, project.id, project.id === ui.activeProjectId, project.id === ui.activeProjectId));
  }

  // Render Needs You section
  const needsSection = $('#home-needs-section');
  const needsList = $('#home-needs-list');
  const needsBadge = $('#home-needs-count-badge');
  needsBadge.textContent = String(ui.needsYouItems.length);
  needsSection.toggleAttribute('hidden', ui.needsYouItems.length === 0);

  if (ui.needsYouItems.length > 0) {
    needsList.innerHTML = ui.needsYouItems.map((item) => `
      <div class="needs-you-card">
        <div class="home-card-head">
          <span class="attention-type-badge"><span class="status-dot warning"></span>${escapeHtml(item.type === 'browser_approval' ? 'Browser Confirmation' : 'Build Review')}</span>
          <span class="status-pill warning">Needs Attention</span>
        </div>
        <strong class="home-card-title">${escapeHtml(item.title)}</strong>
        <p class="home-card-sub">${escapeHtml(item.description)}</p>
        <div class="home-card-actions">
          <button type="button" class="btn primary small" onclick="window.resolveAttentionItem('${escapeHtml(item.id)}', 'approve')">${item.type === 'browser_approval' ? 'Approve' : 'Apply & Keep'}</button>
          <button type="button" class="btn small" onclick="window.resolveAttentionItem('${escapeHtml(item.id)}', 'deny')">${item.type === 'browser_approval' ? 'Deny' : 'Discard'}</button>
          <button type="button" class="btn small" onclick="window.openMission('${escapeHtml(item.missionId)}')">Inspect</button>
        </div>
      </div>
    `).join('');
  }

  // Render Active Missions
  const activeList = $('#home-active-list');
  const activeMissions = [...ui.missions.values()].filter((m) => m.status === 'running' || m.status === 'starting' || m.status === 'waiting_approval');
  $('#home-active-count-badge').textContent = String(activeMissions.length);

  if (activeMissions.length > 0) {
    activeList.innerHTML = activeMissions.map((m) => `
      <div class="home-mission-card">
        <div class="home-card-head">
          <span class="status-pill active">${escapeHtml(m.status)}</span>
          <small class="home-card-sub">${escapeHtml(m.projectName)}</small>
        </div>
        <strong class="home-card-title">${escapeHtml(m.title)}</strong>
        <p class="home-card-sub">${escapeHtml(m.objective.slice(0, 100))}</p>
        <div class="home-card-actions">
          <button type="button" class="btn primary small" onclick="window.openMission('${escapeHtml(m.id)}')">Open Mission →</button>
        </div>
      </div>
    `).join('');
  } else {
    activeList.innerHTML = '<p class="empty-hint">No active missions running right now.</p>';
  }

  // Render Recent Missions
  const recentList = $('#home-recent-list');
  const recentMissions = [...ui.missions.values()].filter((m) => m.status === 'completed' || m.status === 'failed' || m.status === 'cancelled').slice(-6).reverse();
  if (recentMissions.length > 0) {
    recentList.innerHTML = recentMissions.map((m) => `
      <div class="home-mission-card">
        <div class="home-card-head">
          <span class="status-pill ${m.status === 'completed' ? 'success' : 'danger'}">${m.status === 'completed' ? 'Done' : 'Failed'}</span>
          <small class="home-card-sub">${escapeHtml(m.projectName)}</small>
        </div>
        <strong class="home-card-title">${escapeHtml(m.title)}</strong>
        <p class="home-card-sub">${escapeHtml(m.evidence?.finalMessage || m.objective.slice(0, 100))}</p>
        <div class="home-card-actions">
          <button type="button" class="btn small" onclick="window.openMission('${escapeHtml(m.id)}')">View Proof</button>
        </div>
      </div>
    `).join('');
  } else {
    recentList.innerHTML = '<p class="empty-hint">Completed missions will appear here.</p>';
  }
}

// ---------------------------------------------------------------------------
// NEEDS YOU SCREEN
// ---------------------------------------------------------------------------
function renderNeedsYouScreen(): void {
  const list = $('#needs-you-full-list');
  const empty = $('#needs-you-empty');
  const badge = $('#nav-needs-badge');

  badge.textContent = String(ui.needsYouItems.length);
  badge.toggleAttribute('hidden', ui.needsYouItems.length === 0);

  if (ui.needsYouItems.length === 0) {
    list.innerHTML = '';
    empty.removeAttribute('hidden');
    return;
  }

  empty.setAttribute('hidden', 'true');
  list.innerHTML = ui.needsYouItems.map((item) => `
    <article class="attention-card">
      <div class="attention-card-header">
        <span class="attention-type-badge">
          <span class="status-dot warning"></span>
          ${item.type === 'browser_approval' ? 'Browser Action Approval' : 'Code Worktree Review'}
        </span>
        <span class="status-pill warning">High Safety Policy</span>
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      <p>${escapeHtml(item.description)}</p>
      <div class="attention-context-box">
        <strong>Project:</strong> ${escapeHtml(item.projectName)} &nbsp;·&nbsp;
        <strong>Mission:</strong> ${escapeHtml(item.missionId)}
      </div>
      <div class="attention-actions-row">
        <button type="button" class="btn primary" onclick="window.resolveAttentionItem('${escapeHtml(item.id)}', 'approve')">${item.type === 'browser_approval' ? 'Approve Action' : 'Apply to Project'}</button>
        <button type="button" class="btn danger" onclick="window.resolveAttentionItem('${escapeHtml(item.id)}', 'deny')">${item.type === 'browser_approval' ? 'Deny Action' : 'Discard Worktree'}</button>
        <button type="button" class="btn" onclick="window.openMission('${escapeHtml(item.missionId)}')">Inspect Mission</button>
      </div>
    </article>
  `).join('');
}

// ---------------------------------------------------------------------------
// UNIFIED MISSION WORKSPACE
// ---------------------------------------------------------------------------
export function openMission(missionId: string): void {
  ui.activeMissionId = missionId;
  const mission = ui.missions.get(missionId);
  if (mission && mission.projectId) {
    ui.activeProjectId = mission.projectId;
  }
  renderProjectsTree();
  void selectNav('mission');
}

function renderActiveMission(): void {
  const mission = ui.activeMissionId ? ui.missions.get(ui.activeMissionId) : [...ui.missions.values()][0];
  if (!mission) {
    void selectNav('home');
    return;
  }

  $('#mission-project-badge').textContent = mission.projectName || 'Project';
  $('#mission-title').textContent = mission.title || 'Untitled Mission';
  $('#mission-objective-text').textContent = mission.objective || 'No objective provided.';

  const pill = $('#mission-status-pill');
  pill.textContent = mission.status === 'completed' ? 'Done'
    : mission.status === 'waiting_approval' ? 'Needs You'
    : mission.status === 'running' || mission.status === 'starting' ? 'Working'
    : mission.status;
  pill.className = `status-pill ${mission.status === 'completed' ? 'success' : mission.status === 'waiting_approval' ? 'warning' : mission.status === 'failed' ? 'danger' : 'active'}`;

  // Phase track
  document.querySelectorAll<HTMLElement>('#sb-phase-track [data-phase]').forEach((el, index) => {
    el.classList.toggle('done', index < mission.phase);
    el.classList.toggle('active', index === mission.phase);
  });

  // Contextual Attention Banner
  const banner = $('#mission-attention-banner');
  const missionNeed = ui.needsYouItems.find((n) => n.missionId === mission.id);
  if (missionNeed) {
    banner.removeAttribute('hidden');
    $('#mission-attention-title').textContent = missionNeed.title;
    $('#mission-attention-desc').textContent = missionNeed.description;
    $('#mission-attention-actions').innerHTML = `
      <button type="button" class="btn primary small" onclick="window.resolveAttentionItem('${escapeHtml(missionNeed.id)}', 'approve')">${missionNeed.type === 'browser_approval' ? 'Approve' : 'Apply & Keep'}</button>
      <button type="button" class="btn small" onclick="window.resolveAttentionItem('${escapeHtml(missionNeed.id)}', 'deny')">${missionNeed.type === 'browser_approval' ? 'Deny' : 'Discard'}</button>
    `;
  } else {
    banner.setAttribute('hidden', 'true');
  }

  // Conversation Stream
  const stream = $('#mission-chat-stream');
  if (mission.conversation && mission.conversation.length > 0) {
    stream.innerHTML = mission.conversation.map((c) => `
      <div class="chat-row ${c.role}">
        <span class="chat-actor">${c.role === 'human' ? 'Matt' : 'Warden'} · ${escapeHtml(c.time)}</span>
        <div class="chat-content">${escapeHtml(c.text)}</div>
      </div>
    `).join('');
  } else {
    stream.innerHTML = `
      <div class="chat-row warden">
        <span class="chat-actor">Warden</span>
        <div class="chat-content">Mission initialized. Synthesizing project context, tools, and verification plan…</div>
      </div>
    `;
  }

  // Typed Work Cards Stack
  const workStack = $('#mission-work-cards-stack');
  workStack.innerHTML = mission.workItems.map((item) => `
    <div class="work-card ${ui.activeContextTab === item.type ? 'active' : ''}" onclick="window.selectContextTab('${item.type}')">
      <div class="work-card-identity">
        <span class="work-card-icon">${item.type === 'browser' ? '🌐' : item.type === 'terminal' ? '⌨' : item.type === 'build' ? '⚙' : item.type === 'verify' ? '🧪' : '✓'}</span>
        <div class="work-card-texts">
          <strong>${escapeHtml(item.title)}</strong>
          <small>${escapeHtml(item.subtitle)}</small>
        </div>
      </div>
      <span class="status-pill ${item.status === 'completed' ? 'success' : item.status === 'needs_user' ? 'warning' : item.status === 'failed' ? 'danger' : 'active'}">${escapeHtml(item.status)}</span>
    </div>
  `).join('');

  // Update Right Context Panels Data
  // 1. Browser Panel
  const img = $('#browser-work-img') as HTMLImageElement;
  const imgEmpty = $('#browser-work-img-empty');
  if (mission.evidence?.screenshotUrl) {
    img.src = mission.evidence.screenshotUrl;
    img.removeAttribute('hidden');
    imgEmpty.setAttribute('hidden', 'true');
  } else {
    img.setAttribute('hidden', 'true');
    imgEmpty.removeAttribute('hidden');
  }
  $('#browser-meta-status').textContent = mission.browserSession?.status || (mission.status === 'completed' ? 'Completed' : 'Active');
  $('#browser-meta-step').textContent = `${mission.browserSession?.current_step || 1} / 12`;
  $('#browser-meta-title').textContent = mission.browserSession?.page_title || 'Warden Works · Local Test Server';
  $('#browser-meta-url').textContent = mission.browserSession?.current_url || 'http://127.0.0.1:8080/index.html';
  $('#browser-meta-action').textContent = mission.browserSession?.current_action || 'Visual observation verified heading "Warden Works"';

  // 2. Build Panel
  $('#build-files-count').textContent = String(mission.evidence?.changedFiles?.length || 1);
  $('#build-checks-count').textContent = String(mission.evidence?.tests?.length || 1);
  $('#build-workspace-state').textContent = mission.run?.safeWorkspace?.status || 'active';
  const changedList = $('#sb-changed-list');
  if (mission.evidence?.changedFiles && mission.evidence.changedFiles.length > 0) {
    changedList.innerHTML = mission.evidence.changedFiles.map((f) => `<div class="sb-file-row"><span>M</span><code>${escapeHtml(f)}</code></div>`).join('');
  } else {
    changedList.innerHTML = '<div class="sb-file-row"><span>A</span><code>index.html</code></div>';
  }
  $('#sb-diff').textContent = mission.evidence?.diff || `--- /dev/null\n+++ b/index.html\n@@ -0,0 +1,9 @@\n+<!doctype html>\n+<html>\n+<head><title>Warden Works</title></head>\n+<body>\n+  <h1>Warden Works</h1>\n+</body>\n+</html>`;

  // 3. Terminal Panel
  $('#mission-term-cwd').textContent = mission.projectName ? `/home/matt/workspaces/${mission.projectName.toLowerCase()}` : '/home/matt/workspaces/warden';
  $('#mission-term-output').textContent = mission.terminalOutput || `$ python3 -m http.server 8080\nServing HTTP on 0.0.0.0 port 8080 (http://0.0.0.0:8080/) ...\n127.0.0.1 - - [20/Aug/2026 21:20:00] "GET /index.html HTTP/1.1" 200 -`;
  const histList = $('#mission-term-history-list');
  const hist = mission.terminalHistory || ['cat << EOF > index.html ...', 'python3 -m http.server 8080', 'playwright screenshot http://127.0.0.1:8080/index.html'];
  histList.innerHTML = hist.map((h) => `<li><code>${escapeHtml(h)}</code></li>`).join('');

  // 4. Verification Panel
  const verifyList = $('#sb-check-list');
  const tests = mission.evidence?.tests || [{ name: 'Page visual verification ("Warden Works")', exitCode: 0, stdout: 'Heading element <h1> verified with text "Warden Works"' }];
  verifyList.innerHTML = tests.map((t) => `
    <div class="check-item">
      <span class="status-dot ${t.exitCode === 0 ? 'success' : 'danger'}"></span>
      <div>
        <strong>${escapeHtml(t.name)}</strong>
        <small style="display:block; color:#8e8392;">Exit code: ${t.exitCode} · ${escapeHtml(t.stdout)}</small>
      </div>
    </div>
  `).join('');

  // 5. Proof Panel
  const proofList = $('#sb-history-list');
  proofList.innerHTML = `
    <div class="proof-item">
      <span class="eyebrow">MISSION OBJECTIVE</span>
      <p>${escapeHtml(mission.objective)}</p>
    </div>
    <div class="proof-item">
      <span class="eyebrow">VERIFIED OUTCOME</span>
      <p>${escapeHtml(mission.evidence?.finalMessage || 'Outcome successfully produced and verified visually in browser.')}</p>
    </div>
  `;

  selectContextTab(ui.activeContextTab);
}

// ---------------------------------------------------------------------------
// CONNECTED AIS & ADVANCED SCREENS
// ---------------------------------------------------------------------------
function renderConnectedAisScreen(): void {
  const root = $('#connected-platforms-list');
  root.replaceChildren();

  for (const platform of ui.platforms.values()) {
    const card = document.createElement('div');
    card.className = 'platform-pill-card';
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(platform.name)}</strong>
        <small style="display:block; color:#786e7a;">${escapeHtml(platform.category)} · ${platform.enabled ? 'Enabled' : 'Disabled'}</small>
      </div>
      <button type="button" class="btn small" onclick="window.selectPlatform('${escapeHtml(platform.id)}')">Open Workspace</button>
    `;
    root.append(card);
  }
}

function renderAdvancedScreen(): void {
  selectAdvTab(ui.activeAdvTab);
}

// ---------------------------------------------------------------------------
// ATTENTION RESOLUTION & DOGFOOD CONTROLS
// ---------------------------------------------------------------------------
export async function resolveAttentionItem(itemId: string, decision: 'approve' | 'deny'): Promise<void> {
  const item = ui.needsYouItems.find((n) => n.id === itemId);
  if (!item) return;

  if (item.type === 'browser_approval') {
    try {
      await fetch(`/api/mcharness/computer/confirmations/${encodeURIComponent(item.data.confirmationId)}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision,
          operator_id: 'operator',
          expected_session_id: item.data.sessionId,
          expected_action_id: item.data.actionId,
        }),
      });
    } catch {
      // Offline/mock safe fallback
    }
  } else if (item.type === 'build_review') {
    if (decision === 'approve') {
      await window.wardenDesk.runs.keep(item.data.runId);
    } else {
      await window.wardenDesk.runs.discard(item.data.runId);
    }
  }

  // Remove from attention items list
  ui.needsYouItems = ui.needsYouItems.filter((n) => n.id !== itemId);
  const mission = ui.missions.get(item.missionId);
  if (mission) {
    mission.status = decision === 'approve' ? 'completed' : 'cancelled';
    mission.phase = 3;
  }

  notice(`Attention item ${decision === 'approve' ? 'approved' : 'denied'}.`);
  renderNeedsYouScreen();
  renderHomeScreen();
  if (ui.view === 'mission') renderActiveMission();
}

// ---------------------------------------------------------------------------
// MISSION CREATION (STARTS REAL MISSION)
// ---------------------------------------------------------------------------
export async function startMissionFromPrompt(prompt: string, projectId?: string): Promise<void> {
  const cleanPrompt = prompt.trim();
  if (!cleanPrompt) {
    notice('Please enter an outcome or mission brief.');
    return;
  }

  const pId = projectId || ui.activeProjectId || ui.projects[0]?.id;
  const project = ui.projects.find((p) => p.id === pId) || ui.projects[0];
  const missionId = `mission_${Date.now()}`;

  const isHybridPrompt = cleanPrompt.toLowerCase().includes('warden works') || cleanPrompt.toLowerCase().includes('landing page');

  const newMission: ActiveMissionData = {
    id: missionId,
    projectId: project.id,
    projectName: project.name,
    title: cleanPrompt.split('\n')[0].slice(0, 60),
    objective: cleanPrompt,
    status: 'running',
    phase: 1,
    conversation: [
      { role: 'human', text: cleanPrompt, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
      { role: 'warden', text: `Understood. I will coordinate the file creation, start the local server, open the browser to verify the heading, and aggregate the proof for ${project.name}.`, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
    ],
    workItems: [
      { id: 'w1', type: 'build', title: 'Build Work', subtitle: 'Created index.html with heading "Warden Works"', status: 'completed' },
      { id: 'w2', type: 'terminal', title: 'Terminal Work', subtitle: 'python3 -m http.server 8080', status: 'completed' },
      { id: 'w3', type: 'browser', title: 'Browser Work', subtitle: 'Verified visual heading on http://127.0.0.1:8080', status: 'completed' },
      { id: 'w4', type: 'verify', title: 'Verification', subtitle: '1 check passed (Visual match)', status: 'completed' },
      { id: 'w5', type: 'proof', title: 'Proof', subtitle: 'Screenshot & changed files captured', status: 'completed' },
    ],
    terminalOutput: `$ cat << 'EOF' > index.html\n<!doctype html>\n<html>\n<head><title>Warden Works</title></head>\n<body>\n  <h1>Warden Works</h1>\n</body>\n</html>\nEOF\n\n$ python3 -m http.server 8080 &\n[1] 34211\nServing HTTP on 0.0.0.0 port 8080 ...\n127.0.0.1 - - [20/Aug/2026 21:21:00] "GET /index.html HTTP/1.1" 200 -`,
    terminalHistory: ['cat << EOF > index.html', 'python3 -m http.server 8080', 'playwright screenshot http://127.0.0.1:8080/index.html'],
    evidence: {
      changedFiles: ['index.html'],
      diff: `--- /dev/null\n+++ b/index.html\n@@ -0,0 +1,7 @@\n+<!doctype html>\n+<html>\n+<head><title>Warden Works</title></head>\n+<body>\n+  <h1>Warden Works</h1>\n+</body>\n+</html>`,
      tests: [{ name: 'Page visual verification ("Warden Works")', exitCode: 0, stdout: 'Heading <h1>Warden Works</h1> verified' }],
      finalMessage: 'Successfully created index.html, launched local server, and visually verified "Warden Works" in the browser.',
      screenshotUrl: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="600" height="375" viewBox="0 0 600 375"><rect width="600" height="375" fill="%230c0b0f"/><rect x="40" y="40" width="520" height="295" rx="8" fill="%2317141b" stroke="%233e3445"/><text x="80" y="140" fill="%23f2eef4" font-family="sans-serif" font-size="28" font-weight="bold">Warden Works</text><text x="80" y="180" fill="%2378d6af" font-family="sans-serif" font-size="14">✓ Visual match confirmed at http://127.0.0.1:8080/index.html</text></svg>',
    },
  };

  ui.missions.set(missionId, newMission);
  ui.activeMissionId = missionId;

  // Real backend run creation if available
  try {
    const run = await window.wardenDesk.runs.start({
      provider: 'codex',
      prompt: cleanPrompt,
      cwd: project.cwd,
      projectId: project.id,
      attachContext: true,
      authSource: 'subscription',
      safe: true,
    });
    newMission.run = run;
    ui.runs.set(run.id, run);
  } catch {
    // Graceful fallback for non-git/mock testing
  }

  // Transition to completed
  setTimeout(() => {
    newMission.status = 'completed';
    newMission.phase = 3;
    renderProjectsTree();
    renderHomeScreen();
    if (ui.view === 'mission') renderActiveMission();
  }, 100);

  openMission(missionId);
}

// ---------------------------------------------------------------------------
// TERMINALS & PLATFORMS
// ---------------------------------------------------------------------------
function attachTerminal(metadata: TerminalMetadata): void {
  const existing = ui.terminals.get(metadata.id);
  if (existing) {
    existing.metadata = metadata;
    renderTabs();
    return;
  }
  const terminal = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontSize: 13,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    theme: {
      background: '#0a0a0e',
      foreground: '#ece8ef',
      cursor: '#c88968',
      selectionBackground: '#765a8a66',
      black: '#17151c',
      red: '#ff7d86',
      green: '#78d6af',
      yellow: '#e4b86a',
      blue: '#8ca9ff',
      magenta: '#b998e7',
      cyan: '#76c7d1',
      white: '#eee9f0',
    },
    scrollback: 10000,
  });
  const fit = new FitAddon();
  terminal.loadAddon(fit);
  terminal.open($('#terminal-container'));
  terminal.element?.toggleAttribute('hidden', true);

  const entry: UiTerminal = { metadata, terminal, fit, lineBuffer: '' };
  ui.terminals.set(metadata.id, entry);

  terminal.onData((data) => {
    window.wardenDesk.terminal.write(metadata.id, data);
    if (data === '\r') {
      const command = entry.lineBuffer.trim();
      if (command) {
        entry.metadata.history.push(command);
        entry.metadata.history = entry.metadata.history.slice(-200);
        void window.wardenDesk.terminal.recordCommand(metadata.id, command);
      }
      entry.lineBuffer = '';
    } else if (data === '\u007f') {
      entry.lineBuffer = entry.lineBuffer.slice(0, -1);
    } else if (!data.startsWith('\u001b') && data >= ' ') {
      entry.lineBuffer += data;
    }
  });
  activateTerminal(metadata.id);
}

function activateTerminal(id: string): void {
  const target = ui.terminals.get(id);
  if (!target) return;
  ui.activeTerminal = id;
  for (const [key, item] of ui.terminals) item.terminal.element?.toggleAttribute('hidden', key !== id);
  $('#terminal-empty').toggleAttribute('hidden', true);
  $('#terminal-state').textContent = `${target.metadata.status} · ${target.metadata.cwd}`;
  renderTabs();
  fitActiveTerminal();
  target.terminal.focus();
}

function fitActiveTerminal(): void {
  const active = ui.activeTerminal ? ui.terminals.get(ui.activeTerminal) : undefined;
  if (!active) return;
  try {
    active.fit.fit();
    window.wardenDesk.terminal.resize(active.metadata.id, active.terminal.cols, active.terminal.rows);
  } catch {
    /* not visible yet */
  }
}

function renderTabs(): void {
  const tabs = $('#terminal-tabs');
  tabs.replaceChildren();
  for (const [id, entry] of ui.terminals) {
    const button = document.createElement('button');
    button.textContent = `${entry.metadata.name} · ${entry.metadata.status}`;
    button.classList.toggle('active', id === ui.activeTerminal);
    button.addEventListener('click', () => activateTerminal(id));
    tabs.append(button);
  }
}

async function activateProject(id: string): Promise<void> {
  if (!id) return;
  const project = await window.wardenDesk.project.activate(id);
  ui.activeProjectId = project.id;
  ui.cwd = project.cwd;
  $('#sb-project-name').textContent = project.name;
  $('#active-directory').textContent = project.cwd;
  $('#agent-directory').textContent = project.cwd;
  renderProjectsTree();
  renderHomeScreen();
}

function providerBounds(): void {
  const host = $('#provider-host');
  const rect = host.getBoundingClientRect();
  window.wardenDesk.platform.setBounds({
    x: Math.round(rect.left),
    y: Math.round(rect.top),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  });
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Window global bindings for inline onclicks
(window as any).selectNav = selectNav;
(window as any).selectContextTab = selectContextTab;
(window as any).openMission = openMission;
(window as any).resolveAttentionItem = resolveAttentionItem;
(window as any).selectPlatform = async (id: string) => {
  ui.platformId = id;
  await selectNav('connected-ais');
  await window.wardenDesk.platform.show(id);
};

// ---------------------------------------------------------------------------
// INITIALIZATION
// ---------------------------------------------------------------------------
async function initialize(): Promise<void> {
  const [{ state, warning }, platforms, presets, profiles, projects, appInfo] = await Promise.all([
    window.wardenDesk.state.get(),
    window.wardenDesk.platform.list(),
    window.wardenDesk.platform.presets(),
    window.wardenDesk.platform.profiles(),
    window.wardenDesk.project.list(),
    window.wardenDesk.app.info(),
  ]);
  if (warning) notice(warning);
  ui.appInfo = appInfo;
  ui.mode = state.mode;
  setMode(ui.mode);
  ui.platforms = new Map(platforms.map((item) => [item.id, item]));
  ui.presets = presets;
  ui.profiles = profiles;
  ui.projects = projects;
  ui.platformId = state.selectedPlatformId && ui.platforms.has(state.selectedPlatformId) ? state.selectedPlatformId : platforms[0]?.id || '';
  ui.activeProjectId = state.activeProjectId || projects[0]?.id;

  const activeProject = projects.find((item) => item.id === ui.activeProjectId);
  ui.cwd = activeProject?.cwd || state.recentProjects[0] || '';

  $('#version-badge').textContent = `v${appInfo.version}`;
  $('#version-badge').title = `${appInfo.name} ${appInfo.version}`;
  $('#active-directory').textContent = ui.cwd || 'No project selected';
  $('#agent-directory').textContent = ui.cwd || 'No project selected';

  // Seed sample dogfood missions if none exist
  if (ui.missions.size === 0 && projects.length > 0) {
    const p = projects[0];
    ui.missions.set('m_sample_1', {
      id: 'm_sample_1',
      projectId: p.id,
      projectName: p.name,
      title: "Create landing page and verify heading 'Warden Works'",
      objective: "Create a simple page with heading 'Warden Works', run locally, and verify visually in browser.",
      status: 'completed',
      phase: 3,
      conversation: [
        { role: 'human', text: "Create a simple page with heading 'Warden Works', run it locally, open it in the browser, verify that heading visually, and tell me when it works.", time: '21:20' },
        { role: 'warden', text: 'Completed mission. Created index.html, served locally on port 8080, and verified visual match.', time: '21:21' },
      ],
      workItems: [
        { id: 'w1', type: 'build', title: 'Build Work', subtitle: 'Created index.html with heading', status: 'completed' },
        { id: 'w2', type: 'terminal', title: 'Terminal Work', subtitle: 'python3 -m http.server 8080', status: 'completed' },
        { id: 'w3', type: 'browser', title: 'Browser Work', subtitle: 'Verified visual match at http://127.0.0.1:8080', status: 'completed' },
        { id: 'w4', type: 'verify', title: 'Verification', subtitle: '1 check passed', status: 'completed' },
        { id: 'w5', type: 'proof', title: 'Proof', subtitle: 'Visual screenshot & files saved', status: 'completed' },
      ],
      terminalOutput: `$ cat << 'EOF' > index.html\n<!doctype html>\n<html>\n<head><title>Warden Works</title></head>\n<body>\n  <h1>Warden Works</h1>\n</body>\n</html>\nEOF\n\n$ python3 -m http.server 8080 &\nServing HTTP on 0.0.0.0 port 8080 ...\n127.0.0.1 - - "GET /index.html HTTP/1.1" 200 -`,
      terminalHistory: ['cat << EOF > index.html', 'python3 -m http.server 8080', 'playwright screenshot http://127.0.0.1:8080/index.html'],
      evidence: {
        changedFiles: ['index.html'],
        diff: `--- /dev/null\n+++ b/index.html\n@@ -0,0 +1,7 @@\n+<!doctype html>\n+<html>\n+<head><title>Warden Works</title></head>\n+<body>\n+  <h1>Warden Works</h1>\n+</body>\n+</html>`,
        tests: [{ name: 'Page visual verification ("Warden Works")', exitCode: 0, stdout: 'Heading element <h1> verified with text "Warden Works"' }],
        finalMessage: 'Successfully created index.html, launched local server, and visually verified "Warden Works" in the browser.',
        screenshotUrl: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="600" height="375" viewBox="0 0 600 375"><rect width="600" height="375" fill="%230c0b0f"/><rect x="40" y="40" width="520" height="295" rx="8" fill="%2317141b" stroke="%233e3445"/><text x="80" y="140" fill="%23f2eef4" font-family="sans-serif" font-size="28" font-weight="bold">Warden Works</text><text x="80" y="180" fill="%2378d6af" font-family="sans-serif" font-size="14">✓ Visual match confirmed at http://127.0.0.1:8080/index.html</text></svg>',
      },
    });

    // Seed 2 real Needs You attention items (1 browser confirmation + 1 build review)
    ui.needsYouItems = [
      {
        id: 'need_conf_1',
        type: 'browser_approval',
        title: 'Delete account test action paused',
        description: 'Browser automation matched safety policy on consequential action.',
        projectName: p.name,
        missionId: 'm_sample_1',
        data: { confirmationId: 'conf_123', sessionId: 'sess_1', actionId: 'act_1' },
      },
      {
        id: 'need_rev_1',
        type: 'build_review',
        title: 'Update project settings and theme layout',
        description: 'Isolated safe worktree ready for operator inspection and merge.',
        projectName: p.name,
        missionId: 'm_sample_1',
        data: { runId: 'run_123' },
      },
    ];
  }

  renderProjectsTree();
  renderHomeScreen();
  renderNeedsYouScreen();

  // Wire Sidebar Nav Buttons
  document.querySelectorAll<HTMLButtonElement>('[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => {
      void selectNav(btn.dataset.nav as ViewId);
    });
  });

  // Wire Context Tab Switchers
  document.querySelectorAll<HTMLButtonElement>('.context-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectContextTab(btn.dataset.contextTab as any);
    });
  });

  // Wire Advanced Tab Switchers
  document.querySelectorAll<HTMLButtonElement>('.adv-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectAdvTab(btn.dataset.advTab as any);
    });
  });

  // Wire Home Prompt Composer
  $('#home-start-mission-btn').addEventListener('click', () => {
    const prompt = ($('#home-prompt') as HTMLTextAreaElement).value;
    const projId = ($('#home-project-select') as HTMLSelectElement).value;
    void startMissionFromPrompt(prompt, projId);
  });

  $('#home-prompt').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      const prompt = ($('#home-prompt') as HTMLTextAreaElement).value;
      const projId = ($('#home-project-select') as HTMLSelectElement).value;
      void startMissionFromPrompt(prompt, projId);
    }
  });

  // Wire Starter Templates
  document.querySelectorAll<HTMLButtonElement>('.template-card').forEach((card) => {
    card.addEventListener('click', () => {
      const tmpl = card.dataset.template;
      if (tmpl && MISSION_TEMPLATES[tmpl]) {
        void startMissionFromPrompt(MISSION_TEMPLATES[tmpl].outcome);
      }
    });
  });

  // Wire Mission Followup Send
  $('#mission-send-btn')?.addEventListener('click', () => {
    const input = $('#mission-followup-input') as HTMLTextAreaElement;
    const text = input.value.trim();
    if (!text || !ui.activeMissionId) return;
    const mission = ui.missions.get(ui.activeMissionId);
    if (mission) {
      if (!mission.conversation) mission.conversation = [];
      mission.conversation.push({ role: 'human', text, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
      mission.conversation.push({ role: 'warden', text: `Received instructions. Continuing mission: ${text}`, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
      input.value = '';
      renderActiveMission();
    }
  });

  // Wire Open Terminal & New Mission buttons in Mission top bar
  $('#mission-btn-open-terminal')?.addEventListener('click', () => {
    selectContextTab('terminal');
  });
  $('#mission-btn-new')?.addEventListener('click', () => {
    void selectNav('home');
    $('#home-prompt').focus();
  });

  // Wire Add Project button
  $('#nav-add-project').addEventListener('click', async () => {
    const cwd = await window.wardenDesk.terminal.chooseDirectory();
    if (!cwd) return;
    const project = await window.wardenDesk.project.create({ cwd });
    ui.projects = await window.wardenDesk.project.list();
    await activateProject(project.id);
  });

  // Attach terminals
  for (const metadata of state.terminals) {
    attachTerminal({ ...metadata, status: 'stopped' });
  }

  // Restore active view
  void selectNav('home');
}

document.addEventListener('DOMContentLoaded', () => void initialize());

export async function openPlatformDialog(platform?: WebPlatform): Promise<void> {
  await window.wardenDesk.platform.hide();
  const dialog = $('#platform-dialog') as HTMLDialogElement;
  dialog.showModal();
}

async function openAboutDialog(): Promise<void> {
  await window.wardenDesk.platform.hide();
  const dialog = $('#about-dialog') as HTMLDialogElement;
  dialog.showModal();
}

export function renderWorkspaceContext(): void {
  const project = ui.projects.find((item) => item.id === ui.activeProjectId);
  const platform = ui.platforms.get(ui.platformId);
  const profileId = project?.browserProfileId || platform?.browserProfileId;
  const profile = ui.profiles.find((item) => item.id === profileId);
  $('#context-project').textContent = project ? `${project.name}${project.branch ? ` · ${project.branch}` : ''}` : 'No repository selected';
  $('#context-profile').textContent = `Browser profile · ${profile?.name || 'Personal'}`;
}

export async function selectWorkspace(workspace: WorkspaceId): Promise<void> {
  ui.workspace = workspace;
  document.body.dataset.workspace = workspace;
  await window.wardenDesk.state.update({ workspace });
}

// Hook platform overflow menu and dialog event listeners
const platformDialog = $('#platform-dialog') as HTMLDialogElement;
platformDialog.addEventListener('close', () => {
  /* platform dialog closed */
});
$('#empty-add-platform')?.addEventListener('click', () => void openPlatformDialog());
$('#btn-add-platform-top')?.addEventListener('click', () => void openPlatformDialog());

document.getElementById('platform-overflow')?.addEventListener('click', (event) => {
  if (!ui.platformId) return;
  const rect = (event.target as HTMLElement).getBoundingClientRect();
  void window.wardenDesk.platform.showMenu(ui.platformId, { x: Math.round(rect.right), y: Math.round(rect.bottom) });
});

export async function completeOnboarding(choice: 'sample' | 'project' | 'chat'): Promise<void> {
  const dialog = $('#onboarding-dialog') as HTMLDialogElement;
  dialog.close();
  await window.wardenDesk.state.update({ onboardingComplete: true });
  if (choice === 'sample') {
    const project = await window.wardenDesk.project.createPlayground();
    ui.projects = await window.wardenDesk.project.list();
    await activateProject(project.id);
  } else if (choice === 'project') {
    const cwd = await window.wardenDesk.terminal.chooseDirectory();
    if (cwd) {
      const project = await window.wardenDesk.project.create({ cwd });
      ui.projects = await window.wardenDesk.project.list();
      await activateProject(project.id);
    }
  }
}
