import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@fontsource-variable/epilogue/wght.css';
import '@fontsource-variable/sora/wght.css';
import './styles.css';
import type { AppInfo, BrowserProfile, ContextPack, ExecutionMode, InterfaceMode, PlatformMenuAction, PlatformPreset, PlatformStatus, ProjectWorkspace, ProviderAuthReport, StructuredProviderId, TerminalMetadata, WardenRun, WebPlatform, WorkspaceId } from '../shared/types';
import { initSimpleBuild, onSimpleBuildRunsChanged, setMode, syncSimpleBuild } from './simple-build';

const $ = <T extends Element = HTMLElement>(selector: string): T => { const element = document.querySelector<T>(selector); if (!element) throw new Error(`Missing element: ${selector}`); return element; };
type UiTerminal = { metadata: TerminalMetadata; terminal: Terminal; fit: FitAddon; lineBuffer: string };
const ui = { mode: 'simple' as InterfaceMode, workspace: 'chat' as WorkspaceId, platformId: '', splitPlatformId: undefined as string | undefined, editingPlatformId: undefined as string | undefined, execution: 'local' as ExecutionMode, cwd: '', activeProjectId: undefined as string | undefined, activeTerminal: null as string | null, activeRun: null as string | null, appInfo: undefined as AppInfo | undefined, runs: new Map<string, WardenRun>(), terminals: new Map<string, UiTerminal>(), platforms: new Map<string, WebPlatform>(), profiles: [] as BrowserProfile[], presets: [] as PlatformPreset[], projects: [] as ProjectWorkspace[], platformStatus: new Map<string, PlatformStatus>(), auth: new Map<StructuredProviderId, ProviderAuthReport>() };
const buildProviderNames: Record<StructuredProviderId, string> = { codex: 'Codex', claude: 'Claude Code', gemini: 'Gemini CLI', grok: 'Grok Build' };

function notice(message?: string): void { const box = $('#notice'); box.textContent = message || ''; box.toggleAttribute('hidden', !message); }
function providerBounds(): void { const host = $('#provider-host').getBoundingClientRect(); window.wardenDesk.platform.setBounds({ x: Math.round(host.left), y: Math.round(host.top), width: Math.round(host.width), height: Math.round(host.height) }); }
function applyMode(): void {
  const developer = ui.mode === 'developer';
  $('#simple-build').toggleAttribute('hidden', developer || ui.workspace !== 'build');
  $('.build-top').toggleAttribute('hidden', !developer || ui.workspace !== 'build');
  $('#terminal-workspace').toggleAttribute('hidden', !developer || ui.workspace !== 'build' || ui.execution !== 'local');
  $('#agent-workspace').toggleAttribute('hidden', !developer || ui.workspace !== 'build' || ui.execution === 'local');
  $('#team-chat-workspace').toggleAttribute('hidden', ui.workspace !== 'team-chat');
  const toggle = document.getElementById('mode-toggle') as HTMLInputElement | null; if (toggle) toggle.checked = developer;
}
async function ensureWardenServerAndMount(): Promise<void> {
  const loading = document.getElementById('mission-server-state');
  const frame = document.getElementById('team-chat-frame') as HTMLIFrameElement | null;
  const title = document.getElementById('mission-server-title');
  const detail = document.getElementById('mission-server-detail');
  const actions = document.getElementById('mission-server-actions');
  const errBox = document.getElementById('mission-server-error');

  if (!loading || !frame) return;

  const showLoading = (msg: string) => {
    loading.removeAttribute('hidden');
    frame.setAttribute('hidden', 'true');
    actions?.setAttribute('hidden', 'true');
    errBox?.setAttribute('hidden', 'true');
    if (title) title.textContent = msg;
    if (detail) detail.textContent = 'Connecting to local Warden control plane (:6969)…';
  };

  const showError = (err: string) => {
    loading.removeAttribute('hidden');
    frame.setAttribute('hidden', 'true');
    if (title) title.textContent = 'Warden runtime unavailable';
    if (detail) detail.textContent = 'The local Warden backend server could not be started or reached.';
    actions?.removeAttribute('hidden');
    if (errBox && err) {
      errBox.textContent = err;
      errBox.removeAttribute('hidden');
    }
  };

  const showFrame = () => {
    loading.setAttribute('hidden', 'true');
    frame.removeAttribute('hidden');
    if (!frame.src || frame.src === 'about:blank' || frame.src.endsWith('index.html')) {
      frame.src = 'http://127.0.0.1:6969/web/warden/app.html?embed=true';
    }
  };

  if (await window.wardenDesk.warden.serverHealth()) {
    showFrame();
    return;
  }

  showLoading('Starting Warden…');

  const started = await window.wardenDesk.warden.ensureServer();
  if (started && await window.wardenDesk.warden.serverHealth()) {
    showFrame();
    return;
  }

  for (let i = 0; i < 15; i++) {
    await new Promise((r) => setTimeout(r, 300));
    if (await window.wardenDesk.warden.serverHealth()) {
      showFrame();
      return;
    }
  }

  const status = await window.wardenDesk.warden.serverStatus();
  showError(status.error || 'Server did not respond to health check in time.');
}

