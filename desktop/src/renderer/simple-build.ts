import type { InterfaceMode, ProviderAuthReport, ProjectWorkspace, WardenRun } from '../shared/types';
import { providerOnboardingCopy, translateApproval, translateEvent } from './copy';

const $ = <T extends Element = HTMLElement>(selector: string): T => { const element = document.querySelector<T>(selector); if (!element) throw new Error(`Missing element: ${selector}`); return element; };
type SimpleBuildOptions = {
  projects: ProjectWorkspace[];
  activeProjectId?: string;
  activateProject(id: string): Promise<void>;
  chooseProject(): Promise<void>;
  openDeveloperMode(): Promise<void>;
  openTerminal(): Promise<void>;
  activateRun(run?: WardenRun, project?: ProjectWorkspace): void;
  notify(message?: string): void;
};

const sb = {
  mode: 'simple' as InterfaceMode,
  projects: [] as ProjectWorkspace[],
  activeProject: undefined as ProjectWorkspace | undefined,
  codexAuth: undefined as ProviderAuthReport | undefined,
  run: undefined as WardenRun | undefined,
  runs: [] as WardenRun[],
  technicalOpen: false,
  options: undefined as SimpleBuildOptions | undefined,
};

function setPanel(id: 'sb-no-project' | 'sb-readonly' | 'sb-onboarding' | 'sb-composer' | 'sb-progress', visible: boolean): void { $(`#${id}`).toggleAttribute('hidden', !visible); }
function hideAllPanels(): void { for (const id of ['sb-no-project', 'sb-readonly', 'sb-onboarding', 'sb-composer', 'sb-progress'] as const) setPanel(id, false); }
function showError(error?: unknown): void {
  const message = error ? (error instanceof Error ? error.message : String(error)) : '';
  $('#sb-error').textContent = message;
  $('#sb-error').toggleAttribute('hidden', !message);
  sb.options?.notify(message || undefined);
}
async function runAction(buttonId: string, action: () => Promise<void>): Promise<void> {
  const button = $<HTMLButtonElement>(`#${buttonId}`); button.disabled = true; showError();
  try { await action(); } catch (error) { showError(error); } finally { button.disabled = false; }
}

export function isSimpleBuildActive(): boolean { return sb.mode === 'simple'; }
export function setMode(mode: InterfaceMode): void { sb.mode = mode; }

export function renderProjectList(): void {
  const root = $('#sb-project-list'); root.replaceChildren();
  for (const project of sb.projects) {
    const button = document.createElement('button'); button.textContent = project.name; button.title = project.cwd; button.classList.toggle('active', project.id === sb.activeProject?.id);
    button.addEventListener('click', () => void runAction('sb-choose-directory', () => sb.options!.activateProject(project.id)));
    root.append(button);
  }
}

function statusLabel(status: WardenRun['status']): string {
  return ({ starting: 'Starting', running: 'In progress', waiting_approval: 'Needs approval', completed: 'Ready to review', failed: 'Needs attention', cancelled: 'Stopped', interrupted: 'Interrupted' })[status];
}

function renderProjectIdentity(): void {
  $('#sb-project-name').textContent = sb.activeProject?.name || 'No project selected';
  $('#sb-project-meta').textContent = sb.activeProject ? `${sb.activeProject.branch || 'Current branch'} · ${sb.activeProject.cwd}` : 'Open a repository to begin';
  const badge = $('#sb-safe-badge');
  const workspace = sb.run?.safeWorkspace;
  badge.className = 'status-pill';
  if (!sb.activeProject) badge.textContent = 'No safe workspace';
  else if (!workspace) { badge.textContent = 'Git safety check'; badge.classList.add('quiet'); }
  else if (workspace.status === 'active') { badge.textContent = 'Isolated worktree'; badge.classList.add('active'); }
  else if (workspace.status === 'kept') { badge.textContent = 'Applied safely'; badge.classList.add('success'); }
  else if (workspace.status === 'undone') { badge.textContent = 'Update undone'; badge.classList.add('quiet'); }
  else if (workspace.status === 'discarded') { badge.textContent = 'Worktree discarded'; badge.classList.add('quiet'); }
  else { badge.textContent = 'Merge needs attention'; badge.classList.add('warning'); }
  $<HTMLButtonElement>('#sb-new-task').disabled = !sb.activeProject;
  $<HTMLButtonElement>('#sb-open-terminal').disabled = !sb.activeProject;
}

