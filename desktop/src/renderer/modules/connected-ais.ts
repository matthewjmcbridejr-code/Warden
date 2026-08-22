import { $, ui, escapeHtml, notice } from './state';
import { selectNav, selectAdvTab } from './nav';
import { providerBounds } from './util';
import type { WebPlatform, PlatformPreset } from '../../shared/types';

// ---------------------------------------------------------------------------
export function renderConnectedAisScreen(): void {
  const root = $('#connected-platforms-list');
  root.replaceChildren();

  for (const platform of ui.platforms.values()) {
    const card = document.createElement('div');
    card.className = 'platform-pill-card';
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(platform.name)}</strong>
        <small style="display:block; color:#786e7a;">${escapeHtml(platform.category)} · ${platform.enabled ? 'Enabled' : 'Disabled'}</small>
      </div>
      <button type="button" class="btn small" onclick="window.selectPlatform('${escapeHtml(platform.id)}')">Open Workspace</button>
    `;
    root.append(card);
  }
}

export function renderAdvancedScreen(): void {
  selectAdvTab(ui.activeAdvTab);
}