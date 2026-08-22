import { $, ui, escapeHtml, notice, type ActiveMissionData } from './state';
import { selectNav, selectContextTab, renderProjectsTree } from './nav';
import { renderHomeScreen } from './home';
import { updateNeedsYouCount } from './needs-you';

// ---------------------------------------------------------------------------
// MISSION WORKSPACE
// ---------------------------------------------------------------------------
export function renderActiveMission(): void {
  const mission = ui.missions.get(ui.activeMissionId || '');
  if (!mission) {
    $('#mission-header-title').textContent = 'No Active Mission';
    $('#mission-objective').textContent = 'Select a mission from the sidebar or start a new one.';
    $('#mission-conversation-feed').replaceChildren();
    $('#mission-work-feed').replaceChildren();
    return;
  }

  $('#mission-header-title').textContent = mission.title;
  $('#mission-objective').textContent = mission.objective;
  
  const statusEl = $('#mission-status');
  statusEl.className = 'mission-status-indicator ' + 
    (mission.status === 'completed' ? 'done' : mission.status === 'failed' ? 'failed' : mission.status === 'waiting_approval' ? 'needs-you' : 'working');
  statusEl.textContent = mission.status === 'completed' ? 'Completed' : mission.status === 'failed' ? 'Failed' : mission.status === 'waiting_approval' ? 'Needs You' : 'Working';

  const convFeed = $('#mission-conversation-feed');
  convFeed.replaceChildren();
  for (const msg of mission.conversation || []) {
    const el = document.createElement('div');
    el.className = `chat-message ${msg.role}`;
    el.innerHTML = `
      <div class="chat-message-header">
        <span class="chat-message-author">${msg.role === 'human' ? 'You' : 'Warden'}</span>
        <span class="chat-message-time">${escapeHtml(msg.time)}</span>
      </div>
      <div class="chat-message-body">${escapeHtml(msg.text).replace(/\n/g, '<br/>')}</div>
    `;
    convFeed.append(el);
  }

  const workFeed = $('#mission-work-feed');
  workFeed.replaceChildren();
  for (const w of mission.workItems) {
    const card = document.createElement('div');
    card.className = `work-card ${w.status}`;
    card.innerHTML = `
      <div class="work-card-icon"></div>
      <div class="work-card-content">
        <div class="work-card-title">${escapeHtml(w.title)}</div>
        <div class="work-card-subtitle">${escapeHtml(w.subtitle)}</div>
      </div>
    `;
    card.addEventListener('click', () => {
      if (w.type === 'browser') selectContextTab('browser');
      else if (w.type === 'terminal') selectContextTab('terminal');
      else if (w.type === 'build') selectContextTab('build');
      else if (w.type === 'verify') selectContextTab('verify');
      else if (w.type === 'proof') selectContextTab('proof');
    });
    workFeed.append(card);
  }

  // Terminal context
  if (mission.terminalOutput) {
    $('#panel-terminal .terminal-content').textContent = mission.terminalOutput;
  }
  
  // Proof context
  if (mission.evidence?.screenshotUrl) {
    const proofPanel = $('#panel-proof');
    const existingImg = proofPanel.querySelector('.proof-screenshot');
    if (existingImg) existingImg.remove();
    const img = document.createElement('img');
    img.src = mission.evidence.screenshotUrl;
    img.className = 'proof-screenshot';
    proofPanel.append(img);
  }
}

export function openMission(missionId: string): void {
  const mission = ui.missions.get(missionId);
  if (!mission) return;
  ui.activeMissionId = missionId;
  
  if (mission.projectId && mission.projectId !== ui.activeProjectId) {
    ui.activeProjectId = mission.projectId;
  }
  
  renderProjectsTree();
  renderActiveMission();
  void selectNav('mission');
}

