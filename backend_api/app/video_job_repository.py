from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .workflow_service import WORKFLOW_VIDEO_JOB_ROOT, WORKFLOW_VIDEO_OUTPUT_ROOT

BATCH_ROOT = settings.work_root / "video_batches"
RESULT_ROOT = WORKFLOW_VIDEO_OUTPUT_ROOT
JOB_ROOT = WORKFLOW_VIDEO_JOB_ROOT

for directory in (BATCH_ROOT, RESULT_ROOT, JOB_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def job_path(job_id: str) -> Path:
    return JOB_ROOT / f"{job_id}.json"


def batch_path(batch_id: str) -> Path:
    return BATCH_ROOT / f"{batch_id}.json"


def result_path(job_id: str) -> Path:
    return RESULT_ROOT / f"{job_id}.result.json"


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id 不得为空")
    job["updated_at"] = utc_now()
    with _lock:
        _atomic_write(job_path(job_id), job)
    return job


def load_job(job_id: str) -> dict[str, Any] | None:
    return _read_json(job_path(job_id))


def save_batch(batch: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(batch.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("batch_id 不得为空")
    batch["updated_at"] = utc_now()
    with _lock:
        _atomic_write(batch_path(batch_id), batch)
    return batch


def load_batch(batch_id: str) -> dict[str, Any] | None:
    return _read_json(batch_path(batch_id))


def load_latest_batch() -> dict[str, Any] | None:
    candidates = [
        path
        for path in BATCH_ROOT.glob("*.json")
        if not path.name.endswith(".tmp")
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return _read_json(latest)


def save_result(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    payload = {"job_id": job_id, **result, "saved_at": utc_now()}
    with _lock:
        _atomic_write(result_path(job_id), payload)
    return payload


def load_result(job_id: str) -> dict[str, Any] | None:
    return _read_json(result_path(job_id))


def list_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in JOB_ROOT.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        job = _read_json(path)
        if job:
            jobs.append(job)
    return jobs


def list_active_jobs() -> list[dict[str, Any]]:
    return [
        job
        for job in list_jobs()
        if job.get("status") in {"queued", "submitting", "running"}
        and job.get("provider_task_id")
    ]


def _job_slot_key(job: dict[str, Any]) -> str:
    return str(job.get("slot_key") or job.get("shot_id") or job.get("job_id") or "").strip()


def jobs_for_batch(batch_id: str) -> list[dict[str, Any]]:
    batch = load_batch(batch_id) or {}
    job_ids = batch.get("job_ids") or []
    jobs_by_slot: dict[str, dict[str, Any]] = {}
    slot_order: list[str] = []
    for job_id in job_ids:
        job = load_job(str(job_id))
        if not job:
            continue
        slot_key = _job_slot_key(job)
        if slot_key not in jobs_by_slot:
            slot_order.append(slot_key)
        jobs_by_slot[slot_key] = job
    return [jobs_by_slot[slot_key] for slot_key in slot_order]
