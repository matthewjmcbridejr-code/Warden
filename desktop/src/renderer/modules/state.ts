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
} from '../../shared/types';

export const $ = <T extends Element = HTMLElement>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
};

export type ViewId = 'home' | 'needs-you' | 'mission' | 'connected-ais' | 'advanced';

export interface UiTerminal {
  metadata: TerminalMetadata;
  terminal: Terminal;
  fit: FitAddon;
  lineBuffer: string;
}

export interface MissionWorkItem {
  id: string;
  type: 'browser' | 'terminal' | 'build' | 'verify' | 'proof';
  title: string;
  subtitle: string;
  status: 'working' | 'needs_user' | 'completed' | 'failed' | 'idle';
  meta?: any;
}

export interface ActiveMissionData {
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

export const ui = {
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

export function notice(message?: string): void {
  const element = $('#notice');
  element.textContent = message || '';
  element.toggleAttribute('hidden', !message);
  if (message) setTimeout(() => element.setAttribute('hidden', 'true'), 6000);
}

export function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
