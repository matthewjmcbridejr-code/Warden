import { randomUUID } from 'node:crypto';
import { basename } from 'node:path';
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { BrowserProfile, DesktopState, InterfaceMode, ProjectWorkspace, ProviderId, TerminalMetadata, WebPlatform, WorkspaceId } from '../shared/types';
import { createPlatform, presetInput } from './web-platforms';

const createdAt = new Date(0).toISOString();
const personalProfile: BrowserProfile = { id: 'profile-personal', name: 'Personal', createdAt };
function defaultPlatforms(): WebPlatform[] { return ['claude', 'chatgpt', 'gemini', 'grok'].map((key, order) => createPlatform({ ...presetInput(key), id: `platform-${key}`, browserProfileId: personalProfile.id, order }, [personalProfile], order)); }
const defaults: DesktopState = { version: 2, onboardingComplete: false, mode: 'simple', workspace: 'chat', selectedProvider: 'claude', selectedPlatformId: 'platform-claude', recentProjects: [], projects: [], browserProfiles: [personalProfile], platforms: defaultPlatforms(), removedPlatforms: [], terminals: [], windowBounds: { width: 1440, height: 920 } };
function isProvider(value: unknown): value is ProviderId { return ['claude', 'chatgpt', 'gemini', 'grok'].includes(String(value)); }
function isWorkspace(value: unknown): value is WorkspaceId { return value === 'chat' || value === 'build'; }
function isMode(value: unknown): value is InterfaceMode { return value === 'simple' || value === 'developer'; }
function cleanTerminal(value: unknown): TerminalMetadata | null { if (!value || typeof value !== 'object') return null; const item = value as Partial<TerminalMetadata>; if (typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.cwd !== 'string') return null; return { id: item.id, name: item.name.slice(0, 60), cwd: item.cwd, status: 'stopped', history: Array.isArray(item.history) ? item.history.filter((x): x is string => typeof x === 'string').slice(-200) : [] }; }
function cleanProfile(value: unknown): BrowserProfile | null { if (!value || typeof value !== 'object') return null; const item = value as Partial<BrowserProfile>; if (typeof item.id !== 'string' || !/^profile-[\w-]{1,100}$/.test(item.id) || typeof item.name !== 'string') return null; return { id: item.id, name: item.name.trim().slice(0, 60) || 'Profile', createdAt: typeof item.createdAt === 'string' ? item.createdAt : new Date().toISOString() }; }

