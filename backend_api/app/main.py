from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .contracts import (
    BindRequest,
    CompileRequest,
    ContinuityAnalyzeRequest,
    DirectorRequest,
    GenerateRequest,
    ReferenceImageFromShotRequest,
    ReferenceImagePairRequest,
    WorkflowPlanRequest,
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
from .pipeline_service import compile_video_plan
from .reference_image_service import (
    DEMO_IMAGE_ROOT,
    GENERATED_IMAGE_ROOT,
    create_reference_image_pair_job,
    create_reference_image_pair_provider_job,
    demo_reference_images_available,
)
from .workflow_service import (
    DEMO_INPUT_ASSET_ROOT,
    MAX_IMAGE_BYTES,
    WORKFLOW_UPLOAD_ROOT,
    asset_reference_data_urls,
    auto_bind_video_plan,
    missing_asset_ids,
    register_reference_pair,
    registry_snapshot,
    save_uploaded_asset,
    seed_demo_assets,
    submit_video_jobs,
)


app = FastAPI(title="Short Drama Video Planning API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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


@app.get("/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "demo_available": demo_case_available(),
        "generation_available": director_is_configured(),
        "reference_image_demo_available": demo_reference_images_available(),
        "reference_image_provider_available": bool(settings.openrouter_api_key),
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
        "provider": "openrouter",
        "configured": bool(settings.openrouter_api_key),
        "model": settings.openrouter_image_model,
        "resolution": settings.openrouter_image_resolution,
        "quality": settings.openrouter_image_quality,
        "aspect_ratio": "9:16",
        "prompt_source": "final_video_plan.shots[].reference_image_plan",
    }


@app.post("/v1/workflow/assets/seed-demo")
def workflow_seed_demo_assets() -> dict:
    try:
        return seed_demo_assets()
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
        if missing:
            raise ValueError(f"请先上传或登记该分镜使用的图片资产：{', '.join(missing)}")
        payload["image_model"] = request.image_model
        payload["aspect_ratio"] = "9:16"
        if request.generation_mode == "provider":
            references = asset_reference_data_urls(input_ids)
            manifest = create_reference_image_pair_provider_job(payload, references)
        else:
            manifest = create_reference_image_pair_job(payload)
        manifest["input_asset_ids"] = input_ids
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
