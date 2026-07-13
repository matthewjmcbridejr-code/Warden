import atexit
import os
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

from .contracts import CapabilityStatus, HumanDecision, MemoryContext, TaskState, WorkerResult
from .worker import WorkerStub

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when dependency is missing
    SqliteSaver = None  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    START = END = None  # type: ignore[assignment]
    Command = None  # type: ignore[assignment]
    interrupt = None  # type: ignore[assignment]
    LANGGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)

from src.warden.paths import data_root as _warden_data_root
MCTABLE_ROOT = _warden_data_root()
TASKS_DIR = MCTABLE_ROOT / "tasks"
CHECKPOINTS_DIR = MCTABLE_ROOT / "checkpoints"
CHECKPOINT_DB_PATH = CHECKPOINTS_DIR / "warden.sqlite"

FINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
PAUSED_TASK_STEP = "human_review_gate"
TASK_IDENTITY_FIELDS = {
    "task_id",
    "title",
    "description",
    "status",
    "risk_level",
    "proof_status",
    "current_step",
    "agent_id",
    "command",
    "args",
    "metadata",
    "memory_context",
    "worker_run_id",
    "worker_result",
    "human_decision",
    "recovery_hint",
    "created_at",
    "updated_at",
}


class MariusDesktopGraphState(TypedDict, total=False):
    task_id: str
    title: str
    description: str
    status: str
    risk_level: str
    proof_status: str
    current_step: str
    agent_id: Optional[str]
    command: Optional[str]
    args: list[str]
    metadata: dict[str, Any]
    memory_context: Optional[dict[str, Any]]
    worker_run_id: Optional[str]
    worker_result: Optional[dict[str, Any]]
    human_decision: Optional[dict[str, Any]]
    recovery_hint: Optional[str]
    created_at: Any
    updated_at: Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_json() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _state_snapshot_to_model(values: dict[str, Any], *, paused: bool = False) -> TaskState:
    data = dict(values)
    if paused:
        data["status"] = "paused"
        data["current_step"] = PAUSED_TASK_STEP
    return TaskState.model_validate(data)


def _ensure_dirs() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


def _build_capabilities() -> list[CapabilityStatus]:
    if LANGGRAPH_AVAILABLE:
        langgraph_summary = f"LangGraph is installed and checkpointing to {CHECKPOINT_DB_PATH}"
        sqlite_summary = f"SQLite checkpointing is active at {CHECKPOINT_DB_PATH}"
        langgraph_status = "available"
        sqlite_status = "available"
        langgraph_hint = None
        sqlite_hint = None
    else:
        langgraph_summary = "LangGraph is not installed in the current environment."
        sqlite_summary = "SQLite checkpointing is not available without LangGraph."
        langgraph_status = "unavailable"
        sqlite_status = "unavailable"
        langgraph_hint = "Install langgraph to enable checkpointed orchestration."
        sqlite_hint = "Install langgraph-checkpoint-sqlite to enable SQLite checkpointing."

    return [
        CapabilityStatus(
            name="langgraph",
            status=langgraph_status,
            summary=langgraph_summary,
            recovery_hint=langgraph_hint,
        ),
        CapabilityStatus(
            name="sqlite_checkpointing",
            status=sqlite_status,
            summary=sqlite_summary,
            recovery_hint=sqlite_hint,
        ),
        CapabilityStatus(
            name="worker_runner",
            status="available",
            summary="Local stub fake-worker runner is available.",
            recovery_hint=None,
        ),
        CapabilityStatus(
            name="api",
            status="available",
            summary="McHarness API is fully online.",
            recovery_hint=None,
        ),
    ]


