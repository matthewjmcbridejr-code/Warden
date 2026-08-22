const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  electronApp.on('window', async (page) => {
    page.on('console', msg => console.log('RENDERER:', msg.text()));
  });

  // Main process logs
  const client = await electronApp.browserWindow(await electronApp.firstWindow());
  console.log("launched");
  await new Promise(r => setTimeout(r, 5000));
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