function renderRunList(): void {
  const root = $('#sb-run-list'); root.replaceChildren();
  $('#sb-run-count').textContent = String(sb.runs.length);
  if (!sb.runs.length) { const empty = document.createElement('p'); empty.className = 'sb-rail-empty'; empty.textContent = 'Tasks for this project will stay here.'; root.append(empty); return; }
  for (const run of [...sb.runs].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))) {
    const button = document.createElement('button'); button.className = 'sb-run-card'; button.classList.toggle('active', run.id === sb.run?.id); button.dataset.status = run.status;
    const signal = document.createElement('span'); signal.className = 'sb-run-signal'; signal.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('span'); copy.className = 'sb-run-copy';
    const title = document.createElement('strong'); title.textContent = run.prompt.split('\n')[0].slice(0, 72) || 'Untitled mission';
    const meta = document.createElement('small'); meta.textContent = `${statusLabel(run.status)} · ${new Date(run.updatedAt).toLocaleDateString([], { month: 'short', day: 'numeric' })}`;
    copy.append(title, meta); button.append(signal, copy);
    button.addEventListener('click', () => void selectHistoricalRun(run));
    root.append(button);
  }
}

async function selectHistoricalRun(run: WardenRun): Promise<void> {
  showError();
  try {
    sb.run = run;
    if (sb.activeProject) sb.activeProject = await window.wardenDesk.project.update(sb.activeProject.id, { activeRunId: run.id });
    sb.options?.activateRun(run, sb.activeProject);
    setPanel('sb-composer', false); setPanel('sb-progress', true); renderProgress(run);
  } catch (error) { showError(error); }
}

async function loadProject(project?: ProjectWorkspace): Promise<void> {
  sb.activeProject = project; sb.run = undefined; sb.runs = []; renderProjectList(); renderProjectIdentity(); renderRunList(); hideAllPanels(); showError();
  if (!project) { setPanel('sb-no-project', true); return; }
  const runs = await window.wardenDesk.runs.list(project.id);
  sb.runs = runs;
  sb.run = runs.find((run) => run.id === project.activeRunId) || runs[0];
  renderRunList(); renderProjectIdentity();
  if (sb.run) { setPanel('sb-progress', true); renderProgress(sb.run); return; }
  const status = await window.wardenDesk.runs.checkProject(project.cwd);
  if (!status.isGit || !status.clean) { setPanel('sb-readonly', true); return; }
  await refreshCodexOnboarding();
}

async function refreshCodexOnboarding(): Promise<void> {
  hideAllPanels();
  const reports = await window.wardenDesk.runs.providers();
  sb.codexAuth = reports.find((report) => report.provider === 'codex');
  const copy = providerOnboardingCopy('codex', sb.codexAuth);
  if (copy.action === 'ready') {
    setPanel('sb-composer', true);
    $('#sb-provider-line').textContent = `${copy.headline} · Subscription authentication`;
    $<HTMLButtonElement>('#sb-start').disabled = false;
  } else {
    setPanel('sb-onboarding', true);
    $('#sb-onboarding-headline').textContent = copy.headline;
    $('#sb-onboarding-body').textContent = copy.body;
  }
}

