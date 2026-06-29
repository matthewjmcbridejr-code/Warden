const fs = require("fs");
const path = require("path");
const PLAYWRIGHT_TEST_MODULE =
  process.env.MCHARNESS_PLAYWRIGHT_TEST_MODULE || "/root/.hermes/node/lib/node_modules/playwright/test";
const { test, expect } = require(PLAYWRIGHT_TEST_MODULE);

const ROOT = path.resolve(__dirname, "..", "..");
const RUNTIME_DIRS = [
  path.join(ROOT, "_mctable", "workbench"),
  path.join(ROOT, "_mctable", "captain"),
  path.join(ROOT, "_mctable", "mcharness", "artifacts"),
];

function resetRuntimeState() {
  for (const directory of RUNTIME_DIRS) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

function builtinCodexAgent() {
  return {
    id: "codex_cli",
    name: "Codex CLI",
    kind: "cli",
    adapter: "codex_cli",
    enabled: true,
    private_only: true,
    builtin: true,
    user_created: false,
    status: "ready",
    runnable: true,
    lane_id: "codex_cli",
    capabilities: ["live_terminal", "code_editing", "tests", "read_only_inspection"],
  };
}

function agentRegistryTemplatesPayload() {
  return {
    service: "mcharness-control-plane",
    templates: [
      { id: "codex_cli", label: "Codex CLI", kind: "cli", adapter: "codex_cli", registerable: false, runnable: true, builtin: true, requires_config: false },
      { id: "jules_remote", label: "Jules Remote", kind: "remote", adapter: "jules_remote", registerable: true, runnable: false, builtin: false, requires_config: true },
      { id: "agy_cli", label: "AGY CLI Coming Later", kind: "cli", adapter: "agy_cli", registerable: false, runnable: false, builtin: false, requires_config: false },
      { id: "custom_cli", label: "Custom CLI Coming Later", kind: "cli", adapter: "custom_cli", registerable: false, runnable: false, builtin: false, requires_config: false },
      { id: "custom_remote", label: "Custom Remote Coming Later", kind: "remote", adapter: "custom_remote", registerable: false, runnable: false, builtin: false, requires_config: false },
    ],
  };
}

async function fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled = true, registeredAgents = [] }) {
  if (pathname.endsWith("/agents/templates")) {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(agentRegistryTemplatesPayload()),
    });
    return true;
  }
  if (pathname.endsWith("/agents") && method === "GET") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        service: "mcharness-control-plane",
        registry_write_enabled: registryWriteEnabled,
        agents: [builtinCodexAgent(), ...registeredAgents],
      }),
    });
    return true;
  }
  return false;
}

function normalizeMockCaptainPlan(plan) {
  const steps = (plan.steps || []).map((step, index) => ({
    ...step,
    id: step.id || step.step_id || `step_${index + 1}`,
    step_id: step.step_id || step.id || `step_${index + 1}`,
    status: step.status || "queued",
    agent_id: step.agent_id || step.agent || "codex_cli",
  }));
  return {
    ...plan,
    status: plan.status || "active",
    current_step_id: plan.current_step_id || (steps[0] && steps[0].id),
    repo_id: plan.repo_id || "hybrid-agent-os",
    steps,
  };
}

function idleMissionSnapshot(overrides = {}) {
  return {
    service: "mcharness-control-plane",
    service_mode: "public",
    generated_at: new Date().toISOString(),
    mission: { status: "idle", mission_id: null, title: null, progress_pct: 0 },
    plan: { plan_id: null, steps: [] },
    timeline: { items: [] },
    worklog: { items: [] },
    proof_gates: { summary: { passed: 0, pending: 0, blocked: 0, needs_more_evidence: 0, total: 0 }, items: [] },
    agents: {
      summary: {},
      items: [
        { id: "captain", name: "Captain", kind: "orchestrator", status: "not_configured", mode: "orchestrator", runnable: false },
        { id: "codex_cli", name: "Codex CLI", kind: "cli", status: "disabled", mode: "disabled", runnable: false },
      ],
    },
    safety: {
      secure: true,
      public_runner_enabled: false,
      private_runner_enabled: false,
      arbitrary_shell_input: false,
      jules_runnable: false,
      secrets_exposed: false,
      items: [
        { key: "public_runner", label: "Public runner", status: "disabled", severity: "good", summary: "Public runner is disabled." },
        { key: "private_runner", label: "Private runner", status: "disabled", severity: "good", summary: "Private runner is disabled on public service." },
      ],
    },
    runner_sessions: { max_active_runner_sessions: 4, total_runner_sessions: 0, active_runner_sessions: 0, stale_runner_sessions: 0 },
    next_move: { label: "Develop a plan", description: "Create or load a Captain plan to begin supervised work.", action: "develop_plan" },
    ...overrides,
  };
}

function idleRunnerSessions() {
  return {
    service: "mcharness-control-plane",
    service_mode: "public",
    max_active_runner_sessions: 4,
    total_runner_sessions: 0,
    active_runner_sessions: 0,
    stale_runner_sessions: 0,
    items: [],
  };
}

async function fulfillControlRoomRoutes(route, { snapshot = idleMissionSnapshot(), runner = idleRunnerSessions() } = {}) {
  const url = new URL(route.request().url());
  const { pathname } = url;
  if (pathname.endsWith("/mission-control/snapshot")) {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(snapshot) });
    return true;
  }
  if (pathname.endsWith("/runner/sessions")) {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runner) });
    return true;
  }
  if (pathname.endsWith("/runner/sessions/cleanup") && route.request().method() === "POST") {
    const body = route.request().postDataJSON() || {};
    await route.fulfill({
      status: body.confirm ? 200 : 200,
      contentType: "application/json",
      body: JSON.stringify({
        dry_run: !body.confirm,
        candidates: body.confirm ? [] : ["mch_run_run_stale01"],
        killed: body.confirm ? ["mch_run_run_stale01"] : [],
        skipped: [],
        errors: [],
        inventory: { total_runner_sessions: 0, active_runner_sessions: 0, stale_runner_sessions: 0 },
      }),
    });
    return true;
  }
  return false;
}

function nextQueuedMockStepId(plan, afterStepId) {
  const steps = plan.steps || [];
  const index = steps.findIndex((step) => (step.id || step.step_id) === afterStepId);
  for (let i = index + 1; i < steps.length; i += 1) {
    const status = steps[i].status || "queued";
    if (status === "queued" || status === "revised") return steps[i].id || steps[i].step_id;
  }
  return null;
}

async function fulfillCaptainLoopRoute(route, ctx) {
  const url = new URL(route.request().url());
  const { pathname } = url;
  const method = route.request().method();
  const body = route.request().postDataJSON ? route.request().postDataJSON() : null;

  if (pathname.endsWith("/captain/plans/recent") && method === "GET") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        service: "mcharness-control-plane",
        plans: ctx.activePlan ? [ctx.activePlan] : [],
      }),
    });
    return true;
  }

  let match = pathname.match(/\/captain\/plans\/([^/]+)$/);
  if (match && method === "GET") {
    const planId = decodeURIComponent(match[1]);
    if (!ctx.activePlan || ctx.activePlan.plan_id !== planId) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: `Captain plan not found: ${planId}` }),
      });
      return true;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ plan: ctx.activePlan }),
    });
    return true;
  }

  match = pathname.match(/\/captain\/plans\/([^/]+)\/steps\/([^/]+)\/dispatch$/);
  if (match && method === "POST") {
    const stepId = decodeURIComponent(match[2]);
    ctx.dispatchCalls = ctx.dispatchCalls || [];
    ctx.dispatchCalls.push({ stepId, body });
    if (ctx.runnerStartCalls) ctx.runnerStartCalls.push(body);
    const step = (ctx.activePlan?.steps || []).find((item) => (item.id || item.step_id) === stepId);
    const prompt = step?.prompt || "";
    ctx.runnerStatus = { ...ctx.runnerStatus, status: "running" };
    ctx.activePlan = normalizeMockCaptainPlan({
      ...ctx.activePlan,
      steps: (ctx.activePlan.steps || []).map((item) => {
        const id = item.id || item.step_id;
        return id === stepId
          ? { ...item, status: "dispatched", run_id: ctx.runnerStatus.runner_id }
          : item;
      }),
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        plan: ctx.activePlan,
        dispatch: {
          session_id: ctx.runnerStatus.session_id,
          runner_id: ctx.runnerStatus.runner_id,
          prompt,
        },
      }),
    });
    return true;
  }

  match = pathname.match(/\/captain\/plans\/([^/]+)\/steps\/([^/]+)\/complete$/);
  if (match && method === "POST") {
    const stepId = decodeURIComponent(match[2]);
    ctx.completeCalls = ctx.completeCalls || [];
    ctx.completeCalls.push({ stepId, body });
    const nextStepId = nextQueuedMockStepId(ctx.activePlan, stepId);
    ctx.activePlan = normalizeMockCaptainPlan({
      ...ctx.activePlan,
      status: nextStepId ? "active" : "completed",
      current_step_id: nextStepId || stepId,
      steps: (ctx.activePlan.steps || []).map((item) => {
        const id = item.id || item.step_id;
        return id === stepId ? { ...item, status: "passed", evidence_ids: body?.evidence_ids || [] } : item;
      }),
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, plan: ctx.activePlan }),
    });
    return true;
  }

  match = pathname.match(/\/captain\/plans\/([^/]+)\/steps\/([^/]+)\/revise$/);
  if (match && method === "POST") {
    const stepId = decodeURIComponent(match[2]);
    ctx.reviseCalls = ctx.reviseCalls || [];
    ctx.reviseCalls.push({ stepId, body });
    ctx.activePlan = normalizeMockCaptainPlan({
      ...ctx.activePlan,
      steps: (ctx.activePlan.steps || []).map((item) => {
        const id = item.id || item.step_id;
        return id === stepId
          ? { ...item, status: "revised", prompt: body?.prompt || item.prompt, title: body?.title || item.title }
          : item;
      }),
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, plan: ctx.activePlan }),
    });
    return true;
  }

  match = pathname.match(/\/captain\/plans\/([^/]+)\/stop$/);
  if (match && method === "POST") {
    ctx.stopCalls = ctx.stopCalls || [];
    ctx.stopCalls.push(body);
    ctx.activePlan = normalizeMockCaptainPlan({
      ...ctx.activePlan,
      status: "stopped",
      steps: (ctx.activePlan.steps || []).map((item) => {
        const status = item.status || "queued";
        return ["queued", "revised", "dispatched", "running", "needs_review"].includes(status)
          ? { ...item, status: "stopped" }
          : item;
      }),
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, plan: ctx.activePlan }),
    });
    return true;
  }

  return false;
}

