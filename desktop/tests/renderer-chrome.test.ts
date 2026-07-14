import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const html = readFileSync(join(process.cwd(), 'src/renderer/index.html'), 'utf8');
const css = readFileSync(join(process.cwd(), 'src/renderer/styles.css'), 'utf8');
const renderer = readFileSync(join(process.cwd(), 'src/renderer/index.ts'), 'utf8');
const main = readFileSync(join(process.cwd(), 'src/main/index.ts'), 'utf8');
const manager = readFileSync(join(process.cwd(), 'src/main/platform-manager.ts'), 'utf8');

describe('quiet native browser chrome', () => {
  it('keeps frequent navigation in the compact toolbar and delegates overflow to Electron Menu', () => {
    const toolbar = html.match(/<header id="browser-toolbar">([\s\S]+?)<\/header>/)?.[1] || '';
    expect(toolbar).toContain('data-action="back"'); expect(toolbar).toContain('data-action="forward"'); expect(toolbar).toContain('id="reload-stop"'); expect(toolbar).toContain('id="platform-overflow"');
    expect(toolbar).not.toContain('page-title'); expect(toolbar).not.toContain('Clear Session'); expect(toolbar).not.toContain('data-action="home"'); expect(toolbar).not.toContain('id="platform-menu"');
    expect(renderer).toContain('window.wardenDesk.platform.showMenu'); expect(manager).toContain('Menu.buildFromTemplate'); expect(manager).toContain('menu.popup'); expect(css).toContain('#browser-toolbar{height:38px');
  });

  it('validates the narrow menu IPC and keeps destructive confirmation native', () => {
    expect(main).toContain('requireMainRenderer(event)'); expect(main).toContain("ipcMain.handle('platform:show-menu'");
    expect(manager).toContain("title: 'Clear this site’s data?'"); expect(manager).toContain('Chromium cookies are registrable-domain scoped'); expect(manager).toContain("title: 'Remove platform?'");
    expect(manager).toContain('callback: resolve'); expect(manager).toContain("event: 'menu.opened'"); expect(manager).not.toContain('positioningItem:');
  });

  it('detaches the native provider surface before opening the add-platform dialog', () => {
    const openDialog = renderer.match(/async function openPlatformDialog[\s\S]+?\n}/)?.[0] || '';
    expect(openDialog).toContain('await window.wardenDesk.platform.hide()'); expect(openDialog).toContain('dialog.showModal()');
    expect(openDialog.indexOf('platform.hide()')).toBeLessThan(openDialog.indexOf('dialog.showModal()'));
    expect(renderer).toContain("platformDialog.addEventListener('close'"); expect(renderer).toContain('void openPlatformDialog()');
  });
});
