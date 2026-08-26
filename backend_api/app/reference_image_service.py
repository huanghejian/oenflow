from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import settings


DEMO_IMAGE_ROOT = settings.project_root.parent / "work" / "EP001_V73" / "分镜参考图"
GENERATED_IMAGE_ROOT = settings.work_root / "demo_workflow" / "generated"
GENERATED_IMAGE_ROOT.mkdir(parents=True, exist_ok=True)


def demo_reference_images_available() -> bool:
    return (DEMO_IMAGE_ROOT / "u001_entry-v4.png").is_file() and (
        DEMO_IMAGE_ROOT / "u001_exit-v4.png"
    ).is_file()


def create_reference_image_pair_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job_root = settings.work_root / "reference_images" / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "job_id": job_id,
        "episode_id": payload["episode_id"],
        "shot_id": payload["shot_id"],
        "generation_strategy": "generate_entry_then_edit_exit",
        "usage": "ordinary_image_reference",
        "continuity_source_shot_id": payload.get("continuity_source_shot_id"),
        "entry": {
            "status": "queued",
            "asset_id": payload.get("entry_asset_id")
            or f"shotref::{payload['shot_id']}::entry",
            "prompt_zh": payload["entry_prompt_zh"],
        },
        "exit": {
            "status": "blocked_by_entry",
            "asset_id": payload.get("exit_asset_id")
            or f"shotref::{payload['shot_id']}::exit",
            "prompt_zh": payload["exit_prompt_zh"],
        },
    }

    if payload.get("demo_case") and demo_reference_images_available():
        manifest["status"] = "completed"
        manifest["demo_placeholder"] = payload["shot_id"] != "u001"
        manifest["entry"].update(
            {"status": "completed", "image_url": "/demo-assets/u001_entry-v4.png"}
        )
        manifest["exit"].update(
            {
                "status": "completed",
                "image_url": "/demo-assets/u001_exit-v4.png",
                "source_image_url": "/demo-assets/u001_entry-v4.png",
            }
        )
        manifest["message"] = (
            "本地 Demo 已完成站位图登记。u001 使用验收样图；其他分镜复用该样图作为"
            "流程占位，不代表真实逐镜生成结果。"
        )
    else:
        manifest["status"] = "provider_required"
        manifest["message"] = (
            "任务清单已建立；开始图必须先生成，结束图随后以开始图为编辑底图。"
            "当前尚未配置图片模型执行器。"
        )

    (job_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _raster_extension(data: bytes, media_type: str) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise RuntimeError(f"图片模型返回了不支持的格式：{media_type or 'unknown'}")


def _call_openrouter_image(
    prompt: str,
    input_references: list[str],
    model: str,
    aspect_ratio: str,
) -> tuple[bytes, str, dict[str, Any]]:
    if not settings.openrouter_api_key:
        raise RuntimeError("未配置 OPENROUTER_API_KEY，无法执行真实站位图生成")
    request_payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "resolution": settings.openrouter_image_resolution,
        "aspect_ratio": aspect_ratio,
        "quality": settings.openrouter_image_quality,
        "output_format": "png",
    }
    if input_references:
        request_payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": value}}
            for value in input_references
        ]
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                f"{settings.openrouter_base_url}/images",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message")
            except (ValueError, AttributeError):
                detail = response.text[:500]
            raise RuntimeError(
                f"OpenRouter 图片生成失败（HTTP {response.status_code}）：{detail or '未知错误'}"
            )
        result = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"OpenRouter 图片服务连接失败：{exc}") from exc
    images = result.get("data") or []
    if not images or not images[0].get("b64_json"):
        raise RuntimeError("OpenRouter 图片响应中没有 b64_json")
    item = images[0]
    try:
        data = base64.b64decode(item["b64_json"], validate=True)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("OpenRouter 返回的图片数据无法解码") from exc
    media_type = str(item.get("media_type") or "image/png")
    return data, media_type, result.get("usage") or {}


def _save_generated_image(job_id: str, role: str, data: bytes, media_type: str) -> tuple[str, str]:
    extension, normalized_mime = _raster_extension(data, media_type)
    filename = f"{job_id}_{role}{extension}"
    (GENERATED_IMAGE_ROOT / filename).write_bytes(data)
    return f"/workflow-generated/{filename}", normalized_mime


def create_reference_image_pair_provider_job(
    payload: dict[str, Any], input_references: list[str]
) -> dict[str, Any]:
    provider_payload = dict(payload)
    provider_payload["demo_case"] = False
    manifest = create_reference_image_pair_job(provider_payload)
    job_id = manifest["job_id"]
    model = str(payload.get("image_model") or settings.openrouter_image_model).strip()
    if not model:
        raise RuntimeError("未配置站位图图片模型")
    aspect_ratio = str(payload.get("aspect_ratio") or "9:16")

    entry_data, entry_mime, entry_usage = _call_openrouter_image(
        payload["entry_prompt_zh"], input_references, model, aspect_ratio
    )
    entry_url, entry_mime = _save_generated_image(
        job_id, "entry", entry_data, entry_mime
    )
    entry_data_url = f"data:{entry_mime};base64,{base64.b64encode(entry_data).decode('ascii')}"

    exit_data, exit_mime, exit_usage = _call_openrouter_image(
        payload["exit_prompt_zh"], [entry_data_url, *input_references], model, aspect_ratio
    )
    exit_url, exit_mime = _save_generated_image(job_id, "exit", exit_data, exit_mime)

    manifest.update(
        {
            "status": "completed",
            "generation_mode": "openrouter_images_api",
            "provider": "openrouter",
            "image_model": model,
            "aspect_ratio": aspect_ratio,
            "message": "已使用当前分镜 JSON 的站位图提示词和已绑定图片资产真实生成。",
            "usage": {"entry": entry_usage, "exit": exit_usage},
        }
    )
    manifest["entry"].update(
        {"status": "completed", "image_url": entry_url, "mime_type": entry_mime}
    )
    manifest["exit"].update(
        {
            "status": "completed",
            "image_url": exit_url,
            "mime_type": exit_mime,
            "source_image_url": entry_url,
        }
    )
    manifest_path = settings.work_root / "reference_images" / job_id / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
