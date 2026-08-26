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
    generation_mode: Literal["demo", "provider"] = "demo"
    image_model: str | None = Field(default=None, min_length=1, max_length=200)


class WorkflowPlanRequest(BaseModel):
    episode_id: str = "EP001"
    final_video_plan: dict[str, Any]
