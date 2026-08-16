"""Warden Agentic Group Chat v1 Store, Event Pipeline, and Persistence.

Provides persistent chat rooms, monotonic sequence numbering, idempotent event bridges,
identity resolution, @mention parsing, and real-time SSE listener broadcasting.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

ActorType = Literal["human", "agent", "system", "warden"]
RoomPolicy = Literal["supervised", "keep_working", "paused"]
EventType = Literal[
    "human_message",
    "agent_message",
    "warden_message",
    "task_created",
    "task_claimed",
    "task_started",
    "task_progress",
    "task_completed",
    "task_failed",
    "task_cancelled",
    "task_superseded",
    "handoff_created",
    "handoff_accepted",
    "plan_created",
    "step_dispatched",
    "step_completed",
    "decision",
    "context_updated",
    "memory_recalled",
    "proof_created",
    "artifact_created",
    "tests_passed",
    "tests_failed",
    "approval_requested",
    "approval_granted",
    "approval_denied",
    "operator_attention",
    "agent_online",
    "agent_idle",
    "agent_working",
    "agent_waiting",
    "agent_blocked",
    "agent_offline",
]


class Conversation(BaseModel):
    conversation_id: str = "conv_warden_team"
    project: str = "Warden"
    title: str = "Warden Team"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "operator"
    status: str = "active"
    room_policy: RoomPolicy = "supervised"
    is_demo: bool = False
    unread_count: int = 0
    last_seq: int = 0


class ChatEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"evt_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    seq: int = 0
    conversation_id: str = "conv_warden_team"
    project: str = "Warden"
    actor_type: ActorType = "human"
    actor_id: str = "matt"
    actor_display_name: str | None = None
    actor_avatar: str | None = None
    event_type: EventType = "human_message"
    text: str = ""
    mentions: list[str] = Field(default_factory=list)
    task_id: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    run_id: str | None = None
    handoff_id: str | None = None
    approval_id: str | None = None
    grant_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    idempotency_key: str | None = None
    context_revision: str | None = None
    proof_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def parse_mentions(text: str) -> list[str]:
    """Extracts @mentions like @Claude, @Codex, @Spark, @Warden, @team from message text."""
    if not text:
        return []
    matches = re.findall(r"@([A-Za-z0-9_-]+)", text)
    seen = set()
    result = []
    for m in matches:
        lower = m.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(m)
    return result


def map_agent_display_name(actor_id: str) -> tuple[str, str]:
    """Maps internal agent ID to (display_name, actor_type)."""
    mapping = {
        "matt": ("Matt", "human"),
        "operator": ("Matt", "human"),
        "warden": ("Warden", "warden"),
        "captain": ("Warden", "warden"),
        "claude": ("Claude UX", "agent"),
        "codex": ("Codex Builder", "agent"),
        "spark": ("Spark Research", "agent"),
        "agy": ("AGY Pair Programmer", "agent"),
        "marius": ("Marius Resident", "agent"),
    }
    return mapping.get(actor_id.lower(), (actor_id.title(), "agent"))


class GroupChatStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (Path.home() / ".config" / "warden-brain" / "group_chat.sqlite")
        self._listeners: list[asyncio.Queue] = []
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    room_policy TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    last_seq INTEGER NOT NULL DEFAULT 0
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_events (
                    id TEXT PRIMARY KEY,
                    seq INTEGER NOT NULL,
                    conversation_id TEXT NOT NULL,
                    project TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_display_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    mentions TEXT NOT NULL,
                    task_id TEXT,
                    plan_id TEXT,
                    step_id TEXT,
                    run_id TEXT,
                    handoff_id TEXT,
                    approval_id TEXT,
                    grant_id TEXT,
                    source_type TEXT,
                    source_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    context_revision TEXT,
                    proof_refs TEXT NOT NULL,
                    artifact_refs TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_conv_seq ON chat_events(conversation_id, seq);")
            conn.commit()

        # Seed default "Warden Team" room if not exists
        self.get_or_create_conversation(conversation_id="conv_warden_team", title="Warden Team", project="Warden")

    def get_or_create_conversation(
        self,
        conversation_id: str = "conv_warden_team",
        title: str = "Warden Team",
        project: str = "Warden",
        room_policy: RoomPolicy = "supervised",
        is_demo: bool = False,
    ) -> Conversation:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,))
            row = cursor.fetchone()
            if row:
                return Conversation(
                    conversation_id=row["conversation_id"],
                    project=row["project"],
                    title=row["title"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    created_by=row["created_by"],
                    status=row["status"],
                    room_policy=row["room_policy"],
                    is_demo=bool(row["is_demo"]),
                    last_seq=row["last_seq"],
                )

            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """INSERT INTO conversations
                (conversation_id, project, title, created_at, updated_at, created_by, status, room_policy, is_demo, last_seq)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (conversation_id, project, title, now, now, "operator", "active", room_policy, 1 if is_demo else 0),
            )
            conn.commit()
            return Conversation(
                conversation_id=conversation_id,
                project=project,
                title=title,
                created_at=now,
                updated_at=now,
                created_by="operator",
                status="active",
                room_policy=room_policy,
                is_demo=is_demo,
                last_seq=0,
            )

    def list_conversations(self, project: str = "Warden") -> list[Conversation]:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM conversations WHERE project = ? OR project = 'Warden' ORDER BY updated_at DESC",
                (project,),
            )
            rows = cursor.fetchall()
            return [
                Conversation(
                    conversation_id=r["conversation_id"],
                    project=r["project"],
                    title=r["title"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    created_by=r["created_by"],
                    status=r["status"],
                    room_policy=r["room_policy"],
                    is_demo=bool(r["is_demo"]),
                    last_seq=r["last_seq"],
                )
                for r in rows
            ]

    def append_event(self, event: ChatEvent) -> tuple[ChatEvent, bool]:
        """Appends a ChatEvent with monotonic sequence assignment and idempotency check.

        Returns (stored_event, is_new).
        """
        # Ensure mentions are parsed
        if not event.mentions and event.text:
            event.mentions = parse_mentions(event.text)

        display_name, actor_type = map_agent_display_name(event.actor_id)
        if not event.actor_display_name or event.actor_display_name in (event.actor_id, "Matt") and event.actor_id.lower() != "matt":
            event.actor_display_name = display_name
        elif not event.actor_display_name:
            event.actor_display_name = display_name
        if event.actor_type == "human" and actor_type != "human":
            event.actor_type = actor_type

        # Idempotency key check
        if event.idempotency_key:
            existing = self.get_event_by_idempotency_key(event.idempotency_key)
            if existing:
                return existing, False

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE;")

            # Fetch and increment conversation last_seq
            cursor.execute(
                "SELECT last_seq FROM conversations WHERE conversation_id = ?",
                (event.conversation_id,),
            )
            row = cursor.fetchone()
            current_seq = (row["last_seq"] if row else 0) + 1
            event.seq = current_seq
            now = datetime.now(timezone.utc).isoformat()
            event.created_at = now

            cursor.execute(
                """INSERT INTO chat_events (
                    id, seq, conversation_id, project, actor_type, actor_id, actor_display_name,
                    event_type, text, mentions, task_id, plan_id, step_id, run_id, handoff_id,
                    approval_id, grant_id, source_type, source_id, idempotency_key,
                    context_revision, proof_refs, artifact_refs, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.seq,
                    event.conversation_id,
                    event.project,
                    event.actor_type,
                    event.actor_id,
                    event.actor_display_name,
                    event.event_type,
                    event.text,
                    json.dumps(event.mentions),
                    event.task_id,
                    event.plan_id,
                    event.step_id,
                    event.run_id,
                    event.handoff_id,
                    event.approval_id,
                    event.grant_id,
                    event.source_type,
                    event.source_id,
                    event.idempotency_key,
                    event.context_revision,
                    json.dumps(event.proof_refs),
                    json.dumps(event.artifact_refs),
                    json.dumps(event.metadata),
                    event.created_at,
                ),
            )
            cursor.execute(
                "UPDATE conversations SET last_seq = ?, updated_at = ? WHERE conversation_id = ?",
                (current_seq, now, event.conversation_id),
            )
            conn.commit()

        # Notify active SSE listener queues
        self._notify_listeners(event)
        return event, True

    def get_event_by_idempotency_key(self, idempotency_key: str) -> ChatEvent | None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chat_events WHERE idempotency_key = ?", (idempotency_key,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row)

    def list_events(self, conversation_id: str = "conv_warden_team", since_seq: int = 0, limit: int = 100) -> list[ChatEvent]:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM chat_events
                WHERE conversation_id = ? AND seq > ?
                ORDER BY seq ASC LIMIT ?""",
                (conversation_id, since_seq, limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    def get_agent_inbox(self, agent_id: str, conversation_id: str = "conv_warden_team", limit: int = 20) -> list[ChatEvent]:
        """Returns events mentioning or assigned to the specified agent."""
        events = self.list_events(conversation_id=conversation_id, since_seq=0, limit=200)
        agent_lower = agent_id.lower()
        inbox = []
        for e in events:
            mentions_lower = [m.lower() for m in e.mentions]
            if "team" in mentions_lower or "warden" in mentions_lower or agent_lower in mentions_lower:
                inbox.append(e)
            elif e.metadata.get("assigned_agent", "").lower() == agent_lower:
                inbox.append(e)
        return inbox[-limit:]

    def _row_to_event(self, row: sqlite3.Row) -> ChatEvent:
        return ChatEvent(
            id=row["id"],
            seq=row["seq"],
            conversation_id=row["conversation_id"],
            project=row["project"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            actor_display_name=row["actor_display_name"],
            event_type=row["event_type"],
            text=row["text"],
            mentions=json.loads(row["mentions"]) if row["mentions"] else [],
            task_id=row["task_id"],
            plan_id=row["plan_id"],
            step_id=row["step_id"],
            run_id=row["run_id"],
            handoff_id=row["handoff_id"],
            approval_id=row["approval_id"],
            grant_id=row["grant_id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            idempotency_key=row["idempotency_key"],
            context_revision=row["context_revision"],
            proof_refs=json.loads(row["proof_refs"]) if row["proof_refs"] else [],
            artifact_refs=json.loads(row["artifact_refs"]) if row["artifact_refs"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
        )

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._listeners:
            self._listeners.remove(q)

    def _notify_listeners(self, event: ChatEvent) -> None:
        for q in list(self._listeners):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def process_human_message(self, text: str, conversation_id: str = "conv_warden_team", actor_id: str = "matt") -> tuple[ChatEvent, list[ChatEvent]]:
        """Processes an incoming human message, appends events, routes via Captain, and projects team responses."""
        human_event, _ = self.append_event(ChatEvent(
            conversation_id=conversation_id,
            actor_id=actor_id,
            actor_type="human",
            event_type="human_message",
            text=text,
        ))

        responses: list[ChatEvent] = []
        lower = text.lower()

        # 1. Stop / Pause commands
        if "/stop" in lower or "@team stop" in lower or "stop work" in lower:
            w_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="warden",
                actor_type="warden",
                event_type="warden_message",
                text="Team work paused per operator instruction.",
            ))
            responses.append(w_evt)
            return human_event, responses

        # 2. General task request / team coordination
        mentions = parse_mentions(text)
        
        # Formulate Warden response
        if "settings" in lower or "ui" in lower or "feature" in lower or "build" in lower or "verify" in lower:
            w_text = "I split this work across the team. Claude has UX, Spark has research, Codex will verify."
            w_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="warden",
                actor_type="warden",
                event_type="warden_message",
                text=w_text,
            ))
            responses.append(w_evt)

            # Claude response
            c_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="claude",
                actor_type="agent",
                event_type="agent_message",
                text="Picked up Settings UX. Reviewing current implementation.",
                metadata={"status": "working", "assigned_component": "UX"},
            ))
            responses.append(c_evt)

            # Spark response
            s_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="spark",
                actor_type="agent",
                event_type="agent_message",
                text="Researching multi-account patterns now.",
                metadata={"status": "working", "assigned_component": "Research"},
            ))
            responses.append(s_evt)

            # Codex response
            cdx_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="codex",
                actor_type="agent",
                event_type="agent_message",
                text="Waiting on Claude's implementation before verification.",
                metadata={"status": "waiting", "assigned_component": "Verification"},
            ))
            responses.append(cdx_evt)

        elif mentions:
            target_agents = [m for m in mentions if m.lower() != "team"]
            target_str = ", ".join(target_agents) if target_agents else "the team"
            w_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="warden",
                actor_type="warden",
                event_type="warden_message",
                text=f"Routed prompt to {target_str}.",
            ))
            responses.append(w_evt)

            for ag in target_agents:
                ag_lower = ag.lower()
                ag_evt, _ = self.append_event(ChatEvent(
                    conversation_id=conversation_id,
                    actor_id=ag_lower,
                    actor_type="agent",
                    event_type="agent_message",
                    text=f"Received assignment: '{text[:80]}...'",
                    metadata={"status": "working"},
                ))
                responses.append(ag_evt)
        else:
            w_evt, _ = self.append_event(ChatEvent(
                conversation_id=conversation_id,
                actor_id="warden",
                actor_type="warden",
                event_type="warden_message",
                text=f"Acknowledged request. Captain is orchestrating initial assessment.",
            ))
            responses.append(w_evt)

        return human_event, responses