test.beforeEach(() => {
  resetRuntimeState();
});

test.afterEach(() => {
  resetRuntimeState();
});

test("proves the minimal Agent Library + Codex flow (SIMPLE MODE)", async ({ page }, testInfo) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          configured: false,
          provider: "openrouter",
          model: "openrouter/auto",
          planning_enabled: false,
          key_source: "missing",
          private_key_setup_enabled: false,
          notes: ["Captain is not configured. Set OPENROUTER_API_KEY on the private service."],
        }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");

  await expect(page.locator("h1")).toContainText("Warden");
  await expect(page.locator("[data-testid='warden-byline']")).toContainText("by Marius Systems");
  await expect(page.locator("[data-testid='warden-sidebar']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-powered']")).toContainText("Powered by McHarness");
  await expect(page.locator("[data-testid='nav-mission']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='warden-section-mission']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='cr-hero-title']")).toContainText("Control Room");
  await expect(page.locator("[data-testid='cr-product-headline']")).toContainText("Supervise missions");
  await expect(page.locator("[data-testid='current-mission-card']")).toContainText("No active mission");
  await expect(page.locator("[data-testid='cr-tab-timeline']")).toBeVisible();
  await expect(page.locator("[data-testid='operator-inspector']")).toBeVisible();
  await expect(page.locator("[data-testid='inspector-next-move']")).toContainText("Next Move");
  await expect(page.locator("[data-testid='rail-safety-status']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-connected-agents']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-proof-gates']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-runner-sessions']")).toBeVisible();
  await expect(page.locator("[data-testid='cr-pause-mission']")).toBeDisabled();
  await expect(page.locator("[data-testid='cr-adjust-plan']")).toBeDisabled();
  await expect(page.locator("[data-testid='develop-plan-primary']")).toBeVisible();
  await expect(page.locator("#warden-section-agents.active")).toHaveCount(0);
  await expect(page.locator("#warden-section-mission.active")).toBeVisible();

  await page.locator("[data-testid='nav-tasks']").click();
  await expect(page.locator("[data-testid='tasks-empty-state']")).toContainText("No active task plan yet");
  await page.locator("[data-testid='nav-runs']").click();
  await expect(page.locator("[data-testid='runs-empty-state']")).toContainText("Runs will show live and completed agent sessions");
  await page.locator("[data-testid='nav-evidence']").click();
  await expect(page.locator("[data-testid='evidence-empty-state']")).toContainText("Saved outputs");
  await page.locator("[data-testid='nav-settings']").click();
  await expect(page.locator("[data-testid='settings-captain-status']")).toContainText("Captain ·");
  await expect(page.locator("[data-testid='settings-public-runner']")).toContainText("Public runner — Off");
  await expect(page.locator("[data-testid='settings-private-runner']")).toContainText("Private runner");
  await expect(page.locator("[data-testid='settings-shell-input']")).toContainText("Shell access — Restricted");
  await expect(page.locator("[data-testid='settings-agent-registration']")).toContainText("Agent registration");
  await expect(page.locator("text=SERVER CONTROL PLANE")).toHaveCount(0);
  await expect(page.locator("text=Advanced / Legacy Cockpit")).toHaveCount(0);
  await page.locator("[data-testid='nav-agents']").click();
  await expect(page.locator("[data-testid='warden-section-agents'] .workspace-title")).toHaveText("Agents");
  await expect(page.locator("[data-testid='operator-inspector']")).toBeVisible();
  await expect(page.locator("[data-testid='agent-group-captain']")).toBeVisible();
  await expect(page.locator("[data-testid='captain-agent-card']")).toContainText("Captain");
  await expect(page.locator("[data-testid='captain-agent-card']")).toContainText("Orchestrator");
  await expect(page.locator("[data-testid='captain-profile-panel']")).toBeVisible();
  await expect(page.locator("[data-testid='agent-group-cli']")).toBeVisible();
  await expect(page.locator("[data-testid='agent-group-cli']")).toContainText("CLI Agents");
  await expect(page.locator("#codex-card")).toBeVisible();
  await expect(page.locator("#codex-card")).toContainText("Codex CLI");
  await expect(page.locator("#codex-card")).toContainText("Private runner");
  await expect(page.locator("#codex-card")).toContainText("Executes approved CLI tasks");
  await expect(page.locator("#codex-card").getByRole("button", { name: "Open Monitor" })).toBeVisible();
  await expect(page.locator("#codex-card").getByRole("button", { name: "Configure" })).toBeVisible();
  await expect(page.locator("#codex-card").getByRole("button", { name: "Develop Plan" })).toHaveCount(0);
  await expect(page.locator("#codex-card").getByRole("button", { name: "Use Agent" })).toHaveCount(0);
  await expect(page.locator("[data-testid='captain-agent-card']").getByRole("button", { name: "Create Plan" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Agent" })).toBeVisible();
  await expect(page.locator("[data-testid='add-agent-help']")).toContainText("New agents require an adapter");

  await page.locator("[data-testid='codex-open-monitor']").click();
  const viewMon = page.locator("#live-cli-modal");
  await expect(viewMon).toBeVisible();
  await expect(viewMon).toContainText("Codex Live Monitor");
  await viewMon.locator("#modal-close").click();
  await expect(viewMon).not.toBeVisible();

  await page.locator("[data-testid='nav-mission']").click();
  await page.locator("[data-testid='develop-plan-hero']").click();
  const captainModal = page.locator("#captain-deck-modal");
  await expect(captainModal).toBeVisible();
  await expect(captainModal.locator("#captain-config-note")).toContainText("Not configured");
  await expect(captainModal.locator("[data-testid='captain-settings-status']")).toContainText("Not configured");
  await expect(captainModal.locator("[data-testid='captain-settings-note']")).toContainText("Key setup is private-service only");
  await expect(captainModal.locator("[data-testid='captain-set-key']")).toBeDisabled();
  // Create Plan is now enabled even without a cloud key (local preview planner is the fallback)
  await expect(captainModal.locator("#captain-create-plan")).toBeEnabled();
  await captainModal.locator("#captain-close").click();
  await expect(captainModal).not.toBeVisible();

  // Captain Create Plan opens Captain modal
  await page.locator("[data-testid='nav-agents']").click();
  await page.locator("[data-testid='captain-create-plan-btn']").click();
  const captainFromAgents = page.locator("#captain-deck-modal");
  await expect(captainFromAgents).toBeVisible();
  await expect(captainFromAgents.locator("[data-testid='captain-deck-title']")).toHaveText("Captain");
  await captainFromAgents.locator("#captain-close").click();
  await expect(captainFromAgents).not.toBeVisible();

  // Deploy (public disabled path) shows clear message, no arbitrary input
  await page.evaluate(() => window.McHarnessSimple.openUseAgentModal());
  const useModal = page.locator("#use-agent-modal");
  await expect(useModal).toBeVisible();
  await useModal.locator("#modal-task-title").fill("Test task for codex");
  await useModal.locator("#modal-prompt").fill("Print exactly: MCHARNESS_SIMPLE_MODE_PROOF_LINE");
  await useModal.locator("#deploy-prompt-btn").click();

  // Since public runner disabled, the note in the use modal should appear (no real start)
  await expect(useModal.locator("#deploy-disabled-note")).toBeVisible({ timeout: 5000 });
  await expect(useModal.locator("#deploy-disabled-note")).toContainText("Codex runner is disabled");

  // Deploy opens Live Monitor and should close setup modals underneath
  const mon = page.locator("#live-cli-modal").or(page.getByTestId("live-cli-modal"));
  await expect(mon).toBeVisible({ timeout: 10000 });
  await expect(mon).toContainText("Live read-only view. Use the buttons below for safe replies.");

  await mon.locator("#modal-close").or(page.getByTestId("modal-close")).click();
  await expect(mon).not.toBeVisible();
  await expect(useModal).not.toBeVisible();

  await page.screenshot({ path: testInfo.outputPath("cockpit-final.png"), fullPage: true });
});

test("Captain Settings saves a private OpenRouter key and enables Captain planning", async ({ page }) => {
  let captainStatus = {
    ok: true,
    configured: false,
    provider: "openrouter",
    model: "openrouter/auto",
    planning_enabled: false,
    key_source: "missing",
    private_key_setup_enabled: true,
    notes: ["Captain is not configured. Set OPENROUTER_API_KEY on the private service."],
  };
  let transcriptText = "Captain runner idle.\n";
  let runnerStatus = {
    session_id: "captain-settings-session",
    runner_id: "run_captain_settings",
    lane_id: "codex_cli",
    repo_id: "hybrid-agent-os",
    status: "waiting_for_codex",
    tmux_session_name: "mch_captain_settings",
    attach_command: "tmux attach -t mch_captain_settings",
  };
  const runnerStartCalls = [];
  const sendPromptCalls = [];
  const captainLoopCtx = {
    activePlan: null,
    runnerStatus: null,
    runnerStartCalls,
    dispatchCalls: [],
  };
  await page.addInitScript(() => {
    window.__storageWrites = [];
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      window.__storageWrites.push([key, value]);
      return originalSetItem.call(this, key, value);
    };
  });

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;
    captainLoopCtx.runnerStatus = runnerStatus;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          mode: "public_manual",
          real_agent_launch_enabled: false,
          arbitrary_command_execution_enabled: false,
          public_write_enabled: true,
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          available_lanes_count: 7,
          repo_count: 2,
          manual_mode: true,
        }),
      });
      return;
    }

    if (await fulfillCaptainLoopRoute(route, captainLoopCtx)) {
      return;
    }

    if (pathname.endsWith("/agent-lanes")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          manual_mode: true,
          lanes: [
            {
              lane_id: "codex_cli",
              title: "Codex CLI",
              installed: true,
              runner_mode: "controlled_run_ready",
              executable_path: "/root/.hermes/node/bin/codex",
              version: "codex-cli 0.137.0",
              auth_status: "likely_ready",
              safety_notes: ["tmux available: True"],
            },
          ],
        }),
      });
      return;
    }

    if (await fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled: true })) {
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          mode: "server_control_plane",
          repos: [
            {
              repo_id: "hybrid-agent-os",
              label: "hybrid-agent-os",
              path: "/root/hybrid-agent-os",
            },
            {
              repo_id: "mcharness-public-export",
              label: "mcharness-public-export",
              path: "/root/mcharness-public-export",
            },
          ],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(captainStatus),
      });
      return;
    }

    if (pathname.endsWith("/captain/key") && method === "POST") {
      captainStatus = {
        ...captainStatus,
        configured: true,
        planning_enabled: true,
        key_source: "saved",
        model: body.model || "openrouter/auto",
        notes: ["Captain is configured via saved private key."],
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          configured: true,
          provider: "openrouter",
          model: captainStatus.model,
          key_source: "saved",
          private_key_setup_enabled: true,
          notes: ["Captain key saved."],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/plan") && method === "POST") {
      const planBody = normalizeMockCaptainPlan({
        ok: true,
        plan_id: "plan_saved_key",
        title: "Captain Saved Key Plan",
        summary: "Plan after saved key setup.",
        repo_id: "hybrid-agent-os",
        steps: [
          {
            id: "step_1",
            title: "Inspect frontend structure",
            agent: "codex_cli",
            prompt: "Exact goal: Create a read-only plan to inspect the McHarness frontend. Do not edit files.\nForbidden actions: no push, merge, reset, rebase, no secrets, no deploy commands.\nAcceptance checks: identify the frontend entrypoints.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
            status: "queued",
          },
          {
            id: "step_2",
            title: "Verify and report",
            agent: "codex_cli",
            prompt: "Exact goal: Create a read-only plan to inspect the McHarness frontend. Do not edit files.\nForbidden actions: no push, merge, reset, rebase, no secrets, no deploy commands.\nAcceptance checks: return a concise proof report.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
            status: "queued",
          },
          {
            id: "step_3",
            title: "Final proof",
            agent: "codex_cli",
            prompt: "Exact goal: Create a read-only plan to inspect the McHarness frontend. Do not edit files.\nForbidden actions: no push, merge, reset, rebase, no secrets, no deploy commands.\nAcceptance checks: finish with proof only.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
            status: "queued",
          },
        ],
        notes: ["OpenRouter model: openrouter/custom"],
      });
      captainLoopCtx.activePlan = planBody;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(planBody),
      });
      return;
    }

    if (pathname.endsWith("/sessions") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session_id: runnerStatus.session_id }),
      });
      return;
    }

    if (pathname.endsWith("/queue") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queue_item_id: "queue-captain-1" }),
      });
      return;
    }

    if (pathname.endsWith("/prompt-export") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
      return;
    }

    if (pathname.endsWith("/runner/start") && method === "POST") {
      runnerStartCalls.push(body);
      runnerStatus = { ...runnerStatus, status: "running" };
      captainLoopCtx.runnerStatus = runnerStatus;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-prompt") && method === "POST") {
      sendPromptCalls.push(body.prompt);
      transcriptText = `${transcriptText}\n${body.prompt}\nCaptain response pending.`;
      runnerStatus = { ...runnerStatus, status: "awaiting_response" };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          injected: true,
          session_id: runnerStatus.session_id,
          status: runnerStatus.status,
          transcript_excerpt: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: runnerStatus.session_id,
          runner_id: runnerStatus.runner_id,
          lane_id: runnerStatus.lane_id,
          status: runnerStatus.status,
          transcript_path: "/tmp/captain-settings-transcript.txt",
          transcript: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/stop")) {
      runnerStatus = { ...runnerStatus, status: "stopped" };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...runnerStatus, stopped_at: new Date().toISOString() }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("http://127.0.0.1:8125/web/warden/index.html");
  await expect(page.locator("[data-testid='develop-plan-primary']")).toBeVisible();

  await page.locator("[data-testid='develop-plan-primary']").click();
  const captainModal = page.locator("#captain-deck-modal");
  await expect(captainModal).toBeVisible();
  await expect(captainModal.locator("[data-testid='captain-set-key']")).toBeVisible();
  await captainModal.locator("[data-testid='captain-set-key']").click();
  await expect(captainModal.locator("[data-testid='captain-key-form']")).toBeVisible();
  await expect(captainModal.locator("[data-testid='captain-openrouter-key']")).toHaveAttribute("type", "password");
  await captainModal.locator("[data-testid='captain-openrouter-key']").fill("sk-or-private-test-key");
  await captainModal.locator("[data-testid='captain-openrouter-model']").fill("openrouter/custom");
  await captainModal.locator("[data-testid='captain-save-key']").click();
  await expect(captainModal.locator("[data-testid='captain-openrouter-key']")).toHaveValue("");
  await expect(captainModal.locator("[data-testid='captain-settings-status']")).toContainText("Configured");
  await expect(captainModal.locator("[data-testid='captain-settings-status']")).toContainText("saved");
  await expect(captainModal.locator("[data-testid='captain-settings-note']")).toContainText("saved private key");
  await expect(captainModal.locator("[data-testid='captain-create-plan']")).toBeEnabled();
  await expect(captainModal.locator("[data-testid='captain-remove-key']")).toBeVisible();
  await expect(captainModal.locator("[data-testid='captain-openrouter-key']")).toBeHidden();
  await captainModal.locator("[data-testid='captain-goal']").fill("Create a read-only plan to inspect the McHarness frontend. Do not edit files.");
  await captainModal.locator("[data-testid='captain-create-plan']").click();
  await expect(captainModal.locator("[data-testid='captain-plan-status']")).toContainText("Plan ready: Captain Saved Key Plan");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Inspect frontend structure");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Verify and report");
  await page.evaluate(() => {
    const original = window.setTimeout;
    window.setTimeout = (fn, ms, ...args) => (ms === 10000 ? original(fn, 0, ...args) : original(fn, ms, ...args));
  });
  await captainModal.locator("[data-testid='captain-deploy-first']").click();
  await expect.poll(() => runnerStartCalls.length).toBe(1);
  await expect.poll(() => sendPromptCalls.length).toBe(1);
  await expect(page.locator("#captain-deck-modal")).not.toBeVisible();
  const mon = page.locator("#live-cli-modal");
  await expect(mon).toBeVisible();
  await expect(page.locator("#live-cli-modal input, #live-cli-modal textarea")).toHaveCount(0);
  await expect(page.locator("#modal-info")).toContainText("Repo: hybrid-agent-os");
  await expect(page.locator("#modal-info")).toContainText("Status: Running");
  await expect(mon.locator("[data-testid='modal-transcript']")).toContainText("Captain response pending.");
  const storageWrites = await page.evaluate(() => window.__storageWrites || []);
  expect(storageWrites).toEqual([]);
});

