const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  electronApp.process().stdout.on('data', data => console.log('APP STDOUT:', data.toString()));
  electronApp.process().stderr.on('data', data => console.log('APP STDERR:', data.toString()));
  
  const window = await electronApp.firstWindow();
  await new Promise(r => setTimeout(r, 5000));
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
