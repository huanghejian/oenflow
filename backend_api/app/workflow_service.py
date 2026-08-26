from __future__ import annotations

import json
import base64
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .executor_binding import bind_logical_assets


WORKFLOW_ROOT = settings.work_root / "demo_workflow"
WORKFLOW_UPLOAD_ROOT = WORKFLOW_ROOT / "uploads"
WORKFLOW_VIDEO_JOB_ROOT = WORKFLOW_ROOT / "video_jobs"
WORKFLOW_REGISTRY_PATH = WORKFLOW_ROOT / "asset_registry.json"
DEMO_INPUT_ASSET_ROOT = settings.project_root.parent / "work" / "EP001_V73" / "生成图片"
DEMO_REFERENCE_ASSET_ROOT = settings.project_root.parent / "work" / "EP001_V73" / "分镜参考图"
MAX_IMAGE_BYTES = 15 * 1024 * 1024

for directory in (WORKFLOW_UPLOAD_ROOT, WORKFLOW_VIDEO_JOB_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

_registry_lock = threading.Lock()


def _load_registry_unlocked() -> dict[str, dict[str, Any]]:
    if not WORKFLOW_REGISTRY_PATH.is_file():
        return {}
    try:
        data = json.loads(WORKFLOW_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_registry_unlocked(registry: dict[str, dict[str, Any]]) -> None:
    WORKFLOW_ROOT.mkdir(parents=True, exist_ok=True)
    temp = WORKFLOW_REGISTRY_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(WORKFLOW_REGISTRY_PATH)


def registry_snapshot() -> dict[str, Any]:
    with _registry_lock:
        registry = _load_registry_unlocked()
    return {"count": len(registry), "assets": registry}


def register_binding(asset_id: str, binding: dict[str, Any]) -> dict[str, Any]:
    normalized = str(asset_id or "").strip()
    if not normalized:
        raise ValueError("asset_id 不得为空")
    record = {key: value for key, value in binding.items() if value is not None}
    record["asset_id"] = normalized
    record.setdefault("binding_status", "bound")
    with _registry_lock:
        registry = _load_registry_unlocked()
        registry[normalized] = record
        _save_registry_unlocked(registry)
    return record


def _image_extension(content_type: str, data: bytes) -> tuple[str, str]:
    mime = content_type.split(";", 1)[0].strip().lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and mime in {"", "application/octet-stream", "image/png"}:
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff") and mime in {"", "application/octet-stream", "image/jpeg", "image/jpg"}:
        return ".jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and mime in {"", "application/octet-stream", "image/webp"}:
        return ".webp", "image/webp"
    raise ValueError("仅支持真实 PNG、JPEG 或 WebP 图片")


def save_uploaded_asset(
    asset_id: str,
    data: bytes,
    content_type: str,
    original_filename: str | None = None,
) -> dict[str, Any]:
    if not data:
        raise ValueError("上传图片为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片不得超过 15MB")
    extension, normalized_mime = _image_extension(content_type, data)
    file_id = uuid.uuid4().hex
    target = WORKFLOW_UPLOAD_ROOT / f"{file_id}{extension}"
    target.write_bytes(data)
    return register_binding(
        asset_id,
        {
            "file_id": f"local-upload::{file_id}",
            "url": f"/workflow-assets/{target.name}",
            "media_type": "image",
            "mime_type": normalized_mime,
            "size_bytes": len(data),
            "original_filename": original_filename or "uploaded-image",
            "source": "user_upload",
        },
    )


def seed_demo_assets() -> dict[str, Any]:
    if not DEMO_INPUT_ASSET_ROOT.is_dir():
        raise RuntimeError("内置 Demo 图片资产不存在")
    seeded = []
    for path in sorted(DEMO_INPUT_ASSET_ROOT.glob("*.png")):
        seeded.append(
            register_binding(
                path.stem,
                {
                    "file_id": f"demo-asset::{path.stem}",
                    "url": f"/demo-input-assets/{path.name}",
                    "media_type": "image",
                    "mime_type": "image/png",
                    "size_bytes": path.stat().st_size,
                    "original_filename": path.name,
                    "source": "bundled_demo_asset",
                },
            )
        )
    return {"seeded_count": len(seeded), "assets": seeded}


def register_reference_pair(manifest: dict[str, Any]) -> dict[str, Any]:
    registered = []
    for key in ("entry", "exit"):
        item = manifest.get(key) or {}
        asset_id = item.get("asset_id")
        image_url = item.get("image_url")
        if not asset_id or not image_url:
            continue
        registered.append(
            register_binding(
                str(asset_id),
                {
                    "file_id": f"reference-image::{manifest.get('job_id')}::{key}",
                    "url": image_url,
                    "media_type": "image",
                    "mime_type": "image/png",
                    "source": "derived_reference_image",
                    "shot_id": manifest.get("shot_id"),
                    "generated_role": key,
                    "ordinary_image_reference": True,
                },
            )
        )
    return {"registered_count": len(registered), "assets": registered}


def missing_asset_ids(asset_ids: list[str]) -> list[str]:
    with _registry_lock:
        registry = _load_registry_unlocked()
    return [asset_id for asset_id in asset_ids if asset_id not in registry]


def asset_reference_data_urls(asset_ids: list[str]) -> list[str]:
    with _registry_lock:
        registry = _load_registry_unlocked()
    roots = {
        "/workflow-assets/": WORKFLOW_UPLOAD_ROOT,
        "/demo-input-assets/": DEMO_INPUT_ASSET_ROOT,
        "/demo-assets/": DEMO_REFERENCE_ASSET_ROOT,
    }
    references: list[str] = []
    for asset_id in asset_ids:
        binding = registry.get(asset_id)
        if not binding:
            raise ValueError(f"图片资产尚未绑定：{asset_id}")
        url = str(binding.get("url") or "")
        root = next((value for prefix, value in roots.items() if url.startswith(prefix)), None)
        prefix = next((value for value in roots if url.startswith(value)), None)
        if root is None or prefix is None:
            raise ValueError(f"图片资产不是可读取的本地文件：{asset_id}")
        filename = Path(url.removeprefix(prefix)).name
        path = (root / filename).resolve()
        if path.parent != root.resolve() or not path.is_file():
            raise ValueError(f"图片资产文件不存在：{asset_id}")
        mime = str(binding.get("mime_type") or "image/png")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        references.append(f"data:{mime};base64,{encoded}")
    return references


def auto_bind_video_plan(final_video_plan: dict[str, Any]) -> dict[str, Any]:
    with _registry_lock:
        registry = _load_registry_unlocked()
    result = bind_logical_assets(final_video_plan, registry)
    result["registry_count"] = len(registry)
    result["binding_mode"] = "local_demo_registry"
    return result


def submit_video_jobs(final_video_plan: dict[str, Any]) -> dict[str, Any]:
    binding = auto_bind_video_plan(final_video_plan)
    jobs: list[dict[str, Any]] = []
    for ready in binding.get("ready", []):
        job_id = uuid.uuid4().hex
        provider_payload = ready.get("provider_payload") or {}
        references = provider_payload.get("references") or []
        manifest = {
            "job_id": job_id,
            "shot_id": ready.get("shot_id"),
            "status": "queued_demo",
            "mode": "local_video_provider_simulation",
            "message": "已完成资产和开始/结束站位图绑定；Demo 仅模拟送往视频生成器。",
            "provider_payload": provider_payload,
            "bound_asset_ids": [ref.get("asset_id") for ref in references],
            "derived_reference_ids": [
                ref.get("asset_id") for ref in references if ref.get("derived")
            ],
        }
        (WORKFLOW_VIDEO_JOB_ROOT / f"{job_id}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        jobs.append(manifest)
    return {
        "mode": "local_demo",
        "submitted_count": len(jobs),
        "blocked_count": binding.get("blocked_count", 0),
        "jobs": jobs,
        "blocked": binding.get("blocked", []),
        "registry_count": binding.get("registry_count", 0),
    }
