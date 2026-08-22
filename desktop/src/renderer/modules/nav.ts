import { $, ui, escapeHtml, type ViewId } from './state';
import { renderHomeScreen } from './home';
import { renderNeedsYouScreen } from './needs-you';
import { renderActiveMission, openMission } from './mission';
import { renderConnectedAisScreen } from './connected-ais';
import { renderAdvancedScreen } from './connected-ais';
import { fitActiveTerminal } from './terminals';
import { providerBounds } from './util';

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

export function selectContextTab(tab: 'browser' | 'build' | 'terminal' | 'verify' | 'proof'): void {
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

export function selectAdvTab(tab: 'terminals' | 'build-runner' | 'telemetry' | 'brain'): void {
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

export async function activateProject(projectId: string): Promise<void> {
  const p = await window.wardenDesk.project.activate(projectId);
  ui.activeProjectId = p.id;
  renderProjectsTree();
}

export function renderProjectsTree(): void {
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
