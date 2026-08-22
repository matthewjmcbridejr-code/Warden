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
  
  const error = await window.evaluate(async () => {
    try {
      await startMissionFromPrompt("Create a simple page with the heading Warden Works");
      return "SUCCESS";
    } catch (e) {
      return e.message || String(e);
    }
  });

  console.log("EVAL RESULT:", error);
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