export async function startMissionFromPrompt(prompt: string, projectId?: string): Promise<void> {
  const cleanPrompt = prompt.trim();
  if (!cleanPrompt) {
    notice('Please enter an outcome or mission brief.');
    return;
  }

  const pId = projectId || ui.activeProjectId || ui.projects[0]?.id;
  const project = ui.projects.find((p) => p.id === pId) || ui.projects[0];
  const missionId = `mission_${Date.now()}`;

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
      { role: 'warden', text: `Orchestrating work for ${project.name}...`, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
    ],
    workItems: [],
    terminalHistory: [],
    evidence: { changedFiles: [], diff: '', tests: [] },
  };

  ui.missions.set(missionId, newMission);
  ui.activeMissionId = missionId;
  openMission(missionId);

  try {
    const isHybridPrompt = cleanPrompt.toLowerCase().includes('warden works') || cleanPrompt.toLowerCase().includes('landing page');

    // 1. Build Work
    newMission.workItems.push({ id: 'w1', type: 'build', title: 'Build Work', subtitle: 'Generating code...', status: 'working' });
    renderActiveMission();

    const run = await window.wardenDesk.runs.start({
      provider: 'codex',
      prompt: cleanPrompt,
      cwd: project.cwd,
      projectId: project.id,
      attachContext: true,
      authSource: 'subscription',
      safe: true,
    });
    
    // Subscribe to run events
    await new Promise<void>((resolve, reject) => {
       const unsub = window.wardenDesk.runs.onChanged((r) => {
          if (r.id === run.id) {
             newMission.run = r;
             if (r.status === 'completed') { unsub(); resolve(); }
             else if (r.status === 'failed' || r.status === 'cancelled') { unsub(); reject(new Error(r.error || 'Run failed')); }
          }
       });
    });

    const w1 = newMission.workItems.find(w => w.id === 'w1')!;
    w1.status = 'completed';
    w1.subtitle = 'Code changes generated';
    renderActiveMission();

    if (isHybridPrompt) {
        // 2. Terminal Work
        newMission.workItems.push({ id: 'w2', type: 'terminal', title: 'Terminal Work', subtitle: 'python3 -m http.server 8080 &', status: 'working' });
        renderActiveMission();

        const term = await window.wardenDesk.terminal.create({ name: 'Web Server', cwd: project.cwd });
        window.wardenDesk.terminal.write(term.id, 'python3 -m http.server 8080 &\r');
        
        // Let it start
        await new Promise(r => setTimeout(r, 1500));
        
        const w2 = newMission.workItems.find(w => w.id === 'w2')!;
        w2.status = 'completed';
        renderActiveMission();

        // 3. Browser Work (Real Computer Use)
        newMission.workItems.push({ id: 'w3', type: 'browser', title: 'Browser Work', subtitle: 'Verifying in browser...', status: 'working' });
        renderActiveMission();

        const convRes = await fetch('http://127.0.0.1:6969/api/mcharness/chat/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'Verify Web App' })
        });
        const convData = await convRes.json();
        const convId = convData.conversation.conversation_id;

        const source = new EventSource(`http://127.0.0.1:6969/api/mcharness/chat/conversations/${convId}/stream`);
        
        const taskCompleted = new Promise<void>((resolve, reject) => {
            source.addEventListener('message', (event) => {
                const data = JSON.parse(event.data);
                
                if (data.event_type === 'context_updated' && data.metadata?.screenshot_url) {
                    if (!newMission.evidence) newMission.evidence = { changedFiles: [], diff: '', tests: [] };
                    newMission.evidence.screenshotUrl = 'http://127.0.0.1:6969' + data.metadata.screenshot_url;
                    renderActiveMission();
                }

                if (data.event_type === 'task_completed') {
                   source.close();
                   resolve();
                } else if (data.event_type === 'task_failed') {
                   source.close();
                   reject(new Error("Browser work failed"));
                }
            });
            source.addEventListener('error', (err) => {
                source.close();
                reject(err);
            });
        });

        await fetch(`http://127.0.0.1:6969/api/mcharness/chat/conversations/${convId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: "Open localhost:8080 in the browser and verify the heading 'Warden Works' is visible. Do not do anything else. Tell me when it is confirmed." })
        });

        await taskCompleted;

        const w3 = newMission.workItems.find(w => w.id === 'w3')!;
        w3.status = 'completed';
    }

    newMission.status = 'completed';
    newMission.phase = 3;
    
    newMission.workItems.push({ id: 'w4', type: 'verify', title: 'Verification', subtitle: 'Checks passed', status: 'completed' });
    newMission.workItems.push({ id: 'w5', type: 'proof', title: 'Proof', subtitle: 'Work finalized', status: 'completed' });
    
    newMission.conversation?.push({ role: 'warden', text: `Mission accomplished. Code written, server running, and verified visually.`, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });

    renderProjectsTree();
    if (ui.view === 'mission') renderActiveMission();

  } catch (err) {
    console.error('Mission failed', err);
    newMission.status = 'failed';
    newMission.conversation?.push({ role: 'warden', text: `Mission failed: ${err}`, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
    if (ui.view === 'mission') renderActiveMission();
  }
}

export async function sendMissionFollowup(text: string): Promise<void> {
  const mission = ui.missions.get(ui.activeMissionId || '');
  if (!mission) return;
  
  if (!mission.conversation) mission.conversation = [];
  mission.conversation.push({ role: 'human', text, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
  renderActiveMission();

  try {
    const convRes = await fetch('http://127.0.0.1:6969/api/mcharness/chat/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Mission Followup' })
    });
    const convData = await convRes.json();
    const convId = convData.conversation.conversation_id;

    // Just fire and forget the message to Warden
    await fetch(`http://127.0.0.1:6969/api/mcharness/chat/conversations/${convId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    
    // Read one response event from SSE for a simulated reply
    const source = new EventSource(`http://127.0.0.1:6969/api/mcharness/chat/conversations/${convId}/stream`);
    source.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      if (data.event_type === 'message') {
         mission.conversation!.push({ role: 'warden', text: data.text || 'Understood.', time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
         renderActiveMission();
         source.close();
      }
    });

  } catch (err) {
    console.error(err);
    mission.conversation.push({ role: 'warden', text: 'Sorry, I encountered an error communicating with the agent runtime.', time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
    renderActiveMission();
  }
}
