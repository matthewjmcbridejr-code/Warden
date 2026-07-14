import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const html = readFileSync(join(process.cwd(), 'src/renderer/index.html'), 'utf8');
const css = readFileSync(join(process.cwd(), 'src/renderer/styles.css'), 'utf8');

describe('quiet browser chrome', () => {
  it('keeps frequent navigation in the compact toolbar and rare actions in overflow', () => {
    const toolbar = html.match(/<header id="browser-toolbar">([\s\S]+?)<\/header>/)?.[1] || '';
    expect(toolbar).toContain('data-action="back"'); expect(toolbar).toContain('data-action="forward"'); expect(toolbar).toContain('id="reload-stop"'); expect(toolbar).toContain('id="platform-overflow"');
    expect(toolbar).not.toContain('page-title'); expect(toolbar).not.toContain('Clear Session'); expect(toolbar).not.toContain('data-action="home"');
    expect(toolbar.indexOf('id="menu-clear"')).toBeGreaterThan(toolbar.indexOf('id="platform-menu"'));
    expect(css).toContain('#browser-toolbar{height:38px');
  });

  it('states the shared-profile limitation before destructive clearing', () => {
    expect(html).toContain('Electron cannot guarantee that related sites in that profile are unaffected');
    expect(html).toContain('Clear this site’s data…');
    expect(html).not.toContain('Clear session');
  });
});
