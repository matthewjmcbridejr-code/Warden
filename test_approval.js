const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  
  // Start the mission that triggers Needs You
  await window.fill('#home-prompt', 'Go to http://127.0.0.1:8777/warden-confirmation-test.html and click the Dangerous Action button.');
  await window.click('.btn-start-mission');
  
  // Wait for Needs You
  await window.waitForSelector('#panel-needs-you:has-text("Needs You")', { timeout: 120000 });
  await window.screenshot({ path: 'approval_needs_you.png' });
  
  // Click Approve
  await window.click('.btn-approve');
  
  // Wait for execution
  await window.waitForSelector('.work-card.completed:has-text("Browser Work")', { timeout: 60000 });
  await window.screenshot({ path: 'approval_executed.png' });
  
  await electronApp.close();
}

run().catch(console.error);
