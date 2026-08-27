from __future__ import annotations

import hashlib
import mimetypes
import threading
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .logging_utils import get_logger
from .reference_image_service import GENERATED_IMAGE_ROOT
from .workflow_service import (
    DEMO_INPUT_ASSET_ROOT,
    DEMO_REFERENCE_ASSET_ROOT,
    WORKFLOW_UPLOAD_ROOT,
)

logger = get_logger(__name__)
_client_lock = threading.Lock()
_s3_client = None
_url_cache: dict[str, str] = {}

LOCAL_URL_ROOTS = {
    "/workflow-assets/": WORKFLOW_UPLOAD_ROOT,
    "/demo-input-assets/": DEMO_INPUT_ASSET_ROOT,
    "/demo-assets/": DEMO_REFERENCE_ASSET_ROOT,
    "/workflow-generated/": GENERATED_IMAGE_ROOT,
}
IMAGE_UPLOAD_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def _s3_configured() -> bool:
    return not _missing_s3_config()


def _missing_s3_config() -> list[str]:
    checks = {
        "S3_BUCKET": settings.s3_bucket,
        "S3_ACCESS_KEY/AWS_ACCESS_KEY_ID": settings.s3_access_key,
        "S3_SECRET_KEY/AWS_SECRET_ACCESS_KEY": settings.s3_secret_key,
        "S3_ENDPOINT": settings.s3_endpoint,
    }
    return [
        key
        for key, value in checks.items()
        if not value or str(value).strip().upper().startswith("XXX")
    ]


def _client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    if not _s3_configured():
        missing = "、".join(_missing_s3_config())
        raise RuntimeError(f"S3 未配置完整，缺少或仍为占位值：{missing}")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("缺少 boto3，请先安装 backend_api 依赖") from exc
    with _client_lock:
        if _s3_client is None:
            _s3_client = boto3.client(
                "s3",
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                endpoint_url=settings.s3_endpoint,
                verify=settings.s3_verify_ssl,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "virtual"},
                    proxies={},
                ),
            )
    return _s3_client


def is_loopback_url(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def is_public_http_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme in {"http", "https"} and not is_loopback_url(url)


def resolve_local_asset_path(url: str) -> Path | None:
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urllib.parse.urlsplit(text)
    path_text = urllib.parse.unquote(parsed.path if parsed.scheme in {"http", "https", ""} else text)
    for prefix, root in LOCAL_URL_ROOTS.items():
        if path_text.startswith(prefix):
            candidate = (root / Path(path_text.removeprefix(prefix)).name).resolve()
            if candidate.is_file():
                return candidate
    return None


def object_http_url(object_key: str) -> str:
    key = str(object_key or "").lstrip("/")
    if settings.s3_public_base_url:
        return f"{settings.s3_public_base_url.rstrip('/')}/{key}"
    return (
        f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com.cn/{key}"
    )


def normalize_image_content_type(content_type: str | None) -> tuple[str, str]:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    extension = IMAGE_UPLOAD_TYPES.get(mime)
    if not extension:
        raise ValueError("仅支持 PNG、JPEG 或 WebP 图片")
    return ("image/jpeg" if mime == "image/jpg" else mime, extension)


def _upload_key_prefix() -> str:
    prefix = settings.s3_key_prefix.strip("/")
    return f"{prefix}/assets/" if prefix else "assets/"


def validate_upload_object_key(object_key: str) -> str:
    key = str(object_key or "").lstrip("/")
    if not key.startswith(_upload_key_prefix()):
        raise ValueError("S3 对象不属于当前项目上传目录")
    return key


def create_presigned_image_upload(
    *,
    asset_id: str,
    content_type: str,
    size_bytes: int,
    original_filename: str | None = None,
) -> dict[str, Any]:
    if size_bytes <= 0:
        raise ValueError("上传图片为空")
    normalized_mime, extension = normalize_image_content_type(content_type)
    object_key = f"{_upload_key_prefix()}{uuid.uuid4().hex}{extension}"
    client = _client()
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": object_key,
            "ContentType": normalized_mime,
        },
        ExpiresIn=settings.s3_presign_expires_seconds,
    )
    return {
        "asset_id": asset_id,
        "method": "PUT",
        "upload_url": upload_url,
        "headers": {"Content-Type": normalized_mime},
        "s3_key": object_key,
        "url": object_http_url(object_key),
        "public_url": object_http_url(object_key),
        "content_type": normalized_mime,
        "size_bytes": size_bytes,
        "original_filename": original_filename,
        "expires_in": settings.s3_presign_expires_seconds,
        "max_size_bytes": 15 * 1024 * 1024,
    }


