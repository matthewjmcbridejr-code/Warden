const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  await window.fill('#home-prompt', 'Create a simple page...');
  
  window.on('console', msg => console.log('RENDERER:', msg.text()));
  window.on('pageerror', err => console.log('PAGE ERROR:', err));
  
  await window.evaluate(() => {
    document.querySelector('.btn-start-mission').click();
  });
  
  await new Promise(r => setTimeout(r, 2000));
  await electronApp.close();
}
run().catch(console.error);
