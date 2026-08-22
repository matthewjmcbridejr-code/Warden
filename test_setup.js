const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await new Promise(r => setTimeout(r, 2000));
  await window.screenshot({ path: 'setup_screen.png' });
  await electronApp.close();
}
run().catch(console.error);