test("private runner quick replies send allowed keys and refresh transcript", async ({ page }) => {
  const makeTranscript = (count, prefix = "Codex output") =>
    Array.from({ length: count }, (_, idx) => `${prefix} line ${idx + 1}`).join("\n");
  let transcriptText = [
    "Codex update available",
    "",
    "1. Update now",
    "2. Skip",
    "3. Skip until next version",
    "",
    "Press enter to continue",
    "",
    makeTranscript(140, "Initial transcript"),
  ].join("\n");
  let runnerStatus = {
    session_id: "quick-reply-session",
    runner_id: "run_quick_reply",
    lane_id: "codex_cli",
    repo_id: "mcharness-public-export",
    status: "waiting_for_codex",
    tmux_session_name: "mch_quick_reply",
    attach_command: "tmux attach -t mch_quick_reply",
  };
  let sendKeyCalls = [];

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          mode: "public_manual",
          real_agent_launch_enabled: false,
          arbitrary_command_execution_enabled: false,
          public_write_enabled: true,
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          available_lanes_count: 7,
          repo_count: 1,
          manual_mode: true,
        }),
      });
      return;
    }

    if (pathname.endsWith("/agent-lanes")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          manual_mode: true,
          lanes: [
            {
              lane_id: "codex_cli",
              title: "Codex CLI",
              installed: true,
              runner_mode: "controlled_run_ready",
              executable_path: "/root/.hermes/node/bin/codex",
              version: "codex-cli 0.137.0",
              auth_status: "likely_ready",
              safety_notes: ["tmux available: True"],
            },
          ],
        }),
      });
      return;
    }

    if (await fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled: true })) {
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          mode: "server_control_plane",
          repos: [
            {
              repo_id: "mcharness-public-export",
              label: "mcharness-public-export",
              path: "/root/mcharness-public-export",
            },
          ],
        }),
      });
      return;
    }

    if (pathname.endsWith("/sessions") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session_id: "quick-reply-session" }),
      });
      return;
    }

    if (pathname.endsWith("/queue") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queue_item_id: "queue-1" }),
      });
      return;
    }

    if (pathname.endsWith("/prompt-export") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
      return;
    }

    if (pathname.endsWith("/runner/start") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-prompt") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, injected: true }),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-key") && method === "POST") {
      if (body.key === "Submit / Continue") {
        sendKeyCalls.push("Tab", "Enter");
        runnerStatus = { ...runnerStatus, status: "prompt_sent" };
        transcriptText = `${transcriptText}\n# [submit/continue]\nPrompt sent to Codex.\n`;
      } else {
        sendKeyCalls.push(body.key);
        runnerStatus = { ...runnerStatus, status: "prompt_sent" };
        transcriptText = `${transcriptText}\n# [quick reply ${body.key}]\nSent: ${body.key}\n`;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          session_id: runnerStatus.session_id,
          runner_id: runnerStatus.runner_id,
          lane_id: runnerStatus.lane_id,
          tmux_session_name: runnerStatus.tmux_session_name,
          sent_key: body.key,
          status: runnerStatus.status,
          status_note: body.key === "Submit / Continue" ? "Prompt sent to Codex." : undefined,
          transcript_excerpt: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: runnerStatus.session_id,
          runner_id: runnerStatus.runner_id,
          lane_id: runnerStatus.lane_id,
          status: runnerStatus.status,
          transcript_path: "/tmp/quick-reply-transcript.txt",
          transcript: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/stop")) {
      runnerStatus = { ...runnerStatus, status: "stopped" };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...runnerStatus, stopped_at: new Date().toISOString() }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("http://127.0.0.1:8125/web/warden/index.html");
  await page.locator("[data-testid='nav-agents']").click();
  await expect(page.locator("[data-testid='warden-section-agents'] .workspace-title")).toHaveText("Agents");

  await page.evaluate(() => window.McHarnessSimple.openUseAgentModal());
  const useModal = page.locator("#use-agent-modal");
  await expect(useModal).toBeVisible();
  await useModal.locator("#modal-task-title").fill("Private quick reply smoke");
  await useModal.locator("#modal-prompt").fill("Safe smoke prompt");
  await useModal.locator("#deploy-prompt-btn").click();

  const mon = page.locator("#live-cli-modal");
  await expect(mon).toBeVisible();
  await expect(mon).toContainText("Codex Live Monitor");
  await expect(mon.locator("[data-testid='modal-transcript']")).toBeVisible();
  await expect(mon.locator("[data-testid='modal-transcript']")).toHaveCSS("overflow-y", /auto|scroll/);
  await expect(mon.locator("[data-testid='quick-reply-panel']")).toBeVisible();
  await expect(mon.locator("[data-testid='quick-reply-panel']")).toContainText("Use for Codex menus and approvals.");
  await expect(mon.locator("[data-quick-reply='1']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='2']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='3']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='Submit / Continue']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='Enter']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='Esc']")).toBeVisible();
  await expect(mon.locator("[data-quick-reply='Ctrl+C']")).toBeVisible();
  await expect(mon.locator("[data-testid='modal-jump-latest']")).toBeVisible();
  await expect(mon.locator("[data-testid='modal-expand']")).toBeVisible();
  await expect(mon.locator("[data-testid='modal-autorefresh']")).toBeVisible();
  await expect(mon.locator("[data-testid='modal-save-evidence']")).toBeVisible();
  await expect(page.locator("#live-cli-modal input, #live-cli-modal textarea")).toHaveCount(0);
  await expect(page.locator("[data-testid='modal-refresh']")).toContainText("Refresh");
  await expect(page.locator("[data-testid='modal-expand']")).toContainText("Bigger View");
  await expect(page.locator("[data-testid='modal-copy-attach']")).toContainText("Copy Terminal Command");
  await expect(page.locator("[data-testid='modal-save-evidence']")).toContainText("Save Output");
  await expect(page.locator("[data-testid='modal-stop']")).toContainText("Stop Codex");

  const transcript = mon.locator("[data-testid='modal-transcript']");
  const initialMetrics = await transcript.evaluate((el) => ({
    scrollTop: el.scrollTop,
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  }));
  expect(initialMetrics.scrollHeight).toBeGreaterThan(initialMetrics.clientHeight);
  expect(initialMetrics.scrollTop).toBeGreaterThan(0);

  await transcript.evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
  await expect(page.locator("[data-testid='modal-autoscroll-indicator']")).toBeVisible();
  await expect(page.locator("[data-testid='modal-autoscroll-indicator']")).toContainText("Scrolled up — updates paused here");

  transcriptText = `${transcriptText}\n${makeTranscript(40, "Follow-up output")}`;
  await page.evaluate(() => window.McHarnessSimple.refreshLiveMonitor());
  await expect.poll(async () => transcript.evaluate((el) => el.scrollTop)).toBe(0);

  await mon.locator("[data-testid='modal-jump-latest']").click();
  await expect(page.locator("[data-testid='modal-autoscroll-indicator']")).toBeHidden();
  await expect.poll(async () => transcript.evaluate((el) => el.scrollTop > 0)).toBe(true);

  await mon.locator("[data-testid='modal-expand']").click();
  await expect(mon).toHaveClass(/monitor-expanded/);
  await mon.locator("[data-testid='modal-expand']").click();
  await expect(mon).not.toHaveClass(/monitor-expanded/);
  await expect(mon.locator("[data-testid='modal-transcript']")).not.toContainText("Prompt appears pasted but no Codex response yet. Try Enter quick reply or attach manually.");
  await expect(page.locator("#modal-info")).toContainText("Repo: mcharness-public-export");
  await expect(page.locator("#modal-info")).toContainText("Status: Running");
  await expect(page.locator("#modal-info")).toContainText("Session: mch_quick_reply");

  await mon.locator("[data-quick-reply='2']").click();
  await expect(page.locator("[data-testid='quick-reply-status']")).toContainText("Sent: 2");
  await expect(page.locator("[data-testid='modal-transcript']")).toContainText("Sent: 2");
  await expect(page.locator("[data-testid='modal-transcript']")).toContainText("quick reply 2");
  await expect.poll(() => sendKeyCalls.length).toBe(1);
  await expect(sendKeyCalls[0]).toBe("2");

  await mon.locator("[data-quick-reply='Enter']").click();
  await expect.poll(() => sendKeyCalls.length).toBe(2);
  await expect(sendKeyCalls[1]).toBe("Enter");
  await expect(page.locator("[data-testid='quick-reply-status']")).toContainText("Sent: Enter");

  await mon.locator("[data-quick-reply='Submit / Continue']").click();
  await expect.poll(() => sendKeyCalls.length).toBe(4);
  await expect(sendKeyCalls.slice(-2)).toEqual(["Tab", "Enter"]);
  await expect(page.locator("[data-testid='quick-reply-status']")).toContainText("Prompt sent to Codex.");
  await expect(page.locator("[data-testid='modal-transcript']")).toContainText("Prompt sent to Codex.");

  await mon.locator("#modal-stop").click();
  await expect.poll(() => runnerStatus.status).toBe("stopped");
});

