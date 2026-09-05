const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  
  await window.fill('#home-prompt', 'Go to http://127.0.0.1:8777/warden-confirmation-test.html and click the Dangerous Action button again.');
  await window.click('.btn-start-mission');
  
  await window.waitForSelector('#panel-needs-you:has-text("Needs You")', { timeout: 120000 });
  await window.screenshot({ path: 'deny_needs_you.png' });
  
  // Click Deny
  await window.click('.btn-deny');
  
  // Wait for proof / failure
  await new Promise(r => setTimeout(r, 10000));
  await window.screenshot({ path: 'deny_executed.png' });
  
  await electronApp.close();
}

run().catch(console.error);
