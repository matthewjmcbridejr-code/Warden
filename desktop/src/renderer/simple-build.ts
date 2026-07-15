import type { InterfaceMode, ProviderAuthReport, ProjectWorkspace, WardenRun } from '../shared/types';
import { providerOnboardingCopy, translateApproval, translateEvent } from './copy';

const $ = <T extends Element = HTMLElement>(selector: string): T => { const element = document.querySelector<T>(selector); if (!element) throw new Error(`Missing element: ${selector}`); return element; };

const sb = { mode: 'simple' as InterfaceMode, projects: [] as ProjectWorkspace[], activeCwd: '', codexAuth: undefined as ProviderAuthReport | undefined, run: undefined as WardenRun | undefined, technicalOpen: false };

function setPanel(id: 'sb-readonly' | 'sb-onboarding' | 'sb-composer' | 'sb-progress', visible: boolean): void { $(`#${id}`).toggleAttribute('hidden', !visible); }
function hideAllPanels(): void { for (const id of ['sb-readonly', 'sb-onboarding', 'sb-composer', 'sb-progress'] as const) setPanel(id, false); }

export function isSimpleBuildActive(): boolean { return sb.mode === 'simple'; }
export function setMode(mode: InterfaceMode): void { sb.mode = mode; }

export function renderProjectList(): void {
  const root = $('#sb-project-list'); root.replaceChildren();
  for (const project of sb.projects) { const button = document.createElement('button'); button.textContent = project.name; button.classList.toggle('active', project.cwd === sb.activeCwd); button.addEventListener('click', () => void selectSimpleProject(project.cwd)); root.append(button); }
}

async function selectSimpleProject(cwd: string): Promise<void> {
  sb.activeCwd = cwd; sb.run = undefined; renderProjectList(); hideAllPanels();
  const status = await window.wardenDesk.runs.checkProject(cwd);
  if (!status.isGit || !status.clean) { setPanel('sb-readonly', true); return; }
  await refreshCodexOnboarding();
}