test("Captain Deck creates a plan and deploys the first prompt", async ({ page }) => {
  let transcriptText = [
    "Captain runner started.",
    "Waiting for first prompt.",
  ].join("\n");
  let runnerStatus = {
    session_id: "captain-plan-session",
    runner_id: "run_captain_plan",
    lane_id: "codex_cli",
    repo_id: "hybrid-agent-os",
    status: "waiting_for_codex",
    tmux_session_name: "mch_captain_plan",
    attach_command: "tmux attach -t mch_captain_plan",
  };
  const runnerStartCalls = [];
  const sendPromptCalls = [];
  const captainLoopCtx = {
    activePlan: null,
    runnerStatus: null,
    runnerStartCalls,
    dispatchCalls: [],
  };
  const captainPlanResponse = normalizeMockCaptainPlan({
    ok: true,
    plan_id: "plan_1234",
    title: "Build AOL-inspired webpage",
    summary: "Create an AOL-inspired homepage layout in the existing frontend.",
    repo_id: "hybrid-agent-os",
    steps: [
      {
        id: "step_1",
        title: "Inspect frontend structure",
        agent: "codex_cli",
        prompt: "Exact goal: Build a webpage just like aol.com\nForbidden actions: no push, merge, reset, rebase.\nAcceptance checks: identify the entrypoint.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
        status: "queued",
      },
      {
        id: "step_2",
        title: "Implement layout",
        agent: "codex_cli",
        prompt: "Exact goal: Build a webpage just like aol.com\nForbidden actions: no push, merge, reset, rebase.\nAcceptance checks: make the requested layout change.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
        status: "queued",
      },
      {
        id: "step_3",
        title: "Verify and report",
        agent: "codex_cli",
        prompt: "Exact goal: Build a webpage just like aol.com\nForbidden actions: no push, merge, reset, rebase.\nAcceptance checks: run the focused checks and report proof.\nFinal proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
        status: "queued",
      },
    ],
    notes: ["OpenRouter model: openrouter/auto"],
  });

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;
    captainLoopCtx.runnerStatus = runnerStatus;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          mode: "public_manual",
          real_agent_launch_enabled: false,
          arbitrary_command_execution_enabled: false,
          public_write_enabled: true,
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          available_lanes_count: 7,
          repo_count: 2,
          manual_mode: true,
        }),
      });
      return;
    }

    if (await fulfillCaptainLoopRoute(route, captainLoopCtx)) {
      return;
    }

    if (pathname.endsWith("/agent-lanes")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          manual_mode: true,
          lanes: [
            {
              lane_id: "codex_cli",
              title: "Codex CLI",
              installed: true,
              runner_mode: "controlled_run_ready",
              executable_path: "/root/.hermes/node/bin/codex",
              version: "codex-cli 0.137.0",
              auth_status: "likely_ready",
              safety_notes: ["tmux available: True"],
            },
          ],
        }),
      });
      return;
    }

    if (await fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled: true })) {
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          mode: "server_control_plane",
          repos: [
            {
              repo_id: "hybrid-agent-os",
              label: "hybrid-agent-os",
              path: "/root/hybrid-agent-os",
            },
            {
              repo_id: "mcharness-public-export",
              label: "mcharness-public-export",
              path: "/root/mcharness-public-export",
            },
          ],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          configured: true,
          provider: "openrouter",
          model: "openrouter/auto",
          planning_enabled: true,
          notes: [],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/plan") && method === "POST") {
      captainLoopCtx.activePlan = captainPlanResponse;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(captainPlanResponse),
      });
      return;
    }

    if (pathname.endsWith("/sessions") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session_id: runnerStatus.session_id }),
      });
      return;
    }

    if (pathname.endsWith("/queue") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queue_item_id: "queue-captain-1" }),
      });
      return;
    }

    if (pathname.endsWith("/prompt-export") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
      return;
    }

    if (pathname.endsWith("/runner/start") && method === "POST") {
      runnerStartCalls.push(body);
      runnerStatus = { ...runnerStatus, status: "running" };
      captainLoopCtx.runnerStatus = runnerStatus;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-prompt") && method === "POST") {
      sendPromptCalls.push(body.prompt);
      transcriptText = `${transcriptText}\n${body.prompt}\nCaptain response pending.`;
      runnerStatus = { ...runnerStatus, status: "awaiting_response" };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          injected: true,
          session_id: runnerStatus.session_id,
          status: runnerStatus.status,
          transcript_excerpt: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: runnerStatus.session_id,
          runner_id: runnerStatus.runner_id,
          lane_id: runnerStatus.lane_id,
          status: runnerStatus.status,
          transcript_path: "/tmp/captain-plan-transcript.txt",
          transcript: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/stop")) {
      runnerStatus = { ...runnerStatus, status: "stopped" };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...runnerStatus, stopped_at: new Date().toISOString() }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("http://127.0.0.1:8125/web/warden/index.html");
  await expect(page.locator("[data-testid='develop-plan-primary']")).toBeVisible();

  await page.locator("[data-testid='develop-plan-primary']").click();
  const captainModal = page.locator("#captain-deck-modal");
  await expect(captainModal).toBeVisible();
  await captainModal.locator("#captain-goal").fill("Build a webpage just like aol.com");
  await expect(captainModal.locator("#captain-create-plan")).toBeEnabled();
  await captainModal.locator("#captain-create-plan").click();
  await expect(captainModal.locator("[data-testid='captain-plan-status']")).toContainText("Plan ready: Build AOL-inspired webpage");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Build AOL-inspired webpage");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Inspect frontend structure");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Implement layout");
  await expect(captainModal.locator("[data-testid='captain-plan-body']")).toContainText("Verify and report");
  await expect(captainModal.locator("[data-testid='captain-deploy-first']")).toBeEnabled();
  await expect(captainModal.locator("[data-testid='captain-copy-plan']")).toBeEnabled();

  await page.evaluate(() => {
    const original = window.setTimeout;
    window.setTimeout = (fn, ms, ...args) => (ms === 10000 ? original(fn, 0, ...args) : original(fn, ms, ...args));
  });

  await captainModal.locator("[data-testid='captain-deploy-first']").click();
  await expect.poll(() => runnerStartCalls.length).toBe(1);
  await expect.poll(() => sendPromptCalls.length).toBe(1);
  await expect(sendPromptCalls[0]).toContain("Exact goal: Build a webpage just like aol.com");
  await expect(page.locator("#captain-deck-modal")).not.toBeVisible();

  const mon = page.locator("#live-cli-modal");
  await expect(mon).toBeVisible();
  await expect(page.locator("#modal-info")).toContainText("Repo: hybrid-agent-os");
  await expect(page.locator("#modal-info")).toContainText("Status: Running");
  await expect(page.locator("[data-testid='quick-reply-status']")).toContainText("Prompt sent to Codex.");
  await expect(mon.locator("[data-testid='modal-transcript']")).toContainText("Captain response pending.");
  await mon.locator("#modal-stop").click();
  await expect.poll(() => runnerStatus.status).toBe("stopped");
});

