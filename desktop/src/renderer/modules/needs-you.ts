import { $, ui, notice, escapeHtml } from './state';
import { selectNav } from './nav';

export async function fetchPendingConfirmations(): Promise<void> {
  try {
    const res = await fetch('http://127.0.0.1:6969/api/mcharness/computer/confirmations/pending');
    if (res.ok) {
      const data = await res.json();
      const newItems = data.confirmations.map((c: any) => ({
        id: `conf_${c.confirmation_id}`,
        type: 'browser_approval',
        title: 'Action Requires Approval',
        description: c.reason || 'Safety policy matched.',
        projectName: 'Active Project', // Could match by session
        missionId: 'm_active', // Usually would be mapped
        data: { confirmationId: c.confirmation_id, sessionId: c.session_id, actionId: c.action_id }
      }));
      // Filter out existing ones
      ui.needsYouItems = ui.needsYouItems.filter(i => i.type !== 'browser_approval').concat(newItems);
      updateNeedsYouCount();
    }
  } catch (e) {
    console.error('Failed to fetch confirmations', e);
  }
}

export function updateNeedsYouCount(): void {
  const count = ui.needsYouItems.length;
  const badges = document.querySelectorAll('.needs-you-badge, .rail-badge.needs-you');
  badges.forEach(b => {
    b.textContent = count.toString();
    if (count > 0) b.classList.add('visible');
    else b.classList.remove('visible');
  });
}

export function renderNeedsYouScreen(): void {
  const container = $('#needs-you-list');
  container.replaceChildren();

  if (ui.needsYouItems.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✓</div>
        <div class="empty-title">All caught up</div>
        <div class="empty-subtitle">There are no tasks requiring your attention.</div>
      </div>
    `;
    return;
  }

  for (const item of ui.needsYouItems) {
    const card = document.createElement('div');
    card.className = 'needs-you-card';
    
    let actionsHtml = '';
    if (item.type === 'browser_approval') {
      actionsHtml = `
        <button class="btn primary btn-approve" data-id="${item.id}">Approve Action</button>
        <button class="btn secondary btn-deny" data-id="${item.id}">Deny</button>
      `;
    } else {
      actionsHtml = `
        <button class="btn primary btn-review" data-id="${item.id}">Review Diff</button>
      `;
    }

    card.innerHTML = `
      <div class="needs-you-header">
        <div class="needs-you-project">${escapeHtml(item.projectName)}</div>
        <div class="needs-you-title">${escapeHtml(item.title)}</div>
      </div>
      <div class="needs-you-body">
        <p>${escapeHtml(item.description)}</p>
      </div>
      <div class="needs-you-actions">
        ${actionsHtml}
      </div>
    `;

    container.append(card);
  }

  container.querySelectorAll('.btn-approve').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const id = (e.target as HTMLElement).dataset.id!;
      void resolveAttentionItem(id, 'approve');
    });
  });

  container.querySelectorAll('.btn-deny').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const id = (e.target as HTMLElement).dataset.id!;
      void resolveAttentionItem(id, 'deny');
    });
  });

  container.querySelectorAll('.btn-review').forEach(btn => {
    btn.addEventListener('click', () => {
      void selectNav('mission');
    });
  });
}

export async function resolveAttentionItem(itemId: string, decision: 'approve' | 'deny'): Promise<void> {
  const item = ui.needsYouItems.find(i => i.id === itemId);
  if (!item) return;

  try {
    if (item.type === 'browser_approval') {
      const res = await fetch(`http://127.0.0.1:6969/api/mcharness/computer/confirmations/${encodeURIComponent(item.data.confirmationId)}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision,
          operator_id: 'operator',
          expected_session_id: item.data.sessionId,
          expected_action_id: item.data.actionId
        }),
      });
      if (!res.ok) throw new Error('Failed to resolve confirmation');
    } else if (item.type === 'build_review') {
      await window.wardenDesk.runs.approve(item.data.runId, 'diff_approval', decision);
    }
    
    ui.needsYouItems = ui.needsYouItems.filter(i => i.id !== itemId);
    updateNeedsYouCount();
    
    if (ui.view === 'needs-you') {
      renderNeedsYouScreen();
    }
    notice(`Item ${decision === 'approve' ? 'approved' : 'denied'}.`);
  } catch (err) {
    console.error(err);
    notice('Failed to resolve item.');
  }
}
