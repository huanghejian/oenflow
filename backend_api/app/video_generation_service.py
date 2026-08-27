from __future__ import annotations

import json
import hashlib
import mimetypes
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import settings
from .logging_utils import get_logger, log_payload
from .model_ids import canonicalize_model_id
from .long_time_http import LongTimeHttpError
from .providers.base import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    ProviderSubmitPayload,
    is_placeholder_job_id,
    is_placeholder_task_id,
    is_task_not_found,
)
from .providers.registry import service_for
from .s3_asset_service import publish_references
from .s3_asset_service import upload_bytes
from .video_job_repository import (
    RESULT_ROOT,
    jobs_for_batch,
    load_batch,
    load_latest_batch,
    load_job,
    save_batch,
    save_job,
    save_result,
    utc_now,
)
from .workflow_service import auto_bind_video_plan

logger = get_logger(__name__)


def _video_plan_batch_signature(final_video_plan: dict[str, Any]) -> str:
    signature_shots = final_video_plan.get("batch_shots") or final_video_plan.get("shots") or []
    payload = [
        {
            "shot_id": shot.get("shot_id"),
            "group_id": shot.get("group_id"),
            "atomic_ids": shot.get("atomic_ids") or [],
            "duration": shot.get("duration"),
        }
        for shot in signature_shots
        if isinstance(shot, dict)
    ]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _api_model_id(model: str, model_params: dict[str, Any] | None = None) -> str:
    params = model_params or {}
    if params.get("api_model_id"):
        return str(params["api_model_id"])
    mapping = {
        "h3": settings.h3_model,
        "xingguang-3.0": settings.topenrouter_xingguang_30_model,
        "xingguang-3.5": settings.topenrouter_xingguang_35_model,
        "wan3": settings.wan3_model,
    }
    return mapping.get(canonicalize_model_id(model), "")


def _public_job_view(job: dict[str, Any]) -> dict[str, Any]:
    hidden = {"provider_payload", "public_references", "raw_provider_create", "raw_provider_query"}
    return {key: value for key, value in job.items() if key not in hidden}


