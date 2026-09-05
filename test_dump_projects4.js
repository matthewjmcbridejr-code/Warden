const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  const count = await window.evaluate(() => window.globalUiMissions ? window.globalUiMissions.size : 'unknown');
  console.log("MISSIONS SIZE:", count);
  await electronApp.close();
}
run().catch(console.error);