async function refreshCodexOnboarding(): Promise<void> {
  const reports = await window.wardenDesk.runs.providers();
  sb.codexAuth = reports.find((report) => report.provider === 'codex');
  const copy = providerOnboardingCopy('codex', sb.codexAuth);
  if (copy.action === 'ready') {
    setPanel('sb-composer', true);
    $('#sb-provider-line').textContent = copy.headline;
    ($('#sb-start') as HTMLButtonElement).disabled = false;
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
  if (run.status === 'failed' && run.error) { const row = document.createElement('div'); row.className = 'sb-step'; row.textContent = `Something went wrong: ${run.error}`; list.append(row); }

  const pendingApproval = run.approvals.find((item) => item.status === 'pending');
  $('#sb-approval').toggleAttribute('hidden', !pendingApproval);
  if (pendingApproval) { const copy = translateApproval(pendingApproval); $('#sb-approval-title').textContent = copy.title; $('#sb-approval-why').textContent = copy.why ? `Why: ${copy.why}` : ''; }

  const finished = ['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status);
  const kept = run.safeWorkspace?.status === 'kept';
  $('#sb-followup').toggleAttribute('hidden', !finished || kept);
  $('#sb-pre-actions').toggleAttribute('hidden', kept || !finished);
  $('#sb-post-actions').toggleAttribute('hidden', !kept);
  renderTechnical(run);
  renderResultTabs(run);
}

function renderTechnical(run: WardenRun): void { const pre = $('#sb-technical'); pre.toggleAttribute('hidden', !sb.technicalOpen); if (sb.technicalOpen) pre.textContent = JSON.stringify(run.events.slice(-40), null, 2); }

function renderResultTabs(run: WardenRun): void {
  $('#sb-tab-summary').textContent = run.evidence.finalMessage || (run.status === 'running' || run.status === 'starting' ? 'Working…' : 'No summary yet.');
  const changed = $('#sb-tab-changed'); changed.replaceChildren();
  if (!run.evidence.changedFiles.length) changed.textContent = 'No files changed yet.';
  else for (const file of run.evidence.changedFiles) { const row = document.createElement('div'); row.textContent = file; changed.append(row); }
  const checks = $('#sb-tab-checks'); checks.replaceChildren();
  if (!run.evidence.tests.length) checks.textContent = 'No checks recorded for this task.';
  else for (const test of run.evidence.tests) { const row = document.createElement('div'); row.textContent = `${test.exitCode === 0 ? '✓' : '✗'} ${test.command}`; checks.append(row); }
  const history = $('#sb-tab-history'); history.replaceChildren();
  const steps: string[] = [`Started with Codex`];
  if (run.approvals.some((item) => item.status === 'approved')) steps.push(`Approved ${run.approvals.filter((item) => item.status === 'approved').length} request(s)`);
  if (run.safeWorkspace?.status === 'kept') steps.push('Kept changes');
  if (run.safeWorkspace?.status === 'discarded') steps.push('Discarded');
  steps.push(`Last updated ${new Date(run.updatedAt).toLocaleTimeString()}`);
  for (const step of steps) { const row = document.createElement('div'); row.textContent = step; history.append(row); }
}

async function startTask(): Promise<void> {
  const prompt = ($('#sb-task') as HTMLTextAreaElement).value.trim();
  if (!sb.activeCwd || !prompt) return;
  if (sb.codexAuth?.state !== 'subscription_authenticated') return;
  const run = await window.wardenDesk.runs.start({ provider: 'codex', prompt, cwd: sb.activeCwd, attachContext: true, authSource: 'subscription', safe: true });
  sb.run = run; setPanel('sb-composer', false); setPanel('sb-progress', true); renderProgress(run);
}

async function keepChanges(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.keep(sb.run.id); renderProgress(sb.run); }
async function discardTask(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.discard(sb.run.id); hideAllPanels(); await refreshCodexOnboarding(); }
async function undoUpdate(): Promise<void> { if (!sb.run) return; sb.run = await window.wardenDesk.runs.undoUpdate(sb.run.id); hideAllPanels(); await refreshCodexOnboarding(); }
async function askForChanges(): Promise<void> { if (!sb.run) return; const prompt = ($('#sb-followup') as HTMLTextAreaElement).value.trim(); if (!prompt) return; sb.run = await window.wardenDesk.runs.resume(sb.run.id, prompt); ($('#sb-followup') as HTMLTextAreaElement).value = ''; renderProgress(sb.run); }

export async function initSimpleBuild(projects: ProjectWorkspace[]): Promise<void> {
  sb.projects = projects; renderProjectList();
  $('#sb-choose-directory').addEventListener('click', async () => { const cwd = await window.wardenDesk.terminal.chooseDirectory(); if (!cwd) return; const project = await window.wardenDesk.project.create({ cwd }); sb.projects = await window.wardenDesk.project.list(); renderProjectList(); await selectSimpleProject(project.cwd); });
  $('#sb-choose-another').addEventListener('click', () => void $('#sb-choose-directory').dispatchEvent(new Event('click')));
  $('#sb-open-readonly').addEventListener('click', () => { hideAllPanels(); });
  $('#sb-connect-codex').addEventListener('click', () => void refreshCodexOnboarding());
  $('#sb-start').addEventListener('click', () => void startTask());
  $('#sb-keep').addEventListener('click', () => void keepChanges());
  $('#sb-discard').addEventListener('click', () => void discardTask());
  $('#sb-undo').addEventListener('click', () => void undoUpdate());
  $('#sb-open-project').addEventListener('click', () => { hideAllPanels(); void refreshCodexOnboarding(); });
  $('#sb-ask-changes').addEventListener('click', () => { const box = $('#sb-followup') as HTMLTextAreaElement; box.toggleAttribute('hidden', false); box.focus(); });
  $('#sb-technical-toggle').addEventListener('click', () => { sb.technicalOpen = !sb.technicalOpen; if (sb.run) renderTechnical(sb.run); });
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-sb-tab]')) button.addEventListener('click', () => { const tab = button.dataset.sbTab; document.querySelectorAll('[data-sb-tab]').forEach((item) => item.classList.toggle('active', item === button)); for (const panelId of ['summary', 'changed', 'checks', 'history']) $(`#sb-tab-${panelId}`).toggleAttribute('hidden', panelId !== tab); });
}

export function onSimpleBuildRunsChanged(run: WardenRun): void { if (sb.run && run.id === sb.run.id) { sb.run = run; renderProgress(run); } }
