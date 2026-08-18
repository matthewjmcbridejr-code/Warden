"""Persistent disk store for FinishJob instances."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

from .models import FinishJob, FinishStage


class FinishJobStore:
    def __init__(self, root_dir: Optional[Path] = None):
        if root_dir is None:
            root_dir = Path.cwd() / "_mctable" / "finish" / "jobs"
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _job_file(self, job_id: str) -> Path:
        return self.root_dir / f"{job_id}.json"

    def save(self, job: FinishJob) -> FinishJob:
        job.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._job_file(job.job_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(job.model_dump_json(indent=2))
        return job

    def get(self, job_id: str) -> Optional[FinishJob]:
        path = self._job_file(job_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return FinishJob.model_validate(data)

    def list(self, project: Optional[str] = None) -> List[FinishJob]:
        jobs: List[FinishJob] = []
        for file in self.root_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                job = FinishJob.model_validate(data)
                if project is None or job.project == project:
                    jobs.append(job)
            except Exception:
                continue
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs
