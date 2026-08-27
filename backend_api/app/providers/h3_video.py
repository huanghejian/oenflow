from __future__ import annotations

from typing import Any

from ..config import settings
from ..long_time_http import bearer, get_json, join_task_url, post_json
from .base import (
    ProviderQueryResult,
    ProviderSubmitPayload,
    ProviderSubmitResult,
    VideoModelService,
    run_query,
    audio_references,
    extract_resolution_token,
    first_video_url,
    image_references,
    normalize_provider_status,
    normalize_ratio,
    video_references,
)


def h3_resolution(preset: str, fallback: str = "720P") -> str:
    token = extract_resolution_token(preset, fallback)
    if token.upper() == "2K":
        return "2K"
    if "720" in token or "768" in token:
        return "768P"
    return token.upper() if token.upper().endswith("P") else f"{token}P"


def build_h3_request(payload: ProviderSubmitPayload) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for item in image_references(payload):
        content.append(
            {
                "type": "image_url",
                "role": "reference_image",
                "image_url": {"url": item["public_url"]},
            }
        )
    for item in video_references(payload):
        content.append(
            {
                "type": "video_url",
                "role": "reference_video",
                "video_url": {"url": item["public_url"]},
            }
        )
    for item in audio_references(payload):
        content.append(
            {
                "type": "audio_url",
                "role": "reference_audio",
                "audio_url": {"url": item["public_url"]},
            }
        )
    content.append({"type": "text", "text": payload.prompt})
    return {
        "model": payload.api_model_id or settings.h3_model,
        "content": content,
        "resolution": h3_resolution(payload.resolution_preset or payload.resolution),
        "duration": int(payload.duration),
        "ratio": normalize_ratio(payload.ratio),
        "aigc_watermark": False,
    }


def parse_h3_create_response(response: dict[str, Any]) -> ProviderSubmitResult:
    task_id = str(response.get("task_id") or response.get("id") or "").strip()
    if not task_id:
        raise RuntimeError("H3 创建任务未返回 task_id")
    return ProviderSubmitResult(
        provider_task_id=task_id,
        status=normalize_provider_status(response.get("status") or "running"),
        raw=response,
    )


def parse_h3_query_response(response: dict[str, Any]) -> ProviderQueryResult:
    task = response.get("task") if isinstance(response.get("task"), dict) else response
    status = normalize_provider_status(task.get("status"))
    content = task.get("content") if isinstance(task.get("content"), dict) else {}
    error = task.get("error") if isinstance(task.get("error"), dict) else {}
    return ProviderQueryResult(
        status=status,
        output_video_url=first_video_url(content, task, response),
        error_code=str(error.get("code") or "") or None,
        error_message=str(error.get("message") or "") or None,
        raw=response,
    )


class H3VideoService(VideoModelService):
    model_id = "h3"
    provider_name = "h3"

    def generate(self, payload: ProviderSubmitPayload) -> ProviderSubmitResult:
        body = build_h3_request(payload)
        data, _ = post_json(settings.h3_submit_url, body, bearer(settings.h3_api_key))
        return parse_h3_create_response(data)

    def query_result(self, provider_task_id: str) -> ProviderQueryResult:
        def _query() -> ProviderQueryResult:
            url = join_task_url(settings.h3_query_url, provider_task_id)
            data, _ = get_json(url, bearer(settings.h3_api_key))
            return parse_h3_query_response(data)

        return run_query(_query)


H3VideoAdapter = H3VideoService