def _task_config(task_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": task_id}}


def _serialize_human_decision(decision: HumanDecision | dict[str, Any]) -> dict[str, Any]:
    if isinstance(decision, HumanDecision):
        return decision.model_dump(mode="json")
    return decision


def _build_graph_runtime() -> Any:
    if not LANGGRAPH_AVAILABLE:
        return None

    _ensure_dirs()
    checkpointer_cm = SqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH))
    checkpointer = checkpointer_cm.__enter__()
    checkpointer.setup()

    def create_task(state: MariusDesktopGraphState) -> dict[str, Any]:
        return {
            "status": "queued",
            "proof_status": "pending",
            "current_step": "classify_risk",
            "updated_at": _now_json(),
        }

    def classify_risk(state: MariusDesktopGraphState) -> dict[str, Any]:
        text = f"{state.get('title', '')} {state.get('description', '')}".lower()
        risk_level = "high" if "unsafe" in text else "low"
        return {
            "risk_level": risk_level,
            "current_step": "prepare_context",
            "updated_at": _now_json(),
        }

    def prepare_context(state: MariusDesktopGraphState) -> dict[str, Any]:
        context = MemoryContext(
            task_id=str(state["task_id"]),
            memories=["Maharet placeholder memory context"],
            source="maharet_placeholder",
            compacted=False,
            summary="Maharet Context Placeholder",
        )
        return {
            "memory_context": context.model_dump(mode="json"),
            "current_step": "launch_worker",
            "updated_at": _now_json(),
        }

    def launch_worker(state: MariusDesktopGraphState) -> dict[str, Any]:
        command = str(state.get("command") or "")
        args = list(state.get("args") or [])
        agent_id = str(state.get("agent_id") or "fake-agent")
        try:
            run_id = WorkerStub.start_run(agent_id, str(state["task_id"]), command, args)
        except Exception as exc:
            return {
                "status": "failed",
                "recovery_hint": f"Worker failed to launch: {exc}",
                "current_step": "launch_worker",
                "updated_at": _now_json(),
            }

        return {
            "worker_run_id": run_id,
            "status": "running",
            "current_step": "collect_result",
            "updated_at": _now_json(),
        }

    def collect_result(state: MariusDesktopGraphState) -> dict[str, Any]:
        run_id = state.get("worker_run_id")
        if not run_id:
            return {
                "current_step": "collect_result",
                "updated_at": _now_json(),
            }

        run = WorkerStub.get_status(str(run_id))
        if run.status == "running":
            interrupt(
                {
                    "tool": "collect_result",
                    "task_id": state["task_id"],
                    "worker_run_id": run_id,
                    "worker_status": run.status,
                }
            )
            return {
                "status": "running",
                "current_step": "collect_result",
                "updated_at": _now_json(),
            }

        result_path = Path(run.logs_path) / "result.json"
        if result_path.exists():
            result_data = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            result_data = {
                "run_id": run.run_id,
                "task_id": run.task_id,
                "status": run.status,
                "summary": "Worker result was not persisted.",
                "artifacts": [],
                "next_actions": [],
                "recovery_hint": None,
                "raw_output_path": None,
            }

        worker_result = WorkerResult.model_validate(result_data)
        updates: dict[str, Any] = {
            "worker_result": worker_result.model_dump(mode="json"),
            "current_step": "proof_guard",
            "updated_at": _now_json(),
        }

        if worker_result.status == "failed" and worker_result.recovery_hint:
            updates["recovery_hint"] = worker_result.recovery_hint
        elif worker_result.status == "cancelled":
            updates["status"] = "cancelled"
            updates["recovery_hint"] = worker_result.recovery_hint or "Task cancelled by operator."
        elif worker_result.status == "blocked":
            updates["status"] = "failed"
            updates["recovery_hint"] = worker_result.recovery_hint or "Worker run was blocked."

        return updates

    def proof_guard(state: MariusDesktopGraphState) -> dict[str, Any]:
        worker_result = state.get("worker_result") or {}
        worker_status = worker_result.get("status")
        proof_status = "needs_review" if worker_status == "success" else "failed"
        updates = {
            "proof_status": proof_status,
            "current_step": "human_review_gate",
            "updated_at": _now_json(),
        }
        if worker_status in {"failed", "cancelled"}:
            updates["status"] = state.get("status", "running")
        return updates

    def human_review_gate(state: MariusDesktopGraphState) -> dict[str, Any]:
        decision_payload = interrupt(
            {
                "tool": "human_review_gate",
                "task_id": state["task_id"],
                "current_step": state.get("current_step"),
                "proof_status": state.get("proof_status"),
                "worker_run_id": state.get("worker_run_id"),
            }
        )
        decision = HumanDecision.model_validate(decision_payload)
        updates: dict[str, Any] = {
            "human_decision": _serialize_human_decision(decision),
            "updated_at": _now_json(),
        }

        if decision.decision == "approve":
            updates.update(
                {
                    "proof_status": "approved",
                    "status": "completed",
                    "current_step": "complete",
                }
            )
        elif decision.decision == "reject":
            updates.update(
                {
                    "proof_status": "rejected",
                    "status": "failed",
                    "current_step": "complete",
                    "recovery_hint": decision.reviewer_note or "Rejected by human reviewer.",
                }
            )
        else:
            patched = dict(state)
            for key, value in decision.state_patch.items():
                if key in TASK_IDENTITY_FIELDS:
                    patched[key] = value

            patched.update(
                {
                    "human_decision": _serialize_human_decision(decision),
                    "status": "paused",
                    "current_step": PAUSED_TASK_STEP,
                    "updated_at": _now_json(),
                }
            )
            return patched

        return updates

    def complete(state: MariusDesktopGraphState) -> dict[str, Any]:
        return {
            "current_step": "complete",
            "updated_at": _now_json(),
        }

    def route_after_collect(state: MariusDesktopGraphState) -> str:
        if state.get("worker_result"):
            return "proof_guard"
        return END

    def route_after_review(state: MariusDesktopGraphState) -> str:
        if state.get("status") in {"completed", "failed"}:
            return "complete"
        return END

    builder = StateGraph(MariusDesktopGraphState)
    builder.add_node("create_task", create_task)
    builder.add_node("classify_risk", classify_risk)
    builder.add_node("prepare_context", prepare_context)
    builder.add_node("launch_worker", launch_worker)
    builder.add_node("collect_result", collect_result)
    builder.add_node("proof_guard", proof_guard)
    builder.add_node("human_review_gate", human_review_gate)
    builder.add_node("complete", complete)

    builder.add_edge(START, "create_task")
    builder.add_edge("create_task", "classify_risk")
    builder.add_edge("classify_risk", "prepare_context")
    builder.add_edge("prepare_context", "launch_worker")
    builder.add_edge("launch_worker", "collect_result")
    builder.add_conditional_edges(
        "collect_result",
        route_after_collect,
        {
            "proof_guard": "proof_guard",
            END: END,
        },
    )
    builder.add_edge("proof_guard", "human_review_gate")
    builder.add_conditional_edges(
        "human_review_gate",
        route_after_review,
        {
            "complete": "complete",
            END: END,
        },
    )
    builder.add_edge("complete", END)

    graph = builder.compile(checkpointer=checkpointer)

    def _close_checkpointer() -> None:
        try:
            checkpointer_cm.__exit__(None, None, None)
        except Exception:  # pragma: no cover - best effort shutdown
            logger.exception("Failed to close LangGraph SQLite checkpointer.")

    atexit.register(_close_checkpointer)
    return graph


