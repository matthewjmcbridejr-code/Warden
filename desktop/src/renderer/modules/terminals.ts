import { renderProjectsTree, selectNav, selectContextTab } from './nav';
import { renderHomeScreen } from './home';
import { openMission } from './mission';
import { resolveAttentionItem } from './needs-you';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { $, ui, type UiTerminal } from './state';
import type { TerminalMetadata } from '../../shared/types';

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

export function fitActiveTerminal(): void {
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