from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
ACTIVE_STATUSES = {"pending", "queued", "submitting", "running"}


@dataclass
class ProviderSubmitPayload:
    shot_id: str
    model: str
    api_model_id: str
    duration: int
    prompt: str
    ratio: str
    resolution: str
    resolution_preset: str = ""
    model_params: dict[str, Any] = field(default_factory=dict)
    references: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderSubmitResult:
    provider_task_id: str
    status: str = "running"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderQueryResult:
    status: str
    output_video_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


PLACEHOLDER_TASK_IDS = {"fake-task", "test", "placeholder", "none", "null"}
PLACEHOLDER_TASK_RE = re.compile(r"^(fake[-_].+|task-\d+|test[-_].+)$", re.I)
PLACEHOLDER_JOB_RE = re.compile(r"^(job-contract-|job-fake-)", re.I)


def is_placeholder_task_id(task_id: str) -> bool:
    text = str(task_id or "").strip()
    if not text:
        return False
    return text.lower() in PLACEHOLDER_TASK_IDS or bool(PLACEHOLDER_TASK_RE.match(text))


def is_placeholder_job_id(job_id: str) -> bool:
    return bool(PLACEHOLDER_JOB_RE.match(str(job_id or "").strip()))


def is_task_not_found(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return status_code == 404 or "task not found" in text or "任务不存在" in text


def query_error_result(exc: Exception) -> ProviderQueryResult:
    not_found = is_task_not_found(exc)
    return ProviderQueryResult(
        status="failed" if not_found else "running",
        error_code="task_not_found" if not_found else "query_error",
        error_message=str(exc)[:800],
        raw={"exception": exc.__class__.__name__},
    )


def run_query(action) -> ProviderQueryResult:
    try:
        return action()
    except Exception as exc:
        return query_error_result(exc)


class VideoModelService(ABC):
    """每种生视频模型必须实现：生成任务、查询结果。"""

    model_id: str
    provider_name: str

    @abstractmethod
    def generate(self, payload: ProviderSubmitPayload) -> ProviderSubmitResult:
        """提交生视频任务，返回供应商任务 ID。"""

    @abstractmethod
    def query_result(self, provider_task_id: str) -> ProviderQueryResult:
        """查询生视频任务结果。"""


def image_references(payload: ProviderSubmitPayload) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.references
        if str(item.get("media_type") or "image").startswith("image")
        and item.get("public_url")
    ]


def video_references(payload: ProviderSubmitPayload) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.references
        if str(item.get("media_type") or "").startswith("video") and item.get("public_url")
    ]


def audio_references(payload: ProviderSubmitPayload) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.references
        if str(item.get("media_type") or "").startswith("audio") and item.get("public_url")
    ]


def normalize_ratio(value: Any, default: str = "16:9") -> str:
    text = str(value or "").strip()
    return text or default


def extract_resolution_token(preset: Any, fallback: str = "720p") -> str:
    text = str(preset or fallback).lower()
    if "2k" in text:
        return "2K"
    for token in ("1080", "720", "480"):
        if token in text:
            return f"{token}p"
    fallback_text = str(fallback or "720p")
    return fallback_text if fallback_text[-1].lower() == "p" else f"{fallback_text}p"


def normalize_provider_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    mapping = {
        "queued": "queued",
        "pending": "queued",
        "created": "queued",
        "submitting": "submitting",
        "running": "running",
        "processing": "running",
        "in_progress": "running",
        "unknown": "running",
        "succeeded": "succeeded",
        "success": "succeeded",
        "completed": "succeeded",
        "failed": "failed",
        "fail": "failed",
        "error": "failed",
        "expired": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    return mapping.get(text, "running" if text else "failed")


def first_video_url(*candidates: Any) -> str | None:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            for key in ("video_url", "url", "output_video_url"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            results = candidate.get("results")
            if isinstance(results, list) and results:
                found = first_video_url(results[0])
                if found:
                    return found
        if isinstance(candidate, list) and candidate:
            found = first_video_url(candidate[0])
            if found:
                return found
    return None
