from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    pipeline_root: Path
    work_root: Path
    director_prompt_path: Path
    model_registry_path: Path
    openai_api_key: str | None
    openai_director_model: str | None
    openai_max_output_tokens: int
    director_provider: str
    openrouter_api_key: str | None
    openrouter_base_url: str
    openrouter_director_model: str
    openrouter_max_output_tokens: int
    openrouter_reasoning_effort: str
    openrouter_image_model: str
    openrouter_image_resolution: str
    openrouter_image_quality: str
    xingtu_image_api_key: str | None
    xingtu_image_endpoint: str
    xingtu_image_model: str
    xingtu_image_size: str
    xingtu_image_verify_ssl: bool
    claude_converse_url: str | None
    claude_http_proxy_url: str | None
    claude_region: str | None
    claude_converse_api_key: str | None
    claude_director_model: str | None
    claude_max_output_tokens: int
    claude_thinking_effort: str
    claude_converse_timeout_seconds: int
    pipeline_timeout_seconds: int
    h3_api_key: str | None
    h3_submit_url: str
    h3_query_url: str
    h3_model: str
    topenrouter_api_key: str | None
    topenrouter_submit_url: str
    topenrouter_upload_asset_url: str
    topenrouter_query_task_url: str
    topenrouter_xingguang_30_model: str
    topenrouter_xingguang_35_model: str
    xingguang_30_api_key: str | None
    xingguang_30_submit_url: str | None
    xingguang_35_api_key: str | None
    xingguang_35_submit_url: str | None
    wan3_api_key: str | None
    wan3_submit_url: str
    wan3_query_base_url: str
    wan3_model: str
    s3_region: str
    s3_bucket: str
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_endpoint: str
    s3_verify_ssl: bool
    s3_signing_region: str
    s3_key_prefix: str
    s3_public_base_url: str
    s3_presign_expires_seconds: int
    video_poll_interval_seconds: int
    video_task_timeout_seconds: int
    video_max_concurrency: int
    video_asset_process_wait_seconds: int
    video_asset_process_retry: int


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip("'\"")
        os.environ[key] = value


