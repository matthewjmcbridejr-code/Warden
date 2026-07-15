import type { InterfaceMode, ProviderAuthReport, ProjectWorkspace, WardenRun } from '../shared/types';
import { providerOnboardingCopy, translateApproval, translateEvent } from './copy';

const $ = <T extends Element = HTMLElement>(selector: string): T => { const element = document.querySelector<T>(selector); if (!element) throw new Error(`Missing element: ${selector}`); return element; };
type SimpleBuildOptions = {
  projects: ProjectWorkspace[];
  activeProjectId?: string;
  activateProject(id: string): Promise<void>;
  chooseProject(): Promise<void>;
  openDeveloperMode(): Promise<void>;
  activateRun(run?: WardenRun, project?: ProjectWorkspace): void;
  notify(message?: string): void;
};

const sb = {
  mode: 'simple' as InterfaceMode,
  projects: [] as ProjectWorkspace[],
  activeProject: undefined as ProjectWorkspace | undefined,
  codexAuth: undefined as ProviderAuthReport | undefined,
  run: undefined as WardenRun | undefined,
  technicalOpen: false,
  options: undefined as SimpleBuildOptions | undefined,
};

function setPanel(id: 'sb-readonly' | 'sb-onboarding' | 'sb-composer' | 'sb-progress', visible: boolean): void { $(`#${id}`).toggleAttribute('hidden', !visible); }
function hideAllPanels(): void { for (const id of ['sb-readonly', 'sb-onboarding', 'sb-composer', 'sb-progress'] as const) setPanel(id, false); }
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

async function loadProject(project?: ProjectWorkspace): Promise<void> {
  sb.activeProject = project; sb.run = undefined; renderProjectList(); hideAllPanels(); showError();
  if (!project) return;
  const runs = await window.wardenDesk.runs.list(project.id);
  sb.run = runs.find((run) => run.id === project.activeRunId) || runs[0];
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
  const list = $('#sb-progress-list'); list.replaceChildren();
  const seen = new Set<string>();
  for (const event of run.events) { const line = translateEvent(event); if (seen.has(line) && event.type !== 'command.completed') continue; seen.add(line); const row = document.createElement('div'); row.className = 'sb-step'; row.textContent = line; list.append(row); }
  if (run.error) { const row = document.createElement('div'); row.className = 'sb-step sb-step-error'; row.textContent = `Something went wrong: ${run.error}`; list.append(row); }
  if (run.safeWorkspace?.conflictDetail) { const row = document.createElement('div'); row.className = 'sb-step sb-step-error'; row.textContent = run.safeWorkspace.conflictDetail; list.append(row); }

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
  $('#sb-tab-summary').textContent = statusMessage || run.evidence.finalMessage || (run.status === 'running' || run.status === 'starting' ? 'Working…' : 'No summary yet.');
  const changed = $('#sb-tab-changed'); changed.replaceChildren();
  if (!run.evidence.changedFiles.length) changed.textContent = 'No files changed yet.';
  else for (const file of run.evidence.changedFiles) { const row = document.createElement('div'); row.textContent = file; changed.append(row); }
  const checks = $('#sb-tab-checks'); checks.replaceChildren();
  if (!run.evidence.tests.length) checks.textContent = 'No checks recorded for this task.';
  else for (const test of run.evidence.tests) { const row = document.createElement('div'); row.textContent = `${test.exitCode === 0 ? '✓' : '✗'} ${test.command}`; checks.append(row); }
  const history = $('#sb-tab-history'); history.replaceChildren();
  const steps: string[] = ['Started with Codex'];
  const approved = run.approvals.filter((item) => item.status === 'approved').length;
  if (approved) steps.push(`Approved ${approved} request(s)`);
  if (run.safeWorkspace?.status === 'kept') steps.push(`Kept changes${run.safeWorkspace.consolidatedCommit ? ` · ${run.safeWorkspace.consolidatedCommit.slice(0, 8)}` : ''}`);
  if (run.safeWorkspace?.status === 'undone') steps.push(`Undid update${run.safeWorkspace.undoCommit ? ` · ${run.safeWorkspace.undoCommit.slice(0, 8)}` : ''}`);
  if (run.safeWorkspace?.status === 'discarded') steps.push('Discarded safe workspace');
  steps.push(`Last updated ${new Date(run.updatedAt).toLocaleTimeString()}`);
  for (const step of steps) { const row = document.createElement('div'); row.textContent = step; history.append(row); }
}

async function startTask(): Promise<void> {
  const prompt = $<HTMLTextAreaElement>('#sb-task').value.trim(); const project = sb.activeProject;
  if (!project || !prompt) throw new Error('Choose a project and describe what you want Warden to build.');
  if (sb.codexAuth?.state !== 'subscription_authenticated') throw new Error(sb.codexAuth?.detail || 'Codex subscription authentication is not ready.');
  const run = await window.wardenDesk.runs.start({ provider: 'codex', prompt, cwd: project.cwd, projectId: project.id, attachContext: true, authSource: 'subscription', safe: true });
  sb.run = run; sb.activeProject = await window.wardenDesk.project.update(project.id, { activeRunId: run.id });
  sb.options?.activateRun(run, sb.activeProject);
  $<HTMLTextAreaElement>('#sb-task').value = ''; setPanel('sb-composer', false); setPanel('sb-progress', true); renderProgress(run);
}
async function keepChanges(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.keep(sb.run.id); renderProgress(sb.run); }
async function discardTask(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.discard(sb.run.id); renderProgress(sb.run); }
async function undoUpdate(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.undoUpdate(sb.run.id); renderProgress(sb.run); }
async function startAnotherTask(): Promise<void> { if (!sb.activeProject) return; sb.activeProject = await window.wardenDesk.project.update(sb.activeProject.id, { activeRunId: undefined }); sb.run = undefined; sb.options?.activateRun(undefined, sb.activeProject); await refreshCodexOnboarding(); }
async function askForChanges(): Promise<void> { if (!sb.run) return; const box = $<HTMLTextAreaElement>('#sb-followup'); const prompt = box.value.trim(); if (!prompt) throw new Error('Describe the changes you want Codex to make.'); sb.run = await window.wardenDesk.runs.resume(sb.run.id, prompt); box.value = ''; renderProgress(sb.run); }
async function respondToApproval(decision: 'approve' | 'deny'): Promise<void> { const approval = sb.run?.approvals.find((item) => item.status === 'pending'); if (!sb.run || !approval) return; await window.wardenDesk.runs.approve(sb.run.id, approval.id, decision, 'once'); }

export async function initSimpleBuild(options: SimpleBuildOptions): Promise<void> {
  sb.options = options; sb.projects = options.projects; renderProjectList();
  $('#sb-choose-directory').addEventListener('click', () => void runAction('sb-choose-directory', options.chooseProject));
  $('#sb-choose-another').addEventListener('click', () => void runAction('sb-choose-another', options.chooseProject));
  $('#sb-open-readonly').addEventListener('click', () => void runAction('sb-open-readonly', options.openDeveloperMode));
  $('#sb-connect-codex').addEventListener('click', () => void runAction('sb-connect-codex', refreshCodexOnboarding));
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
  const active = ['starting', 'running', 'waiting_approval'].includes(run.status);
  if (!sb.run || run.id === sb.run.id || active) { sb.run = run; setPanel('sb-progress', true); renderProgress(run); }
}
