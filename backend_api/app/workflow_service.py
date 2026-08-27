from __future__ import annotations

import json
import base64
import shutil
import subprocess
import threading
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .executor_binding import bind_logical_assets


WORKFLOW_ROOT = settings.work_root / "demo_workflow"
WORKFLOW_UPLOAD_ROOT = WORKFLOW_ROOT / "uploads"
WORKFLOW_VIDEO_JOB_ROOT = WORKFLOW_ROOT / "video_jobs"
WORKFLOW_VIDEO_OUTPUT_ROOT = WORKFLOW_ROOT / "video_outputs"
WORKFLOW_REGISTRY_PATH = WORKFLOW_ROOT / "asset_registry.json"
DEMO_INPUT_ASSET_ROOT = settings.project_root.parent / "work" / "EP001_V73" / "生成图片"
DEMO_REFERENCE_ASSET_ROOT = settings.project_root.parent / "work" / "EP001_V73" / "分镜参考图"
MAX_IMAGE_BYTES = 15 * 1024 * 1024

for directory in (WORKFLOW_UPLOAD_ROOT, WORKFLOW_VIDEO_JOB_ROOT, WORKFLOW_VIDEO_OUTPUT_ROOT):
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
    from .s3_asset_service import upload_bytes

    published = upload_bytes(
        data,
        suffix=extension,
        content_type=normalized_mime,
        name_hint=original_filename or f"{asset_id}{extension}",
    )
    return register_binding(
        asset_id,
        {
            "file_id": f"s3::{published['s3_key']}",
            "url": published["url"],
            "image_url": published["url"],
            "public_url": published["url"],
            "s3_key": published["s3_key"],
            "local_url": f"/workflow-assets/{target.name}",
            "media_type": "image",
            "mime_type": normalized_mime,
            "size_bytes": len(data),
            "original_filename": original_filename or "uploaded-image",
            "source": "user_upload_s3",
        },
    )


def create_asset_upload_token(
    asset_id: str,
    *,
    content_type: str,
    size_bytes: int,
    original_filename: str | None = None,
) -> dict[str, Any]:
    if size_bytes <= 0:
        raise ValueError("上传图片为空")
    if size_bytes > MAX_IMAGE_BYTES:
        raise ValueError("单张图片不得超过 15MB")
    from .s3_asset_service import create_presigned_image_upload

    return create_presigned_image_upload(
        asset_id=asset_id,
        content_type=content_type,
        size_bytes=size_bytes,
        original_filename=original_filename,
    )


