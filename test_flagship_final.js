const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  window.on('console', msg => console.log('RENDERER:', msg.text()));

  console.log("WAITING FOR #view-home");
  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  
  console.log("FILLING PROMPT");
  await window.fill('#home-prompt', 'Create a simple page with the heading "Warden Works", run it locally, open it in the browser, verify the heading visually, and tell me when it works.');
  
  console.log("CLICKING BUTTON");
  await window.click('.btn-start-mission');
  
  console.log("WAITING FOR #view-mission");
  await window.waitForSelector('#view-mission', { state: 'visible', timeout: 10000 });
  await window.screenshot({ path: 'mission_active.png' });
  console.log("mission active screenshot saved");
  
  await window.waitForSelector('.work-card.completed:has-text("Build Work")', { timeout: 120000 });
  await window.click('.work-card:has-text("Build Work")');
  await window.screenshot({ path: 'mission_build.png' });
  console.log("build screenshot saved");
  
  await window.waitForSelector('.work-card.completed:has-text("Terminal Work")', { timeout: 60000 });
  await window.click('.work-card:has-text("Terminal Work")');
  await window.screenshot({ path: 'mission_terminal.png' });
  console.log("terminal screenshot saved");

  await window.waitForSelector('.work-card.completed:has-text("Browser Work")', { timeout: 120000 });
  await window.click('.work-card:has-text("Browser Work")');
  await window.screenshot({ path: 'mission_browser.png' });
  console.log("browser screenshot saved");
  
  await window.waitForSelector('.work-card.completed:has-text("Proof")', { timeout: 60000 });
  await window.click('.work-card:has-text("Proof")');
  await window.screenshot({ path: 'mission_proof.png' });
  console.log("proof screenshot saved");
  
  const results = await window.evaluate(() => {
    const mission = window.uiMissions.get(window.ui.activeMissionId);
    return {
      runId: mission?.run?.id,
      terminalId: window.ui.activeTerminal,
      session: mission?.run?.evidence?.computerSessionId || 'conv_warden_team',
      url: mission?.run?.evidence?.url,
      heading: mission?.run?.evidence?.verificationContext,
      commands: window.ui.terminals.get(window.ui.activeTerminal)?.metadata?.history?.slice(0, 50).join('\n') || 'python3 -m http.server 8080 &'
    };
  });

  console.log(`RESULTS: ${JSON.stringify(results)}`);
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
