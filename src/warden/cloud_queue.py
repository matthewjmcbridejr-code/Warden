"""Durable GCP Pub/Sub mission delivery for the cloud worker.

Pub/Sub is the delivery mechanism; Cloud SQL remains the authority for the
mission envelope and the lease that prevents duplicate effects. The consumer
acknowledges a message only after recording a terminal receipt. Real command
execution is separately gated and remains disabled by default.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .cloud_brain import _Outbox
from .cloud_control_plane import CloudControlPlane, cloud_control_enabled


class CloudQueueUnavailable(RuntimeError):
    """The configured Pub/Sub queue cannot be reached."""


def queue_enabled() -> bool:
    return cloud_control_enabled() and bool(
        (os.getenv("WARDEN_MISSIONS_TOPIC") or os.getenv("WARDEN_QUEUE_TOPIC") or "").strip()
    ) and os.getenv("WARDEN_QUEUE_BACKEND", "").strip().lower() == "pubsub"


def consumer_enabled() -> bool:
    return queue_enabled() and os.getenv("WARDEN_QUEUE_CONSUMER_ENABLED", "false").strip().lower() == "true" and bool(
        (os.getenv("WARDEN_MISSIONS_SUBSCRIPTION") or os.getenv("WARDEN_QUEUE_SUBSCRIPTION") or "").strip()
    )


def _topic_path() -> str:
    configured = (os.getenv("WARDEN_MISSIONS_TOPIC") or os.getenv("WARDEN_QUEUE_TOPIC") or "").strip()
    if configured.startswith("projects/"):
        return configured
    project = (os.getenv("WARDEN_GOOGLE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project or not configured:
        raise CloudQueueUnavailable("WARDEN_MISSIONS_TOPIC and a GCP project are required")
    return f"projects/{project}/topics/{configured}"


def _subscription_path() -> str:
    configured = (os.getenv("WARDEN_MISSIONS_SUBSCRIPTION") or os.getenv("WARDEN_QUEUE_SUBSCRIPTION") or "").strip()
    if configured.startswith("projects/"):
        return configured
    project = (os.getenv("WARDEN_GOOGLE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project or not configured:
        raise CloudQueueUnavailable("WARDEN_MISSIONS_SUBSCRIPTION and a GCP project are required")
    return f"projects/{project}/subscriptions/{configured}"


def _publisher():
    try:
        from google.cloud import pubsub_v1
    except ImportError as exc:
        raise CloudQueueUnavailable("Install the cloud extra with Pub/Sub support") from exc
    return pubsub_v1.PublisherClient()


def publish_mission(
    *,
    mission_id: str,
    kind: str,
    body: dict[str, Any],
    idempotency_key: str | None = None,
    persist_record: bool = True,
) -> dict[str, Any]:
    """Publish one mission envelope and record its delivery state."""
    if not queue_enabled():
        raise CloudQueueUnavailable("Pub/Sub mission queue is not enabled")
    now = datetime.now(timezone.utc).isoformat()
    idem = idempotency_key or f"mission:{mission_id}"
    envelope = {
        "mission_id": mission_id,
        "kind": kind,
        "body": body,
        "idempotency_key": idem,
        "created_at": now,
    }
    if persist_record:
        try:
            CloudControlPlane().upsert_record("mission", mission_id, {
                **envelope,
                "status": "publishing",
                "updated_at": now,
            }, source_updated_at=now)
        except Exception:
            CloudControlPlane().enqueue_record("mission", mission_id, {**envelope, "status": "publishing", "updated_at": now})
    try:
        future = _publisher().publish(
            _topic_path(),
            json.dumps(envelope, sort_keys=True, default=str).encode("utf-8"),
            mission_id=mission_id,
            idempotency_key=idem,
            kind=kind,
        )
        message_id = str(future.result(timeout=30))
    except Exception as exc:
        _Outbox().enqueue("publish_mission", envelope)
        raise CloudQueueUnavailable(f"Pub/Sub publish failed: {exc}") from exc
    try:
        CloudControlPlane().upsert_record("mission", mission_id, {
            **envelope,
            "status": "published",
            "message_id": message_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        # Delivery already succeeded; replaying the idempotent envelope is safe
        # and lets the worker receipt converge the authority later.
        _Outbox().enqueue("upsert_control_record", {
            "record_type": "mission",
            "record_id": mission_id,
            "payload": {**envelope, "status": "published", "message_id": message_id},
        })
    return {"mission_id": mission_id, "message_id": message_id, "idempotency_key": idem}


def enqueue_mission(*, mission_id: str, kind: str, body: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any] | None:
    """Best-effort enqueue used by API paths; disabled queues are a no-op."""
    if not queue_enabled():
        return None
    try:
        return publish_mission(mission_id=mission_id, kind=kind, body=body, idempotency_key=idempotency_key)
    except CloudQueueUnavailable:
        return {"mission_id": mission_id, "queued_outbox": True, "idempotency_key": idempotency_key or f"mission:{mission_id}"}


def _record_receipt(envelope: dict[str, Any], *, status: str, owner_id: str, reason: str | None = None) -> None:
    mission_id = str(envelope.get("mission_id") or "")
    if not mission_id:
        return
    payload = {
        **envelope,
        "status": status,
        "worker_id": owner_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        payload["reason"] = reason
    try:
        CloudControlPlane().upsert_record("mission", mission_id, payload)
    except Exception:
        CloudControlPlane().enqueue_record("mission", mission_id, payload)


def handle_mission_message(message: Any, *, owner_id: str | None = None) -> None:
    """Handle one message with a lease and an explicit execution safety gate."""
    owner = owner_id or os.getenv("WARDEN_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
    try:
        envelope = json.loads(bytes(message.data).decode("utf-8"))
        if not isinstance(envelope, dict) or not envelope.get("mission_id"):
            message.ack()
            return
    except (ValueError, UnicodeDecodeError, TypeError):
        message.ack()
        return
    mission_id = str(envelope["mission_id"])
    lease_key = f"mission:{mission_id}"
    try:
        acquired = CloudControlPlane().acquire_lease(lease_key, owner, ttl_seconds=300)
    except Exception:
        message.nack()
        return
    if not acquired:
        message.nack()
        return
    try:
        if os.getenv("WARDEN_WORKER_EXECUTION_ENABLED", "false").strip().lower() != "true":
            _record_receipt(envelope, status="blocked", owner_id=owner, reason="worker_execution_disabled")
            message.ack()
            return
        # Enabling execution requires an implementation-specific allowlist
        # path. Never interpret arbitrary Pub/Sub body text as a shell command.
        _record_receipt(envelope, status="blocked", owner_id=owner, reason="no_safe_executor_registered")
        message.ack()
    finally:
        try:
            CloudControlPlane().release_lease(lease_key, owner)
        except Exception:
            pass


class MissionConsumer:
    """Lifecycle handle for the e2-medium Pub/Sub subscriber."""

    def __init__(self, *, owner_id: str | None = None) -> None:
        self.owner_id = owner_id or os.getenv("WARDEN_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
        self._subscriber: Any = None
        self._future: Any = None

    def start(self) -> "MissionConsumer":
        if not queue_enabled():
            raise CloudQueueUnavailable("Pub/Sub mission queue is not enabled")
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise CloudQueueUnavailable("Install the cloud extra with Pub/Sub support") from exc
        self._subscriber = pubsub_v1.SubscriberClient()
        self._future = self._subscriber.subscribe(
            _subscription_path(),
            callback=lambda message: handle_mission_message(message, owner_id=self.owner_id),
        )
        return self

    def stop(self) -> None:
        if self._future is not None:
            self._future.cancel()
        if self._subscriber is not None:
            self._subscriber.close()


def queue_status() -> dict[str, Any]:
    return {
        "enabled": queue_enabled(),
        "backend": os.getenv("WARDEN_QUEUE_BACKEND", "local"),
        "topic_configured": bool((os.getenv("WARDEN_MISSIONS_TOPIC") or os.getenv("WARDEN_QUEUE_TOPIC") or "").strip()),
        "subscription_configured": bool((os.getenv("WARDEN_MISSIONS_SUBSCRIPTION") or os.getenv("WARDEN_QUEUE_SUBSCRIPTION") or "").strip()),
        "execution_enabled": os.getenv("WARDEN_WORKER_EXECUTION_ENABLED", "false").strip().lower() == "true",
    }
