import '@fontsource-variable/sora/wght.css';
import '@fontsource-variable/epilogue/wght.css';
import './styles.css';
import { ui, $ } from './modules/state';
import { selectNav } from './modules/nav';
import { fetchPendingConfirmations, updateNeedsYouCount } from './modules/needs-you';
import { sendMissionFollowup } from './modules/mission';

async function init() {
  const stateResult = await window.wardenDesk.state.get();
  ui.projects = stateResult.state.projects;
  ui.activeProjectId = stateResult.state.activeProjectId || ui.projects[0]?.id;
  ui.mode = stateResult.state.mode;

  try {
    const appInfo = await window.wardenDesk.app.info();
    ui.appInfo = appInfo;
    const title = document.querySelector('.rail-footer-title');
    if (title) title.textContent = `Warden ${appInfo.version}`;
  } catch (e) {}

  document.querySelectorAll<HTMLButtonElement>('[data-nav]').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.nav as any;
      if (view) void selectNav(view);
    });
  });

  const followupInput = document.getElementById('mission-followup-input') as HTMLTextAreaElement;
  if (followupInput) {
    followupInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = followupInput.value.trim();
        if (text) {
          followupInput.value = '';
          void sendMissionFollowup(text);
        }
      }
    });
  }

  const urlParams = new URLSearchParams(window.location.search);
  const initialView = urlParams.get('view') as any;
  void selectNav(initialView || 'home');

  // Poll for needs you
  void fetchPendingConfirmations();
  setInterval(fetchPendingConfirmations, 5000);
}

document.addEventListener('DOMContentLoaded', () => {
  void init();
});