class McTableTaskGraph:
    def __init__(self) -> None:
        self.langgraph_available = LANGGRAPH_AVAILABLE
        self._graph = _build_graph_runtime()

    def _config(self, task_id: str) -> dict[str, Any]:
        return _task_config(task_id)

    def _require_graph(self) -> Any:
        if not self.langgraph_available or self._graph is None:
            raise RuntimeError("LangGraph is not available in this environment.")
        return self._graph

    def _persist_state(self, state: TaskState) -> None:
        _ensure_dirs()
        path = TASKS_DIR / f"{state.task_id}.json"
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def _load_snapshot(self, task_id: str) -> TaskState:
        graph = self._require_graph()
        snapshot = graph.get_state(self._config(task_id))
        if snapshot is None or not getattr(snapshot, "values", None):
            path = TASKS_DIR / f"{task_id}.json"
            if not path.exists():
                raise FileNotFoundError(f"Task {task_id} not found.")
            return TaskState.model_validate_json(path.read_text(encoding="utf-8"))

        paused = (
            getattr(snapshot, "next", None)
            and PAUSED_TASK_STEP in getattr(snapshot, "next", ())
            and snapshot.values.get("current_step") == PAUSED_TASK_STEP
            and not snapshot.values.get("human_decision")
        )
        state = _state_snapshot_to_model(snapshot.values, paused=bool(paused))
        self._persist_state(state)
        return state

    def save_state(self, state: TaskState) -> None:
        self._persist_state(state)

    def load_state(self, task_id: str) -> TaskState:
        if not self.langgraph_available:
            path = TASKS_DIR / f"{task_id}.json"
            if not path.exists():
                raise FileNotFoundError(f"Task {task_id} not found.")
            return TaskState.model_validate_json(path.read_text(encoding="utf-8"))
        return self._load_snapshot(task_id)

    def create_task(
        self,
        task_id: str,
        title: str,
        description: str,
        command: str,
        args: list[str],
    ) -> TaskState:
        _ensure_dirs()
        if (TASKS_DIR / f"{task_id}.json").exists():
            raise FileExistsError(f"Task {task_id} already exists.")

        now = _now()
        state = TaskState(
            task_id=task_id,
            title=title,
            description=description,
            status="queued",
            risk_level="low",
            proof_status="pending",
            current_step="create_task",
            agent_id="fake-agent",
            command=command,
            args=args,
            metadata={},
            memory_context=None,
            worker_run_id=None,
            worker_result=None,
            human_decision=None,
            recovery_hint=None,
            created_at=now,
            updated_at=now,
        )
        self._persist_state(state)

        if self.langgraph_available:
            self._require_graph().invoke(state.model_dump(mode="json"), self._config(task_id))
            state = self.load_state(task_id)
        return state

    def run_step(self, task_id: str) -> TaskState:
        state = self.load_state(task_id)
        if state.status in FINAL_TASK_STATUSES:
            return state
        if state.status == "paused" and state.current_step == PAUSED_TASK_STEP and not state.human_decision:
            return state
        if not self.langgraph_available:
            return state

        self._require_graph().invoke(None, self._config(task_id))
        return self.load_state(task_id)

    def drive_task_to_review(
        self,
        task_id: str,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.25,
    ) -> TaskState:
        deadline = time.time() + timeout_s
        state = self.load_state(task_id)
        while True:
            if state.status in FINAL_TASK_STATUSES:
                return state
            if state.status == "paused" and state.current_step == PAUSED_TASK_STEP:
                return state

            next_state = self.run_step(task_id)
            if (
                next_state.status == state.status
                and next_state.current_step == state.current_step
                and next_state.worker_run_id == state.worker_run_id
            ):
                if next_state.status == "running" and next_state.current_step in {"launch_worker", "collect_result"}:
                    if time.time() >= deadline:
                        return next_state
                    time.sleep(poll_interval_s)
                else:
                    return next_state
            state = next_state

    def resume_task(
        self,
        task_id: str,
        decision: str,
        actor: str,
        reviewer_note: Optional[str] = None,
        state_patch: Optional[dict[str, Any]] = None,
    ) -> TaskState:
        if not self.langgraph_available:
            raise RuntimeError("LangGraph is not available in this environment.")

        payload = HumanDecision(
            decision=decision,
            actor=actor,
            reviewer_note=reviewer_note,
            state_patch=state_patch or {},
            decided_at=_now(),
        )
        self._require_graph().invoke(Command(resume=payload.model_dump(mode="json")), self._config(task_id))
        return self.load_state(task_id)


def get_runtime_capabilities() -> list[CapabilityStatus]:
    return _build_capabilities()


def checkpoint_file_exists() -> bool:
    return CHECKPOINT_DB_PATH.exists()
