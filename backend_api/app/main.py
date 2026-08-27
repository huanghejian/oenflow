from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .contracts import (
    AutoFlowAnalysisRequest,
    AutoFlowAssetPromptRequest,
    AutoFlowAssetSplitRequest,
    AutoFlowComposeRequest,
    AutoFlowRouteRequest,
    AutoFlowReferenceDraftFrameGenerateRequest,
    AutoFlowReferenceFrameGenerateRequest,
    AutoFlowReferenceFramePublishRequest,
    AutoFlowReferenceRegenerateRequest,
    AutoFlowSplitRequest,
    AutoFlowStoryboardSplitRequest,
    AutoFlowSubmitRequest,
    WorkflowAssetRegisterS3Request,
    WorkflowAssetUploadTokenRequest,
    BindRequest,
    CompileRequest,
    ContinuityAnalyzeRequest,
    DirectorRequest,
    GenerateRequest,
    PromptTemplateRequest,
    ReferenceImageFromShotRequest,
    ReferenceImagePairRequest,
    WorkflowPlanRequest,
)
from .autoflow_service import (
    analyze_shot_groups,
    generate_asset_prompts,
    load_latest_analysis_result,
    load_latest_asset_prompt_result,
    load_latest_asset_split_result,
    load_latest_route_result,
    load_latest_storyboard_result,
    generate_latest_reference_frame,
    generate_reference_frame_from_group,
    publish_latest_reference_frame,
    regenerate_latest_reference_images,
    route_and_generate_references,
    split_script_assets,
    split_script_assets_and_segments,
    split_script_storyboard,
    sync_uploaded_asset_reference,
    submit_autoflow_video_jobs,
)
from .continuity_service import analyze_shot_continuity
from .demo_service import (
    demo_case_available,
    demo_debug_artifact_path,
    load_demo_case,
    load_demo_debug_stage,
    load_demo_tier,
)
from .director_service import (
    create_director_plan,
    director_is_configured,
    load_default_director_prompt,
)
from .config import settings
from .executor_binding import bind_logical_assets
from .logging_utils import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_logger,
    log_event,
    log_payload,
    reset_request_id,
    set_request_id,
)
from .pipeline_service import compile_video_plan
try:
    from .video_generation_service import get_batch, get_job, get_latest_batch, retry_job
