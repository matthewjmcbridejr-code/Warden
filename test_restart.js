const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-mission', { state: 'visible', timeout: 10000 });
  await window.screenshot({ path: 'restart_proof.png' });
  
  await electronApp.close();
}
run().catch(console.error);