test("Captain supervised step loop advances manually in Mission", async ({ page }) => {
  let runnerStatus = {
    session_id: "captain-loop-session",
    runner_id: "run_captain_loop",
    lane_id: "codex_cli",
    repo_id: "hybrid-agent-os",
    status: "waiting_for_codex",
    tmux_session_name: "mch_captain_loop",
    attach_command: "tmux attach -t mch_captain_loop",
  };
  const sendPromptCalls = [];
  const captainLoopCtx = {
    activePlan: null,
    runnerStatus: null,
    dispatchCalls: [],
    completeCalls: [],
    reviseCalls: [],
    stopCalls: [],
  };
  const captainPlanResponse = normalizeMockCaptainPlan({
    ok: true,
    plan_id: "plan_loop_ui",
    title: "Captain Loop UI Plan",
    summary: "Supervised manual progression.",
    repo_id: "hybrid-agent-os",
    steps: [
      {
        id: "step_1",
        title: "Inspect frontend structure",
        agent: "codex_cli",
        prompt: "Inspect the frontend entrypoints only.",
        status: "queued",
      },
      {
        id: "step_2",
        title: "Implement layout",
        agent: "codex_cli",
        prompt: "Implement the requested layout change.",
        status: "queued",
      },
    ],
  });

  page.on("dialog", async (dialog) => {
    await dialog.accept("Inspect the frontend entrypoints and report only.");
  });

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;
    captainLoopCtx.runnerStatus = runnerStatus;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          public_write_enabled: true,
        }),
      });
      return;
    }

    if (await fulfillControlRoomRoutes(route, {
      snapshot: idleMissionSnapshot({
        service_mode: "private",
        mission: { status: "planned", mission_id: "plan_loop_ui", title: "Captain Loop UI Plan", progress_pct: 10 },
        plan: { plan_id: "plan_loop_ui", steps: captainPlanResponse.steps },
      }),
      runner: idleRunnerSessions({ service_mode: "private" }),
    })) {
      return;
    }

    if (await fulfillCaptainLoopRoute(route, captainLoopCtx)) {
      return;
    }

    if (await fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled: true })) {
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          repos: [
            { repo_id: "hybrid-agent-os", label: "hybrid-agent-os", path: "/root/hybrid-agent-os" },
          ],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, configured: true, planning_enabled: true, provider: "openrouter", model: "openrouter/auto" }),
      });
      return;
    }

    if (pathname.endsWith("/captain/plan") && method === "POST") {
      captainLoopCtx.activePlan = captainPlanResponse;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(captainPlanResponse),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-prompt") && method === "POST") {
      sendPromptCalls.push(body.prompt);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, injected: true, session_id: runnerStatus.session_id, status: "awaiting_response" }),
      });
      return;
    }

    if (pathname.endsWith("/runner/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session_id: runnerStatus.session_id, transcript: "Captain loop transcript." }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("http://127.0.0.1:8125/web/warden/index.html");
  await page.locator("[data-testid='develop-plan-primary']").click();
  const captainModal = page.locator("#captain-deck-modal");
  await captainModal.locator("#captain-goal").fill("Prove supervised Captain loop in Mission.");
  await captainModal.locator("#captain-create-plan").click();
  await expect(captainModal.locator("[data-testid='captain-plan-status']")).toContainText("Plan ready: Captain Loop UI Plan");
  await captainModal.locator("[data-testid='captain-close']").click();
  await expect(captainModal).not.toBeVisible();
  await expect(page.locator("[data-testid='current-mission-plan']")).toBeVisible();
  await expect(page.locator("[data-testid='captain-plan-steps']")).toContainText("Inspect frontend structure");
  await expect(page.locator("[data-testid='captain-step-actions-step_1']")).toContainText("Deploy Current Step");

  await page.evaluate(() => {
    const original = window.setTimeout;
    window.setTimeout = (fn, ms, ...args) => (ms === 10000 ? original(fn, 0, ...args) : original(fn, ms, ...args));
  });

  await page.locator("[data-testid='captain-step-actions-step_1'] button:has-text('Mark Step Done')").click();
  await expect.poll(() => captainLoopCtx.completeCalls.length).toBe(1);
  expect(captainLoopCtx.dispatchCalls.length).toBe(0);
  await expect(page.locator("[data-testid='captain-step-actions-step_2']")).toContainText("Deploy Next Step");

  await page.locator("[data-testid='captain-step-actions-step_2'] button:has-text('Deploy Next Step')").click();
  await expect.poll(() => captainLoopCtx.dispatchCalls.length).toBe(1);
  await expect(page.locator("#live-cli-modal")).toBeVisible();
  await expect.poll(() => sendPromptCalls.length).toBe(1);

  await page.locator("#live-cli-modal #modal-close, #live-cli-modal .modal-close").first().click({ force: true }).catch(() => {});
  await page.evaluate(() => {
    const modal = document.getElementById("live-cli-modal");
    if (modal) modal.style.display = "none";
  });

  await page.locator("[data-testid='captain-step-actions-step_2'] button:has-text('Revise Step')").click();
  await expect.poll(() => captainLoopCtx.reviseCalls.length).toBe(1);
  await expect(page.locator("[data-testid='captain-plan-steps']")).toContainText("REVISED");

  await page.locator("[data-testid='captain-stop-plan']").click();
  await expect.poll(() => captainLoopCtx.stopCalls.length).toBe(1);
  await expect(page.locator("[data-testid='cr-mission-empty']")).toBeVisible();
});

