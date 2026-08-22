const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  window.on('console', msg => console.log('RENDERER:', msg.text()));

  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  
  const err = await window.evaluate(async () => {
    try {
      await startMissionFromPrompt('test', ui.projects[0].id);
      return 'SUCCESS';
    } catch (e) {
      return e.stack || String(e);
    }
  });

  console.log("EVAL RESULT:", err);
  await electronApp.close();
}
run().catch(console.error);