function renderProgress(run: WardenRun): void {
  $('#sb-run-title').textContent = run.prompt.split('\n')[0].slice(0, 96) || 'Working on your project';
  $('#sb-run-meta').textContent = `${run.provider === 'codex' ? 'Codex' : run.provider} · ${run.auth?.source === 'subscription' ? 'subscription' : run.auth?.source || 'authentication unknown'} · ${new Date(run.updatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  const status = $('#sb-run-status'); status.textContent = statusLabel(run.status); status.className = 'status-pill';
  if (run.status === 'waiting_approval') status.classList.add('warning'); else if (run.status === 'completed') status.classList.add('success'); else if (run.status === 'failed' || run.status === 'interrupted') status.classList.add('danger'); else if (run.status === 'running' || run.status === 'starting') status.classList.add('active'); else status.classList.add('quiet');
  const hasChecks = run.events.some((event) => event.type === 'test.completed' || event.type === 'command.started' && /(?:test|check|build|lint)/i.test(String(event.payload.command || '')));
  const phase = run.status === 'completed' || ['kept', 'undone', 'discarded'].includes(run.safeWorkspace?.status || '') ? 3 : hasChecks ? 2 : run.status === 'starting' ? 0 : 1;
  document.querySelectorAll<HTMLElement>('#sb-phase-track [data-phase]').forEach((item, index) => { item.classList.toggle('done', index < phase); item.classList.toggle('active', index === phase); });
  const list = $('#sb-progress-list'); list.replaceChildren();
  const seen = new Set<string>();
  for (const event of run.events) { const line = translateEvent(event); if (seen.has(line) && event.type !== 'command.completed') continue; seen.add(line); const row = document.createElement('div'); row.className = 'sb-step'; const icon = document.createElement('span'); icon.className = 'sb-step-icon'; icon.textContent = event.type === 'command.completed' && event.payload.exitCode !== 0 ? '×' : event.type === 'approval.requested' ? '!' : '✓'; const copy = document.createElement('span'); copy.textContent = line; const time = document.createElement('time'); time.textContent = new Date(event.timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); row.append(icon, copy, time); list.append(row); }
  if (run.error) { const row = document.createElement('div'); row.className = 'sb-step sb-step-error'; row.textContent = `Something went wrong: ${run.error}`; list.append(row); }
  if (run.safeWorkspace?.conflictDetail) { const row = document.createElement('div'); row.className = 'sb-step sb-step-error'; row.textContent = run.safeWorkspace.conflictDetail; list.append(row); }
  if (!run.events.length) { const waiting = document.createElement('p'); waiting.className = 'sb-activity-empty'; waiting.textContent = 'Preparing the isolated workspace and provider session…'; list.append(waiting); }

  const pendingApproval = run.approvals.find((item) => item.status === 'pending');
  $('#sb-approval').toggleAttribute('hidden', !pendingApproval);
  if (pendingApproval) { const copy = translateApproval(pendingApproval); $('#sb-approval-title').textContent = copy.title; $('#sb-approval-why').textContent = copy.why ? `Why: ${copy.why}` : ''; }

  const active = ['starting', 'running', 'waiting_approval'].includes(run.status);
  const finished = ['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status);
  const workspaceStatus = run.safeWorkspace?.status;
  $('#sb-active-actions').toggleAttribute('hidden', !active);
  $('#sb-followup').toggleAttribute('hidden', true);
  $('#sb-send-followup').toggleAttribute('hidden', true);
  $('#sb-pre-actions').toggleAttribute('hidden', !finished || !['active', 'conflict'].includes(workspaceStatus || ''));
  $('#sb-post-actions').toggleAttribute('hidden', !['kept', 'undone', 'discarded'].includes(workspaceStatus || ''));
  $('#sb-undo').toggleAttribute('hidden', workspaceStatus !== 'kept');
  renderTechnical(run);
  renderResultTabs(run);
  renderProjectIdentity();
  renderRunList();
}

function renderTechnical(run: WardenRun): void {
  const pre = $('#sb-technical'); pre.toggleAttribute('hidden', !sb.technicalOpen);
  if (sb.technicalOpen) {
    const pending = run.approvals.find((item) => item.status === 'pending');
    pre.textContent = JSON.stringify({ pendingApproval: pending ? { method: pending.method, detail: pending.detail, providerPayload: pending.providerPayload } : undefined, recentEvents: run.events.slice(-40) }, null, 2);
  }
}

function renderResultTabs(run: WardenRun): void {
  const statusMessage = run.safeWorkspace?.status === 'undone' ? 'This update was undone with a new Git revert commit.' : run.safeWorkspace?.status === 'discarded' ? 'No changes were kept from this task.' : undefined;
  $('#sb-summary-copy').textContent = statusMessage || run.evidence.finalMessage || (run.status === 'running' || run.status === 'starting' ? 'Warden is working. The outcome summary will appear here when the provider finishes.' : 'No outcome summary was returned.');
  const stats = $('#sb-summary-stats'); stats.removeAttribute('hidden'); stats.replaceChildren();
  const summaryStats = [[String(run.evidence.changedFiles.length), 'files changed'], [String(run.evidence.tests.filter((test) => test.exitCode === 0).length), 'checks passed'], [run.safeWorkspace?.status || 'pending', 'workspace']];
  for (const [value, label] of summaryStats) { const item = document.createElement('div'); const strong = document.createElement('strong'); strong.textContent = value; const span = document.createElement('span'); span.textContent = label; item.append(strong, span); stats.append(item); }
  const changed = $('#sb-changed-list'); changed.replaceChildren();
  if (!run.evidence.changedFiles.length) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'No files changed yet.'; changed.append(empty); }
  else for (const file of run.evidence.changedFiles) { const row = document.createElement('div'); row.className = 'sb-file-row'; const state = document.createElement('span'); state.textContent = 'M'; const name = document.createElement('code'); name.textContent = file; row.append(state, name); changed.append(row); }
  const diff = $('#sb-diff'); diff.textContent = run.evidence.diff || ''; diff.toggleAttribute('hidden', !run.evidence.diff);
  const checks = $('#sb-check-list'); checks.replaceChildren();
  if (!run.evidence.tests.length) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'No checks have been recorded yet.'; checks.append(empty); }
  else for (const test of run.evidence.tests) { const row = document.createElement('div'); row.className = `sb-check-row ${test.exitCode === 0 ? 'passed' : 'failed'}`; const mark = document.createElement('span'); mark.textContent = test.exitCode === 0 ? '✓' : '×'; const copy = document.createElement('div'); const command = document.createElement('code'); command.textContent = test.command; const result = document.createElement('small'); result.textContent = test.exitCode === 0 ? 'Passed' : `Exited ${test.exitCode ?? 'without a result'}`; copy.append(command, result); row.append(mark, copy); checks.append(row); }
  const history = $('#sb-history-list'); history.replaceChildren();
  const steps: string[] = ['Started with Codex'];
  const approved = run.approvals.filter((item) => item.status === 'approved').length;
  if (approved) steps.push(`Approved ${approved} request(s)`);
  if (run.safeWorkspace?.status === 'kept') steps.push(`Kept changes${run.safeWorkspace.consolidatedCommit ? ` · ${run.safeWorkspace.consolidatedCommit.slice(0, 8)}` : ''}`);
  if (run.safeWorkspace?.status === 'undone') steps.push(`Undid update${run.safeWorkspace.undoCommit ? ` · ${run.safeWorkspace.undoCommit.slice(0, 8)}` : ''}`);
  if (run.safeWorkspace?.status === 'discarded') steps.push('Discarded safe workspace');
  steps.push(`Last updated ${new Date(run.updatedAt).toLocaleTimeString()}`);
  for (const step of steps) { const row = document.createElement('div'); const mark = document.createElement('span'); mark.setAttribute('aria-hidden', 'true'); const copy = document.createElement('span'); copy.textContent = step; row.append(mark, copy); history.append(row); }
  $('#sb-proof-state').textContent = run.proof.brain === 'saved' ? 'Proof saved to Warden Brain.' : run.proof.brain === 'failed' ? `Brain save failed: ${run.proof.detail || 'Unknown error'}` : run.proof.brain === 'unavailable' ? `Brain unavailable: ${run.proof.detail || 'Local proof remains available.'}` : run.proof.local === 'saved' ? `Local proof saved${run.proof.path ? ` at ${run.proof.path}` : ''}.` : 'Proof has not been saved.';
}

async function startTask(): Promise<void> {
  const outcome = $<HTMLTextAreaElement>('#sb-task').value.trim(); const acceptance = $<HTMLTextAreaElement>('#sb-acceptance').value.trim(); const project = sb.activeProject;
  const prompt = acceptance ? `${outcome}\n\nReady for review when:\n${acceptance}` : outcome;
  if (!project || !prompt) throw new Error('Choose a project and describe what you want Warden to build.');
  if (sb.codexAuth?.state !== 'subscription_authenticated') throw new Error(sb.codexAuth?.detail || 'Codex subscription authentication is not ready.');
  const run = await window.wardenDesk.runs.start({ provider: 'codex', prompt, cwd: project.cwd, projectId: project.id, attachContext: true, authSource: 'subscription', safe: true });
  sb.run = run; sb.runs = [run, ...sb.runs.filter((item) => item.id !== run.id)]; sb.activeProject = await window.wardenDesk.project.update(project.id, { activeRunId: run.id });
  sb.options?.activateRun(run, sb.activeProject);
  $<HTMLTextAreaElement>('#sb-task').value = ''; $<HTMLTextAreaElement>('#sb-acceptance').value = ''; setPanel('sb-composer', false); setPanel('sb-progress', true); renderProgress(run);
}
async function keepChanges(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.keep(sb.run.id); renderProgress(sb.run); }
async function discardTask(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.discard(sb.run.id); renderProgress(sb.run); }
async function undoUpdate(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.undoUpdate(sb.run.id); renderProgress(sb.run); }
async function startAnotherTask(): Promise<void> { if (!sb.activeProject) return; sb.activeProject = await window.wardenDesk.project.update(sb.activeProject.id, { activeRunId: undefined }); sb.run = undefined; sb.options?.activateRun(undefined, sb.activeProject); await refreshCodexOnboarding(); }
async function beginNewTask(): Promise<void> { if (sb.run && ['starting', 'running', 'waiting_approval'].includes(sb.run.status)) throw new Error('Stop or finish the active mission before starting another one.'); await startAnotherTask(); }
async function askForChanges(): Promise<void> { if (!sb.run) return; const box = $<HTMLTextAreaElement>('#sb-followup'); const prompt = box.value.trim(); if (!prompt) throw new Error('Describe the changes you want Codex to make.'); sb.run = await window.wardenDesk.runs.resume(sb.run.id, prompt); box.value = ''; renderProgress(sb.run); }
async function respondToApproval(decision: 'approve' | 'deny'): Promise<void> { const approval = sb.run?.approvals.find((item) => item.status === 'pending'); if (!sb.run || !approval) return; await window.wardenDesk.runs.approve(sb.run.id, approval.id, decision, 'once'); }
async function prepareHandoff(): Promise<void> { if (!sb.run) throw new Error('Select a mission before preparing a review handoff.'); const result = await window.wardenDesk.runs.handoff(sb.run.id); const output = $('#sb-handoff-output'); output.textContent = `${result.content}\n\nSaved: ${result.path}`; output.removeAttribute('hidden'); $('#sb-proof-state').textContent = `Review handoff saved at ${result.path}`; }
async function saveProof(): Promise<void> { if (!sb.run) throw new Error('Select a mission before saving proof.'); const proof = await window.wardenDesk.runs.saveProof(sb.run.id); sb.run = await window.wardenDesk.runs.get(sb.run.id); sb.runs = sb.runs.map((item) => item.id === sb.run!.id ? sb.run! : item); $('#sb-proof-state').textContent = proof.detail || `Proof: ${proof.brain}`; renderResultTabs(sb.run); }

export async function initSimpleBuild(options: SimpleBuildOptions): Promise<void> {
  sb.options = options; sb.projects = options.projects; renderProjectList();
  $('#sb-choose-directory').addEventListener('click', () => void runAction('sb-choose-directory', options.chooseProject));
  $('#sb-empty-choose').addEventListener('click', () => void runAction('sb-empty-choose', options.chooseProject));
  $('#sb-choose-another').addEventListener('click', () => void runAction('sb-choose-another', options.chooseProject));
  $('#sb-open-readonly').addEventListener('click', () => void runAction('sb-open-readonly', options.openDeveloperMode));
  $('#sb-connect-codex').addEventListener('click', () => void runAction('sb-connect-codex', refreshCodexOnboarding));
  $('#sb-open-terminal').addEventListener('click', () => void runAction('sb-open-terminal', options.openTerminal));
  $('#sb-new-task').addEventListener('click', () => void runAction('sb-new-task', beginNewTask));
  $('#sb-start').addEventListener('click', () => void runAction('sb-start', startTask));
  $('#sb-keep').addEventListener('click', () => void runAction('sb-keep', keepChanges));
  $('#sb-discard').addEventListener('click', () => void runAction('sb-discard', discardTask));
  $('#sb-undo').addEventListener('click', () => void runAction('sb-undo', undoUpdate));
  $('#sb-cancel').addEventListener('click', () => void runAction('sb-cancel', async () => { if (sb.run) await window.wardenDesk.runs.cancel(sb.run.id); }));
  $('#sb-open-project').addEventListener('click', () => void runAction('sb-open-project', startAnotherTask));
  $('#sb-ask-changes').addEventListener('click', () => { const box = $<HTMLTextAreaElement>('#sb-followup'); box.toggleAttribute('hidden', false); $('#sb-send-followup').toggleAttribute('hidden', false); box.focus(); });
  $('#sb-send-followup').addEventListener('click', () => void runAction('sb-send-followup', askForChanges));
  $('#sb-approve-once').addEventListener('click', () => void runAction('sb-approve-once', () => respondToApproval('approve')));
  $('#sb-deny').addEventListener('click', () => void runAction('sb-deny', () => respondToApproval('deny')));
  $('#sb-approve-details').addEventListener('click', () => { sb.technicalOpen = true; if (sb.run) renderTechnical(sb.run); });
  $('#sb-technical-toggle').addEventListener('click', () => { sb.technicalOpen = !sb.technicalOpen; if (sb.run) renderTechnical(sb.run); });
  $('#sb-handoff').addEventListener('click', () => void runAction('sb-handoff', prepareHandoff));
  $('#sb-save-proof').addEventListener('click', () => void runAction('sb-save-proof', saveProof));
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-sb-tab]')) button.addEventListener('click', () => { const tab = button.dataset.sbTab; document.querySelectorAll('[data-sb-tab]').forEach((item) => item.classList.toggle('active', item === button)); for (const panelId of ['summary', 'changed', 'checks', 'history']) $(`#sb-tab-${panelId}`).toggleAttribute('hidden', panelId !== tab); });
  await loadProject(options.projects.find((project) => project.id === options.activeProjectId));
}

export async function syncSimpleBuild(projects: ProjectWorkspace[], activeProjectId?: string): Promise<void> {
  sb.projects = projects; const project = projects.find((item) => item.id === activeProjectId);
  if (project?.id === sb.activeProject?.id) { sb.activeProject = project; renderProjectList(); return; }
  await loadProject(project);
}

export function onSimpleBuildRunsChanged(run: WardenRun): void {
  if (run.projectId !== sb.activeProject?.id && run.id !== sb.run?.id) return;
  sb.runs = [run, ...sb.runs.filter((item) => item.id !== run.id)]; renderRunList();
  const active = ['starting', 'running', 'waiting_approval'].includes(run.status);
  if (!sb.run || run.id === sb.run.id || active) { sb.run = run; setPanel('sb-progress', true); renderProgress(run); }
}