def describe_uploaded_object(object_key: str) -> dict[str, Any]:
    key = validate_upload_object_key(object_key)
    response = _client().head_object(Bucket=settings.s3_bucket, Key=key)
    return {
        "s3_key": key,
        "size_bytes": int(response.get("ContentLength") or 0),
        "content_type": response.get("ContentType") or "",
        "url": object_http_url(key),
        "public_url": object_http_url(key),
    }


def upload_bytes(
    data: bytes,
    *,
    suffix: str,
    content_type: str,
    name_hint: str = "",
) -> dict[str, str]:
    if not data:
        raise ValueError("上传内容为空")
    digest = hashlib.sha256(data).hexdigest()
    extension = suffix if suffix.startswith(".") else f".{suffix or 'bin'}"
    object_key = f"{settings.s3_key_prefix}/assets/{digest}{extension}"
    cached = _url_cache.get(object_key)
    if cached:
        return {"s3_key": object_key, "url": cached}
    client = _client()
    extra: dict[str, str] = {"ContentType": content_type or "application/octet-stream"}
    if name_hint:
        extra["ContentDisposition"] = f'inline; filename="{Path(name_hint).name}"'
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=object_key,
        Body=data,
        **extra,
    )
    url = object_http_url(object_key)
    _url_cache[object_key] = url
    _url_cache[digest] = url
    logger.info("s3.upload.ok key=%s bytes=%s", object_key, len(data))
    return {"s3_key": object_key, "url": url}


def publish_local_file(path: Path, *, cache_key: str | None = None) -> str:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    key = cache_key or digest
    cached = _url_cache.get(key)
    if cached:
        return cached
    suffix = resolved.suffix.lower() or ".bin"
    object_key = f"{settings.s3_key_prefix}/{digest}{suffix}"
    content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    client = _client()
    client.upload_file(
        str(resolved),
        settings.s3_bucket,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": object_key},
        ExpiresIn=settings.s3_presign_expires_seconds,
    )
    _url_cache[key] = url
    _url_cache[digest] = url
    return url


def publish_image_asset(url: str) -> dict[str, str]:
    """将本地图片发布到 S3，并返回可持久化的对象存储信息。"""
    text = str(url or "").strip()
    if not text:
        raise ValueError("图片地址为空")
    if is_public_http_url(text):
        return {"url": text, "public_url": text}
    local = resolve_local_asset_path(text)
    if local is None:
        raise ValueError(f"无法定位待上传图片：{text}")
    content_type = mimetypes.guess_type(local.name)[0] or "image/png"
    published = upload_bytes(
        local.read_bytes(),
        suffix=local.suffix or ".png",
        content_type=content_type,
        name_hint=local.name,
    )
    return {
        "url": published["url"],
        "public_url": published["url"],
        "s3_key": published["s3_key"],
        "local_url": text,
    }


def publish_asset_url(url: str | None, s3_key: str | None = None) -> str:
    if s3_key:
        return object_http_url(str(s3_key))
    text = str(url or "").strip()
    if not text:
        raise ValueError("素材 URL 为空")
    if is_public_http_url(text):
        return text
    local = resolve_local_asset_path(text)
    if local is None:
        raise ValueError(f"无法发布素材 URL：{text}")
    return publish_local_file(local, cache_key=text)


def publish_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = []
    for item in references:
        record = dict(item)
        source = str(
            record.get("url")
            or record.get("public_url")
            or record.get("image_url")
            or ""
        )
        record["public_url"] = publish_asset_url(source, record.get("s3_key"))
        record["url"] = record["public_url"]
        published.append(record)
    return published
