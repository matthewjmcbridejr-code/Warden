import { ui } from './state';

export function providerBounds(): void {
  const container = document.getElementById('provider-frame-container');
  if (!container || ui.view !== 'connected-ais') return;
  const rect = container.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  window.wardenDesk.platform.setBounds({
    x: Math.round(rect.x * dpr),
    y: Math.round(rect.y * dpr),
    width: Math.round(rect.width * dpr),
    height: Math.round(rect.height * dpr),
  });
}
