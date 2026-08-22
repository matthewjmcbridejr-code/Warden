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
  
  // Type the prompt
  await window.fill('#home-prompt', 'Create a simple page with the heading "Warden Works",\nrun it locally,\nopen it in the browser,\nverify the heading visually,\nand tell me when it works.');
  await window.click('#home-prompt-submit');
  
  // Wait for mission view
  await window.waitForSelector('#view-mission', { state: 'visible', timeout: 10000 });
  await window.screenshot({ path: 'mission_active.png' });
  
  // Wait for build work to complete
  await window.waitForSelector('.work-card.completed:has-text("Build Work")', { timeout: 60000 });
  await window.click('.work-card:has-text("Build Work")');
  await window.screenshot({ path: 'mission_build.png' });
  
  // Wait for terminal work
  await window.waitForSelector('.work-card.completed:has-text("Terminal Work")', { timeout: 60000 });
  await window.click('.work-card:has-text("Terminal Work")');
  await window.screenshot({ path: 'mission_terminal.png' });

  // Wait for browser work
  await window.waitForSelector('.work-card.completed:has-text("Browser Work")', { timeout: 120000 });
  await window.click('.work-card:has-text("Browser Work")');
  await window.screenshot({ path: 'mission_browser.png' });
  
  // Wait for proof
  await window.waitForSelector('.work-card.completed:has-text("Proof")', { timeout: 30000 });
  await window.click('.work-card:has-text("Proof")');
  await window.screenshot({ path: 'mission_proof.png' });
  
  // Extract info
  const runId = await window.evaluate(() => {
    const mission = ui.missions.get(ui.activeMissionId);
    return mission.run ? mission.run.id : null;
  });
  
  const terminalId = await window.evaluate(() => {
    return ui.activeTerminal;
  });
  
  const evidence = await window.evaluate(() => {
    const mission = ui.missions.get(ui.activeMissionId);
    return mission.evidence;
  });

  const termOutput = await window.evaluate(() => {
    return document.querySelector('#panel-terminal .terminal-content')?.textContent;
  });

  console.log(`RUN_ID: ${runId}`);
  console.log(`TERM_ID: ${terminalId}`);
  console.log(`TERM_OUTPUT: ${termOutput}`);
  console.log(`EVIDENCE: ${JSON.stringify(evidence)}`);

  await electronApp.close();
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});