export class StateStore {
  readonly file: string; state: DesktopState = structuredClone(defaults); warning?: string;
  constructor(userData: string) { this.file = join(userData, 'desktop-state.json'); this.load(); }
  private load(): void {
    if (!existsSync(this.file)) return;
    try {
      const raw = JSON.parse(readFileSync(this.file, 'utf8')) as Record<string, unknown>;
      const browserProfiles = Array.isArray(raw.browserProfiles) ? raw.browserProfiles.map(cleanProfile).filter((item): item is BrowserProfile => Boolean(item)) : [personalProfile];
      if (!browserProfiles.length) browserProfiles.push(personalProfile);
      const platformWarnings: string[] = [];
      const cleanPlatforms = (values: unknown, label: string): WebPlatform[] => Array.isArray(values) ? values.flatMap((value, index) => { try { if (!value || typeof value !== 'object') throw new Error('not an object'); return [createPlatform(value as Partial<WebPlatform> & { name: string; startUrl: string }, browserProfiles, index, process.env.NODE_ENV === 'development')]; } catch (error) { platformWarnings.push(`Skipped invalid ${label} ${index + 1}: ${error instanceof Error ? error.message : String(error)}`); return []; } }) : [];
      const platforms = Array.isArray(raw.platforms) ? cleanPlatforms(raw.platforms, 'platform') : defaultPlatforms(); const removedPlatforms = cleanPlatforms(raw.removedPlatforms, 'removed platform');
      const terminals = Array.isArray(raw.terminals) ? raw.terminals.map(cleanTerminal).filter((item): item is TerminalMetadata => Boolean(item)) : [];
      const recentProjects = Array.isArray(raw.recentProjects) ? raw.recentProjects.filter((x): x is string => typeof x === 'string').slice(0, 20) : [];
      const projects: ProjectWorkspace[] = Array.isArray(raw.projects) ? raw.projects.flatMap((value) => this.cleanProject(value, browserProfiles, platforms)) : recentProjects.map((cwd, index) => this.makeProject(cwd, browserProfiles[0].id, terminals, index));
      const selectedProvider = isProvider(raw.selectedProvider) ? raw.selectedProvider : 'claude';
      const legacySelected = `platform-${selectedProvider}`;
      const selectedPlatformId = typeof raw.selectedPlatformId === 'string' && platforms.some((item) => item.id === raw.selectedPlatformId) ? raw.selectedPlatformId : platforms.find((item) => item.id === legacySelected)?.id || platforms[0]?.id;
      const activeProjectId = typeof raw.activeProjectId === 'string' && projects.some((item) => item.id === raw.activeProjectId) ? raw.activeProjectId : projects[0]?.id;
      this.state = { version: 2, onboardingComplete: raw.onboardingComplete === true, mode: isMode(raw.mode) ? raw.mode : 'simple', workspace: isWorkspace(raw.workspace) ? raw.workspace : 'chat', selectedProvider, selectedPlatformId, activeProjectId, recentProjects, projects, browserProfiles, platforms, removedPlatforms, terminals, windowBounds: { ...defaults.windowBounds, ...((raw.windowBounds && typeof raw.windowBounds === 'object') ? raw.windowBounds : {}) } };
      if (platformWarnings.length) this.warning = `Recovered desktop state with warnings. ${platformWarnings.join(' ')}`;
    } catch (error) {
      const backup = `${this.file}.corrupt-${Date.now()}`; try { copyFileSync(this.file, backup); } catch { /* best effort */ }
      this.warning = `Desktop state was corrupt and reset. A diagnostic copy was saved to ${backup}.`;
      this.state = structuredClone(defaults);
    }
  }
  private makeProject(cwd: string, browserProfileId: string, terminals: TerminalMetadata[], index = 0): ProjectWorkspace { const safe = basename(cwd) || `Project ${index + 1}`; return { id: `project-${randomUUID()}`, name: safe, cwd, browserProfileId, selectedPlatformId: this.state.selectedPlatformId || 'platform-claude', workspace: 'build', executionMode: 'local', terminalIds: terminals.filter((terminal) => terminal.cwd === cwd).map((terminal) => terminal.id), updatedAt: new Date().toISOString() }; }
  private cleanProject(value: unknown, profiles: BrowserProfile[], platforms: WebPlatform[]): ProjectWorkspace[] { if (!value || typeof value !== 'object') return []; const item = value as Partial<ProjectWorkspace>; if (typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.cwd !== 'string') return []; return [{ id: item.id, name: item.name.slice(0, 100), cwd: item.cwd, branch: typeof item.branch === 'string' ? item.branch : undefined, browserProfileId: profiles.some((profile) => profile.id === item.browserProfileId) ? item.browserProfileId! : profiles[0].id, selectedPlatformId: platforms.some((platform) => platform.id === item.selectedPlatformId) ? item.selectedPlatformId : platforms[0]?.id, splitPlatformId: platforms.some((platform) => platform.id === item.splitPlatformId) ? item.splitPlatformId : undefined, workspace: isWorkspace(item.workspace) ? item.workspace : 'build', executionMode: ['local', 'codex', 'claude', 'gemini', 'grok'].includes(String(item.executionMode)) ? item.executionMode! : 'local', terminalIds: Array.isArray(item.terminalIds) ? item.terminalIds.filter((id): id is string => typeof id === 'string') : [], activeRunId: typeof item.activeRunId === 'string' ? item.activeRunId : undefined, updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt : new Date().toISOString() }]; }
  save(): void { mkdirSync(dirname(this.file), { recursive: true }); const temp = `${this.file}.tmp`; writeFileSync(temp, JSON.stringify(this.state, null, 2), { mode: 0o600 }); renameSync(temp, this.file); }
  patch(patch: Partial<DesktopState>): DesktopState { this.state = { ...this.state, ...patch, version: 2 }; this.save(); return this.state; }
  upsertTerminal(terminal: TerminalMetadata): void { const terminals = this.state.terminals.filter((item) => item.id !== terminal.id); terminals.push({ ...terminal, history: terminal.history.slice(-200) }); const projects = this.state.projects.map((project) => project.cwd === terminal.cwd ? { ...project, terminalIds: [...new Set([...project.terminalIds, terminal.id])], updatedAt: new Date().toISOString() } : project); this.patch({ terminals, projects }); }
  createPlatform(input: Partial<WebPlatform> & { name: string; startUrl: string }): WebPlatform { const platform = createPlatform(input, this.state.browserProfiles, this.state.platforms.length, process.env.NODE_ENV === 'development'); this.patch({ platforms: [...this.state.platforms, platform], selectedPlatformId: platform.id }); return platform; }
  updatePlatform(id: string, patch: Partial<WebPlatform>): WebPlatform { const current = this.state.platforms.find((item) => item.id === id); if (!current) throw new Error('Platform not found.'); const updated = createPlatform({ ...current, ...patch, id, createdAt: current.createdAt }, this.state.browserProfiles, current.order, process.env.NODE_ENV === 'development'); this.patch({ platforms: this.state.platforms.map((item) => item.id === id ? updated : item) }); return updated; }
  removePlatform(id: string): void { const removed = this.state.platforms.find((item) => item.id === id); if (!removed) throw new Error('Platform not found.'); const platforms = this.state.platforms.filter((item) => item.id !== id); const projects = this.state.projects.map((project) => ({ ...project, selectedPlatformId: project.selectedPlatformId === id ? platforms[0]?.id : project.selectedPlatformId, splitPlatformId: project.splitPlatformId === id ? undefined : project.splitPlatformId })); this.patch({ platforms, removedPlatforms: [removed, ...this.state.removedPlatforms.filter((item) => item.id !== id)], projects, selectedPlatformId: this.state.selectedPlatformId === id ? platforms[0]?.id : this.state.selectedPlatformId }); }
  restorePlatform(id: string): WebPlatform { const removed = this.state.removedPlatforms.find((item) => item.id === id); if (!removed) throw new Error('Removed platform not found.'); const restored = createPlatform({ ...removed, id: removed.id }, this.state.browserProfiles, this.state.platforms.length, process.env.NODE_ENV === 'development'); this.patch({ platforms: [...this.state.platforms, restored], removedPlatforms: this.state.removedPlatforms.filter((item) => item.id !== id), selectedPlatformId: restored.id }); return restored; }
  createProfile(name: string): BrowserProfile { const clean = String(name || '').trim().slice(0, 60); if (!clean) throw new Error('A browser profile name is required.'); const profile = { id: `profile-${randomUUID()}`, name: clean, createdAt: new Date().toISOString() }; this.patch({ browserProfiles: [...this.state.browserProfiles, profile] }); return profile; }
  renameProfile(id: string, name: string): BrowserProfile { const profile = this.state.browserProfiles.find((item) => item.id === id); if (!profile) throw new Error('Browser profile not found.'); const clean = String(name || '').trim().slice(0, 60); if (!clean) throw new Error('A browser profile name is required.'); const updated = { ...profile, name: clean }; this.patch({ browserProfiles: this.state.browserProfiles.map((item) => item.id === id ? updated : item) }); return updated; }
  removeProfile(id: string): void { if (this.state.browserProfiles.length <= 1) throw new Error('At least one browser profile is required.'); if (this.state.platforms.some((item) => item.browserProfileId === id) || this.state.projects.some((item) => item.browserProfileId === id)) throw new Error('Move platforms and projects to another profile before removing this profile. Browser data is not deleted.'); this.patch({ browserProfiles: this.state.browserProfiles.filter((item) => item.id !== id) }); }
  createProject(cwd: string, name?: string, browserProfileId?: string): ProjectWorkspace { const existing = this.state.projects.find((project) => project.cwd === cwd); if (existing) return this.activateProject(existing.id); const profile = this.state.browserProfiles.find((item) => item.id === browserProfileId) || this.state.browserProfiles[0]; const project = { ...this.makeProject(cwd, profile.id, this.state.terminals), name: String(name || basename(cwd) || 'Project').trim().slice(0, 100) }; this.patch({ projects: [project, ...this.state.projects], activeProjectId: project.id, recentProjects: [cwd, ...this.state.recentProjects.filter((item) => item !== cwd)].slice(0, 20) }); return project; }
  preparePlayground(playgroundsDir: string): { cwd: string; name: string; filesToCommit: string[] } {
    mkdirSync(playgroundsDir, { recursive: true });
    let count = 1;
    let cwd = join(playgroundsDir, `playground-${count}`);
    while (existsSync(cwd)) {
      count++;
      cwd = join(playgroundsDir, `playground-${count}`);
    }
    mkdirSync(cwd, { recursive: true });
    writeFileSync(join(cwd, 'README.md'), `# Playground ${count}\n\nWelcome to Warden AI Desk! This safe local playground is ready for your AI missions.\n`);
    writeFileSync(join(cwd, 'WELCOME.md'), `# Welcome Mission\n\nWelcome to Warden AI Desk! Try editing this file or adding a feature in Simple Mode.\n`);
    writeFileSync(join(cwd, '.gitignore'), ".env\n.env.*\n!.env.*.example\nnode_modules/\n");
    return { cwd, name: `Playground ${count}`, filesToCommit: ['.gitignore', 'README.md', 'WELCOME.md'] };
  }
  activateProject(id: string): ProjectWorkspace { const project = this.state.projects.find((item) => item.id === id); if (!project) throw new Error('Project not found.'); this.patch({ activeProjectId: id, workspace: project.workspace, selectedPlatformId: project.selectedPlatformId, recentProjects: [project.cwd, ...this.state.recentProjects.filter((item) => item !== project.cwd)].slice(0, 20) }); return project; }

  updateProject(id: string, patch: Partial<ProjectWorkspace>): ProjectWorkspace { const current = this.state.projects.find((item) => item.id === id); if (!current) throw new Error('Project not found.'); const updated = this.cleanProject({ ...current, ...patch, id, cwd: current.cwd }, this.state.browserProfiles, this.state.platforms)[0]; if (!updated) throw new Error('Invalid project update.'); updated.updatedAt = new Date().toISOString(); this.patch({ projects: this.state.projects.map((item) => item.id === id ? updated : item) }); return updated; }
}
