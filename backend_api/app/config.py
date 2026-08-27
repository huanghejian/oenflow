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
    claude_converse_url: str | None
    claude_http_proxy_url: str | None
    claude_region: str | None
    claude_converse_api_key: str | None
    claude_director_model: str | None
    claude_max_output_tokens: int
    claude_thinking_effort: str
    claude_converse_timeout_seconds: int
    pipeline_timeout_seconds: int


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
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
    )


settings = load_settings()
