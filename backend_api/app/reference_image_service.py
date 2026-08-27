from __future__ import annotations

import base64
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def _xingtu_request_payload(
    prompt: str,
    model: str,
    aspect_ratio: str,
    size: str,
    input_references: list[str] | None = None,
) -> dict[str, Any]:
    ratio = (aspect_ratio or "9:16").strip() or "9:16"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": f"【图片比例{ratio}】{prompt}",
        "sequential_image_generation": "disabled",
        "watermark": False,
        "response_format": "url",
        "size": size,
        "output_format": "jpeg",
    }
    if input_references:
        payload["image"] = list(input_references)
    return payload


def _station_finished_prompt(prompt: str, state_label: str) -> str:
    cleaned = str(prompt or "").strip()
    legacy_prefixes = (
        "生成本原子镜头的动作开始状态参考图。该图片仅作为视频模型的普通图片参考，不作为首帧控制参数。",
        "以本镜动作开始状态参考图作为编辑底图，生成同一原子镜头的动作结束状态参考图。该图片仅作为视频模型的普通图片参考，不作为尾帧控制参数。",
    )
    for prefix in legacy_prefixes:
        cleaned = cleaned.replace(prefix, "")
    cleaned = cleaned.replace(
        "开始时可见状态：首帧普通参考图，9:16短剧画面。",
        "开始状态：",
    ).replace(
        "只把动作与表演推进到以下结束状态：尾帧普通参考图，9:16短剧画面。",
        "结束状态：",
    ).replace(
        "；要求构图清晰、身份稳定、可作为后续视频生成的普通图片参考。",
        "",
    )
    while "。。" in cleaned:
        cleaned = cleaned.replace("。。", "。")
    return (
        f"竖屏 9:16 短剧分镜{state_label}帧，全彩高完成度成片，"
        "严格融合并继承输入角色、场景和道具图片的造型、颜色、材质、光影与视觉风格，"
        "人物位置、身体朝向、表情、动作、前中后景层次和镜头构图必须清晰，"
        "环境、材质和关键道具细节完整，画面可直接作为视频生成的首尾帧。"
        "禁止线稿、草图、白底设定稿、低细节占位图，禁止字幕、字卡、水印和额外文字。"
        f"镜头状态：{cleaned}"
    )


