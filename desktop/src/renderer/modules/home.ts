import { $, ui, escapeHtml } from './state';
import { selectNav } from './nav';
import { MISSION_TEMPLATES } from '../simple-build';
import { startMissionFromPrompt } from './mission';

export function renderHomeScreen(): void {
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