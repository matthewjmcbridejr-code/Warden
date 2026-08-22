const { _electron: electron } = require('playwright');
const path = require('path');
const fs = require('fs');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  
  // Start build mission
  await window.fill('#home-prompt', 'Create a file test_build.txt with content "Hello Apply"');
  await window.click('.btn-start-mission');
  
  await window.waitForSelector('.work-card.completed:has-text("Build Work")', { timeout: 60000 });
  await window.click('.work-card:has-text("Build Work")');
  
  await window.waitForSelector('#panel-needs-you:has-text("Ready to Review")', { timeout: 10000 });
  await window.click('.btn-approve'); // Apply
  
  await new Promise(r => setTimeout(r, 2000));
  
  // Start discard mission
  await window.click('#mission-btn-new');
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  await window.fill('#home-prompt', 'Create a file test_discard.txt with content "Hello Discard"');
  await window.click('.btn-start-mission');
  
  await window.waitForSelector('.work-card.completed:has-text("Build Work")', { timeout: 60000 });
  await window.click('.work-card:has-text("Build Work")');
  
  await window.waitForSelector('#panel-needs-you:has-text("Ready to Review")', { timeout: 10000 });
  await window.click('.btn-deny'); // Discard
  
  await new Promise(r => setTimeout(r, 2000));
  
  await electronApp.close();
}
run().catch(console.error);