def _load_local_env(project_root: Path) -> None:
    _load_env_file(project_root / ".env")
    _load_env_file(project_root.parent / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    _load_local_env(project_root)
    pipeline_root = Path(
        os.environ.get("PIPELINE_ROOT", project_root / "pipeline_runtime")
    ).resolve()
    work_root = Path(
        os.environ.get("PIPELINE_WORK_ROOT", project_root / "var" / "jobs")
    ).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    return Settings(
        project_root=project_root,
        pipeline_root=pipeline_root,
        work_root=work_root,
        director_prompt_path=pipeline_root / "resources" / "director_prompt.md",
        model_registry_path=pipeline_root / "resources" / "model_registry.json",
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_director_model=os.environ.get("OPENAI_DIRECTOR_MODEL"),
        openai_max_output_tokens=int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "60000")),
        director_provider=os.environ.get("DIRECTOR_PROVIDER", "openrouter").strip().lower(),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        openrouter_director_model=os.environ.get(
            "OPENROUTER_DIRECTOR_MODEL", "anthropic/claude-opus-5"
        ),
        openrouter_max_output_tokens=int(
            os.environ.get("OPENROUTER_MAX_OUTPUT_TOKENS", "110000")
        ),
        openrouter_reasoning_effort=os.environ.get(
            "OPENROUTER_REASONING_EFFORT", "medium"
        ).strip().lower(),
        openrouter_image_model=os.environ.get(
            "OPENROUTER_IMAGE_MODEL", "openai/gpt-image-2"
        ).strip(),
        openrouter_image_resolution=os.environ.get(
            "OPENROUTER_IMAGE_RESOLUTION", "1K"
        ).strip(),
        openrouter_image_quality=os.environ.get(
            "OPENROUTER_IMAGE_QUALITY", "medium"
        ).strip().lower(),
        xingtu_image_api_key=(os.environ.get("XINGTU_IMAGE_API_KEY", "").strip() or None),
        xingtu_image_endpoint=os.environ.get(
            "XINGTU_IMAGE_ENDPOINT",
            "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        ).strip(),
        xingtu_image_model=os.environ.get(
            "XINGTU_IMAGE_MODEL", "doubao-seedream-5-0-pro-260628"
        ).strip(),
        xingtu_image_size=os.environ.get("XINGTU_IMAGE_SIZE", "2K").strip().upper(),
        xingtu_image_verify_ssl=_env_bool("XINGTU_IMAGE_VERIFY_SSL", False),
        claude_converse_url=os.environ.get("CLAUDE_CONVERSE_URL"),
        claude_http_proxy_url=(
            os.environ.get("CLAUDE_HTTP_PROXY_URL", "").strip() or None
        ),
        claude_region=os.environ.get("CLAUDE_REGION"),
        claude_converse_api_key=os.environ.get("CLAUDE_CONVERSE_API_KEY"),
        claude_director_model=os.environ.get("CLAUDE_DIRECTOR_MODEL"),
        claude_max_output_tokens=int(
            os.environ.get("CLAUDE_MAX_OUTPUT_TOKENS", "128000")
        ),
        claude_thinking_effort=os.environ.get(
            "CLAUDE_THINKING_EFFORT", "medium"
        ).strip().lower(),
        claude_converse_timeout_seconds=int(
            os.environ.get("CLAUDE_CONVERSE_TIMEOUT_SECONDS", "300")
        ),
        pipeline_timeout_seconds=int(os.environ.get("PIPELINE_TIMEOUT_SECONDS", "300")),
        h3_api_key=(os.environ.get("H3_API_KEY", "").strip() or None),
        h3_submit_url=os.environ.get("H3_SUBMIT_URL", "").strip().rstrip("/"),
        h3_query_url=os.environ.get("H3_QUERY_URL", "").strip().rstrip("/"),
        h3_model=os.environ.get("H3_MODEL", "MiniMax-H3").strip(),
        topenrouter_api_key=(
            os.environ.get("TOPENROUTER_API_KEY", "").strip() or None
        ),
        topenrouter_submit_url=os.environ.get(
            "TOPENROUTER_SUBMIT_URL", ""
        ).strip().rstrip("/"),
        topenrouter_upload_asset_url=os.environ.get(
            "TOPENROUTER_UPLOAD_ASSET_URL", ""
        ).strip().rstrip("/"),
        topenrouter_query_task_url=os.environ.get(
            "TOPENROUTER_QUERY_TASK_URL", ""
        ).strip().rstrip("/"),
        topenrouter_xingguang_30_model=os.environ.get(
            "TOPENROUTER_XINGGUANG_30_MODEL", "doubao-seedance-2.0"
        ).strip(),
        topenrouter_xingguang_35_model=os.environ.get(
            "TOPENROUTER_XINGGUANG_35_MODEL", "doubao-seedance-2-5-260628"
        ).strip(),
        xingguang_30_api_key=(
            os.environ.get("XINGGUANG_30_API_KEY", "").strip() or None
        ),
        xingguang_30_submit_url=(
            os.environ.get("XINGGUANG_30_SUBMIT_URL", "").strip() or None
        ),
        xingguang_35_api_key=(
            os.environ.get("XINGGUANG_35_API_KEY", "").strip() or None
        ),
        xingguang_35_submit_url=(
            os.environ.get("XINGGUANG_35_SUBMIT_URL", "").strip() or None
        ),
        wan3_api_key=(os.environ.get("WAN3_API_KEY", "").strip() or None),
        wan3_submit_url=os.environ.get("WAN3_SUBMIT_URL", "").strip().rstrip("/"),
        wan3_query_base_url=os.environ.get(
            "WAN3_QUERY_BASE_URL", ""
        ).strip().rstrip("/"),
        wan3_model=os.environ.get("WAN3_MODEL", "wan3.0-video").strip(),
        s3_region=os.environ.get("S3_REGION", "cn-northwest-1").strip(),
        s3_bucket=os.environ.get("S3_BUCKET", "").strip(),
        s3_access_key=(
            os.environ.get("S3_ACCESS_KEY")
            or os.environ.get("AWS_ACCESS_KEY_ID")
            or None
        ),
        s3_secret_key=(
            os.environ.get("S3_SECRET_KEY")
            or os.environ.get("AWS_SECRET_ACCESS_KEY")
            or None
        ),
        s3_endpoint=os.environ.get("S3_ENDPOINT", "").strip().rstrip("/"),
        s3_verify_ssl=_env_bool("S3_VERIFY_SSL", False),
        s3_signing_region=os.environ.get(
            "S3_SIGNING_REGION", "cn-northwest-1"
        ).strip(),
        s3_key_prefix=os.environ.get(
            "S3_KEY_PREFIX", "oenflow/video-assets"
        ).strip("/"),
        s3_public_base_url=os.environ.get(
            "S3_PUBLIC_BASE_URL", ""
        ).strip().rstrip("/"),
        s3_presign_expires_seconds=int(
            os.environ.get("S3_PRESIGN_EXPIRES_SECONDS", "21600")
        ),
        video_poll_interval_seconds=int(
            os.environ.get("VIDEO_POLL_INTERVAL_SECONDS", "10")
        ),
        video_task_timeout_seconds=int(
            os.environ.get("VIDEO_TASK_TIMEOUT_SECONDS", "3600")
        ),
        video_max_concurrency=int(os.environ.get("VIDEO_MAX_CONCURRENCY", "3")),
        video_asset_process_wait_seconds=int(
            os.environ.get("VIDEO_ASSET_PROCESS_WAIT_SECONDS", "15")
        ),
        video_asset_process_retry=int(
            os.environ.get("VIDEO_ASSET_PROCESS_RETRY", "5")
        ),
    )


settings = load_settings()
