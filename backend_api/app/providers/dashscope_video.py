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


def build_wan3_request(payload: ProviderSubmitPayload) -> dict[str, Any]:
    media: list[dict[str, str]] = []
    for item in image_references(payload):
        media.append({"type": "reference_image", "url": item["public_url"]})
    for item in video_references(payload):
        media.append({"type": "reference_video", "url": item["public_url"]})
    for item in audio_references(payload):
        media.append({"type": "reference_audio", "url": item["public_url"]})
    return {
        "model": payload.api_model_id or settings.wan3_model,
        "input": {
            "prompt": payload.prompt,
            "media": media,
        },
        "parameters": {
            "resolution": _wan_resolution(payload.resolution_preset or payload.resolution),
            "ratio": normalize_ratio(payload.ratio),
            "duration": int(payload.duration),
            "watermark": False,
        },
    }


def _wan_resolution(preset: str) -> str:
    token = extract_resolution_token(preset)
    return token.upper() if token.upper().endswith("P") else token


def parse_wan3_create_response(response: dict[str, Any]) -> ProviderSubmitResult:
    output = response.get("output") if isinstance(response.get("output"), dict) else {}
    task_id = str(output.get("task_id") or response.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(response.get("message") or "Wan3 创建任务未返回 task_id")
    return ProviderSubmitResult(
        provider_task_id=task_id,
        status=normalize_provider_status(output.get("task_status") or "pending"),
        raw=response,
    )


def parse_wan3_query_response(response: dict[str, Any]) -> ProviderQueryResult:
    output = response.get("output") if isinstance(response.get("output"), dict) else {}
    status = normalize_provider_status(output.get("task_status") or response.get("status"))
    error_code = str(output.get("code") or response.get("code") or "") or None
    error_message = str(output.get("message") or response.get("message") or "") or None
    return ProviderQueryResult(
        status=status,
        output_video_url=first_video_url(output, output.get("results"), response),
        error_code=error_code if status == "failed" else None,
        error_message=error_message if status == "failed" else None,
        raw=response,
    )


class Wan3VideoService(VideoModelService):
    model_id = "wan3"
    provider_name = "dashscope"

    def generate(self, payload: ProviderSubmitPayload) -> ProviderSubmitResult:
        headers = {
            "X-DashScope-Async": "enable",
            "X-DashScope-DataInspection": '{"input":"enable","output":"enable"}',
        }
        data, _ = post_json(
            settings.wan3_submit_url,
            build_wan3_request(payload),
            bearer(settings.wan3_api_key),
            headers=headers,
        )
        return parse_wan3_create_response(data)

    def query_result(self, provider_task_id: str) -> ProviderQueryResult:
        def _query() -> ProviderQueryResult:
            url = join_task_url(settings.wan3_query_base_url, provider_task_id)
            data, _ = get_json(url, bearer(settings.wan3_api_key))
            return parse_wan3_query_response(data)

        return run_query(_query)


DashScopeWan3Adapter = Wan3VideoService