test("Agent Registry configure flow and Captain dropdown use registered agents", async ({ page }) => {
  let registeredAgents = [];
  const agentPostCalls = [];
  const testConfigCalls = [];

  await page.addInitScript(() => {
    window.__storageWrites = [];
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      window.__storageWrites.push([key, value]);
      return originalSetItem.call(this, key, value);
    };
  });

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          public_write_enabled: true,
        }),
      });
      return;
    }

    if (pathname.endsWith("/agent-lanes")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          manual_mode: true,
          lanes: [{ lane_id: "codex_cli", title: "Codex CLI", installed: true }],
        }),
      });
      return;
    }

    if (pathname.endsWith("/agents/templates")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(agentRegistryTemplatesPayload()),
      });
      return;
    }

    if (pathname.endsWith("/agents") && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          registry_write_enabled: true,
          agents: [builtinCodexAgent(), ...registeredAgents],
        }),
      });
      return;
    }

    if (pathname.endsWith("/agents/test-config") && method === "POST") {
      testConfigCalls.push(body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          adapter: "jules_remote",
          status: "connected",
          message: "Jules API key verified via sources list.",
          safe_details: { sources_count: 1 },
        }),
      });
      return;
    }

    if (pathname.endsWith("/agents") && method === "POST") {
      agentPostCalls.push(body);
      const created = {
        id: "jules_remote_test01",
        name: body.name,
        kind: body.kind,
        adapter: body.adapter,
        enabled: body.enabled,
        builtin: false,
        user_created: true,
        status: "ready",
        connection_status: "connected",
        configured: true,
        runnable: false,
        description: "Jules profile only.",
        capabilities: ["remote_planning", "status_tracking"],
      };
      registeredAgents = [created];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, agent: created }),
      });
      return;
    }

    if (pathname.match(/\/agents\/[^/]+$/) && method === "DELETE") {
      registeredAgents = [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, deleted_id: pathname.split("/").pop() }),
      });
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          repos: [{ repo_id: "mcharness-public-export", label: "mcharness-public-export", path: "/root/mcharness-public-export" }],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          configured: true,
          provider: "openrouter",
          model: "openrouter/auto",
          planning_enabled: true,
          key_source: "env",
          private_key_setup_enabled: true,
          notes: [],
        }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("/web/warden/index.html");
  await expect(page.locator("h1")).toContainText("Warden");
  await expect(page.locator("[data-testid='nav-mission']")).toHaveClass(/active/);
  await page.locator("[data-testid='nav-agents']").click();
  await expect(page.locator("[data-testid='warden-section-agents'] .workspace-title")).toHaveText("Agents");
  await expect(page.locator("[data-testid='agent-group-cli']")).toContainText("CLI Agents");
  await expect(page.locator("#codex-card")).toContainText("Codex CLI");
  await expect(page.getByRole("button", { name: "Add Agent" })).toBeVisible();
  await expect(page.locator("input[type='text'][placeholder*='shell'], textarea[placeholder*='shell']")).toHaveCount(0);

  await page.getByRole("button", { name: "Add Agent" }).click();
  const addModal = page.locator("#add-agent-modal");
  await expect(addModal).toBeVisible();
  await expect(addModal.locator("[data-testid='add-agent-step-choose']")).toBeVisible();
  await expect(addModal.locator("[data-testid='add-agent-category-list']")).toContainText("Captain profile");
  await expect(addModal.locator("[data-testid='add-agent-remote-options'] button[data-template-adapter='jules_remote']")).toBeVisible();
  await expect(addModal.locator("button[data-template-adapter='custom_cli']")).toHaveCount(0);

  await addModal.locator("[data-testid='add-agent-remote-options'] button[data-template-adapter='jules_remote']").click();
  await expect(addModal.locator("[data-testid='add-agent-step-config']")).toBeVisible();
  await expect(addModal.locator("[data-testid='add-agent-api-key']")).toHaveAttribute("type", "password");
  await expect(addModal.locator("[data-testid='add-agent-test']")).toBeVisible();
  await expect(addModal.locator("[data-testid='add-agent-save']")).toBeDisabled();

  await addModal.locator("[data-testid='add-agent-name']").fill("Jules Remote Worker");
  await addModal.locator("[data-testid='add-agent-api-key']").fill("test-jules-key");
  await addModal.locator("[data-testid='add-agent-test']").click();
  await expect.poll(() => testConfigCalls.length).toBe(1);
  await expect(testConfigCalls[0].adapter).toBe("jules_remote");
  await expect(testConfigCalls[0].api_key).toBe("test-jules-key");
  await expect(addModal.locator("[data-testid='add-agent-test-status']")).toContainText("Jules API key verified");
  await expect(addModal.locator("[data-testid='add-agent-save']")).toBeEnabled();

  await addModal.locator("[data-testid='add-agent-save']").click();
  await expect.poll(() => agentPostCalls.length).toBe(1);
  await expect(agentPostCalls[0].adapter).toBe("jules_remote");
  await expect(agentPostCalls[0].api_key).toBe("test-jules-key");
  await expect(addModal.locator("[data-testid='add-agent-api-key']")).toHaveValue("");
  await expect(page.locator("[data-testid='agent-group-remote']")).toBeVisible();
  await expect(page.locator("[data-testid='agent-group-remote']")).toContainText("Remote Agents");
  await expect(page.locator(".registered-agent-card")).toContainText("Jules Remote");
  await expect(page.locator(".registered-agent-card")).toContainText("Planning and status only");
  await expect(page.locator(".registered-agent-card")).toContainText("Not executable");
  await expect(page.locator(".registered-agent-card button", { hasText: "Use Agent" })).toHaveCount(0);
  await expect(page.locator(".registered-agent-card button", { hasText: "View Config" })).toBeVisible();
  await expect(page.locator(".registered-agent-card [data-testid='view-agent-jules']")).toHaveCount(0);
  await expect(page.evaluate(() => window.__storageWrites || [])).resolves.toEqual([]);

  await page.locator("[data-testid='develop-plan-primary']").click();
  const captainModal = page.locator("#captain-deck-modal");
  await expect(captainModal).toBeVisible();
  await expect(captainModal.locator("[data-testid='captain-agent-select']")).toContainText("Codex CLI — Ready");
  await expect(captainModal.locator("[data-testid='captain-agent-select']")).toContainText("Jules Remote Worker — Connected, execution coming next");
  await captainModal.locator("[data-testid='captain-agent-select']").selectOption("jules_remote_test01");
  await expect(captainModal.locator("[data-testid='captain-agent-note']")).toContainText("Jules Remote is configured for planning/status only. Execution comes next.");
  await expect(captainModal.locator("[data-testid='captain-create-plan']")).toBeDisabled();
  await expect(captainModal.locator("[data-testid='captain-deploy-first']")).toBeDisabled();
  await captainModal.locator("[data-testid='captain-agent-select']").selectOption("codex_cli");
  await expect(captainModal.locator("[data-testid='captain-agent-note']")).toBeHidden();
});

