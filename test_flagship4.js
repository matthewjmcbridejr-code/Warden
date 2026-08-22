const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  window.on('console', msg => console.log(msg.text()));

  await window.waitForSelector('#view-home', { state: 'visible', timeout: 10000 });
  console.log("home visible");
  
  await window.fill('#home-prompt', 'Create a simple page with the heading "Warden Works", run it locally, open it in the browser, verify the heading visually, and tell me when it works.');
  console.log("filled");
  await window.click('.btn-start-mission');
  console.log("clicked submit");
  
  // Wait for mission view
  await window.waitForSelector('#view-mission', { state: 'visible', timeout: 10000 });
  console.log("mission active");
  await electronApp.close();
}
run().catch(err => {
  console.error(err);
  process.exit(1);
});
