export type FlowStep = "split" | "assetPrompts" | "assets" | "analysis" | "routing" | "submit" | "compose" | "finale";
export type RoutingTier = "low" | "medium" | "high";
export type GenerationMode = "demo" | "openrouter" | "xingtu";

export type ProjectParams = {
  episode_id: string;
  project_type: string;
  aspect_ratio: string;
  resolution: string;
  routing_tier: RoutingTier;
  global_visual_lock: string;
  feedback: string;
};

export type AssetItem = {
  id: string;
  gid?: string;
  name: string;
  asset_prompt?: string;
  image_prompts?: Record<string, string>;
  prompt?: string;
  description?: string;
  localized_prompt?: string;
  file_id?: string;
  url?: string;
  image_url?: string;
  public_url?: string;
  s3_key?: string;
  source?: string;
  mime_type?: string;
  size_bytes?: number;
};

export type AutoFlowAssets = {
  characters: AssetItem[];
  scenes: AssetItem[];
  items: AssetItem[];
};

export type AssetRecord = {
  asset_id?: string;
  file_id?: string;
  url?: string;
  image_url?: string;
  public_url?: string;
  local_url?: string;
  s3_key?: string;
  source?: string;
  mime_type?: string;
  original_filename?: string;
  size_bytes?: number;
  binding_status?: string;
};

export type AssetUploadToken = {
  asset_id?: string;
  method?: "PUT" | string;
  upload_url: string;
  headers?: Record<string, string>;
  s3_key: string;
  url: string;
  public_url?: string;
  content_type?: string;
  size_bytes?: number;
  original_filename?: string;
  expires_in?: number;
  max_size_bytes?: number;
  detail?: string;
};

export type Dialogue = {
  speaker?: string;
  type?: string;
  source_content?: string;
  content?: string;
};

export type SubShot = {
  id: string;
  segment_id?: string;
  duration: number;
  content?: string;
  scene?: string;
  characters?: string[];
  items?: string[];
  shot_type?: string;
  camera_movement?: string;
  entry_state?: string;
  performance?: string;
  exit_state?: string;
  dialogue?: Dialogue;
  indivisible?: boolean;
  transition_from_previous?: string;
  continuity_hint?: string;
};

export type Segment = {
  segment_id: string;
  start?: string;
  end?: string;
  duration?: number;
  scene?: string;
  scene_phase?: string;
  frame_background?: string;
  characters?: string[];
  items?: string[];
  shot_type?: string;
  camera_movement?: string;
  transition_from_previous?: string;
  entry_state?: string;
  performance?: string;
  exit_state?: string;
  dialogue?: Dialogue;
  emotion?: string;
  vfx?: string;
  sub_shots?: SubShot[];
};

export type SplitResponse = {
  assets: AutoFlowAssets;
  story_context: Record<string, unknown>;
  segments: Segment[];
  llm?: Record<string, unknown>;
  detail?: string;
};

export type AssetSplitResponse = {
  assets: AutoFlowAssets;
  asset_ledger?: Record<string, unknown> | null;
  asset_prompt_result?: Record<string, unknown> | null;
  prompt_variables?: Record<string, unknown>;
  story_context: Record<string, unknown>;
  llm?: Record<string, unknown>;
  detail?: string;
};

export type AssetPromptResponse = AssetSplitResponse;

export type ShotGroup = {
  group_id: string;
  group_type: "continuous_take" | "independent" | string;
  source_segment_ids: string[];
  sub_shot_ids: string[];
  duration: number;
  reason: string;
  scene_asset?: string;
  sub_shots?: SubShot[];
  entry_prompt_zh: string;
  exit_prompt_zh: string;
};

export type AnalysisResponse = {
  assets?: AutoFlowAssets;
  story_context?: Record<string, unknown>;
  segments?: Segment[];
  summary?: string;
  shot_groups: ShotGroup[];
  llm?: Record<string, unknown>;
  detail?: string;
};

export type RoutingCandidate = {
  model?: string;
  preset?: string;
  qualified?: boolean;
  selected?: boolean;
  fit_quality?: number;
  reliability?: number;
  call_points?: number;
  expected_usable_points?: number;
  tier_score?: number;
  hard_reasons?: string[];
};

export type RoutingModelComparison = {
  model?: string;
  display_name?: string;
  preset?: string;
  qualified?: boolean;
  selected?: boolean;
  verdict?: "selected" | "qualified" | "rejected" | "unavailable" | string;
  fit_quality?: number;
  reliability?: number;
  call_points?: number;
  expected_usable_points?: number;
  hard_reasons?: string[];
  why?: string;
};

