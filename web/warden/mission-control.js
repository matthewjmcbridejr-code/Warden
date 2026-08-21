(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.WardenMissionPresentation = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const browserStatuses = new Set(["working", "needs_user", "completed", "failed"]);

  function missionTitle(objective) {
    const raw = String(objective || "Browser mission").replace(/\s+/g, " ").trim();
    if (!raw) return "Browser mission";
    if (/delete\s+account/i.test(raw)) return "Delete Account Confirmation Test";
    let title = raw
      .replace(/https?:\/\/\S+/gi, "")
      .replace(/^please\s+/i, "")
      .replace(/^(?:use the browser to|in the browser,?)\s+/i, "")
      .replace(/^(?:navigate directly to|go to|open)\s+/i, "")
      .replace(/\s+(?:and then|then|and)\s+(?:report|tell me|click|press|submit).*/i, "")
      .replace(/\s+[-–—:]\s*$/, "")
      .trim();
    if (!title) title = raw.replace(/https?:\/\/\S+/gi, "").trim();
    if (title.length > 56) title = `${title.slice(0, 53).replace(/\s+\S*$/, "")}…`;
    return title.charAt(0).toUpperCase() + title.slice(1);
  }

  function providerLabel(value) {
    const provider = String(value || "").trim();
    if (!provider) return "Computer Use";
    if (/gemini|vertex/i.test(provider)) return "Gemini Computer Use";
    return provider.replace(/ComputerProvider$/i, " Computer Use").replace(/([a-z])([A-Z])/g, "$1 $2");
  }

  function meaningfulAction(meta) {
    const type = String(meta.action_type || "").toLowerCase();
    const summary = String(meta.summary || "").trim();
    if (type === "type" || /^Typed\s+/i.test(summary)) return "Entering text in the page";
    const coordinateClick = summary.match(/^(?:Clicked|Double-clicked|Right-clicked)\s+at\s+\([^)]*\):\s*(.+)$/i);
    if (coordinateClick) return coordinateClick[1] || "Selecting an item on the page";
    if (["click", "double_click", "right_click"].includes(type)) {
      const reason = summary.includes(":") ? summary.split(":").slice(1).join(":").trim() : "";
      return reason || "Selecting an item on the page";
    }
    if (type === "scroll") return "Reviewing more of the page";
    if (type === "key_press" || type === "hotkey") return "Using a keyboard control";
    if (type === "navigate") return summary.replace(/^Navigated to\s+/i, "Opening ") || "Opening a page";
    return summary.replace(/\s+at\s+\(\d+\s*,\s*\d+\)\s*$/i, "") || "Working in the browser…";
  }

  function failureLabel(value) {
    const error = String(value || "").trim();
    if (/resource_exhausted|429/i.test(error)) return "Gemini Computer Use reached its current service quota. Try again shortly.";
    if (/reauthentication|application-default login|invalid.*credential/i.test(error)) return "Gemini Computer Use needs Google Cloud sign-in again before it can continue.";
    return error.replace(/^Computer session failed before completing the objective:\s*/i, "").split(/\.\s*\{'error':/)[0] || "Browser work failed.";
  }

  function outcomeLabel(value) {
    const result = String(value || "").trim();
    if (/^Action prevented:/i.test(result)) return "Action prevented by operator. The browser action was not run.";
    return result;
  }

  function isBrowserEvent(event) {
    return Boolean(event && event.metadata && event.metadata.subsystem === "computer_use" && event.metadata.session_id);
  }

  function blankState() {
    return { lastSeq: 0, missions: {}, order: [] };
  }

  function ensureMission(state, event) {
    const meta = event.metadata || {};
    const id = meta.session_id;
    if (!state.missions[id]) {
      state.missions[id] = {
        id,
        objective: meta.objective || "Browser mission",
        title: missionTitle(meta.objective),
        status: "working",
        workItems: [{ id: `${id}:browser`, type: "browser", status: "working" }],
        needsUser: null,
        evidence: [],
        provider: providerLabel(meta.provider),
        currentStep: 0,
        maxSteps: meta.max_steps || null,
        currentAction: "Starting browser work…",
        currentUrl: null,
        pageTitle: null,
        screenshotUrl: null,
        result: null,
        error: null,
        startedAt: event.created_at || null,
        completedAt: null,
        activity: [],
      };
      state.order.push(id);
    }
    return state.missions[id];
  }

  function setWorkStatus(mission, status) {
    mission.status = browserStatuses.has(status) ? status : mission.status;
    mission.workItems[0].status = mission.status;
  }

  function applyEvent(state, event) {
    if (!isBrowserEvent(event)) return state;
    const meta = event.metadata || {};
    const mission = ensureMission(state, event);
    state.lastSeq = Math.max(state.lastSeq, Number(event.seq) || 0);

    if (meta.objective) mission.objective = meta.objective;
    if (meta.objective) mission.title = missionTitle(meta.objective);
    if (meta.provider) mission.provider = providerLabel(meta.provider);
    if (meta.step != null) mission.currentStep = Number(meta.step) || mission.currentStep;

    switch (meta.phase) {
      case "session_started":
        setWorkStatus(mission, "working");
        mission.currentAction = "Opening the browser…";
        mission.activity.push({ kind: "start", label: "Started browser mission", step: mission.currentStep });
        break;
      case "observation":
        mission.currentUrl = meta.url || mission.currentUrl;
        mission.pageTitle = meta.title || mission.pageTitle;
        mission.screenshotUrl = meta.screenshot_url || mission.screenshotUrl;
        mission.activity.push({ kind: "observation", label: mission.pageTitle ? `Observed ${mission.pageTitle}` : "Captured page observation", step: mission.currentStep });
        if (mission.status !== "needs_user") setWorkStatus(mission, "working");
        break;
      case "action":
        mission.currentAction = meaningfulAction(meta);
        mission.activity.push({ kind: "action", label: mission.currentAction, step: mission.currentStep });
        if (mission.status !== "needs_user") setWorkStatus(mission, "working");
        break;
      case "action_executed":
        mission.currentAction = meaningfulAction(meta);
        mission.lastExecutedActionId = meta.executed === true ? meta.action_id : mission.lastExecutedActionId;
        if (meta.executed === true) mission.activity.push({ kind: "success", label: `Completed: ${meaningfulAction(meta)}`, step: mission.currentStep });
        if (mission.status !== "needs_user") setWorkStatus(mission, "working");
        break;
      case "confirmation_required":
        setWorkStatus(mission, "needs_user");
        mission.currentUrl = meta.url || mission.currentUrl;
        mission.pageTitle = meta.title || mission.pageTitle;
        mission.screenshotUrl = meta.screenshot_url || mission.screenshotUrl;
        mission.needsUser = {
          confirmationId: meta.confirmation_id || event.approval_id,
          sessionId: meta.session_id,
          actionId: meta.action_id,
          actionType: meta.action_type,
          description: meaningfulAction({ action_type: meta.action_type, summary: meta.description || event.text }),
          reason: meta.reason || meta.description || "This action can have an external effect.",
          riskLevel: meta.risk_level || "high",
          pageTitle: meta.title || mission.pageTitle,
          url: meta.url || mission.currentUrl,
          screenshotUrl: meta.screenshot_url || mission.screenshotUrl,
          status: "pending",
        };
        mission.activity.push({ kind: "approval", label: "Approval required for this action", step: mission.currentStep });
        break;
      case "confirmation_resolved":
        if (!mission.needsUser || mission.needsUser.confirmationId === meta.confirmation_id) {
          mission.needsUser = null;
        }
        if (meta.decision === "approve") {
          setWorkStatus(mission, "working");
          mission.currentAction = "Approval recorded. Resuming browser work…";
          mission.activity.push({ kind: "success", label: "Approval granted; resuming work", step: mission.currentStep });
        } else {
          mission.currentAction = meta.status === "expired" ? "Approval expired; action was not run." : "Action denied; it was not run.";
          mission.activity.push({ kind: "warning", label: meta.status === "expired" ? "Approval expired" : "Action denied; action was not run", step: mission.currentStep });
        }
        break;
      case "session_completed": {
        const succeeded = meta.status === "completed";
        setWorkStatus(mission, succeeded ? "completed" : "failed");
        mission.needsUser = null;
        mission.result = meta.result ? outcomeLabel(meta.result) : null;
        mission.error = meta.error ? failureLabel(meta.error) : null;
        mission.currentStep = Number(meta.steps) || mission.currentStep;
        mission.completedAt = event.created_at || null;
        mission.evidence = [{
          kind: succeeded ? "completion" : "failure",
          summary: mission.result || mission.error || (succeeded ? "Browser work completed." : "Browser work failed."),
          steps: mission.currentStep,
          url: mission.currentUrl,
          pageTitle: mission.pageTitle,
          screenshotUrl: mission.screenshotUrl,
        }];
        mission.activity.push({ kind: succeeded ? "success" : "warning", label: succeeded ? "Mission completed" : "Mission failed", step: mission.currentStep });
        break;
      }
      default:
        break;
    }
    return state;
  }

  function reduceEvents(events) {
    const state = blankState();
    const seen = new Set();
    [...(events || [])]
      .sort((a, b) => (Number(a.seq) || 0) - (Number(b.seq) || 0))
      .forEach((event) => {
        const key = event.id || `seq:${event.seq}`;
        if (seen.has(key)) return;
        seen.add(key);
        applyEvent(state, event);
      });
    return state;
  }

  function recoverState(state, sessions, confirmations) {
    for (const snapshot of sessions || []) {
      const event = {
        id: `snapshot:${snapshot.session_id}`,
        seq: 0,
        created_at: snapshot.started_at,
        metadata: {
          subsystem: "computer_use",
          session_id: snapshot.session_id,
          objective: snapshot.objective,
          provider: snapshot.provider,
        },
      };
      const mission = ensureMission(state, event);
      mission.objective = snapshot.objective || mission.objective;
      mission.title = missionTitle(snapshot.objective || mission.title);
      mission.provider = providerLabel(snapshot.provider || mission.provider);
      mission.currentStep = Number(snapshot.current_step || snapshot.steps) || mission.currentStep;
      mission.maxSteps = snapshot.max_steps || mission.maxSteps;
      mission.currentUrl = snapshot.current_url || mission.currentUrl;
      mission.pageTitle = snapshot.page_title || mission.pageTitle;
      mission.screenshotUrl = snapshot.latest_screenshot || mission.screenshotUrl;
      mission.currentAction = snapshot.current_action_summary
        ? meaningfulAction({ summary: snapshot.current_action_summary })
        : mission.currentAction;
      mission.result = snapshot.result ? outcomeLabel(snapshot.result) : mission.result;
      mission.error = snapshot.error ? failureLabel(snapshot.error) : mission.error;
      const hadTerminalEvent = Boolean(mission.completedAt);
      if (!hadTerminalEvent) {
        if (snapshot.status === "waiting_for_confirmation") setWorkStatus(mission, "needs_user");
        else if (snapshot.status === "completed") setWorkStatus(mission, "completed");
        else if (["failed", "cancelled"].includes(snapshot.status)) setWorkStatus(mission, "failed");
        else if (!mission.needsUser) setWorkStatus(mission, "working");
        if (["completed", "failed", "cancelled"].includes(snapshot.status)) {
          mission.completedAt = snapshot.completed_at || "recovered";
        }
      }
      if (["completed", "failed", "cancelled"].includes(snapshot.status) && !mission.evidence.length) {
        mission.evidence = [{
          kind: snapshot.status === "completed" ? "completion" : "failure",
          summary: mission.result || mission.error || "Browser session ended.",
          steps: mission.currentStep,
          url: mission.currentUrl,
          pageTitle: mission.pageTitle,
          screenshotUrl: mission.screenshotUrl,
        }];
      }
    }

    for (const confirmation of confirmations || []) {
      const mission = state.missions[confirmation.session_id];
      if (!mission || mission.completedAt || confirmation.status !== "pending") continue;
      setWorkStatus(mission, "needs_user");
      mission.needsUser = {
        confirmationId: confirmation.confirmation_id,
        sessionId: confirmation.session_id,
        actionId: confirmation.action_id,
        actionType: confirmation.action_type,
        description: meaningfulAction({ action_type: confirmation.action_type, summary: confirmation.description }),
        reason: "This action matched Warden's consequential-action safety policy.",
        riskLevel: "high",
        pageTitle: mission.pageTitle,
        url: mission.currentUrl,
        screenshotUrl: mission.screenshotUrl,
        status: "pending",
      };
    }
    return state;
  }

  return { blankState, failureLabel, isBrowserEvent, meaningfulAction, missionTitle, outcomeLabel, providerLabel, reduceEvents, recoverState };
});