def _summarize_batch(batch: dict[str, Any], jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = jobs if jobs is not None else jobs_for_batch(str(batch.get("batch_id") or ""))
    statuses = [str(job.get("status") or "") for job in records]
    succeeded = sum(1 for status in statuses if status == "succeeded")
    failed = sum(1 for status in statuses if status in {"failed", "cancelled", "blocked"})
    active = sum(1 for status in statuses if status in ACTIVE_STATUSES)
    if records and succeeded == len(records):
        batch_status = "succeeded"
    elif active:
        batch_status = "running"
    elif failed:
        batch_status = "failed"
    else:
        batch_status = str(batch.get("status") or "queued")
    views = [_public_job_view(job) for job in records]
    summary = {
        **batch,
        "status": batch_status,
        "batch_status": batch_status,
        "jobs": views,
        "submitted_count": sum(1 for job in records if job.get("status") != "blocked"),
        "blocked_count": sum(1 for job in records if job.get("status") == "blocked"),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "running_count": active,
        "mode": "provider",
    }
    save_batch({key: value for key, value in summary.items() if key != "jobs"} | {
        "job_ids": [job.get("job_id") for job in records],
        "status": batch_status,
    })
    return summary


def _video_job_slot_key(shot_id: Any) -> str:
    return str(shot_id or "").strip()


def _reset_job_for_resubmit(job: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "provider_task_id",
        "raw_provider_create",
        "raw_provider_query",
        "provider_output_video_url",
        "output_video_url",
        "output_s3_key",
        "output_video_path",
        "output_path",
        "output_url",
        "error_code",
        "error_message",
        "query_error_count",
        "submitted_at",
    ):
        job.pop(key, None)
    return job


def _job_has_video_result(job: dict[str, Any]) -> bool:
    return any(
        str(job.get(key) or "").strip()
        for key in (
            "output_video_url",
            "output_url",
            "video_url",
            "provider_output_video_url",
            "output_s3_key",
            "output_video_path",
            "output_path",
            "video_path",
        )
    )


def _merge_job_ids(existing_ids: list[Any], changed_jobs: list[dict[str, Any]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing_ids, *[job.get("job_id") for job in changed_jobs]]:
        job_id = str(value or "").strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        merged.append(job_id)
    return merged


def _to_provider_payload(
    job: dict[str, Any],
    references: list[dict[str, Any]],
    project_params: dict[str, Any],
    final_video_plan: dict[str, Any],
) -> ProviderSubmitPayload:
    model = canonicalize_model_id(job.get("model"))
    model_params = job.get("model_params") or {}
    return ProviderSubmitPayload(
        shot_id=str(job.get("shot_id") or ""),
        model=model,
        api_model_id=_api_model_id(model, model_params),
        duration=int(job.get("duration") or 0),
        prompt=str(job.get("prompt") or ""),
        ratio=str(
            project_params.get("aspect_ratio")
            or final_video_plan.get("aspect_ratio")
            or "16:9"
        ),
        resolution=str(
            project_params.get("resolution")
            or final_video_plan.get("target_resolution")
            or "720P"
        ),
        resolution_preset=str(model_params.get("resolution_preset") or ""),
        model_params=dict(model_params),
        references=references,
    )


def _submit_one(job: dict[str, Any]) -> dict[str, Any]:
    job["status"] = "submitting"
    save_job(job)
    try:
        references = publish_references(job.get("references") or [])
        job["public_references"] = references
        payload = _to_provider_payload(
            job,
            references,
            job.get("project_params") or {},
            job.get("final_video_plan") or {},
        )
        log_payload(
            logger,
            "video.provider.submit.input",
            {
                "job_id": job.get("job_id"),
                "batch_id": job.get("batch_id"),
                "shot_id": payload.shot_id,
                "model": payload.model,
                "api_model_id": payload.api_model_id,
                "duration": payload.duration,
                "ratio": payload.ratio,
                "resolution": payload.resolution,
                "resolution_preset": payload.resolution_preset,
                "include_reference_frames": settings.video_submit_include_reference_frames,
                "rewrite_prompt": settings.video_submit_rewrite_prompt,
                "prompt": payload.prompt,
                "image_references": [
                    {
                        "picture_index": item.get("picture_index"),
                        "picture_label": item.get("picture_label"),
                        "asset_id": item.get("asset_id"),
                        "logical_asset_id": item.get("logical_asset_id"),
                        "binding_asset_id": item.get("binding_asset_id"),
                        "display_name": item.get("display_name"),
                        "public_url": item.get("public_url"),
                        "url": item.get("url"),
                        "source": item.get("source"),
                    }
                    for item in references
                    if str(item.get("media_type") or "image").startswith("image")
                ],
            },
        )
        result = service_for(job["model"]).generate(payload)
        job["provider_task_id"] = result.provider_task_id
        job["provider"] = service_for(job["model"]).provider_name
        job["status"] = result.status if result.status in TERMINAL_STATUSES else "running"
        job["raw_provider_create"] = result.raw
        job["submitted_at"] = utc_now()
        job["error_code"] = None
        job["error_message"] = None
    except Exception as exc:
        logger.exception("video.generate.failed job_id=%s", job.get("job_id"))
        job["status"] = "failed"
        job["error_code"] = "generate_failed"
        job["error_message"] = str(exc)
    return save_job(job)


def submit_video_batch(
    final_video_plan: dict[str, Any],
    project_params: dict[str, Any] | None = None,
    *,
    regenerate_existing: bool = False,
) -> dict[str, Any]:
    params = project_params or {}
    binding = auto_bind_video_plan(
        final_video_plan,
        include_reference_frames=settings.video_submit_include_reference_frames,
        rewrite_prompt=settings.video_submit_rewrite_prompt,
    )
    plan_signature = _video_plan_batch_signature(final_video_plan)
    latest_batch = load_latest_batch()
    latest_signature = str((latest_batch or {}).get("plan_signature") or "")
    if latest_batch and latest_signature and latest_signature != plan_signature:
        latest_batch = None
    batch_id = str(latest_batch.get("batch_id") or "") if latest_batch else ""
    if not batch_id:
        batch_id = uuid.uuid4().hex
        latest_batch = None
    existing_jobs = jobs_for_batch(batch_id) if latest_batch else []
    existing_by_slot = {
        _video_job_slot_key(job.get("shot_id")): job
        for job in existing_jobs
        if _video_job_slot_key(job.get("shot_id"))
    }
    existing_job_ids = [job.get("job_id") for job in existing_jobs]
    jobs: list[dict[str, Any]] = []
    for ready in binding.get("ready", []):
        provider_payload = ready.get("provider_payload") or {}
        references = provider_payload.get("references") or []
        slot_key = _video_job_slot_key(ready.get("shot_id"))
        existing_job = existing_by_slot.get(slot_key)
        if existing_job and existing_job.get("status") in ACTIVE_STATUSES and existing_job.get("status") != "pending":
            jobs.append(existing_job)
            continue
        if existing_job and not regenerate_existing and _job_has_video_result(existing_job):
            jobs.append(existing_job)
            continue
        job_id = str(existing_job.get("job_id") or uuid.uuid4().hex) if existing_job else uuid.uuid4().hex
        retry_count = int(existing_job.get("retry_count") or 0) + 1 if existing_job else 0
        job = _reset_job_for_resubmit(dict(existing_job or {}))
        job = {
            **job,
            "job_id": job_id,
            "batch_id": batch_id,
            "shot_id": ready.get("shot_id"),
            "slot_key": slot_key,
            "model": canonicalize_model_id(provider_payload.get("model")),
            "provider": "",
            "status": "pending",
            "duration": provider_payload.get("duration"),
            "prompt": provider_payload.get("prompt"),
            "model_params": provider_payload.get("model_params") or {},
            "references": references,
            "bound_asset_ids": [ref.get("asset_id") for ref in references],
            "derived_reference_ids": [
                ref.get("asset_id") for ref in references if ref.get("derived")
            ],
            "project_params": params,
            "final_video_plan": {
                "aspect_ratio": final_video_plan.get("aspect_ratio"),
                "target_resolution": final_video_plan.get("target_resolution"),
            },
            "retry_count": retry_count,
            "created_at": (existing_job or {}).get("created_at") or utc_now(),
        }
        jobs.append(save_job(job))
    for blocked in binding.get("blocked", []):
        slot_key = _video_job_slot_key(blocked.get("shot_id"))
        existing_job = existing_by_slot.get(slot_key)
        job_id = str(existing_job.get("job_id") or uuid.uuid4().hex) if existing_job else uuid.uuid4().hex
        job = _reset_job_for_resubmit(dict(existing_job or {}))
        jobs.append(
            save_job(
                {
                    **job,
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "shot_id": blocked.get("shot_id"),
                    "slot_key": slot_key,
                    "status": "blocked",
                    "error_code": blocked.get("status") or "blocked",
                    "error_message": json.dumps(blocked, ensure_ascii=False),
                    "missing_required_asset_ids": blocked.get("missing_required_asset_ids"),
                    "missing_derived_reference_ids": blocked.get("missing_derived_reference_ids"),
                    "created_at": (existing_job or {}).get("created_at") or utc_now(),
                }
            )
        )
    batch = save_batch(
        {
            **(latest_batch or {}),
            "batch_id": batch_id,
            "episode_id": params.get("episode_id"),
            "status": "queued",
            "job_ids": _merge_job_ids(existing_job_ids, jobs),
            "created_at": (latest_batch or {}).get("created_at") or utc_now(),
            "registry_count": binding.get("registry_count", 0),
            "include_reference_frames": binding.get("include_reference_frames"),
            "rewrite_prompt": binding.get("rewrite_prompt"),
            "plan_signature": plan_signature,
            "plan_shot_count": len(final_video_plan.get("batch_shots") or final_video_plan.get("shots") or []),
        }
    )
    summary = _summarize_batch(batch)
    log_payload(logger, "video.batch.submit", summary)
    return summary


def _job_timed_out(job: dict[str, Any]) -> bool:
    started = job.get("submitted_at") or job.get("created_at")
    if not started:
        return False
    try:
        started_at = datetime.fromisoformat(str(started))
    except ValueError:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    return elapsed > settings.video_task_timeout_seconds


def _download_output_video(job: dict[str, Any], remote_url: str) -> dict[str, Any]:
    job_id = str(job["job_id"])
    suffix = Path(urlparse(remote_url).path).suffix or ".mp4"
    if suffix.lower() not in {".mp4", ".webm", ".mov"}:
        suffix = ".mp4"
    filename = f"{job_id}{suffix}"
    target = RESULT_ROOT / filename
    with httpx.Client(timeout=120.0, follow_redirects=True, trust_env=False) as client:
        response = client.get(remote_url)
        response.raise_for_status()
        data = response.content
    target.write_bytes(data)
    content_type = response.headers.get("content-type") or mimetypes.guess_type(filename)[0] or "video/mp4"
    published = upload_bytes(
        data,
        suffix=suffix,
        content_type=content_type,
        name_hint=filename,
    )
    job["provider_output_video_url"] = remote_url
    job["output_video_url"] = published["url"]
    job["output_s3_key"] = published["s3_key"]
    job["output_video_path"] = str(target)
    job["output_path"] = str(target)
    job["output_url"] = published["url"]
    log_payload(
        logger,
        "video.result.publish_s3",
        {
            "job_id": job_id,
            "shot_id": job.get("shot_id"),
            "provider_output_video_url": remote_url,
            "output_video_url": job["output_video_url"],
            "output_s3_key": job["output_s3_key"],
            "size_bytes": len(data),
        },
    )
    return job


def _is_s3_output_url(url: str) -> bool:
    text = str(url or "")
    return bool(settings.s3_bucket and settings.s3_bucket in text and settings.s3_key_prefix in text)


def _needs_result_publish(job: dict[str, Any]) -> bool:
    if job.get("status") != "succeeded" or job.get("output_s3_key"):
        return False
    remote_url = str(job.get("provider_output_video_url") or job.get("output_video_url") or "")
    return bool(remote_url and not _is_s3_output_url(remote_url))


def _publish_existing_result(job: dict[str, Any]) -> dict[str, Any]:
    remote_url = str(job.get("provider_output_video_url") or job.get("output_video_url") or "")
    try:
        job = _download_output_video(job, remote_url)
        job["error_message"] = None
    except Exception as exc:
        logger.exception("video.result.publish_failed job_id=%s", job.get("job_id"))
        job["provider_output_video_url"] = remote_url
        job["output_video_url"] = remote_url
        job["error_message"] = f"结果已生成但发布到 S3 失败: {exc}"
    return save_job(job)


def apply_query_result(job: dict[str, Any], query) -> dict[str, Any]:
    job["status"] = query.status
    job["raw_provider_query"] = query.raw
    if query.error_code:
        job["error_code"] = query.error_code
    if query.error_message:
        job["error_message"] = query.error_message
    if query.status == "succeeded" and query.output_video_url:
        try:
            job = _download_output_video(job, query.output_video_url)
        except Exception as exc:
            logger.exception("video.result.publish_failed job_id=%s", job.get("job_id"))
            job["output_video_url"] = query.output_video_url
            job["error_message"] = f"结果已生成但发布到 S3 失败: {exc}"
        save_result(
            str(job["job_id"]),
            {
                "shot_id": job.get("shot_id"),
                "model": job.get("model"),
                "provider": job.get("provider"),
                "provider_task_id": job.get("provider_task_id"),
                "status": job.get("status"),
                "provider_output_video_url": job.get("provider_output_video_url"),
                "output_video_url": job.get("output_video_url"),
                "output_s3_key": job.get("output_s3_key"),
                "output_video_path": job.get("output_video_path"),
                "output_url": job.get("output_url"),
            },
        )
    elif query.status in {"failed", "cancelled"}:
        save_result(
            str(job["job_id"]),
            {
                "shot_id": job.get("shot_id"),
                "model": job.get("model"),
                "provider": job.get("provider"),
                "provider_task_id": job.get("provider_task_id"),
                "status": job.get("status"),
                "error_code": job.get("error_code"),
                "error_message": job.get("error_message"),
            },
        )
    return save_job(job)


def _mark_job_failed(job: dict[str, Any], error_code: str, error_message: str) -> dict[str, Any]:
    job["status"] = "failed"
    job["error_code"] = error_code
    job["error_message"] = error_message
    save_result(
        str(job["job_id"]),
        {
            "shot_id": job.get("shot_id"),
            "model": job.get("model"),
            "provider": job.get("provider"),
            "provider_task_id": job.get("provider_task_id"),
            "status": "failed",
            "error_code": error_code,
            "error_message": error_message,
        },
    )
    return save_job(job)


def refresh_job(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.get("status") in TERMINAL_STATUSES or job.get("status") == "blocked":
        if _needs_result_publish(job):
            return _publish_existing_result(job)
        return job
    task_id = str(job.get("provider_task_id") or "").strip()
    if not task_id:
        return job
    if is_placeholder_job_id(str(job.get("job_id") or "")) or is_placeholder_task_id(task_id):
        return _mark_job_failed(job, "invalid_task", f"无效的供应商任务编号: {task_id}")
    if _job_timed_out(job):
        return _mark_job_failed(job, "timeout", "视频任务超时")
    try:
        query = service_for(str(job.get("model"))).query_result(task_id)
    except Exception as exc:
        if is_task_not_found(exc) or (
            isinstance(exc, LongTimeHttpError) and exc.status_code == 404
        ):
            return _mark_job_failed(job, "task_not_found", str(exc)[:800])
        job["query_error_count"] = int(job.get("query_error_count") or 0) + 1
        save_job(job)
        if int(job["query_error_count"]) >= 5:
            return _mark_job_failed(job, "query_error", str(exc)[:800])
        raise
    if query.status == "failed" and query.error_code in {"task_not_found", "invalid_task"}:
        return _mark_job_failed(
            job, query.error_code, query.error_message or "供应商任务不存在"
        )
    return apply_query_result(job, query)


def submit_created_jobs(batch_id: str) -> list[dict[str, Any]]:
    pending_jobs = [
        job
        for job in jobs_for_batch(batch_id)
        if job.get("status") == "pending"
    ]
    if not pending_jobs:
        return []
    max_workers = max(1, min(settings.video_max_concurrency, len(pending_jobs)))
    submitted: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_submit_one, job) for job in pending_jobs]
        for future in as_completed(futures):
            submitted.append(future.result())
    return submitted


def poll_pending_jobs() -> dict[str, Any]:
    refreshed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    batch = load_latest_batch()
    if not batch:
        return {"refreshed_count": 0, "error_count": 0, "errors": [], "mode": "latest_batch"}
    batch_id = str(batch.get("batch_id") or "")
    submitted = submit_created_jobs(batch_id)
    active_jobs = [
        job
        for job in jobs_for_batch(batch_id)
        if (
            (job.get("status") in ACTIVE_STATUSES and job.get("provider_task_id"))
            or _needs_result_publish(job)
        )
    ]
    for job in active_jobs:
        try:
            refreshed.append(refresh_job(str(job["job_id"])))
        except Exception as exc:
            if is_task_not_found(exc):
                refreshed.append(
                    _mark_job_failed(job, "task_not_found", str(exc)[:800])
                )
                continue
            logger.warning("video.poll.job_failed job_id=%s detail=%s", job.get("job_id"), exc)
            errors.append({"job_id": job.get("job_id"), "detail": str(exc)})
    latest = load_batch(batch_id)
    if latest:
        _summarize_batch(latest)
    return {
        "batch_id": batch_id,
        "active_count": len(active_jobs),
        "created_submit_count": len(submitted),
        "refreshed_count": len(refreshed),
        "error_count": len(errors),
        "errors": errors,
        "mode": "latest_batch",
    }


def get_batch(batch_id: str, *, refresh: bool = True) -> dict[str, Any]:
    batch = load_batch(batch_id)
    if batch is None:
        raise KeyError(batch_id)
    if refresh:
        for job in jobs_for_batch(batch_id):
            if job.get("status") in ACTIVE_STATUSES and job.get("provider_task_id"):
                try:
                    refresh_job(str(job["job_id"]))
                except Exception:
                    logger.exception("video.batch.refresh_failed job_id=%s", job.get("job_id"))
    return _summarize_batch(batch)


def get_latest_batch(*, refresh: bool = True) -> dict[str, Any]:
    batch = load_latest_batch()
    if batch is None:
        raise KeyError("latest")
    return get_batch(str(batch.get("batch_id") or ""), refresh=refresh)


def get_job(job_id: str, *, refresh: bool = True) -> dict[str, Any]:
    job = refresh_job(job_id) if refresh else load_job(job_id)
    if job is None:
        raise KeyError(job_id)
    return _public_job_view(job)


def retry_job(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.get("status") not in {"failed", "cancelled"}:
        raise ValueError("只有失败或取消的镜头可以重试")
    job["retry_count"] = int(job.get("retry_count") or 0) + 1
    job["provider_task_id"] = None
    job["output_video_url"] = None
    job["output_video_path"] = None
    job["output_url"] = None
    job["error_code"] = None
    job["error_message"] = None
    job["status"] = "queued"
    save_job(job)
    updated = _submit_one(job)
    batch = load_batch(str(updated.get("batch_id") or ""))
    if batch:
        return _summarize_batch(batch)
    return {"jobs": [_public_job_view(updated)], "batch_status": updated.get("status")}


def prepare_compose_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not jobs:
        raise ValueError("没有可合成的视频任务")
    batch_ids = {job.get("batch_id") for job in jobs if job.get("batch_id")}
    if len(batch_ids) == 1:
        summary = get_batch(str(next(iter(batch_ids))), refresh=True)
        latest = summary.get("jobs") or []
    else:
        latest = []
        for job in jobs:
            job_id = job.get("job_id")
            latest.append(get_job(str(job_id), refresh=True) if job_id else job)
    latest = [
        job
        for job in latest
        if job.get("status") == "succeeded" and _job_has_video_result(job)
    ]
    if len(latest) < 2:
        raise ValueError("至少需要 2 个已生成视频才能合成")
    prepared: list[dict[str, Any]] = []
    for job in latest:
        path = Path(str(job.get("output_video_path") or ""))
        if path.is_file():
            prepared.append(job)
            continue
        remote = str(job.get("output_video_url") or "")
        if not remote:
            raise ValueError(f"镜头 {job.get('shot_id')} 缺少视频文件")
        full = load_job(str(job.get("job_id") or "")) or job
        saved = save_job(_download_output_video(full, remote))
        prepared.append(_public_job_view(saved))
    return prepared
