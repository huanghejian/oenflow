from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from ..config import settings
from ..long_time_http import LongTimeHttpError, bearer, get_json, join_task_url, post_json
from ..model_ids import canonicalize_model_id
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


def xingguang_api_model(model: str) -> str:
    canonical = canonicalize_model_id(model)
    if canonical == "xingguang-3.5":
        return settings.topenrouter_xingguang_35_model
    return settings.topenrouter_xingguang_30_model


def _configured(value: str | None) -> str:
    text = str(value or "").strip()
    return "" if not text or text.upper().startswith("XXX") else text


def xingguang_submit_url(model: str) -> str:
    canonical = canonicalize_model_id(model)
    if canonical == "xingguang-3.5":
        return (
            _configured(settings.xingguang_35_submit_url)
            or settings.topenrouter_submit_url
        ).rstrip("/")
    if canonical == "xingguang-3.0":
        return (
            _configured(settings.xingguang_30_submit_url)
            or settings.topenrouter_submit_url
        ).rstrip("/")
    return settings.topenrouter_submit_url.rstrip("/")


def xingguang_api_key(model: str) -> str:
    canonical = canonicalize_model_id(model)
    if canonical == "xingguang-3.5":
        return (
            _configured(settings.xingguang_35_api_key)
            or _configured(settings.topenrouter_api_key)
        )
    if canonical == "xingguang-3.0":
        return (
            _configured(settings.xingguang_30_api_key)
            or _configured(settings.topenrouter_api_key)
        )
    return _configured(settings.topenrouter_api_key)


def xingguang_resolution(model: str, preset: str, fallback: str = "720P") -> str:
    text = str(preset or fallback)
    if "SR" in text.upper() or "sr" in text.lower():
        if canonicalize_model_id(model) == "xingguang-3.5":
            return "480p"
        if "1080" in text or "2k" in text.lower() or "2K" in text:
            return "720p"
        return "480p"
    return extract_resolution_token(text, fallback)


def parse_upload_asset_id(response: dict[str, Any]) -> str:
    code = response.get("code")
    if code not in {0, "0", "success", "Success"}:
        raise RuntimeError(response.get("message") or "TopenRouter 素材上传失败")
    data = response.get("data") or {}
    asset_id = str(data.get("Id") or data.get("id") or "").strip()
    if not asset_id:
        raise RuntimeError("TopenRouter 素材上传未返回资产 ID")
    return f"asset://{asset_id}"


def build_xingguang_request(
    payload: ProviderSubmitPayload, asset_refs: list[dict[str, Any]]
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for item in asset_refs:
        media_type = str(item.get("media_type") or "image")
        url = item.get("provider_asset_url") or item.get("public_url")
        if not url:
            continue
        if media_type.startswith("video"):
            content.append(
                {
                    "type": "video_url",
                    "role": "reference_video",
                    "video_url": {"url": url},
                }
            )
        elif media_type.startswith("audio"):
            content.append(
                {
                    "type": "audio_url",
                    "role": "reference_audio",
                    "audio_url": {"url": url},
                }
            )
        else:
            content.append(
                {
                    "type": "image_url",
                    "role": "reference_image",
                    "image_url": {"url": url},
                }
            )
    content.append({"type": "text", "text": payload.prompt})
    return {
        "model": payload.api_model_id or xingguang_api_model(payload.model),
        "generate_audio": True,
        "draft": False,
        "resolution": xingguang_resolution(
            payload.model, payload.resolution_preset or payload.resolution
        ),
        "ratio": normalize_ratio(payload.ratio),
        "duration": int(payload.duration),
        "watermark": False,
        "content": content,
    }


def parse_xingguang_create_response(response: dict[str, Any]) -> ProviderSubmitResult:
    task_id = str(response.get("id") or response.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(response.get("message") or "星光创建任务未返回 id")
    return ProviderSubmitResult(
        provider_task_id=task_id,
        status=normalize_provider_status(response.get("status") or "queued"),
        raw=response,
    )


def parse_xingguang_query_response(response: dict[str, Any]) -> ProviderQueryResult:
    status = normalize_provider_status(response.get("status"))
    content = response.get("content") if isinstance(response.get("content"), dict) else {}
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    return ProviderQueryResult(
        status=status,
        output_video_url=first_video_url(content, response),
        error_code=str(error.get("code") or "") or None,
        error_message=str(error.get("message") or "") or None,
        raw=response,
    )


def _asset_still_processing(exc: Exception) -> bool:
    text = str(exc).lower()
    return "asset is still processing" in text or "still processing" in text


class XingguangVideoService(VideoModelService):
    model_id = "xingguang-3.0"
    provider_name = "topenrouter"

    def __init__(self) -> None:
        self._asset_cache: dict[str, str] = {}

    def upload_asset(self, public_url: str, asset_type: str, model: str) -> str:
        cache_key = f"{xingguang_api_model(model)}|{asset_type}|{public_url}"
        cached = self._asset_cache.get(cache_key)
        if cached:
            return cached
        query = urlencode({"model": xingguang_api_model(model)})
        url = f"{settings.topenrouter_upload_asset_url}?{query}"
        data, _ = post_json(
            url,
            {"url": public_url, "asset_type": asset_type},
            bearer(xingguang_api_key(model)),
        )
        asset_url = parse_upload_asset_id(data)
        self._asset_cache[cache_key] = asset_url
        return asset_url

    def prepare_assets(self, payload: ProviderSubmitPayload) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        groups = (
            (image_references(payload), "Image"),
            (video_references(payload), "Video"),
            (audio_references(payload), "Audio"),
        )
        for items, asset_type in groups:
            for item in items:
                public_url = str(item["public_url"])
                prepared.append(
                    {
                        **item,
                        "provider_asset_url": self.upload_asset(
                            public_url, asset_type, payload.model
                        ),
                    }
                )
        if prepared and settings.video_asset_process_wait_seconds > 0:
            time.sleep(settings.video_asset_process_wait_seconds)
        return prepared

    def generate(self, payload: ProviderSubmitPayload) -> ProviderSubmitResult:
        prepared = self.prepare_assets(payload)
        body = build_xingguang_request(payload, prepared)
        last_error: Exception | None = None
        for attempt in range(settings.video_asset_process_retry + 1):
            try:
                data, _ = post_json(
                    xingguang_submit_url(payload.model or self.model_id),
                    body,
                    bearer(xingguang_api_key(payload.model or self.model_id)),
                )
                return parse_xingguang_create_response(data)
            except (LongTimeHttpError, RuntimeError) as exc:
                last_error = exc
                if attempt < settings.video_asset_process_retry and _asset_still_processing(exc):
                    time.sleep(3)
                    continue
                raise
        raise last_error or RuntimeError("星光创建任务失败")

    def query_result(self, provider_task_id: str) -> ProviderQueryResult:
        def _query() -> ProviderQueryResult:
            url = join_task_url(settings.topenrouter_query_task_url, provider_task_id)
            data, _ = get_json(url, bearer(xingguang_api_key(self.model_id)))
            return parse_xingguang_query_response(data)

        return run_query(_query)


class Xingguang30VideoService(XingguangVideoService):
    model_id = "xingguang-3.0"


class Xingguang35VideoService(XingguangVideoService):
    model_id = "xingguang-3.5"


TopenRouterXingguangAdapter = XingguangVideoService
