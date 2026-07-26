import { build } from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';

await rm('dist', { recursive: true, force: true });
await mkdir('dist', { recursive: true });

await build({ entryPoints: ['src/main/index.ts'], outfile: 'dist/main.cjs', bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['electron', 'node-pty'], sourcemap: true });
await build({ entryPoints: ['src/preload/index.ts'], outfile: 'dist/preload.cjs', bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['electron'], sourcemap: true });
await build({ entryPoints: ['src/renderer/index.ts'], outfile: 'dist/renderer.js', bundle: true, platform: 'browser', format: 'iife', target: 'chrome140', sourcemap: true, loader: { '.woff2': 'file' }, assetNames: 'assets/fonts/[name]-[hash]' });
await cp('src/renderer/index.html', 'dist/index.html');
await mkdir('dist/assets', { recursive: true });
await cp('assets/icon.png', 'dist/assets/icon.png');
await mkdir('dist/licenses', { recursive: true });
await cp('node_modules/@fontsource-variable/sora/LICENSE', 'dist/licenses/Sora-OFL.txt');
await cp('node_modules/@fontsource-variable/epilogue/LICENSE', 'dist/licenses/Epilogue-OFL.txt');