def register_s3_uploaded_asset(
    asset_id: str,
    *,
    s3_key: str,
    url: str | None = None,
    content_type: str | None = None,
    size_bytes: int | None = None,
    original_filename: str | None = None,
) -> dict[str, Any]:
    from .s3_asset_service import (
        normalize_image_content_type,
        object_http_url,
        validate_upload_object_key,
    )

    key = validate_upload_object_key(s3_key)
    actual_size = int(size_bytes or 0)
    if actual_size <= 0:
        raise ValueError("S3 图片对象为空")
    if actual_size > MAX_IMAGE_BYTES:
        raise ValueError("单张图片不得超过 15MB")
    normalized_mime, _ = normalize_image_content_type(content_type)
    public_url = object_http_url(key)
    if url and urllib.parse.urlsplit(url).scheme in {"http", "https"}:
        public_url = url
    return register_binding(
        asset_id,
        {
            "file_id": f"s3::{key}",
            "url": public_url,
            "image_url": public_url,
            "public_url": public_url,
            "s3_key": key,
            "media_type": "image",
            "mime_type": normalized_mime,
            "size_bytes": actual_size,
            "original_filename": original_filename or "uploaded-image",
            "source": "user_upload_s3_direct",
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
    from .s3_asset_service import publish_image_asset

    registered = []
    for key in ("entry", "exit"):
        item = manifest.get(key) or {}
        asset_id = item.get("asset_id")
        image_url = item.get("image_url")
        if not asset_id or not image_url:
            continue
        published = (
            {
                "url": str(image_url),
                "public_url": str(item.get("public_url") or image_url),
                "s3_key": str(item["s3_key"]),
                **(
                    {"local_url": str(item["local_url"])}
                    if item.get("local_url")
                    else {}
                ),
            }
            if item.get("s3_key")
            else publish_image_asset(str(image_url))
        )
        item.update(published)
        item["image_url"] = published["url"]
        registered.append(
            register_binding(
                str(asset_id),
                {
                    "file_id": (
                        f"s3::{published['s3_key']}"
                        if published.get("s3_key")
                        else f"reference-image::{manifest.get('job_id')}::{key}"
                    ),
                    "url": published["url"],
                    "image_url": published["url"],
                    "public_url": published["url"],
                    "local_url": published.get("local_url"),
                    "s3_key": published.get("s3_key"),
                    "media_type": "image",
                    "mime_type": item.get("mime_type") or "image/png",
                    "source": "derived_reference_image_s3",
                    "shot_id": manifest.get("shot_id"),
                    "generated_role": key,
                    "ordinary_image_reference": True,
                },
            )
        )
    entry_url = (manifest.get("entry") or {}).get("image_url")
    if entry_url and isinstance(manifest.get("exit"), dict):
        manifest["exit"]["source_image_url"] = entry_url
    job_id = str(manifest.get("job_id") or "").strip()
    if job_id:
        manifest_path = settings.work_root / "reference_images" / job_id / "manifest.json"
        temp = manifest_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(manifest_path)
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
        url = str(binding.get("local_url") or binding.get("url") or "")
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
    from .video_generation_service import submit_video_batch

    return submit_video_batch(final_video_plan)


VIDEO_OUTPUT_FIELDS = (
    "output_video_path",
    "output_path",
    "video_path",
    "output_video_url",
    "video_url",
)


def _video_source_from_job(job: dict[str, Any]) -> str | None:
    candidates: list[Any] = [job]
    for key in ("result", "output", "provider_result", "video_result"):
        nested = job.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        for field in VIDEO_OUTPUT_FIELDS:
            value = candidate.get(field)
            if value:
                return str(value)
    return None


def _local_path_from_source(source: str) -> Path | None:
    text = source.strip()
    if not text:
        return None
    parsed = urllib.parse.urlsplit(text)
    path_text = urllib.parse.unquote(parsed.path if parsed.scheme in {"http", "https"} else text)
    url_roots = {
        "/workflow-videos/": WORKFLOW_VIDEO_OUTPUT_ROOT,
        "/workflow-assets/": WORKFLOW_UPLOAD_ROOT,
        "/demo-input-assets/": DEMO_INPUT_ASSET_ROOT,
        "/demo-assets/": DEMO_REFERENCE_ASSET_ROOT,
    }
    for prefix, root in url_roots.items():
        if path_text.startswith(prefix):
            return (root / Path(path_text.removeprefix(prefix)).name).resolve()
    path = Path(path_text)
    if not path.is_absolute():
        path = (WORKFLOW_VIDEO_JOB_ROOT / path).resolve()
    return path


def _concat_file_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def compose_video_jobs(
    jobs: list[dict[str, Any]],
    project_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .video_generation_service import prepare_compose_jobs

    jobs = prepare_compose_jobs(jobs)
    compose_id = uuid.uuid4().hex
    compose_root = WORKFLOW_VIDEO_OUTPUT_ROOT / compose_id
    compose_root.mkdir(parents=True, exist_ok=True)
    input_paths: list[Path] = []
    blocked: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        source = _video_source_from_job(job)
        shot_id = job.get("shot_id") or f"job_{index:03d}"
        if not source:
            blocked.append({"shot_id": shot_id, "job_id": job.get("job_id"), "detail": "job 中缺少视频输出路径或 URL"})
            continue
        path = _local_path_from_source(source)
        if path is None or not path.is_file():
            blocked.append({"shot_id": shot_id, "job_id": job.get("job_id"), "source": source, "detail": "视频文件不存在或不是本地可读文件"})
            continue
        input_paths.append(path)

    if not input_paths:
        return {
            "mode": "ffmpeg_concat",
            "compose_id": compose_id,
            "status": "blocked",
            "input_count": 0,
            "blocked_count": len(blocked),
            "blocked": blocked,
            "message": "没有可合成的本地分镜视频。",
        }

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg 并加入 PATH。")

    concat_path = compose_root / "inputs.txt"
    concat_path.write_text(
        "\n".join(_concat_file_line(path) for path in input_paths),
        encoding="utf-8",
    )
    output_name = f"{compose_id}.mp4"
    output_path = WORKFLOW_VIDEO_OUTPUT_ROOT / output_name
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        transcode_command = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            transcode_command, capture_output=True, text=True, check=False
        )
        command = transcode_command
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 合成失败: {(result.stderr or result.stdout)[-2000:]}")

    manifest_path = compose_root / "manifest.json"
    manifest = {
        "mode": "ffmpeg_concat",
        "compose_id": compose_id,
        "status": "completed",
        "episode_id": (project_params or {}).get("episode_id"),
        "input_count": len(input_paths),
        "blocked_count": len(blocked),
        "blocked": blocked,
        "output_path": str(output_path),
        "output_url": f"/workflow-videos/{output_name}",
        "concat_list": str(concat_path),
        "manifest_path": str(manifest_path),
        "command": command,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