def _call_xingtu_image(
    prompt: str,
    model: str,
    aspect_ratio: str,
    size: str,
    input_references: list[str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    if not settings.xingtu_image_api_key:
        raise RuntimeError("未配置 XINGTU_IMAGE_API_KEY，无法执行星图 5.0 Pro 生图")
    if size not in {"1K", "2K", "4K"}:
        raise RuntimeError(f"星图图片尺寸必须是 1K、2K 或 4K，当前为：{size}")
    request_payload = _xingtu_request_payload(
        prompt, model, aspect_ratio, size, input_references
    )
    try:
        with httpx.Client(
            timeout=300.0,
            follow_redirects=True,
            verify=settings.xingtu_image_verify_ssl,
            trust_env=False,
        ) as client:
            response = client.post(
                settings.xingtu_image_endpoint,
                headers={
                    "Authorization": f"Bearer {settings.xingtu_image_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            if (
                response.status_code == 400
                and "sequential_image_generation" in response.text
                and any(marker in response.text for marker in ("not supported", "InvalidParameter"))
            ):
                compatible_payload = dict(request_payload)
                compatible_payload.pop("sequential_image_generation", None)
                response = client.post(
                    settings.xingtu_image_endpoint,
                    headers={
                        "Authorization": f"Bearer {settings.xingtu_image_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=compatible_payload,
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"星图 5.0 Pro 图片生成失败（HTTP {response.status_code}）：{response.text[:500]}"
                )
            result = response.json()
            images = result.get("data") or []
            if not images:
                raise RuntimeError("星图 5.0 Pro 响应中没有 data")
            item = images[0]
            if item.get("url"):
                image_url = str(item["url"])
                parsed_url = urlparse(image_url)
                if parsed_url.scheme not in {"https", "http"} or not parsed_url.netloc:
                    raise RuntimeError("星图 5.0 Pro 返回了无效图片 URL")
                image_response = client.get(image_url, timeout=120.0)
                image_response.raise_for_status()
                image_data = image_response.content
                media_type = image_response.headers.get("content-type", "image/jpeg")
            elif item.get("b64_json"):
                image_data = base64.b64decode(item["b64_json"], validate=True)
                media_type = str(item.get("media_type") or "image/jpeg")
            else:
                raise RuntimeError("星图 5.0 Pro 的 data[0] 中没有 url 或 b64_json")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"星图 5.0 Pro 图片服务连接失败：{exc}") from exc
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"星图 5.0 Pro 返回数据无法解析：{exc}") from exc
    return image_data, media_type, result.get("usage") or {}


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


def create_reference_image_pair_xingtu_job(
    payload: dict[str, Any], input_references: list[str]
) -> dict[str, Any]:
    provider_payload = dict(payload)
    provider_payload["demo_case"] = False
    manifest = create_reference_image_pair_job(provider_payload)
    job_id = manifest["job_id"]
    model = str(payload.get("image_model") or settings.xingtu_image_model).strip()
    if not model:
        raise RuntimeError("未配置星图 5.0 Pro 图片模型")
    aspect_ratio = str(payload.get("aspect_ratio") or "9:16").strip() or "9:16"
    size = str(payload.get("image_size") or settings.xingtu_image_size).strip().upper()

    if not input_references:
        raise RuntimeError("星图融合生图至少需要一张已绑定的角色、场景或道具图片")
    entry_prompt = _station_finished_prompt(payload["entry_prompt_zh"], "开始")
    exit_prompt = _station_finished_prompt(payload["exit_prompt_zh"], "结束")
    with ThreadPoolExecutor(max_workers=2) as pool:
        entry_future = pool.submit(
            _call_xingtu_image, entry_prompt, model, aspect_ratio, size, input_references
        )
        exit_future = pool.submit(
            _call_xingtu_image, exit_prompt, model, aspect_ratio, size, input_references
        )
        entry_data, entry_mime, entry_usage = entry_future.result()
        exit_data, exit_mime, exit_usage = exit_future.result()
    entry_url, entry_mime = _save_generated_image(
        job_id, "entry", entry_data, entry_mime
    )
    exit_url, exit_mime = _save_generated_image(job_id, "exit", exit_data, exit_mime)

    manifest.update(
        {
            "status": "completed",
            "generation_strategy": "parallel_entry_exit_from_same_assets",
            "generation_mode": "xingtu_image_fusion",
            "provider": "volcengine_ark",
            "image_model": model,
            "aspect_ratio": aspect_ratio,
            "size": size,
            "message": (
                "星图同时以本镜头绑定的角色、场景和道具图片为参考，"
                "并行生成全彩开始图与结束图。"
            ),
            "usage": {"entry": entry_usage, "exit": exit_usage},
        }
    )
    manifest["entry"].update(
        {
            "status": "completed",
            "image_url": entry_url,
            "mime_type": entry_mime,
            "prompt_zh": entry_prompt,
            "local_image_url": entry_url,
            "storage": {"status": "pending_frontend_upload", "provider": "r2"},
        }
    )
    manifest["exit"].update(
        {
            "status": "completed",
            "image_url": exit_url,
            "mime_type": exit_mime,
            "prompt_zh": exit_prompt,
            "local_image_url": exit_url,
            "storage": {"status": "pending_frontend_upload", "provider": "r2"},
        }
    )
    manifest_path = settings.work_root / "reference_images" / job_id / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def create_reference_image_frame_xingtu_job(
    payload: dict[str, Any],
    role: str,
    input_references: list[str],
) -> dict[str, Any]:
    """Generate one fused frame locally; the browser publishes it to frontend R2."""
    if role not in {"entry", "exit"}:
        raise RuntimeError(f"不支持的参考图角色：{role}")
    if not input_references:
        raise RuntimeError("融合生图至少需要一张已绑定的角色、场景或道具图片")

    model = str(payload.get("image_model") or settings.xingtu_image_model).strip()
    if not model:
        raise RuntimeError("未配置星图 5.0 Pro 图片模型")
    aspect_ratio = str(payload.get("aspect_ratio") or "9:16").strip() or "9:16"
    size = str(payload.get("image_size") or settings.xingtu_image_size).strip().upper()
    prompt_key = "entry_prompt_zh" if role == "entry" else "exit_prompt_zh"
    state_label = "开始" if role == "entry" else "结束"
    raw_prompt = str(payload.get(prompt_key) or "").strip()
    if not raw_prompt:
        raise RuntimeError(f"缺少{state_label}参考图提示词")
    prompt = _station_finished_prompt(raw_prompt, state_label)

    job_id = uuid.uuid4().hex
    image_data, image_mime, usage = _call_xingtu_image(
        prompt, model, aspect_ratio, size, input_references
    )
    local_url, image_mime = _save_generated_image(
        job_id, role, image_data, image_mime
    )
    asset_id = payload.get(f"{role}_asset_id") or f"shotref::{payload['shot_id']}::{role}"
    frame = {
        "status": "generated_local",
        "asset_id": asset_id,
        "prompt_zh": prompt,
        "image_url": local_url,
        "local_image_url": local_url,
        "mime_type": image_mime,
        "storage": {"status": "pending_frontend_upload", "provider": "r2"},
    }
    if role == "exit" and payload.get("source_image_url"):
        frame["source_image_url"] = payload["source_image_url"]
    return {
        "job_id": job_id,
        "episode_id": payload.get("episode_id"),
        "shot_id": payload.get("shot_id"),
        "status": "waiting_r2_upload",
        "generation_mode": "xingtu_manual_frame",
        "generation_strategy": "manual_one_frame_per_request",
        "provider": "volcengine_ark",
        "image_model": model,
        "aspect_ratio": aspect_ratio,
        "size": size,
        "generated_role": role,
        "usage": usage,
        role: frame,
    }
