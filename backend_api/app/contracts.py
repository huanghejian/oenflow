from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RoutingTier = Literal["low", "medium", "high"]


class ScriptInput(BaseModel):
    episode_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class RegisteredAssets(BaseModel):
    model_config = ConfigDict(extra="allow")

    scenes: list[dict[str, Any]] = Field(default_factory=list)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    props: list[dict[str, Any]] = Field(default_factory=list)


class DirectorRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_params: dict[str, Any]
    registered_assets: RegisteredAssets
    script: ScriptInput
    global_visual_lock: str = ""
    previous_continuity: dict[str, Any] = Field(default_factory=dict)
    director_prompt: str | None = Field(default=None, min_length=1, max_length=300_000)


class CompileRequest(BaseModel):
    director_plan: dict[str, Any]
    tier: RoutingTier = "medium"
    target_resolution: str = "720P"


class GenerateRequest(DirectorRequest):
    tier: RoutingTier = "medium"
    target_resolution: str = "720P"


class AssetBinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    file_id: str | None = None
    url: str | None = None
    provider_handle: str | None = None


class BindRequest(BaseModel):
    final_video_plan: dict[str, Any]
    asset_registry: dict[str, AssetBinding]


class ContinuityAnalyzeRequest(BaseModel):
    previous_shot: dict[str, Any] | None = None
    current_shot: dict[str, Any]
    next_shot: dict[str, Any] | None = None
    use_ai: bool = True


class ReferenceImagePairRequest(BaseModel):
    episode_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    entry_prompt_zh: str = Field(min_length=1)
    exit_prompt_zh: str = Field(min_length=1)
    continuity_source_shot_id: str | None = None
    demo_case: bool = False


class ReferenceImageFromShotRequest(BaseModel):
    episode_id: str = Field(min_length=1)
    shot: dict[str, Any]
    demo_case: bool = True
    generation_mode: Literal["demo", "provider", "openrouter", "xingtu"] = "demo"
    image_model: str | None = Field(default=None, min_length=1, max_length=200)


class WorkflowPlanRequest(BaseModel):
    episode_id: str = "EP001"
    final_video_plan: dict[str, Any]


class WorkflowAssetUploadTokenRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    filename: str | None = Field(default=None, max_length=260)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0, le=15 * 1024 * 1024)


class WorkflowAssetRegisterS3Request(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    s3_key: str = Field(min_length=1, max_length=1024)
    url: str | None = Field(default=None, max_length=4096)
    content_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None, gt=0, le=15 * 1024 * 1024)
    original_filename: str | None = Field(default=None, max_length=260)


class AutoFlowProjectParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    episode_id: str = "EP001"
    project_type: str = "短剧"
    aspect_ratio: str = "9:16"
    resolution: str = "720P"
    routing_tier: RoutingTier = "medium"
    global_visual_lock: str = ""
    feedback: str = ""


class PromptTemplateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=300_000)


class AutoFlowSplitRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    script: str = Field(min_length=1)
    split_prompt: str = Field(min_length=1, max_length=300_000)
    asset_prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    storyboard_prompt: str | None = Field(default=None, min_length=1, max_length=300_000)
    assets: dict[str, Any] | None = None
    story_context: dict[str, Any] | None = None
    image_models: list[str] = Field(default_factory=list)
    use_ai: bool = True
    use_network_proxy: bool = False


class AutoFlowAssetSplitRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    script: str = Field(min_length=1)
    asset_prompt: str = Field(min_length=1, max_length=100_000)
    batch_info: dict[str, Any] | None = None
    id_range: dict[str, Any] | None = None
    existing_assets: str | list[dict[str, Any]] | None = None
    image_models: list[str] = Field(default_factory=list)
    use_ai: bool = True
    use_network_proxy: bool = False


class AutoFlowAssetPromptRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    script: str = Field(min_length=1)
    assets: dict[str, Any] = Field(default_factory=dict)
    asset_ledger: dict[str, Any] | None = None
    story_context: dict[str, Any] = Field(default_factory=dict)
    prompt_instruction: str = Field(min_length=1, max_length=100_000)
    image_models: list[str] = Field(default_factory=list)
    use_ai: bool = True
    use_network_proxy: bool = False


class AutoFlowStoryboardSplitRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    script: str = Field(min_length=1)
    assets: dict[str, Any] = Field(default_factory=dict)
    story_context: dict[str, Any] = Field(default_factory=dict)
    storyboard_prompt: str = Field(min_length=1, max_length=300_000)
    use_ai: bool = True
    use_network_proxy: bool = False


class AutoFlowAnalysisRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    assets: dict[str, Any] = Field(default_factory=dict)
    story_context: dict[str, Any] = Field(default_factory=dict)
    segments: list[dict[str, Any]]
    analysis_prompt: str = Field(min_length=1, max_length=100_000)
    reanalysis_prompt: str | None = Field(default=None, max_length=100_000)
    previous_analysis: dict[str, Any] | None = None
    use_ai: bool = True
    use_network_proxy: bool = False


class AutoFlowRouteRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    assets: dict[str, Any] = Field(default_factory=dict)
    story_context: dict[str, Any] = Field(default_factory=dict)
    shot_groups: list[dict[str, Any]]
    generation_mode: Literal["demo", "provider", "openrouter", "xingtu"] = "demo"
    image_model: str | None = Field(default=None, min_length=1, max_length=200)
    routing_analysis_prompt: str = Field(
        default="请逐镜头评估真实生成难度和能力需求，禁止直接选择模型。",
        min_length=1,
        max_length=100_000,
    )
    use_ai_difficulty: bool = True
    use_network_proxy: bool = False


class AutoFlowReferenceRegenerateRequest(BaseModel):
    generation_mode: Literal["demo", "xingtu"] = "xingtu"
    image_model: str | None = Field(default=None, min_length=1, max_length=200)
    shot_ids: list[str] = Field(default_factory=list)


class AutoFlowSubmitRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    final_video_plan: dict[str, Any]
    regenerate_existing: bool = False


class AutoFlowComposeRequest(BaseModel):
    project_params: AutoFlowProjectParams = Field(default_factory=AutoFlowProjectParams)
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    submit_result: dict[str, Any] | None = None
