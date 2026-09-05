const { _electron: electron } = require('playwright');
const path = require('path');
const fs = require('fs');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });

  console.log('App launched.');
  const window = await electronApp.firstWindow();
  
  // Wait for home screen to appear
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  console.log('Home screen visible.');
  
  // Take screenshot
  await window.screenshot({ path: 'home_cold_start.png' });
  console.log('Screenshot saved.');

  // Close app
  await electronApp.close();
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});