except ModuleNotFoundError:
    def _missing_video_service(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("线上代码缺少 video_generation_service.py")

    get_batch = get_job = get_latest_batch = retry_job = _missing_video_service

try:
    from .video_poll_scheduler import start_video_poll_scheduler, stop_video_poll_scheduler
except ModuleNotFoundError:
    def start_video_poll_scheduler() -> None:
        return None

    def stop_video_poll_scheduler() -> None:
        return None
from .reference_image_service import (
    DEMO_IMAGE_ROOT,
    GENERATED_IMAGE_ROOT,
    create_reference_image_pair_job,
    create_reference_image_pair_provider_job,
    create_reference_image_pair_xingtu_job,
    demo_reference_images_available,
)
from .workflow_service import (
    DEMO_INPUT_ASSET_ROOT,
    MAX_IMAGE_BYTES,
    WORKFLOW_UPLOAD_ROOT,
    WORKFLOW_VIDEO_OUTPUT_ROOT,
    asset_reference_data_urls,
    auto_bind_video_plan,
    compose_video_jobs,
    create_asset_upload_token,
    missing_asset_ids,
    register_s3_uploaded_asset,
    register_reference_pair,
    registry_snapshot,
    save_uploaded_asset,
    seed_demo_assets,
    submit_video_jobs,
)


configure_logging()
logger = get_logger(__name__)
PROMPT_TEMPLATE_ROOT = settings.project_root.parent / "demo_web" / "public" / "prompts"
PROMPT_TEMPLATE_FILES = {
    "asset-split": "asset-split.txt",
    "asset-prompts": "asset-prompts.txt",
    "storyboard-split": "storyboard-split.txt",
    "shot-group-analysis": "shot-group-analysis.txt",
    "routing-analysis": "routing-analysis.txt",
}
PROMPT_TEMPLATE_VERSION_ROOT = PROMPT_TEMPLATE_ROOT / "versions"
PROMPT_VERSION_RE = re.compile(r"^2\.0\.(\d+)$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_video_poll_scheduler()
    yield
    stop_video_poll_scheduler()


app = FastAPI(
    title="Short Drama Video Planning API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9001", "http://127.0.0.1:9001"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Filename"],
)
if DEMO_IMAGE_ROOT.is_dir():
    app.mount("/demo-assets", StaticFiles(directory=DEMO_IMAGE_ROOT), name="demo-assets")
if DEMO_INPUT_ASSET_ROOT.is_dir():
    app.mount(
        "/demo-input-assets",
        StaticFiles(directory=DEMO_INPUT_ASSET_ROOT),
        name="demo-input-assets",
    )
app.mount(
    "/workflow-assets",
    StaticFiles(directory=WORKFLOW_UPLOAD_ROOT),
    name="workflow-assets",
)
app.mount(
    "/workflow-generated",
    StaticFiles(directory=GENERATED_IMAGE_ROOT),
    name="workflow-generated",
)
app.mount(
    "/workflow-videos",
    StaticFiles(directory=WORKFLOW_VIDEO_OUTPUT_ROOT),
    name="workflow-videos",
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
    token = set_request_id(request_id)
    started_at = time.perf_counter()
    log_event(
        logger,
        "http.request.start",
        method=request.method,
        path=request.url.path,
        query=str(request.url.query),
        client=request.client.host if request.client else None,
        content_length=request.headers.get("content-length"),
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.exception(
            "http.request.failed method=%s path=%s elapsed_ms=%s",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    else:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        log_event(
            logger,
            "http.request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        return response
    finally:
        reset_request_id(token)


def _run_logged_endpoint(
    name: str,
    request_payload: Any,
    action: Callable[[], dict],
    *,
    error_status_code: int = 422,
) -> dict:
    log_payload(logger, f"{name}.request", request_payload)
    try:
        result = action()
    except Exception as exc:
        logger.exception("%s failed", name)
        log_payload(
            logger,
            f"{name}.error",
            {"error": str(exc), "request": request_payload},
            level=logging.ERROR,
        )
        raise HTTPException(status_code=error_status_code, detail=str(exc)) from exc
    log_payload(logger, f"{name}.response", result)
    return result


def _prompt_template_path(name: str) -> Path:
    filename = PROMPT_TEMPLATE_FILES.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail=f"未知提示词模板：{name}")
    return PROMPT_TEMPLATE_ROOT / filename


def _prompt_version_dir(name: str) -> Path:
    _prompt_template_path(name)
    return PROMPT_TEMPLATE_VERSION_ROOT / name


def _prompt_version_number(path: Path) -> int | None:
    match = PROMPT_VERSION_RE.match(path.stem)
    if not match:
        return None
    return int(match.group(1))


def _prompt_version_files(name: str) -> list[Path]:
    version_dir = _prompt_version_dir(name)
    if not version_dir.is_dir():
        return []
    files = [path for path in version_dir.glob("2.0.*.txt") if _prompt_version_number(path) is not None]
    return sorted(files, key=lambda path: _prompt_version_number(path) or 0, reverse=True)


def _next_prompt_version(name: str) -> str:
    latest_number = 0
    for path in _prompt_version_files(name):
        latest_number = max(latest_number, _prompt_version_number(path) or 0)
    return f"2.0.{latest_number + 1}"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def _prompt_version_path(name: str, version: str) -> Path:
    if not PROMPT_VERSION_RE.match(version):
        raise HTTPException(status_code=404, detail=f"未知提示词版本：{version}")
    path = _prompt_version_dir(name) / f"{version}.txt"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"提示词版本不存在：{version}")
    return path


@app.get("/v1/autoflow/prompts/{name}")
def autoflow_prompt_template(name: str) -> dict[str, str]:
    path = _prompt_template_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"提示词模板不存在：{name}")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@app.post("/v1/autoflow/prompts/{name}")
def autoflow_save_prompt_template(name: str, request: PromptTemplateRequest) -> dict[str, Any]:
    path = _prompt_template_path(name)
    version_files = _prompt_version_files(name)
    if version_files:
        latest_version_path = version_files[0]
        if latest_version_path.read_text(encoding="utf-8") == request.content:
            if not path.is_file() or path.read_text(encoding="utf-8") != request.content:
                _write_text_atomic(path, request.content)
            return {
                "name": name,
                "path": str(path),
                "version": latest_version_path.stem,
                "created": False,
            }
    version = _next_prompt_version(name)
    version_path = _prompt_version_dir(name) / f"{version}.txt"
    _write_text_atomic(version_path, request.content)
    _write_text_atomic(path, request.content)
    return {"name": name, "path": str(path), "version": version, "created": True}


@app.get("/v1/autoflow/prompts/{name}/versions")
def autoflow_prompt_versions(name: str) -> dict[str, Any]:
    versions = []
    for path in _prompt_version_files(name):
        version = path.stem
        stat = path.stat()
        versions.append(
            {
                "version": version,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
            }
        )
    return {"name": name, "versions": versions}


@app.get("/v1/autoflow/prompts/{name}/versions/{version}")
def autoflow_prompt_version(name: str, version: str) -> dict[str, str]:
    path = _prompt_version_path(name, version)
    return {"name": name, "version": version, "content": path.read_text(encoding="utf-8")}


@app.get("/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "demo_available": demo_case_available(),
        "generation_available": director_is_configured(),
        "network_proxy_available": bool(settings.claude_http_proxy_url),
        "reference_image_demo_available": demo_reference_images_available(),
        "reference_image_provider_available": bool(
            settings.openrouter_api_key or settings.xingtu_image_api_key
        ),
        "openrouter_image_provider_available": bool(settings.openrouter_api_key),
        "xingtu_image_provider_available": bool(settings.xingtu_image_api_key),
    }


@app.get("/v1/director-prompt")
def director_prompt() -> dict:
    try:
        model = {
            "openrouter": settings.openrouter_director_model,
            "openai": settings.openai_director_model,
            "claude_converse": settings.claude_director_model,
        }.get(settings.director_provider)
        return {
            "prompt": load_default_director_prompt(),
            "provider": settings.director_provider,
            "model": model,
            "internal_output_format": "A1c",
            "reasoning_effort": (
                settings.openrouter_reasoning_effort
                if settings.director_provider == "openrouter"
                else None
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/demo/sample")
def demo_sample() -> dict:
    try:
        return load_demo_case()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/demo/tier/{tier}")
def demo_tier(tier: str) -> dict:
    try:
        return load_demo_tier(tier)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/demo/debug/{stage}")
def demo_debug_stage(stage: str, tier: str = "medium") -> dict:
    try:
        return load_demo_debug_stage(stage, tier)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/demo/debug/{stage}/download")
def demo_debug_download(stage: str, tier: str = "medium") -> FileResponse:
    try:
        path = demo_debug_artifact_path(stage, tier)
        return FileResponse(path, media_type="application/json", filename=path.name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/continuity/analyze-shot")
def continuity_analyze(request: ContinuityAnalyzeRequest) -> dict:
    try:
        return analyze_shot_continuity(
            request.previous_shot,
            request.current_shot,
            request.next_shot,
            request.use_ai,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/reference-images/generate-pair")
def reference_image_pair(request: ReferenceImagePairRequest) -> dict:
    try:
        return create_reference_image_pair_job(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _reference_payload_from_shot(
    episode_id: str, shot: dict, demo_case: bool
) -> tuple[dict, list[str]]:
    shot_id = str(shot.get("shot_id") or "").strip()
    image_plan = shot.get("reference_image_plan") or {}
    output_ids = image_plan.get("output_asset_ids") or {}
    input_ids = [str(value) for value in image_plan.get("input_asset_ids", []) if value]
    if not shot_id or not image_plan:
        raise ValueError("该分镜缺少 shot_id 或 reference_image_plan")
    entry_prompt = str(image_plan.get("entry_state_reference_prompt_zh") or "").strip()
    exit_prompt = str(image_plan.get("exit_state_reference_edit_prompt_zh") or "").strip()
    if not entry_prompt or not exit_prompt:
        raise ValueError("该分镜缺少开始图或结束图提示词")
    return (
        {
            "episode_id": episode_id,
            "shot_id": shot_id,
            "entry_prompt_zh": entry_prompt,
            "exit_prompt_zh": exit_prompt,
            "entry_asset_id": output_ids.get("entry"),
            "exit_asset_id": output_ids.get("exit"),
            "continuity_source_shot_id": image_plan.get("continuity_source_shot_id"),
            "demo_case": demo_case,
        },
        input_ids,
    )


@app.get("/v1/workflow/assets")
def workflow_assets() -> dict:
    return registry_snapshot()


@app.get("/v1/workflow/image-generation")
def workflow_image_generation_config() -> dict:
    return {
        "default_provider": "xingtu",
        "providers": {
            "xingtu": {
                "configured": bool(settings.xingtu_image_api_key),
                "provider": "volcengine_ark",
                "model": settings.xingtu_image_model,
                "size": settings.xingtu_image_size,
                "aspect_ratio": "9:16",
                "generation_strategy": "parallel_entry_exit_from_same_assets",
                "reference_input_field": "image",
            },
            "openrouter": {
                "configured": bool(settings.openrouter_api_key),
                "provider": "openrouter",
                "model": settings.openrouter_image_model,
                "resolution": settings.openrouter_image_resolution,
                "quality": settings.openrouter_image_quality,
                "aspect_ratio": "9:16",
                "generation_strategy": "generate_entry_then_edit_exit",
            },
        },
        "prompt_source": "final_video_plan.shots[].reference_image_plan",
    }


@app.post("/v1/workflow/assets/seed-demo")
def workflow_seed_demo_assets() -> dict:
    try:
        return seed_demo_assets()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/workflow/assets/upload-token")
def workflow_asset_upload_token(request: WorkflowAssetUploadTokenRequest) -> dict:
    try:
        return create_asset_upload_token(
            request.asset_id,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            original_filename=request.filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/workflow/assets/register-s3")
def workflow_register_s3_asset(request: WorkflowAssetRegisterS3Request) -> dict:
    try:
        record = register_s3_uploaded_asset(
            request.asset_id,
            s3_key=request.s3_key,
            url=request.url,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            original_filename=request.original_filename,
        )
        record["synced_asset_files"] = sync_uploaded_asset_reference(request.asset_id, record)["updated_files"]
        return record
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/workflow/assets/upload")
async def workflow_upload_asset(asset_id: str, request: Request) -> dict:
    try:
        declared_size = request.headers.get("content-length")
        if declared_size and int(declared_size) > MAX_IMAGE_BYTES:
            raise ValueError("单张图片不得超过 15MB")
        data = await request.body()
        return save_uploaded_asset(
            asset_id,
            data,
            request.headers.get("content-type", "application/octet-stream"),
            request.headers.get("x-filename"),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/workflow/reference-images/generate-shot")
def workflow_generate_reference_shot(request: ReferenceImageFromShotRequest) -> dict:
    try:
        payload, input_ids = _reference_payload_from_shot(
            request.episode_id, request.shot, request.demo_case
        )
        missing = missing_asset_ids(input_ids)
        if missing and request.generation_mode in {"provider", "openrouter"}:
            raise ValueError(f"请先上传或登记该分镜使用的图片资产：{', '.join(missing)}")
        payload["image_model"] = request.image_model
        payload["aspect_ratio"] = "9:16"
        if request.generation_mode == "xingtu":
            references = asset_reference_data_urls(input_ids)
            manifest = create_reference_image_pair_xingtu_job(payload, references)
        elif request.generation_mode in {"provider", "openrouter"}:
            references = asset_reference_data_urls(input_ids)
            manifest = create_reference_image_pair_provider_job(payload, references)
        else:
            manifest = create_reference_image_pair_job(payload)
        manifest["input_asset_ids"] = input_ids
        if missing and request.generation_mode == "xingtu":
            manifest["unused_missing_asset_ids"] = missing
        manifest["prompt_source"] = (
            f"final_video_plan.shots[{payload['shot_id']}].reference_image_plan"
        )
        manifest["registry"] = register_reference_pair(manifest)
        return manifest
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/workflow/reference-images/generate-all")
def workflow_generate_all_reference_shots(request: WorkflowPlanRequest) -> dict:
    completed: list[dict] = []
    blocked: list[dict] = []
    for shot in request.final_video_plan.get("shots", []):
        try:
            payload, input_ids = _reference_payload_from_shot(
                request.episode_id, shot, True
            )
            missing = missing_asset_ids(input_ids)
            if missing:
                blocked.append(
                    {"shot_id": shot.get("shot_id"), "missing_asset_ids": missing}
                )
                continue
            manifest = create_reference_image_pair_job(payload)
            manifest["input_asset_ids"] = input_ids
            manifest["registry"] = register_reference_pair(manifest)
            completed.append(manifest)
        except Exception as exc:
            blocked.append({"shot_id": shot.get("shot_id"), "detail": str(exc)})
    return {
        "mode": "local_demo",
        "completed_count": len(completed),
        "blocked_count": len(blocked),
        "completed": completed,
        "blocked": blocked,
    }


@app.post("/v1/workflow/bind")
def workflow_bind(request: WorkflowPlanRequest) -> dict:
    return auto_bind_video_plan(request.final_video_plan)


@app.post("/v1/workflow/video/submit")
def workflow_submit_video(request: WorkflowPlanRequest) -> dict:
    return submit_video_jobs(request.final_video_plan)


@app.post("/v1/autoflow/split")
def autoflow_split(request: AutoFlowSplitRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.split",
        payload,
        lambda: split_script_assets_and_segments(
            request.project_params.model_dump(),
            request.script,
            request.split_prompt,
            request.asset_prompt,
            request.storyboard_prompt,
            request.assets,
            request.story_context,
            request.image_models,
            request.use_ai,
            request.use_network_proxy,
        ),
    )


@app.post("/v1/autoflow/assets/split")
def autoflow_split_assets(request: AutoFlowAssetSplitRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.assets.split",
        payload,
        lambda: split_script_assets(
            request.project_params.model_dump(),
            request.script,
            request.asset_prompt,
            request.batch_info,
            request.id_range,
            request.existing_assets,
            request.image_models,
            request.use_ai,
            request.use_network_proxy,
        ),
    )


@app.post("/v1/autoflow/assets/prompts")
def autoflow_generate_asset_prompts(request: AutoFlowAssetPromptRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.assets.prompts",
        payload,
        lambda: generate_asset_prompts(
            request.project_params.model_dump(),
            request.script,
            request.assets,
            request.asset_ledger,
            request.story_context,
            request.prompt_instruction,
            request.image_models,
            request.use_ai,
            request.use_network_proxy,
        ),
    )


@app.get("/v1/autoflow/assets/latest")
def autoflow_load_latest_assets() -> dict:
    log_event(logger, "autoflow.assets.latest.request")
    try:
        result = load_latest_asset_split_result()
        log_payload(logger, "autoflow.assets.latest.response", result)
        return result
    except FileNotFoundError as exc:
        logger.exception("autoflow.assets.latest not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("autoflow.assets.latest failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/autoflow/assets/prompts/latest")
def autoflow_load_latest_asset_prompts() -> dict:
    log_event(logger, "autoflow.assets.prompts.latest.request")
    try:
        result = load_latest_asset_prompt_result()
        log_payload(logger, "autoflow.assets.prompts.latest.response", result)
        return result
    except FileNotFoundError as exc:
        logger.exception("autoflow.assets.prompts.latest not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("autoflow.assets.prompts.latest failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/autoflow/storyboard/split")
def autoflow_split_storyboard(request: AutoFlowStoryboardSplitRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.storyboard.split",
        payload,
        lambda: split_script_storyboard(
            request.project_params.model_dump(),
            request.script,
            request.assets,
            request.story_context,
            request.storyboard_prompt,
            request.use_ai,
            request.use_network_proxy,
        ),
    )


@app.get("/v1/autoflow/storyboard/latest")
def autoflow_load_latest_storyboard() -> dict:
    log_event(logger, "autoflow.storyboard.latest.request")
    try:
        result = load_latest_storyboard_result()
        log_payload(logger, "autoflow.storyboard.latest.response", result)
        return result
    except FileNotFoundError as exc:
        logger.exception("autoflow.storyboard.latest not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("autoflow.storyboard.latest failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/autoflow/analyze-shot-groups")
def autoflow_analyze_shot_groups(request: AutoFlowAnalysisRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.analyze_shot_groups",
        payload,
        lambda: analyze_shot_groups(
            request.project_params.model_dump(),
            request.assets,
            request.story_context,
            request.segments,
            request.analysis_prompt,
            request.reanalysis_prompt,
            request.previous_analysis,
            request.use_ai,
            request.use_network_proxy,
        ),
    )


@app.get("/v1/autoflow/analyze-shot-groups/latest")
def autoflow_load_latest_analysis() -> dict:
    log_event(logger, "autoflow.analyze_shot_groups.latest.request")
    try:
        result = load_latest_analysis_result()
        log_payload(logger, "autoflow.analyze_shot_groups.latest.response", result)
        return result
    except FileNotFoundError as exc:
        logger.exception("autoflow.analyze_shot_groups.latest not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("autoflow.analyze_shot_groups.latest failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/autoflow/route-and-generate-refs")
def autoflow_route_and_generate_refs(request: AutoFlowRouteRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.route_and_generate_refs",
        payload,
        lambda: route_and_generate_references(
            request.project_params.model_dump(),
            request.assets,
            request.story_context,
            request.shot_groups,
            request.generation_mode,
            request.image_model,
            request.routing_analysis_prompt,
            request.use_ai_difficulty,
            request.use_network_proxy,
        ),
    )


@app.get("/v1/autoflow/route-and-generate-refs/latest")
def autoflow_load_latest_route_and_refs() -> dict:
    log_event(logger, "autoflow.route_and_generate_refs.latest.request")
    try:
        result = load_latest_route_result()
        log_payload(logger, "autoflow.route_and_generate_refs.latest.response", result)
        return result
    except FileNotFoundError as exc:
        logger.exception("autoflow.route_and_generate_refs.latest not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("autoflow.route_and_generate_refs.latest failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/autoflow/reference-images/regenerate")
def autoflow_regenerate_reference_images(request: AutoFlowReferenceRegenerateRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.reference_images.regenerate",
        payload,
        lambda: regenerate_latest_reference_images(
            request.generation_mode,
            request.image_model,
            request.shot_ids,
        ),
    )


@app.post("/v1/autoflow/reference-images/generate-frame")
def autoflow_generate_reference_frame(request: AutoFlowReferenceFrameGenerateRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.reference_images.generate_frame",
        payload,
        lambda: generate_latest_reference_frame(
            request.shot_id,
            request.role,
            request.generation_mode,
            request.image_model,
        ),
    )


@app.post("/v1/autoflow/reference-images/generate-draft-frame")
def autoflow_generate_reference_draft_frame(
    request: AutoFlowReferenceDraftFrameGenerateRequest,
) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.reference_images.generate_draft_frame",
        payload,
        lambda: generate_reference_frame_from_group(
            request.project_params.model_dump(),
            request.assets,
            request.story_context,
            request.shot_group,
            request.shot_index,
            request.role,
            request.generation_mode,
            request.image_model,
        ),
    )


@app.post("/v1/autoflow/reference-images/publish-frame")
def autoflow_publish_reference_frame(request: AutoFlowReferenceFramePublishRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.reference_images.publish_frame",
        payload,
        lambda: publish_latest_reference_frame(
            request.shot_id,
            request.role,
            request.image_url,
            request.r2_key,
            request.generated_frame,
        ),
    )


@app.post("/v1/autoflow/video/submit")
def autoflow_submit_video(request: AutoFlowSubmitRequest) -> dict:
    payload = request.model_dump()
    return _run_logged_endpoint(
        "autoflow.video.submit",
        payload,
        lambda: submit_autoflow_video_jobs(
            request.final_video_plan,
            request.project_params.model_dump(),
            regenerate_existing=request.regenerate_existing,
        ),
    )


@app.get("/v1/autoflow/video/batches/latest")
def autoflow_get_latest_video_batch() -> dict:
    try:
        return get_latest_batch(refresh=False)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="暂无视频生成批次"
        ) from exc


@app.get("/v1/autoflow/video/batches/{batch_id}")
def autoflow_get_video_batch(batch_id: str) -> dict:
    try:
        return get_batch(batch_id, refresh=False)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"视频批次不存在: {batch_id}"
        ) from exc


@app.get("/v1/autoflow/video/jobs/{job_id}")
def autoflow_get_video_job(job_id: str) -> dict:
    try:
        return get_job(job_id, refresh=True)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"视频任务不存在: {job_id}"
        ) from exc


@app.post("/v1/autoflow/video/jobs/{job_id}/retry")
def autoflow_retry_video_job(job_id: str) -> dict:
    return _run_logged_endpoint(
        "autoflow.video.retry",
        {"job_id": job_id},
        lambda: retry_job(job_id),
    )


@app.post("/v1/autoflow/video/compose")
def autoflow_compose_video(request: AutoFlowComposeRequest) -> dict:
    payload = request.model_dump()
    jobs = request.jobs or (request.submit_result or {}).get("jobs") or []
    return _run_logged_endpoint(
        "autoflow.video.compose",
        payload,
        lambda: compose_video_jobs(jobs, request.project_params.model_dump()),
    )


@app.post("/v1/director-plan")
def director_plan(request: DirectorRequest) -> dict:
    try:
        payload = request.model_dump(exclude={"director_prompt"})
        plan, meta = create_director_plan(payload, request.director_prompt)
        return {"director_plan": plan, "llm": meta}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/compile-video-plan")
def compile_plan(request: CompileRequest) -> dict:
    try:
        return compile_video_plan(
            request.director_plan, request.tier, request.target_resolution
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/episode/generate-plan")
def generate_plan(request: GenerateRequest) -> dict:
    try:
        payload = request.model_dump(
            exclude={"tier", "target_resolution", "director_prompt"}
        )
        plan, openai_meta = create_director_plan(payload, request.director_prompt)
        compiled = compile_video_plan(plan, request.tier, request.target_resolution)
        compiled["openai"] = openai_meta
        return compiled
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/episode/generate-all-tiers")
def generate_all_tiers(request: GenerateRequest) -> dict:
    try:
        payload = request.model_dump(
            exclude={"tier", "target_resolution", "director_prompt"}
        )
        plan, openai_meta = create_director_plan(payload, request.director_prompt)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                tier: pool.submit(
                    compile_video_plan, plan, tier, request.target_resolution
                )
                for tier in ("low", "medium", "high")
            }
            tiers = {tier: future.result() for tier, future in futures.items()}
        return {
            "director_plan": plan,
            "openai": openai_meta,
            "tiers": tiers,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/executor/bind")
def bind_assets(request: BindRequest) -> dict:
    return bind_logical_assets(
        request.final_video_plan,
        {key: value.model_dump(exclude_none=True) for key, value in request.asset_registry.items()},
    )
