const { _electron: electron } = require('playwright');
const path = require('path');

async function run() {
  const electronApp = await electron.launch({
    executablePath: path.join(__dirname, 'desktop/dist-electron/linux-unpacked/warden-ai-desk'),
    args: ['--no-sandbox']
  });
  
  const window = await electronApp.firstWindow();
  
  const res = await window.evaluate(async () => {
    try {
       const project = ui.projects[0];
       const r = await window.wardenDesk.runs.start({
         provider: 'codex',
         prompt: 'hello world',
         cwd: project.cwd,
         projectId: project.id,
         attachContext: true,
         authSource: 'subscription',
         safe: true
       });
       return r.id;
    } catch(e) { return e.stack; }
  });
  console.log("RUN ID:", res);
  await new Promise(r => setTimeout(r, 10000));
  
  const status = await window.evaluate((id) => ui.missions.get(ui.activeMissionId)?.run?.status || 'no run in mission', res);
  console.log("STATUS:", status);
  
  await electronApp.close();
}
run().catch(console.error);
