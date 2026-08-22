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
    return {
       projects: ui.projects,
       active: ui.activeProjectId,
       projIdVal: document.querySelector('#home-project-select')?.value
    };
  });

  console.log("EVAL RESULT:", JSON.stringify(error));
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