test("run history and evidence appear after private Codex dispatch", async ({ page }) => {
  const runs = [];
  const evidence = [];
  let transcriptText = "Codex output line 1\nCodex output line 2\n";
  let runnerStatus = {
    session_id: "history-session",
    runner_id: "run_history01",
    lane_id: "codex_cli",
    repo_id: "mcharness-public-export",
    status: "running",
    tmux_session_name: "mch_history",
    attach_command: "tmux attach -t mch_history",
  };

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();
    const body = route.request().postDataJSON ? route.request().postDataJSON() : null;

    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          service: "mcharness-control-plane",
          commit: "test-commit",
          mode: "public_manual",
          real_agent_launch_enabled: false,
          arbitrary_command_execution_enabled: false,
          public_write_enabled: true,
          tmux_runner_enabled: true,
          codex_runner_enabled: true,
          available_lanes_count: 7,
          repo_count: 1,
          manual_mode: true,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runs/recent")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ service: "mcharness-control-plane", service_mode: "private", runs }),
      });
      return;
    }

    if (pathname.match(/\/runs\/[^/]+$/) && method === "GET") {
      const runId = pathname.split("/").pop();
      const run = runs.find((item) => item.run_id === runId);
      if (!run) {
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Run not found" }) });
        return;
      }
      const linked = evidence.filter((item) => item.run_id === runId);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ service: "mcharness-control-plane", service_mode: "private", run, evidence: linked }),
      });
      return;
    }

    if (pathname.endsWith("/evidence/recent")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ service: "mcharness-control-plane", service_mode: "private", evidence }),
      });
      return;
    }

    if (pathname.match(/\/evidence\/[^/]+$/) && method === "GET") {
      const evidenceId = pathname.split("/").pop();
      const item = evidence.find((entry) => entry.evidence_id === evidenceId);
      if (!item) {
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Evidence not found" }) });
        return;
      }
      const linkedRun = runs.find((run) => run.run_id === item.run_id);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          service_mode: "private",
          evidence: { ...item, content: item.content_excerpt },
          linked_run: linkedRun ? { run_id: linkedRun.run_id, title: linkedRun.title, status: linkedRun.status } : null,
        }),
      });
      return;
    }

    if (pathname.endsWith("/agent-lanes")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          manual_mode: true,
          lanes: [{ lane_id: "codex_cli", title: "Codex CLI", installed: true, runner_mode: "controlled_run_ready" }],
        }),
      });
      return;
    }

    if (await fulfillAgentRegistryRoute(route, { method, pathname, registryWriteEnabled: true })) {
      return;
    }

    if (pathname.endsWith("/repos")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          service: "mcharness-control-plane",
          repos: [{ repo_id: "mcharness-public-export", label: "mcharness-public-export", path: "/root/mcharness-public-export" }],
        }),
      });
      return;
    }

    if (pathname.endsWith("/captain/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          configured: true,
          provider: "openrouter",
          model: "openrouter/auto",
          planning_enabled: true,
          key_source: "env",
          private_key_setup_enabled: true,
          notes: [],
        }),
      });
      return;
    }

    if (pathname.endsWith("/sessions") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session_id: "history-session" }),
      });
      return;
    }

    if (pathname.endsWith("/queue") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queue_item_id: "queue-history-1" }),
      });
      return;
    }

    if (pathname.endsWith("/prompt-export") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompt_text: "History prompt export" }),
      });
      return;
    }

    if (pathname.endsWith("/runner/start") && method === "POST") {
      const run = {
        run_id: runnerStatus.runner_id,
        title: body.title || "History smoke",
        agent_id: "codex_cli",
        agent_adapter: "codex_cli",
        repo_id: "mcharness-public-export",
        status: "dispatched",
        started_at: "2026-06-09T12:00:00.000Z",
        prompt_excerpt: body.prompt || "History prompt",
        transcript_excerpt: "",
        evidence_count: 0,
        evidence_ids: [],
      };
      runs.unshift(run);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...runnerStatus,
          warden_run: run,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/send-prompt") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, status: "running", transcript_excerpt: transcriptText }),
      });
      return;
    }

    if (pathname.endsWith("/runner/status")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runnerStatus),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: "history-session",
          runner_id: runnerStatus.runner_id,
          transcript: transcriptText,
        }),
      });
      return;
    }

    if (pathname.endsWith("/runner/transcript-to-evidence") && method === "POST") {
      const item = {
        evidence_id: "ev_history01",
        run_id: runnerStatus.runner_id,
        type: "transcript",
        title: "Codex transcript snapshot",
        summary: "Saved runner transcript as evidence",
        content_excerpt: transcriptText,
        created_at: "2026-06-09T12:05:00.000Z",
        agent_id: "codex_cli",
        source: "live_monitor",
        redacted: false,
      };
      evidence.unshift(item);
      const run = runs.find((entry) => entry.run_id === runnerStatus.runner_id);
      if (run) {
        run.evidence_count = 1;
        run.evidence_ids = [item.evidence_id];
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, warden_evidence: item }),
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled route: ${pathname}` }) });
  });

  await page.goto("/web/warden/index.html");
  await page.locator("[data-testid='nav-runs']").click();
  await expect(page.locator("[data-testid='runs-empty-state']")).toBeVisible();

  await page.locator("[data-testid='nav-agents']").click();
  await page.evaluate(() => window.McHarnessSimple.openUseAgentModal());
  const useModal = page.locator("#use-agent-modal");
  await useModal.locator("#modal-task-title").fill("History smoke");
  await useModal.locator("#modal-prompt").fill("Capture run history after dispatch.");
  await useModal.locator("#deploy-prompt-btn").click();

  const liveModal = page.locator("#live-cli-modal");
  await expect(liveModal).toBeVisible();
  await liveModal.locator("[data-testid='modal-close']").click();
  await expect(liveModal).not.toBeVisible();
  await page.locator("[data-testid='nav-runs']").click();
  await expect(page.locator("[data-testid='runs-list']")).toBeVisible();
  await expect(page.locator("[data-testid='runs-list']")).toContainText("History smoke");
  await expect(page.locator("[data-testid='runs-list']")).toContainText("codex_cli");
  await page.locator("[data-testid='runs-list'] button", { hasText: "View Run" }).click();
  const runModal = page.locator("#run-detail-modal");
  await expect(runModal).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-prompt']")).toContainText("Capture run history");
  await runModal.locator("[data-testid='run-detail-close']").click();

  await page.locator("[data-testid='nav-agents']").click();
  await page.locator("[data-testid='codex-open-monitor']").click();
  await page.locator("[data-testid='modal-save-evidence']").click();
  await expect(page.locator("[data-testid='quick-reply-status']")).toContainText("Transcript saved as evidence");
  await liveModal.locator("[data-testid='modal-close']").click();
  await expect(liveModal).not.toBeVisible();

  await page.locator("[data-testid='nav-evidence']").click();
  await expect(page.locator("[data-testid='evidence-list']")).toBeVisible();
  await expect(page.locator("[data-testid='evidence-list']")).toContainText("Codex transcript snapshot");
  await page.locator("[data-testid='evidence-list'] button", { hasText: "View Evidence" }).click();
  const evidenceModal = page.locator("#evidence-detail-modal");
  await expect(evidenceModal).toBeVisible();
  await expect(evidenceModal.locator("[data-testid='evidence-detail-content']")).toContainText("Codex output line 1");
  await expect(page.locator("text=sk-or-")).toHaveCount(0);
});

test("Mission timeline filters gate events and shows honest empty states", async ({ page }) => {
  const timelineItems = [
    {
      id: "wl_plan_1",
      kind: "plan_created",
      label: "Plan created",
      title: "Captain plan",
      summary: "Plan persisted.",
      status: "saved",
      created_at: "2026-06-09T12:00:00Z",
      links: { plan_id: "plan_1" },
    },
    {
      id: "wl_gate_created_1",
      kind: "gate_created",
      label: "Proof gate created",
      title: "Review gate",
      summary: "Manual proof gate created.",
      status: "pending",
      created_at: "2026-06-09T12:05:00Z",
      links: { gate_id: "gate_1", run_id: "run_1" },
    },
    {
      id: "wl_gate_approved_1",
      kind: "gate_approved",
      label: "Proof gate approved",
      title: "Review gate",
      summary: "Looks good.",
      status: "approved",
      created_at: "2026-06-09T12:10:00Z",
      links: { gate_id: "gate_1", run_id: "run_1" },
    },
  ];

  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route, {
      snapshot: idleMissionSnapshot({ timeline: { items: timelineItems }, worklog: { items: timelineItems } }),
    })) return;
    await route.continue();
  });

  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='cr-panel-timeline']")).toBeVisible();
  await expect(page.locator("[data-testid='cr-timeline-item']")).toHaveCount(3);

  await page.locator("[data-cr-timeline-filter='gates']").click();
  await expect(page.locator("[data-testid='cr-timeline-item']")).toHaveCount(2);

  await page.locator("[data-cr-timeline-filter='evidence']").click();
  await expect(page.locator("[data-testid='cr-timeline-item']")).toHaveCount(0);
  await expect(page.getByText("No timeline events match this filter.")).toBeVisible();
  await expect(page.locator("text=Advanced / Legacy Cockpit")).toHaveCount(0);
  await expect(page.locator("text=SERVER CONTROL PLANE")).toHaveCount(0);
});

test("Run detail review flow exposes sections and manual actions by gate state", async ({ page }) => {
  const pendingGate = {
    gate_id: "gate_review_1",
    title: "Pending gate",
    status: "pending",
    gate_type: "manual_review",
    created_at: "2026-06-09T12:01:00Z",
    summary: "Awaiting review.",
    decision_log: [],
  };
  const runDetail = {
    run_id: "run_review_1",
    title: "Review smoke",
    agent_id: "codex_cli",
    status: "completed",
    started_at: "2026-06-09T12:00:00Z",
    prompt_excerpt: "Review this run.",
    transcript_excerpt: "Done.",
    gate_status: "pending",
    gate_label: "Proof pending",
  };

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    if (pathname.endsWith("/health")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tmux_runner_enabled: true, codex_runner_enabled: true }),
      });
      return;
    }
    if (pathname.endsWith("/runs/recent")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ runs: [runDetail] }),
      });
      return;
    }
    if (pathname.endsWith("/runs/run_review_1/gates")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gates: [pendingGate] }),
      });
      return;
    }
    if (pathname.endsWith("/runs/run_review_1")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          run: runDetail,
          evidence: [{ evidence_id: "ev_1", title: "Transcript", type: "transcript" }],
          gates: [pendingGate],
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });

  await page.goto("/web/warden/index.html");
  await page.locator("[data-testid='nav-runs']").click();
  await page.locator("[data-testid='runs-list'] button", { hasText: "View Run" }).click();
  const runModal = page.locator("#run-detail-modal");
  await expect(runModal).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-summary-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-transcript-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-evidence-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-gates-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-decisions-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-next-actions-section']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-approve-gate']")).toBeVisible();
  await expect(runModal.locator("[data-testid='run-detail-export']")).toBeVisible();
});

test("Control Room loads by default with bold product headline", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='nav-mission']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='cr-hero-title']")).toContainText("Control Room");
  await expect(page.locator("[data-testid='warden-topbar']")).toBeVisible();
});

test("demo mode is visibly labeled simulated", async ({ page }) => {
  await page.goto("/web/warden/index.html?demo=1");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='demo-mode-banner']")).toBeVisible();
  await expect(page.locator("[data-testid='demo-mode-banner']")).toContainText("Demo data — simulated preview");
  await expect(page.locator("[data-testid='cr-mission-active']")).toBeVisible();
});

test("demo mode renders simulated mission title", async ({ page }) => {
  await page.goto("/web/warden/index.html?demo=1");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("#cr-mission-title")).toContainText("Warden auth hardening sprint");
  await expect(page.locator("#cr-mission-id")).toContainText("plan_demo01");
  await expect(page.locator("[data-testid='cr-mission-status-pill']")).toContainText("in progress");
});

test("demo mode renders populated proof gates", async ({ page }) => {
  await page.goto("/web/warden/index.html?demo=1");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='rail-proof-gates']")).toContainText("1 passed");
  await expect(page.locator("[data-testid='rail-proof-gates']")).toContainText("1 pending");
  await page.locator("[data-testid='cr-tab-gates']").click();
  await expect(page.locator("[data-testid='cr-gate-row']")).toHaveCount(2);
});

test("demo mode renders connected agents", async ({ page }) => {
  await page.goto("/web/warden/index.html?demo=1");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='rail-connected-agents'] [data-testid='rail-agent-row']")).toHaveCount(3);
  await expect(page.locator("[data-testid='rail-connected-agents']")).toContainText("Codex CLI");
  await expect(page.locator("[data-testid='rail-connected-agents']")).toContainText("Captain");
});

test("demo mode renders runner sessions", async ({ page }) => {
  await page.goto("/web/warden/index.html?demo=1");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='rail-runner-sessions']")).toContainText("2 active");
  await expect(page.locator("[data-testid='rail-runner-session-row']")).toHaveCount(2);
  await page.locator("[data-testid='nav-runner-sessions']").click();
  await expect(page.locator("[data-testid='runner-session-row']")).toHaveCount(2);
});

test("real mode does not show demo banner", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='demo-mode-banner']")).toBeHidden();
});

test("real idle state stays honest", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='cr-mission-empty']")).toBeVisible();
  await expect(page.locator("[data-testid='current-mission-status']")).toContainText("No active mission. Start a Captain plan.");
  await expect(page.locator("[data-testid='cr-idle-cards']")).toBeVisible();
  await expect(page.locator("[data-testid='idle-card-captain']")).toContainText("Captain");
  await expect(page.locator("[data-testid='idle-card-agents']")).toContainText("Agents");
  await expect(page.locator("[data-testid='idle-card-runners']")).toContainText("Runners");
  await expect(page.locator("[data-testid='idle-card-safety']")).toContainText("Safety");
  await expect(page.locator("[data-testid='cr-mission-active']")).toBeHidden();
  await expect(page.locator("text=Warden auth hardening sprint")).toHaveCount(0);
});

test("command center tabs switch and right rail renders", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await page.locator("[data-testid='cr-tab-plan']").click();
  await expect(page.locator("[data-testid='cr-panel-plan']")).toHaveClass(/active/);
  await page.locator("[data-testid='cr-tab-gates']").click();
  await expect(page.locator("[data-testid='cr-panel-gates']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='rail-proof-gates-card']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-connected-agents-card']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-runner-sessions-card']")).toBeVisible();
  await expect(page.locator("[data-testid='rail-safety-card']")).toBeVisible();
});

test("command palette opens and runner sessions view renders", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    if (await fulfillControlRoomRoutes(route)) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await page.locator("[data-testid='topbar-command']").click();
  await expect(page.locator("[data-testid='command-palette']")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.locator("[data-testid='nav-runner-sessions']").click();
  await expect(page.locator("[data-testid='warden-section-runner-sessions']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='runner-sessions-summary']")).toBeVisible();
});

test("runner cleanup dry-run uses confirm false on private mock", async ({ page }) => {
  let cleanupBody = null;
  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/runner/sessions/cleanup") && route.request().method() === "POST") {
      cleanupBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ dry_run: true, candidates: ["mch_run_run_stale01"], killed: [], skipped: [], errors: [], inventory: {} }),
      });
      return;
    }
    if (await fulfillControlRoomRoutes(route, {
      snapshot: idleMissionSnapshot({ service_mode: "private" }),
      runner: idleRunnerSessions({ service_mode: "private" }),
    })) return;
    await route.continue();
  });
  await page.goto("/web/warden/index.html");
  await page.waitForSelector("[data-control-room-ready='1']");
  await expect(page.locator("[data-testid='rail-runner-dry-run']")).toBeEnabled();
  await page.locator("[data-testid='rail-runner-dry-run']").click();
  await expect(page.locator("[data-testid='cleanup-dryrun-modal']")).toBeVisible();
  expect(cleanupBody.confirm).toBe(false);
  await page.locator("#cleanup-dryrun-close").click();
  await page.locator("[data-testid='rail-runner-confirm']").click();
  await expect(page.locator("[data-testid='cleanup-confirm-modal']")).toBeVisible();
});

test("Memory cockpit lists, searches, remembers, previews, and redacts", async ({ page }) => {
  const memories = [
    {
      memory_id: "m-decision-1",
      scope: "mcharness-public-export",
      project_id: "mcharness-public-export",
      title: "Private memory decision",
      summary: "Keep Authorization: Bearer browser.fake.token behind the private runner.",
      source: "warden",
      source_ref: "run://run_1",
      tags: ["decision", "private-runner"],
      kind: "decision",
      status: "active",
      created_at: "2026-06-20T10:00:00Z",
      updated_at: "2026-06-20T10:00:00Z",
    },
    {
      memory_id: "m-failure-1",
      scope: "mcharness-public-export",
      project_id: "mcharness-public-export",
      title: "Prior failure",
      summary: "The first context preview was unbounded.",
      source: "test",
      tags: ["failure"],
      kind: "failure",
      status: "active",
      created_at: "2026-06-20T09:00:00Z",
      updated_at: "2026-06-20T09:00:00Z",
    },
  ];
  let rememberBody = null;

  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/memory/health")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, private_only: true, memory_count: memories.length }) });
      return;
    }
    if (url.pathname.endsWith("/memories/search")) {
      const query = (url.searchParams.get("q") || "").toLowerCase();
      const results = memories.filter((memory) => `${memory.title} ${memory.summary}`.toLowerCase().includes(query));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, memories: results, count: results.length }) });
      return;
    }
    if (url.pathname.endsWith("/memories") && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, memories, count: memories.length }) });
      return;
    }
    if (url.pathname.endsWith("/memory/remember") && method === "POST") {
      rememberBody = route.request().postDataJSON();
      const memory = {
        memory_id: "m-handoff-1",
        ...rememberBody,
        summary: rememberBody.content,
        source_ref: "manual://ui",
        created_at: "2026-06-20T11:00:00Z",
        updated_at: "2026-06-20T11:00:00Z",
      };
      memories.unshift(memory);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, memory }) });
      return;
    }
    if (url.pathname.endsWith("/memory/context-pack") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          context: "# Warden Memory Context\n\n## Known Constraints\n- Authorization: Bearer preview.secret.value",
          memory_count: 2,
          memory_ids: ["m-decision-1", "m-failure-1"],
          truncated: false,
          scope: "mcharness-public-export",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/agent-lanes")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ lanes: [] }) });
      return;
    }
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ tmux_runner_enabled: true, codex_runner_enabled: true }) });
      return;
    }
    if (await fulfillAgentRegistryRoute(route, { method, pathname: url.pathname })) return;
    if (await fulfillControlRoomRoutes(route, {
      snapshot: idleMissionSnapshot({ service_mode: "private" }),
      runner: { ...idleRunnerSessions(), service_mode: "private" },
    })) return;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.goto("/web/warden/index.html");
  await page.locator("[data-testid='nav-memory']").click();
  await expect(page.locator("[data-testid='warden-section-memory']")).toHaveClass(/active/);
  await expect(page.locator("[data-testid='memory-status-value']")).toContainText("Memory ready");
  await expect(page.locator("[data-testid='memory-recent-list']")).toContainText("Private memory decision");
  await expect(page.locator("[data-testid='memory-recent-list']")).toContainText("[REDACTED]");
  await expect(page.locator("[data-testid='memory-recent-list']")).not.toContainText("browser.fake.token");

  await page.locator("[data-testid='memory-search-query']").fill("failure");
  await page.locator("[data-testid='memory-search-submit']").click();
  await expect(page.locator("[data-testid='memory-search-results']")).toContainText("Prior failure");

  await page.locator("[data-testid='memory-note-title']").fill("Next handoff");
  await page.locator("[data-testid='memory-note-kind']").selectOption("handoff");
  await page.locator("[data-testid='memory-note-tags']").fill("handoff, api");
  await page.locator("[data-testid='memory-note-content']").fill("Verify the Memory cockpit before the next run.");
  await page.locator("[data-testid='memory-remember-submit']").click();
  await expect(page.locator("[data-testid='memory-remember-status']")).toContainText("Remembered");
  expect(rememberBody.kind).toBe("handoff");
  expect(rememberBody.tags).toEqual(["handoff", "api"]);
  expect(rememberBody.content).toBe("Verify the Memory cockpit before the next run.");

  await page.locator("[data-testid='memory-context-prompt']").fill("Prepare the next private runner task.");
  await page.locator("[data-testid='memory-context-build']").click();
  await expect(page.locator("[data-testid='memory-context-preview']")).toContainText("# Warden Memory Context");
  await expect(page.locator("[data-testid='memory-context-preview']")).toContainText("[REDACTED]");
  await expect(page.locator("[data-testid='memory-context-preview']")).not.toContainText("preview.secret.value");
  await expect(page.locator("[data-testid='memory-context-meta']")).toContainText("2 memories");
  await expect(page.locator("[data-testid='memory-context-sources']")).toContainText("m-decision-1");
});

test("Memory cockpit disables controls on the public service", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("/memory") || url.pathname.endsWith("/memories")) {
      await route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Warden Memory is available only on the private runner service." }) });
      return;
    }
    if (await fulfillControlRoomRoutes(route)) return;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.goto("/web/warden/index.html");
  await page.locator("[data-testid='nav-memory']").click();
  await expect(page.locator("[data-testid='memory-private-notice']")).toBeVisible();
  await expect(page.locator("[data-testid='memory-private-notice']")).toContainText("Memory is private-runner-only.");
  await expect(page.locator("[data-testid='memory-search-submit']")).toBeDisabled();
  await expect(page.locator("[data-testid='memory-remember-submit']")).toBeDisabled();
  await expect(page.locator("[data-testid='memory-context-build']")).toBeDisabled();
});

test("single-section nav: only one workspace section visible at a time", async ({ page }) => {
  await page.route("**/api/mcharness/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("/memory") || url.pathname.endsWith("/memories")) {
      await route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Memory is private-runner-only." }) });
      return;
    }
    if (url.pathname.includes("/warden/memory-agent")) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline" }) });
      return;
    }
    if (url.pathname.includes("/warden/agent")) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline" }) });
      return;
    }
    if (url.pathname.includes("/captain/status")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, configured: false, planning_enabled: false, key_source: "missing", private_key_setup_enabled: false, notes: [] }) });
      return;
    }
    if (await fulfillControlRoomRoutes(route)) return;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.goto("/web/warden/index.html");

  // Default: Command visible, all others hidden
  await expect(page.locator("[data-testid='warden-section-mission']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-section-memory']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-agent']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-gateway']")).toBeHidden();
  await expect(page.locator("[data-testid='nav-mission']")).toHaveClass(/active/);

  // Click Memory Chat — only Memory Chat visible
  await page.locator("[data-testid='nav-memory']").click();
  await expect(page.locator("[data-testid='warden-section-memory']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-section-mission']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-agent']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-gateway']")).toBeHidden();
  await expect(page.locator("[data-testid='nav-memory']")).toHaveClass(/active/);

  // Click Marius Agent — only Marius Agent section visible
  await page.locator("[data-testid='nav-agent']").click();
  await expect(page.locator("[data-testid='warden-section-agent']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-section-memory']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-mission']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-gateway']")).toBeHidden();
  await expect(page.locator("[data-testid='nav-agent']")).toHaveClass(/active/);

  // Click Gateway Status — only Gateway visible
  await page.locator("[data-testid='nav-gateway']").click();
  await expect(page.locator("[data-testid='warden-section-gateway']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-section-agent']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-memory']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-mission']")).toBeHidden();
  await expect(page.locator("[data-testid='nav-gateway']")).toHaveClass(/active/);

  // Click Command — back to default
  await page.locator("[data-testid='nav-mission']").click();
  await expect(page.locator("[data-testid='warden-section-mission']")).toBeVisible();
  await expect(page.locator("[data-testid='warden-section-memory']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-agent']")).toBeHidden();
  await expect(page.locator("[data-testid='warden-section-gateway']")).toBeHidden();
});