export type RoutingDecision = {
  tier?: RoutingTier;
  selected_model?: string;
  selected_display_name?: string;
  selected_preset?: string;
  fit_quality?: number;
  reliability?: number;
  call_points?: number;
  expected_usable_points?: number;
  medium_target_quality?: number;
  medium_reliability_floor?: number;
  medium_target_met?: boolean;
  medium_selection_mode?: string;
  candidates?: RoutingCandidate[];
  selection_reason?: string;
  model_comparison?: RoutingModelComparison[];
};

export type SubShotDifficultyScore = {
  sub_shot_id?: string;
  difficulty_score?: number;
  overall_difficulty?: string;
  dimension_scores?: Record<string, number>;
  reason?: string;
  risks?: string[];
};

export type RoutingShot = {
  shot_id?: string;
  source_group?: string;
  atomic_ids?: string[];
  source_sub_shot_ids?: string[];
  duration?: number;
  routing_requirements?: Record<string, string>;
  complexity?: Record<string, string>;
  difficulty_analysis?: {
    story_priority?: string;
    difficulty_score?: number;
    overall_difficulty?: string;
    reason?: string;
    risks?: string[];
    sub_shot_scores?: SubShotDifficultyScore[];
  };
  routing_decision?: RoutingDecision;
};

export type FinalShot = {
  shot_id?: string;
  atomic_ids?: string[];
  group_id?: string;
  model?: string;
  model_params?: { resolution_preset?: string };
  duration?: number;
  prompt_zh?: string;
  references?: Array<{
    asset_id?: string;
    media_type?: string;
    asset_type?: string;
    required?: boolean;
    derived?: boolean;
    purpose?: string;
    derived_role?: string;
    generated_role?: string;
    url?: string;
    image_url?: string;
    public_url?: string;
  }>;
  reference_image_plan?: {
    input_asset_ids?: string[];
    output_asset_ids?: { entry?: string; exit?: string };
    entry_state_reference_prompt_zh?: string;
    exit_state_reference_edit_prompt_zh?: string;
  };
};

export type ReferenceManifest = {
  job_id?: string;
  shot_id?: string;
  status?: string;
  demo_placeholder?: boolean;
  message?: string;
  detail?: string;
  image_model?: string;
  provider?: string;
  generation_mode?: string;
  aspect_ratio?: string;
  size?: string;
  input_asset_ids?: string[];
  missing_asset_ids?: string[];
  entry?: { asset_id?: string; image_url?: string; url?: string; public_url?: string; s3_key?: string; prompt_zh?: string; status?: string };
  exit?: { asset_id?: string; image_url?: string; url?: string; public_url?: string; s3_key?: string; prompt_zh?: string; status?: string };
};

export type RouteResponse = {
  difficulty_analysis?: {
    summary?: string;
    shots?: Array<RoutingShot["difficulty_analysis"] & { group_id?: string }>;
    llm?: Record<string, unknown>;
  };
  routing_analysis?: { tier?: RoutingTier; target_resolution?: string; shots?: RoutingShot[] };
  final_video_plan?: { shots?: FinalShot[]; reference_image_jobs?: unknown[] };
  reference_generation?: {
    completed_count?: number;
    blocked_count?: number;
    completed?: ReferenceManifest[];
    blocked?: ReferenceManifest[];
    generation_mode?: GenerationMode;
  };
  source_context?: {
    project_params?: ProjectParams;
    assets?: AutoFlowAssets;
    story_context?: Record<string, unknown>;
    shot_groups?: ShotGroup[];
  };
  detail?: string;
};

export type SubmitResponse = {
  batch_id?: string;
  status?: string;
  batch_status?: string;
  submitted_count?: number;
  blocked_count?: number;
  succeeded_count?: number;
  failed_count?: number;
  running_count?: number;
  registry_count?: number;
  mode?: string;
  jobs?: Array<{
    job_id?: string;
    batch_id?: string;
    shot_id?: string;
    model?: string;
    provider?: string;
    provider_task_id?: string;
    status?: string;
    duration?: number | string;
    bound_asset_ids?: string[];
    derived_reference_ids?: string[];
    output_video_path?: string;
    output_path?: string;
    video_path?: string;
    output_video_url?: string;
    output_url?: string;
    video_url?: string;
    error_code?: string;
    error_message?: string;
  }>;
  blocked?: unknown[];
  detail?: string;
};

export type ComposeResponse = {
  mode?: string;
  compose_id?: string;
  status?: string;
  input_count?: number;
  blocked_count?: number;
  blocked?: unknown[];
  output_path?: string;
  output_url?: string;
  manifest_path?: string;
  message?: string;
  detail?: string;
};