async function selectWorkspace(workspace: WorkspaceId): Promise<void> {
  ui.workspace = workspace; document.body.dataset.workspace = workspace; document.querySelectorAll<HTMLButtonElement>('[data-workspace]').forEach((button) => button.classList.toggle('active', button.dataset.workspace === workspace));
  $('#provider-host').toggleAttribute('hidden', workspace !== 'chat'); $('#build-workspace').toggleAttribute('hidden', workspace !== 'build'); $('#team-chat-workspace').toggleAttribute('hidden', workspace !== 'team-chat'); $('#browser-toolbar').toggleAttribute('hidden', workspace !== 'chat');
  applyMode();
  await window.wardenDesk.state.update({ workspace });
  if (ui.activeProjectId) await window.wardenDesk.project.update(ui.activeProjectId, { workspace });
  if (workspace === 'team-chat') {
    void ensureWardenServerAndMount();
  }
  if (workspace === 'chat') { providerBounds(); if (ui.platformId) await window.wardenDesk.platform.show(ui.platformId, ui.splitPlatformId); } else { await window.wardenDesk.platform.hide(); queueMicrotask(() => fitActiveTerminal()); }
}
async function selectPlatform(id: string, splitId?: string): Promise<void> { const platform = ui.platforms.get(id); if (!platform?.enabled) return; ui.platformId = id; ui.splitPlatformId = splitId; renderPlatforms(); renderWorkspaceContext(); await window.wardenDesk.state.update({ selectedPlatformId: id }); if (ui.activeProjectId) await window.wardenDesk.project.update(ui.activeProjectId, { selectedPlatformId: id, splitPlatformId: splitId }); await selectWorkspace('chat'); await window.wardenDesk.platform.show(id, splitId); }
function renderProviderStatus(status: PlatformStatus): void { ui.platformStatus.set(status.id, status); if (status.id !== ui.platformId || ui.workspace !== 'chat') return; const reload = $('#reload-stop') as HTMLButtonElement; reload.dataset.action = status.loading ? 'stop' : 'reload'; reload.textContent = status.loading ? '■' : '↻'; reload.title = status.loading ? 'Stop loading' : 'Reload (Ctrl+R)'; $('#loading-state').textContent = status.error ? 'Load error' : status.loading ? 'Loading…' : ''; document.querySelector<HTMLButtonElement>('[data-action="back"]')!.disabled = !status.canGoBack; document.querySelector<HTMLButtonElement>('[data-action="forward"]')!.disabled = !status.canGoForward; if (status.error) notice(status.error); if (status.cleared) notice('Configured site data was cleared. Related domains in the shared profile may also have been affected.'); }
function renderPlatforms(): void { const root = $('#platforms'); root.replaceChildren(); const query = ($('#platform-search') as HTMLInputElement).value.trim().toLowerCase(); for (const platform of [...ui.platforms.values()].filter((item) => item.name.toLowerCase().includes(query) || item.category.toLowerCase().includes(query)).sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.order - b.order)) { const button = document.createElement('button'); button.dataset.platformId = platform.id; button.classList.toggle('active', platform.id === ui.platformId); button.setAttribute('aria-pressed', String(platform.id === ui.platformId)); button.disabled = !platform.enabled; const profile = ui.profiles.find((item) => item.id === platform.browserProfileId); button.title = `${platform.name} · ${profile?.name || 'unknown'} browser profile${platform.enabled ? '' : ' · disabled'}`; const icon = document.createElement('i'); if (platform.icon.kind === 'url') { const image = document.createElement('img'); image.src = platform.icon.value; image.alt = ''; icon.append(image); } else icon.textContent = platform.icon.value; const name = document.createTextNode(platform.name); const meta = document.createElement('span'); meta.className = 'platform-meta'; meta.textContent = platform.category; button.append(icon, name, meta); button.addEventListener('click', () => void selectPlatform(platform.id)); root.append(button); } }
function renderWorkspaceContext(): void { const project = ui.projects.find((item) => item.id === ui.activeProjectId); const platform = ui.platforms.get(ui.platformId); const profileId = project?.browserProfileId || platform?.browserProfileId; const profile = ui.profiles.find((item) => item.id === profileId); const projectLabel = $('#context-project'); projectLabel.textContent = project ? `${project.name}${project.branch ? ` · ${project.branch}` : ''}` : 'No repository selected'; projectLabel.title = project?.cwd || 'Choose a project in Build to bind repository context.'; const profileLabel = $('#context-profile'); profileLabel.textContent = `Browser profile · ${profile?.name || 'Default'}`; profileLabel.title = profile ? `Platforms assigned to ${profile.name} share this Warden-managed Chromium session.` : 'Warden browser profiles never import Chrome cookies.'; }
function renderProjects(): void { const select = $('#project-picker') as HTMLSelectElement; select.replaceChildren(new Option('No project selected', '')); for (const project of ui.projects) select.add(new Option(project.name, project.id)); select.value = ui.activeProjectId || ''; renderWorkspaceContext(); }
async function activateProject(id: string): Promise<void> { if (!id) return; const project = await window.wardenDesk.project.activate(id); ui.activeProjectId = project.id; ui.cwd = project.cwd; ui.execution = project.executionMode; ui.activeRun = project.activeRunId || null; ui.platformId = project.selectedPlatformId && ui.platforms.has(project.selectedPlatformId) ? project.selectedPlatformId : ui.platformId; ui.splitPlatformId = project.splitPlatformId; $('#active-directory').textContent = project.cwd; $('#agent-directory').textContent = project.cwd; selectExecution(project.executionMode); await refreshRuns(); renderProjects(); await syncSimpleBuild(ui.projects, project.id); await selectWorkspace(project.workspace); }
function renderTabs(): void { const tabs = $('#terminal-tabs'); tabs.replaceChildren(); for (const [id, entry] of ui.terminals) { const button = document.createElement('button'); button.textContent = `${entry.metadata.name} · ${entry.metadata.status}`; button.classList.toggle('active', id === ui.activeTerminal); button.addEventListener('click', () => activateTerminal(id)); tabs.append(button); } }
function activateTerminal(id: string): void { const target = ui.terminals.get(id); if (!target) return; ui.activeTerminal = id; for (const [key, item] of ui.terminals) item.terminal.element?.toggleAttribute('hidden', key !== id); $('#terminal-empty').toggleAttribute('hidden', true); $('#terminal-state').textContent = `${target.metadata.status} · ${target.metadata.cwd}`; renderTabs(); fitActiveTerminal(); target.terminal.focus(); }
function fitActiveTerminal(): void { const active = ui.activeTerminal ? ui.terminals.get(ui.activeTerminal) : undefined; if (!active || ui.workspace !== 'build') return; try { active.fit.fit(); window.wardenDesk.terminal.resize(active.metadata.id, active.terminal.cols, active.terminal.rows); } catch { /* not visible yet */ } }
function attachTerminal(metadata: TerminalMetadata): void {
  const existing = ui.terminals.get(metadata.id); if (existing) { existing.metadata = metadata; renderTabs(); return; }
  const terminal = new Terminal({ cursorBlink: true, convertEol: true, fontSize: 13, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', theme: { background: '#0a0a0e', foreground: '#ece8ef', cursor: '#c88968', selectionBackground: '#765a8a66', black: '#17151c', red: '#ff7d86', green: '#78d6af', yellow: '#e4b86a', blue: '#8ca9ff', magenta: '#b998e7', cyan: '#76c7d1', white: '#eee9f0' }, scrollback: 10000 }); const fit = new FitAddon(); terminal.loadAddon(fit); terminal.open($('#terminal-container')); terminal.element?.toggleAttribute('hidden', true);
  const entry: UiTerminal = { metadata, terminal, fit, lineBuffer: '' }; ui.terminals.set(metadata.id, entry);
  terminal.onData((data) => { window.wardenDesk.terminal.write(metadata.id, data); if (data === '\r') { const command = entry.lineBuffer.trim(); if (command) { entry.metadata.history.push(command); entry.metadata.history = entry.metadata.history.slice(-200); void window.wardenDesk.terminal.recordCommand(metadata.id, command); } entry.lineBuffer = ''; } else if (data === '\u007f') entry.lineBuffer = entry.lineBuffer.slice(0, -1); else if (!data.startsWith('\u001b') && data >= ' ') entry.lineBuffer += data; });
  activateTerminal(metadata.id);
}
async function createTerminal(restore?: TerminalMetadata): Promise<void> { if (!ui.cwd && !restore?.cwd) { notice('Choose a valid project directory first.'); return; } try { const metadata = await window.wardenDesk.terminal.create({ name: restore?.name || `Terminal ${ui.terminals.size + 1}`, cwd: restore?.cwd || ui.cwd, restoreId: restore?.id }); ui.cwd = metadata.cwd; $('#active-directory').textContent = metadata.cwd; if (!ui.activeProjectId) { const project = await window.wardenDesk.project.create({ cwd: metadata.cwd }); ui.projects = await window.wardenDesk.project.list(); ui.activeProjectId = project.id; renderProjects(); } notice(); attachTerminal(metadata); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } }
function authStateLabel(report?: ProviderAuthReport): string { if (!report) return 'checking…'; return report.state.replaceAll('_', ' '); }
function activeBuildProvider(): StructuredProviderId | null { return ui.execution === 'local' ? null : ui.execution; }
function renderAuthStatus(): void {
  const provider = activeBuildProvider(); if (!provider) return; const report = ui.auth.get(provider);
  ($('#auth-status') as HTMLElement).dataset.state = report?.state || 'checking';
  $(`#auth-tab-${provider}`).textContent = authStateLabel(report);
  $('#auth-title').textContent = report ? `${buildProviderNames[provider]} · ${authStateLabel(report)}` : `Checking ${buildProviderNames[provider]}…`;
  $('#auth-detail').textContent = report?.detail || 'Authentication remains owned by the official local client.';
  const apiInput = document.querySelector<HTMLInputElement>('input[name="billing-source"][value="api_key"]')!; apiInput.disabled = !report?.apiFallbackAvailable;
  $('#api-source-label').classList.toggle('disabled', apiInput.disabled);
  if (apiInput.disabled && apiInput.checked) (document.querySelector<HTMLInputElement>('input[name="billing-source"][value="subscription"]')!).checked = true;
  const button = $('#start-run') as HTMLButtonElement; button.textContent = `Start ${buildProviderNames[provider]} run`; button.disabled = !report?.canStart && !report?.apiFallbackAvailable;
}
async function refreshProviderAuth(): Promise<void> { try { const reports = await window.wardenDesk.runs.providers(); ui.auth = new Map(reports.map((report) => [report.provider, report])); for (const report of reports) $(`#auth-tab-${report.provider}`).textContent = authStateLabel(report); renderAuthStatus(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } }
function selectExecution(mode: ExecutionMode): void { ui.execution = mode; document.querySelectorAll<HTMLButtonElement>('[data-execution]').forEach((button) => button.classList.toggle('active', button.dataset.execution === mode)); $('#terminal-workspace').toggleAttribute('hidden', mode !== 'local'); $('#agent-workspace').toggleAttribute('hidden', mode === 'local'); if (ui.activeProjectId) void window.wardenDesk.project.update(ui.activeProjectId, { executionMode: mode }); if (mode === 'local') fitActiveTerminal(); else renderAuthStatus(); }

function formatErrorString(err: unknown): string {
  if (!err) return '';
  if (typeof err === 'string') return err;
  if (typeof err === 'object') {
    const obj = err as Record<string, unknown>;
    if (typeof obj.message === 'string' && obj.message) return obj.message;
    if (typeof obj.error === 'string' && obj.error) return obj.error;
    if (typeof obj.detail === 'string' && obj.detail) return obj.detail;
    try { const s = JSON.stringify(err); return s === '{}' ? String(err) : s; } catch { return String(err); }
  }
  return String(err);
}

function runSummary(run: WardenRun): string {
  const recent = run.events.slice(-80).map((event) => {
    if (event.type === 'message.delta') return String(event.payload.delta || '');
    if (event.type === 'command.started') return `\n$ ${String(event.payload.command || '')}\n`;
    if (event.type === 'command.completed') return `[exit ${String(event.payload.exitCode ?? '?')}]\n${String(event.payload.output || '').slice(-3000)}\n`;
    if (event.type === 'file.changed') return `[files changed: ${JSON.stringify(event.payload.changes || [])}]\n`;
    if (event.type === 'approval.requested') return `[approval required: ${String(event.payload.detail || '')}]\n`;
    if (event.type === 'run.completed') return `\nCompleted: ${String(event.payload.finalMessage || '')}`;
    if (event.type === 'run.failed') return `\nFailed: ${formatErrorString(event.payload.error) || 'Task failed.'}`;
    return '';
  }).join('');
  const fallbackError = run.error && !recent.includes(run.error) ? formatErrorString(run.error) : '';
  return [`Run ${run.id}`, `Provider: ${run.provider}`, `Authentication / billing: ${run.auth?.source || 'unknown'}${run.auth?.entitlement ? ` · ${run.auth.entitlement}` : ''}`, `Status: ${run.status}`, `Project: ${run.projectCwd || run.cwd}`, `Session: ${run.threadId || 'not started'}`, `Turn: ${run.turnId || 'not started'}`, `Changed files: ${run.evidence.changedFiles.join(', ') || 'none recorded'}`, `Tests: ${run.evidence.tests.map((test) => `${test.command} → ${test.exitCode}`).join('; ') || 'none recorded'}`, `Proof: local=${run.proof.local}, brain=${run.proof.brain}${run.proof.detail ? ` (${run.proof.detail})` : ''}`, '', recent || fallbackError || 'Waiting for events…'].join('\n');
}
function renderApprovals(run?: WardenRun): void { const root = $('#approval-list'); root.replaceChildren(); for (const approval of run?.approvals.filter((item) => item.status === 'pending') || []) { const card = document.createElement('div'); card.className = 'approval'; const title = document.createElement('strong'); title.textContent = approval.title; const detail = document.createElement('code'); detail.textContent = approval.detail; const once = document.createElement('button'); once.textContent = 'Approve once'; once.addEventListener('click', () => void respondApproval(run!.id, approval.id, 'approve', 'once')); const session = document.createElement('button'); session.textContent = 'Approve session'; session.addEventListener('click', () => void respondApproval(run!.id, approval.id, 'approve', 'session')); const deny = document.createElement('button'); deny.textContent = 'Deny'; deny.addEventListener('click', () => void respondApproval(run!.id, approval.id, 'deny', 'once')); card.append(title, detail, once, session, deny); root.append(card); } }
function renderRun(run?: WardenRun): void { if (!run) { $('#run-detail').textContent = 'Select or start a run.'; renderApprovals(); return; } const projectCwd = run.projectCwd || run.cwd; ui.activeRun = run.id; ui.cwd = projectCwd; if (['codex', 'claude', 'gemini', 'grok'].includes(run.provider) && ui.execution !== run.provider) selectExecution(run.provider as StructuredProviderId); $('#active-directory').textContent = projectCwd; $('#agent-directory').textContent = projectCwd; $('#run-detail').textContent = runSummary(run); renderApprovals(run); document.querySelectorAll<HTMLButtonElement>('.run-card').forEach((card) => card.classList.toggle('active', card.dataset.runId === run.id)); }
function renderRuns(): void { const root = $('#runs'); root.replaceChildren(); const runs = [...ui.runs.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)); for (const run of runs) { const button = document.createElement('button'); button.className = 'run-card'; button.dataset.runId = run.id; const title = document.createElement('strong'); title.textContent = run.prompt.split('\n')[0].slice(0, 80) || run.project; const meta = document.createElement('span'); meta.textContent = `${run.provider} · ${run.status} · ${new Date(run.updatedAt).toLocaleString()}`; button.append(title, meta); button.addEventListener('click', () => renderRun(run)); root.append(button); } if (ui.activeRun) renderRun(ui.runs.get(ui.activeRun)); }
async function refreshRuns(): Promise<void> { const runs = await window.wardenDesk.runs.list(ui.activeProjectId); ui.runs = new Map(runs.map((run) => [run.id, run])); if ((!ui.activeRun || !ui.runs.has(ui.activeRun)) && runs[0]) ui.activeRun = runs[0].id; renderRuns(); }
async function respondApproval(runId: string, approvalId: string, decision: 'approve' | 'deny', scope: 'once' | 'session'): Promise<void> { try { await window.wardenDesk.runs.approve(runId, approvalId, decision, scope); notice(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } }
function contextText(pack: ContextPack): string { return [`Project: ${pack.project}`, `Directory: ${pack.cwd}`, `Branch: ${pack.branch || 'unknown'}`, `Git status:\n${pack.gitStatus || '(clean)'}`, `Instructions: ${pack.instructionFiles.map((file) => file.path).join(', ') || 'none'}`, `Skills: ${pack.skills.join(', ') || 'none'}`, `Local scoped memories: ${pack.memories.length}`, `Warden Brain: ${pack.brainContext ? 'attached' : 'unavailable'}`, ...pack.warnings.map((warning) => `Warning: ${warning}`)].join('\n'); }
function approveApiBilling(provider: StructuredProviderId): Promise<boolean> { return new Promise((resolve) => { const dialog = $('#api-warning-dialog') as HTMLDialogElement; $('#api-warning-copy').textContent = `${buildProviderNames[provider]} will use an API key for this run. Provider usage charges may apply. Warden will not remember this approval.`; const finish = (approved: boolean): void => { dialog.close(); resolve(approved); }; ($('#confirm-api-run') as HTMLButtonElement).onclick = () => finish(true); ($('#cancel-api-run') as HTMLButtonElement).onclick = () => finish(false); ($('#cancel-api-run-secondary') as HTMLButtonElement).onclick = () => finish(false); dialog.addEventListener('cancel', () => resolve(false), { once: true }); dialog.showModal(); }); }

function domainLines(values: string[]): string { return values.join('\n'); }
function readDomainLines(selector: string): string[] { return [...new Set(($(selector) as HTMLTextAreaElement).value.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean))]; }
function fillPlatformForm(platform?: WebPlatform): void {
  ui.editingPlatformId = platform?.id; $('#platform-dialog-title').textContent = platform ? `Edit ${platform.name}` : 'Add AI platform'; ($('#platform-preset') as HTMLSelectElement).value = ''; ($('#platform-name') as HTMLInputElement).value = platform?.name || ''; ($('#platform-url') as HTMLInputElement).value = platform?.startUrl || ''; ($('#platform-icon') as HTMLInputElement).value = platform?.icon.value || ''; ($('#platform-category') as HTMLSelectElement).value = platform?.category || 'Other'; ($('#platform-profile') as HTMLSelectElement).value = platform?.browserProfileId || ui.profiles[0]?.id || ''; ($('#platform-domains') as HTMLTextAreaElement).value = domainLines(platform?.trustedFirstPartyDomains || []); ($('#platform-auth-domains') as HTMLTextAreaElement).value = domainLines(platform?.trustedAuthDomains || []); ($('#platform-enabled') as HTMLInputElement).checked = platform?.enabled ?? true; ($('#platform-pinned') as HTMLInputElement).checked = platform?.pinned ?? false; ($('#platform-main') as HTMLInputElement).checked = platform?.allowMainView ?? true; ($('#platform-split') as HTMLInputElement).checked = platform?.allowSplitView ?? true;
}
async function openPlatformDialog(platform?: WebPlatform): Promise<void> {
  const dialog = $('#platform-dialog') as HTMLDialogElement; if (dialog.open) return;
  try {
    if (ui.workspace === 'chat') await window.wardenDesk.platform.hide();
    fillPlatformForm(platform); ($('#platform-preset') as HTMLSelectElement).disabled = Boolean(platform); dialog.showModal();
    queueMicrotask(() => ($('#platform-name') as HTMLInputElement).focus());
  } catch (error) {
    notice(error instanceof Error ? error.message : String(error));
    if (ui.workspace === 'chat' && ui.platformId) await selectPlatform(ui.platformId, ui.splitPlatformId);
  }
}
async function createPlaygroundProject(): Promise<ProjectWorkspace> {
  const project = await window.wardenDesk.project.createPlayground();
  ui.projects = await window.wardenDesk.project.list();
  await activateProject(project.id);
  notice(`Created playground project "${project.name}" with Git safety enabled.`);
  return project;
}

async function openProviderSetupDialog(): Promise<void> {
  const dialog = $('#provider-setup-dialog') as HTMLDialogElement;
  if (dialog.open) return;
  if (ui.workspace === 'chat') await window.wardenDesk.platform.hide();
  const matrix = $('#provider-setup-matrix');
  matrix.replaceChildren();
  const reports = await window.wardenDesk.runs.providers();
  for (const report of reports) {
    const card = document.createElement('div');
    card.className = 'provider-card-setup';
    card.innerHTML = `<h4>${buildProviderNames[report.provider]} <span class="status-pill ${report.state === 'subscription_authenticated' ? 'success' : report.state === 'api_key_authenticated' ? 'quiet' : 'warning'}">${report.state.replaceAll('_', ' ')}</span></h4><p>${report.detail || 'Standard CLI provider.'}</p><div class="provider-caps"><span>Isolated Worktree</span><span>Approval Gate</span><span>Diff Review</span><span>Proof Signature</span></div>`;
    matrix.append(card);
  }
  dialog.showModal();
}

async function openChatHandoffDialog(): Promise<void> {
  const dialog = $('#chat-to-build-dialog') as HTMLDialogElement;
  if (dialog.open) return;
  if (ui.workspace === 'chat') await window.wardenDesk.platform.hide();
  dialog.showModal();
}

async function openAboutDialog(): Promise<void> { const dialog = $('#about-dialog') as HTMLDialogElement; if (dialog.open) return; try { if (ui.workspace === 'chat') await window.wardenDesk.platform.hide(); $('#about-version').textContent = `Version ${ui.appInfo?.version || 'unknown'}`; $('#about-runtime').textContent = `${ui.appInfo?.platform || 'Linux'} · ${ui.appInfo?.arch || 'unknown architecture'}`; dialog.showModal(); queueMicrotask(() => ($('#about-done') as HTMLButtonElement).focus()); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } }
async function openOnboarding(): Promise<void> { const dialog = $('#onboarding-dialog') as HTMLDialogElement; if (dialog.open) return; if (ui.workspace === 'chat') await window.wardenDesk.platform.hide(); dialog.showModal(); queueMicrotask(() => ($('#onboarding-chat') as HTMLButtonElement).focus()); }
async function completeOnboarding(next: 'chat' | 'project' | 'sample'): Promise<void> {
  await window.wardenDesk.state.update({ onboardingComplete: true });
  ($('#onboarding-dialog') as HTMLDialogElement).close();
  if (next === 'sample') {
    const project = await createPlaygroundProject();
    await selectWorkspace('build');
    const taskInput = document.querySelector<HTMLTextAreaElement>('#sb-task');
    const acceptanceInput = document.querySelector<HTMLTextAreaElement>('#sb-acceptance');
    if (taskInput) taskInput.value = 'Create a WELCOME.md file introducing this repository, describing its purpose, and detailing how Warden AI Desk manages safe build missions.';
    if (acceptanceInput) acceptanceInput.value = 'The WELCOME.md file exists in the root directory, contains clean Markdown headings, and lists Warden safety principles.';
    notice(`Sample project "${project.name}" ready! Review the pre-filled mission brief below and click "Start mission".`);
  } else if (next === 'project') {
    const previousProject = ui.activeProjectId;
    await chooseProjectDirectory();
    if (ui.activeProjectId === previousProject) await selectWorkspace('chat');
  } else await selectWorkspace('chat');
}
async function savePlatformForm(event: SubmitEvent): Promise<void> { event.preventDefault(); const iconValue = ($('#platform-icon') as HTMLInputElement).value.trim(); const input = { name: ($('#platform-name') as HTMLInputElement).value, startUrl: ($('#platform-url') as HTMLInputElement).value, icon: { kind: iconValue.startsWith('https://') ? 'url' as const : 'text' as const, value: iconValue }, category: ($('#platform-category') as HTMLSelectElement).value as WebPlatform['category'], browserProfileId: ($('#platform-profile') as HTMLSelectElement).value, trustedFirstPartyDomains: readDomainLines('#platform-domains'), trustedAuthDomains: readDomainLines('#platform-auth-domains'), enabled: ($('#platform-enabled') as HTMLInputElement).checked, pinned: ($('#platform-pinned') as HTMLInputElement).checked, allowMainView: ($('#platform-main') as HTMLInputElement).checked, allowSplitView: ($('#platform-split') as HTMLInputElement).checked }; try { const platform = ui.editingPlatformId ? await window.wardenDesk.platform.update(ui.editingPlatformId, input) : await window.wardenDesk.platform.create(input); ui.platforms.set(platform.id, platform); ui.platformId = platform.id; ($('#platform-dialog') as HTMLDialogElement).close(); renderPlatforms(); await selectPlatform(platform.id); notice(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } }
function applyPreset(key: string): void { const preset = ui.presets.find((item) => item.key === key); if (!preset) return; ($('#platform-name') as HTMLInputElement).value = preset.name; ($('#platform-url') as HTMLInputElement).value = preset.startUrl; ($('#platform-icon') as HTMLInputElement).value = preset.icon.value; ($('#platform-category') as HTMLSelectElement).value = preset.category; ($('#platform-domains') as HTMLTextAreaElement).value = domainLines(preset.trustedFirstPartyDomains); ($('#platform-auth-domains') as HTMLTextAreaElement).value = domainLines(preset.trustedAuthDomains); }
function openSplitDialog(): void { const select = $('#split-platform') as HTMLSelectElement; select.replaceChildren(); for (const platform of ui.platforms.values()) if (platform.id !== ui.platformId && platform.enabled && platform.allowSplitView) select.add(new Option(platform.name, platform.id)); if (!select.options.length) return notice('No other split-view platform is available.'); ($('#split-dialog') as HTMLDialogElement).showModal(); }
async function refreshPlatforms(): Promise<void> { const platforms = await window.wardenDesk.platform.list(); ui.platforms = new Map(platforms.map((item) => [item.id, item])); renderPlatforms(); }
async function handleMenuAction(payload: PlatformMenuAction): Promise<void> { if (payload.action === 'refresh') return refreshPlatforms(); if (payload.action === 'settings') { const platform = ui.platforms.get(payload.platformId); if (platform) openPlatformDialog(platform); return; } if (payload.action === 'split') { openSplitDialog(); return; } if (payload.action === 'removed') { await refreshPlatforms(); if (ui.platformId === payload.platformId) { ui.platformId = [...ui.platforms.values()][0]?.id || ''; if (ui.platformId) await selectPlatform(ui.platformId); } return; } if (payload.action === 'cleared') notice('Configured site data was cleared. Related registrable domains in the shared profile may also have been affected.'); }
async function chooseProjectDirectory(): Promise<void> { const cwd = await window.wardenDesk.terminal.chooseDirectory(); if (!cwd) return; const project = await window.wardenDesk.project.create({ cwd, browserProfileId: ui.platforms.get(ui.platformId)?.browserProfileId }); ui.projects = await window.wardenDesk.project.list(); await activateProject(project.id); notice(); }

async function initialize(): Promise<void> {
  const [{ state, warning }, platforms, presets, profiles, projects, appInfo] = await Promise.all([window.wardenDesk.state.get(), window.wardenDesk.platform.list(), window.wardenDesk.platform.presets(), window.wardenDesk.platform.profiles(), window.wardenDesk.project.list(), window.wardenDesk.app.info()]); if (warning) notice(warning); ui.appInfo = appInfo; ui.mode = state.mode; setMode(ui.mode); ui.platforms = new Map(platforms.map((item) => [item.id, item])); ui.presets = presets; ui.profiles = profiles; ui.projects = projects; ui.platformId = state.selectedPlatformId && ui.platforms.has(state.selectedPlatformId) ? state.selectedPlatformId : platforms[0]?.id || ''; ui.activeProjectId = state.activeProjectId; const activeProject = projects.find((item) => item.id === ui.activeProjectId); ui.activeRun = activeProject?.activeRunId || null; ui.cwd = activeProject?.cwd || state.recentProjects[0] || ''; ui.splitPlatformId = activeProject?.splitPlatformId; $('#version-badge').textContent = `v${appInfo.version}`; $('#version-badge').title = `${appInfo.name} ${appInfo.version}`; $('#active-directory').textContent = ui.cwd || 'No project selected';
  await initSimpleBuild({ projects, activeProjectId: activeProject?.id, activateProject, chooseProject: chooseProjectDirectory, createPlayground: async () => { await createPlaygroundProject(); }, openDeveloperMode: async () => { ui.mode = 'developer'; setMode(ui.mode); applyMode(); await window.wardenDesk.state.update({ mode: ui.mode }); }, openTerminal: async () => { ui.mode = 'developer'; setMode(ui.mode); selectExecution('local'); applyMode(); await window.wardenDesk.state.update({ mode: ui.mode }); }, activateRun: (run, project) => { if (project) { ui.projects = ui.projects.map((item) => item.id === project.id ? project : item); renderProjects(); } ui.activeRun = run?.id || null; if (run) ui.runs.set(run.id, run); renderRuns(); }, notify: notice });

  const modeToggle = document.getElementById('mode-toggle') as HTMLInputElement | null; if (modeToggle) modeToggle.checked = ui.mode === 'developer';
  document.getElementById('mode-toggle')?.addEventListener('change', (event) => { const checked = (event.target as HTMLInputElement).checked; ui.mode = checked ? 'developer' : 'simple'; setMode(ui.mode); applyMode(); void window.wardenDesk.state.update({ mode: ui.mode }); if (ui.mode === 'simple') void syncSimpleBuild(ui.projects, ui.activeProjectId); });
  $('#agent-directory').textContent = ui.cwd || 'No project selected'; renderProjects(); renderPlatforms();
  const presetSelect = $('#platform-preset') as HTMLSelectElement; for (const preset of presets) presetSelect.add(new Option(preset.name, preset.key)); const profileSelect = $('#platform-profile') as HTMLSelectElement; for (const profile of profiles) profileSelect.add(new Option(profile.name, profile.id));
  for (const metadata of state.terminals) { const stopped = { ...metadata, status: 'stopped' as const }; attachTerminal(stopped); stopped && stopped.id === ui.activeTerminal; }
  document.querySelectorAll<HTMLButtonElement>('[data-workspace]').forEach((button) => button.addEventListener('click', () => void selectWorkspace(button.dataset.workspace as WorkspaceId)));
  document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach((button) => button.addEventListener('click', () => { if (ui.platformId) void window.wardenDesk.platform.action(ui.platformId, button.dataset.action as 'back' | 'forward' | 'reload' | 'stop' | 'home'); }));
  document.querySelectorAll<HTMLButtonElement>('[data-execution]').forEach((button) => button.addEventListener('click', () => selectExecution(button.dataset.execution as ExecutionMode)));
  document.querySelectorAll<HTMLInputElement>('input[name="billing-source"]').forEach((input) => input.addEventListener('change', renderAuthStatus));
  $('#project-picker').addEventListener('change', () => void activateProject(($('#project-picker') as HTMLSelectElement).value)); $('#platform-search').addEventListener('input', renderPlatforms); $('#add-platform').addEventListener('click', () => void openPlatformDialog()); $('#empty-add-platform').addEventListener('click', () => void openPlatformDialog()); $('#restore-platform').addEventListener('click', async () => { const removed = await window.wardenDesk.platform.removed(); if (!removed.length) return notice('No removed platforms are available to restore.'); const choice = removed.length === 1 ? removed[0].name : prompt(`Enter the platform to restore:\n${removed.map((item) => item.name).join('\n')}`); const target = removed.find((item) => item.name.toLowerCase() === choice?.trim().toLowerCase()); if (!target) return choice && notice('No removed platform matched that name.'); const restored = await window.wardenDesk.platform.restore(target.id); ui.platforms.set(restored.id, restored); renderPlatforms(); await selectPlatform(restored.id); }); presetSelect.addEventListener('change', () => applyPreset(presetSelect.value)); const platformDialog = $('#platform-dialog') as HTMLDialogElement; ($('#platform-form') as HTMLFormElement).addEventListener('submit', (event) => void savePlatformForm(event)); platformDialog.addEventListener('close', () => { if (ui.workspace === 'chat' && ui.platformId && ui.platforms.get(ui.platformId)?.enabled) void selectPlatform(ui.platformId, ui.splitPlatformId); }); ($('#split-dialog') as HTMLDialogElement).addEventListener('close', () => { if (ui.workspace === 'chat' && ui.platformId && ui.platforms.get(ui.platformId)?.enabled) void selectPlatform(ui.platformId, ui.splitPlatformId); });
  document.getElementById('mission-server-retry')?.addEventListener('click', () => { void ensureWardenServerAndMount(); });
  document.getElementById('mission-server-details-btn')?.addEventListener('click', () => { document.getElementById('mission-server-error')?.toggleAttribute('hidden'); });
  const aboutDialog = $('#about-dialog') as HTMLDialogElement; $('#about-button').addEventListener('click', () => void openAboutDialog()); $('#about-close').addEventListener('click', () => aboutDialog.close()); $('#about-done').addEventListener('click', () => aboutDialog.close()); aboutDialog.addEventListener('close', () => { if (ui.workspace === 'chat' && ui.platformId) void selectPlatform(ui.platformId, ui.splitPlatformId); });
  const providerSetupDialog = $('#provider-setup-dialog') as HTMLDialogElement; $('#provider-setup-button').addEventListener('click', () => void openProviderSetupDialog()); $('#provider-setup-close').addEventListener('click', () => providerSetupDialog.close()); $('#provider-setup-done').addEventListener('click', () => providerSetupDialog.close()); providerSetupDialog.addEventListener('close', () => { if (ui.workspace === 'chat' && ui.platformId) void selectPlatform(ui.platformId, ui.splitPlatformId); });
  const chatHandoffDialog = $('#chat-to-build-dialog') as HTMLDialogElement; $('#handoff-to-build').addEventListener('click', () => void openChatHandoffDialog()); $('#chat-handoff-close').addEventListener('click', () => chatHandoffDialog.close()); $('#chat-handoff-cancel').addEventListener('click', () => chatHandoffDialog.close());
  $('#chat-handoff-preview-btn').addEventListener('click', async () => {
    if (!ui.cwd) return notice('Select a project directory first.');
    const prompt = ($('#chat-handoff-prompt') as HTMLTextAreaElement).value.trim();
    const pack = await window.wardenDesk.runs.previewContext(ui.cwd);
    const output = $('#chat-handoff-preview');
    output.textContent = contextText(pack);
    output.removeAttribute('hidden');
  });
  $('#chat-handoff-start').addEventListener('click', async () => {
    const prompt = ($('#chat-handoff-prompt') as HTMLTextAreaElement).value.trim();
    if (!prompt) return notice('Enter or paste a mission brief.');
    chatHandoffDialog.close();
    await selectWorkspace('build');
    const taskInput = document.querySelector<HTMLTextAreaElement>('#sb-task');
    if (taskInput) taskInput.value = prompt;
    notice('Mission brief transferred to Build workspace. Click "Start mission" to launch.');
  });
  const onboardingDialog = $('#onboarding-dialog') as HTMLDialogElement;
  $('#onboarding-create-sample')?.addEventListener('click', () => void completeOnboarding('sample'));
  $('#onboarding-chat').addEventListener('click', () => void completeOnboarding('chat'));
  $('#onboarding-project').addEventListener('click', () => void completeOnboarding('project'));
  onboardingDialog.addEventListener('cancel', (event) => { event.preventDefault(); void completeOnboarding('chat'); });
  $('#new-profile').addEventListener('click', async () => { const name = prompt('Name this Warden browser profile. Profiles share cookies only with platforms assigned to the same profile.'); if (!name) return; try { const profile = await window.wardenDesk.platform.createProfile(name); ui.profiles.push(profile); profileSelect.add(new Option(profile.name, profile.id)); profileSelect.value = profile.id; } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#platform-overflow').addEventListener('click', async () => { if (!ui.platformId) return; const button = $('#platform-overflow') as HTMLButtonElement; const rect = button.getBoundingClientRect(); button.setAttribute('aria-expanded', 'true'); try { await window.wardenDesk.platform.showMenu(ui.platformId, { x: rect.left, y: rect.bottom }); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } finally { button.setAttribute('aria-expanded', 'false'); } });
  $('#open-system').addEventListener('click', () => ui.platformId && void window.wardenDesk.platform.openExternal(ui.platformId));
  $('#confirm-split').addEventListener('click', async () => { const id = ($('#split-platform') as HTMLSelectElement).value; ($('#split-dialog') as HTMLDialogElement).close(); if (id) await selectPlatform(ui.platformId, id); }); $('#split-cancel').addEventListener('click', () => ($('#split-dialog') as HTMLDialogElement).close()); $('#split-cancel-x').addEventListener('click', () => ($('#split-dialog') as HTMLDialogElement).close());
  $('#choose-directory').addEventListener('click', () => void chooseProjectDirectory());
  $('#agent-choose-directory').addEventListener('click', () => void chooseProjectDirectory());
  $('#preview-context').addEventListener('click', async () => { if (!ui.cwd) return notice('Choose a project directory first.'); try { const pack = await window.wardenDesk.runs.previewContext(ui.cwd); const output = $('#context-preview'); output.textContent = contextText(pack); output.removeAttribute('hidden'); notice(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#start-run').addEventListener('click', async () => { const provider = activeBuildProvider(); const prompt = ($('#run-prompt') as HTMLTextAreaElement).value.trim(); if (!provider) return notice('Choose a structured provider first.'); if (!ui.cwd || !prompt) return notice('Choose a project and enter a build task.'); const authSource = document.querySelector<HTMLInputElement>('input[name="billing-source"]:checked')?.value === 'api_key' ? 'api_key' : 'subscription'; const report = ui.auth.get(provider); if (authSource === 'subscription' && report?.state !== 'subscription_authenticated') return notice(report?.detail || 'Subscription authentication is not ready.'); const apiFallbackApproved = authSource === 'api_key' ? await approveApiBilling(provider) : false; if (authSource === 'api_key' && !apiFallbackApproved) return notice('API-key run cancelled. No billable request was started.'); try { notice(`Starting ${buildProviderNames[provider]} run with ${authSource === 'subscription' ? 'subscription' : 'approved API-key'} authentication…`); const run = await window.wardenDesk.runs.start({ provider, prompt, cwd: ui.cwd, projectId: ui.activeProjectId, attachContext: ($('#attach-context') as HTMLInputElement).checked, authSource, apiFallbackApproved }); ui.runs.set(run.id, run); ui.activeRun = run.id; if (ui.activeProjectId) await window.wardenDesk.project.update(ui.activeProjectId, { activeRunId: run.id }); renderRuns(); renderRun(run); notice(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); await refreshRuns(); } });
  $('#resume-run').addEventListener('click', async () => { const prompt = ($('#run-prompt') as HTMLTextAreaElement).value.trim(); if (!ui.activeRun) return notice('Select a run to resume.'); try { notice('Resuming preserved Codex thread…'); const run = await window.wardenDesk.runs.resume(ui.activeRun, prompt); ui.runs.set(run.id, run); renderRun(run); notice(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#cancel-run').addEventListener('click', async () => { if (!ui.activeRun) return; try { await window.wardenDesk.runs.cancel(ui.activeRun); notice('Cancellation requested.'); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#generate-handoff').addEventListener('click', async () => { if (!ui.activeRun) return notice('Select a run first.'); try { const result = await window.wardenDesk.runs.handoff(ui.activeRun); $('#run-detail').textContent = `${result.content}\n\nSaved: ${result.path}`; notice('Handoff generated.'); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#save-proof').addEventListener('click', async () => { if (!ui.activeRun) return notice('Select a run first.'); try { const proof = await window.wardenDesk.runs.saveProof(ui.activeRun); notice(proof.detail); await refreshRuns(); } catch (error) { notice(error instanceof Error ? error.message : String(error)); } });
  $('#refresh-runs').addEventListener('click', () => void refreshRuns());
  $('#refresh-auth').addEventListener('click', () => void refreshProviderAuth());
  $('#new-terminal').addEventListener('click', () => void createTerminal()); $('#clear-display').addEventListener('click', () => { const active = ui.activeTerminal ? ui.terminals.get(ui.activeTerminal) : undefined; active?.terminal.clear(); });
  $('#restart-terminal').addEventListener('click', async () => { const id = ui.activeTerminal; if (!id) return; const active = ui.terminals.get(id); if (!active || active.metadata.status === 'running') return; active.terminal.dispose(); ui.terminals.delete(id); await createTerminal(active.metadata); });
  $('#close-terminal').addEventListener('click', async () => { const id = ui.activeTerminal; if (!id) return; const active = ui.terminals.get(id); if (!active) return; if (active.metadata.status === 'running' && !confirm(`Close ${active.metadata.name} and terminate its process?`)) return; await window.wardenDesk.terminal.kill(id); active.terminal.dispose(); ui.terminals.delete(id); ui.activeTerminal = ui.terminals.keys().next().value || null; if (ui.activeTerminal) activateTerminal(ui.activeTerminal); else $('#terminal-empty').removeAttribute('hidden'); renderTabs(); });
  const historyDialog = $('#history-dialog') as HTMLDialogElement; $('#show-history').addEventListener('click', () => { const active = ui.activeTerminal ? ui.terminals.get(ui.activeTerminal) : undefined; const list = $('#history-list'); list.replaceChildren(); for (const command of active?.metadata.history || []) { const li = document.createElement('li'); li.textContent = command; list.append(li); } historyDialog.showModal(); }); $('[data-close-dialog]').addEventListener('click', () => historyDialog.close()); $('#clear-history').addEventListener('click', async () => { const active = ui.activeTerminal ? ui.terminals.get(ui.activeTerminal) : undefined; if (active) { await window.wardenDesk.terminal.clearHistory(active.metadata.id); active.metadata.history = []; } historyDialog.close(); });
  window.wardenDesk.platform.onStatus(renderProviderStatus); window.wardenDesk.platform.onMenuAction((action) => void handleMenuAction(action)); window.wardenDesk.terminal.onData(({ id, data }) => ui.terminals.get(id)?.terminal.write(data)); window.wardenDesk.terminal.onState((metadata) => { const item = ui.terminals.get(metadata.id); if (item) item.metadata = metadata; renderTabs(); });
  window.wardenDesk.runs.onChanged((run) => { if (!ui.activeProjectId || run.projectId === ui.activeProjectId) ui.runs.set(run.id, run); renderRuns(); if (ui.activeRun === run.id) renderRun(run); onSimpleBuildRunsChanged(run); });
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.altKey && event.key.toLowerCase() === 'w') {
      event.preventDefault();
      void selectWorkspace('team-chat');
      return;
    }
    if (ui.workspace !== 'chat' || !ui.platformId) return;
    if (event.altKey && event.key === 'ArrowLeft') { event.preventDefault(); void window.wardenDesk.platform.action(ui.platformId, 'back'); }
    if (event.altKey && event.key === 'ArrowRight') { event.preventDefault(); void window.wardenDesk.platform.action(ui.platformId, 'forward'); }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'r') { event.preventDefault(); void window.wardenDesk.platform.action(ui.platformId, 'reload'); }
  });
  new ResizeObserver(() => { providerBounds(); fitActiveTerminal(); }).observe(document.body); window.addEventListener('beforeunload', () => void window.wardenDesk.platform.hide());
  await Promise.all([refreshRuns(), refreshProviderAuth()]); if (activeProject) { ui.execution = activeProject.executionMode; selectExecution(ui.execution); } if (ui.platformId && state.workspace === 'chat') await selectPlatform(ui.platformId, ui.splitPlatformId); else await selectWorkspace(state.workspace); applyMode(); if (!state.onboardingComplete) await openOnboarding();
}
void initialize();
