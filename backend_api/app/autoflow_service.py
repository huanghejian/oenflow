from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType
from typing import Any

from .config import settings
from .director_service import (
    _bedrock_additional_model_fields,
    _bedrock_converse_url,
    _bedrock_inference_config,
    _extract_claude_text,
    _extract_openrouter_text,
    _openrouter_reasoning,
    _parse_json_text,
    _unwrap_gateway_body,
)
from .long_time_http import LongTimeHttpError, post_json
from .logging_utils import get_logger, log_event, log_payload
from .reference_image_service import (
    create_reference_image_pair_job,
    create_reference_image_pair_provider_job,
)
from .workflow_service import (
    asset_reference_data_urls,
    missing_asset_ids,
    register_reference_pair,
    submit_video_jobs,
)


ROUTING_DIMENSIONS = [
    "acting_precision",
    "dialogue_lipsync",
    "identity_consistency",
    "multi_character_control",
    "motion_action",
    "physical_interaction",
    "camera_control",
    "prop_precision",
    "vfx_environment",
    "temporal_continuity",
]
COMPLEXITY_FIELDS = ["motion", "spatial", "asset_density", "continuity"]
SCRIPT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
ROLE_LINE_RE = re.compile(r"^([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{0,11})[：:]")
EPISODE_TITLE_RE = re.compile(r"^\s*第\s*(\d+)\s*集\b", re.MULTILINE)
SCENE_TITLE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\d+)\s*-+\s*(?:\d+)|第\s*\d+\s*场)(?:\s|日|夜|内|外|$)", re.MULTILINE)
SCENE_KEYWORDS = ["山门", "广场", "大殿", "庭院", "房间", "屋内", "街道", "战场", "办公室", "医院", "车内"]
PROP_KEYWORDS = ["剑", "刀", "枪", "玉佩", "玉牌", "手机", "信", "书", "门", "金色剑尖"]
DEFAULT_IMAGE_PROMPT_MODELS = ["gpt_image_2", "seedream_4", "flux_kontext"]
AUTOFLOW_ASSET_RESULT_PATH = settings.work_root / "autoflow_assets" / "latest.json"
AUTOFLOW_ASSET_IDENTIFY_RESULT_PATH = settings.work_root / "autoflow_assets" / "latest_identify.json"
AUTOFLOW_ASSET_PROMPT_RESULT_PATH = settings.work_root / "autoflow_assets" / "latest_prompts.json"
AUTOFLOW_STORYBOARD_RESULT_PATH = settings.work_root / "autoflow_storyboard" / "latest.json"
AUTOFLOW_ANALYSIS_RESULT_PATH = settings.work_root / "autoflow_analysis" / "latest.json"
_SCRIPT_MODULE_CACHE: dict[str, ModuleType] = {}
logger = get_logger(__name__)


def _object_schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": True,
    }


def _array_schema(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _string_schema() -> dict[str, Any]:
    return {"type": "string"}


def _nullable_string_schema() -> dict[str, Any]:
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _number_schema() -> dict[str, Any]:
    return {"type": "number"}


def _asset_schema() -> dict[str, Any]:
    return _object_schema(
        {
            "id": _string_schema(),
            "gid": _string_schema(),
            "name": _string_schema(),
            "description": _string_schema(),
            "asset_prompt": _string_schema(),
            "localized_prompt": _string_schema(),
            "anchor_timestamp": _string_schema(),
            "importance_reason": _string_schema(),
            "image_prompts": _object_schema({}, []),
        },
        ["id", "gid", "name", "description", "asset_prompt"],
    )


def _asset_identity_schema() -> dict[str, Any]:
    return _object_schema(
        {
            "id": _string_schema(),
            "gid": _string_schema(),
            "name": _string_schema(),
            "description": _string_schema(),
            "anchor_timestamp": _string_schema(),
            "importance_reason": _string_schema(),
        },
        ["id", "gid", "name", "description"],
    )


def _asset_inventory_response_schema() -> dict[str, Any]:
    asset = _asset_identity_schema()
    return _object_schema(
        {
            "characters": _array_schema(asset),
            "scenes": _array_schema(asset),
            "items": _array_schema(asset),
            "story_context": _object_schema(
                {
                    "summary": _string_schema(),
                    "story_era": _string_schema(),
                    "story_genre": _string_schema(),
                    "visual_medium": _string_schema(),
                    "source_region": _string_schema(),
                    "story_background": _string_schema(),
                    "visual_style": _string_schema(),
                },
                ["summary", "story_era", "story_genre", "visual_medium", "source_region", "story_background", "visual_style"],
            ),
        },
        ["characters", "scenes", "items", "story_context"],
    )


def _agent_a_ledger_response_schema() -> dict[str, Any]:
    ledger_item = _object_schema(
        {
            "id": _string_schema(),
            "type": _string_schema(),
            "name": _string_schema(),
            "match": _string_schema(),
            "status": _string_schema(),
            "occurrences": _array_schema({"type": "integer"}),
            "aliasesAdded": {"anyOf": [_array_schema(_string_schema()), {"type": "null"}]},
            "reference": _nullable_string_schema(),
            "visualSpec": _object_schema({}, []),
            "possibleSameAs": _nullable_string_schema(),
        },
        ["id", "type", "name", "match", "status", "occurrences", "reference", "visualSpec"],
    )
    return _object_schema(
        {
            "episodeIndex": _array_schema(
                _object_schema(
                    {"ep": {"type": "integer"}, "scenes": {"type": "integer"}},
                    ["ep", "scenes"],
                )
            ),
            "overflow": _nullable_string_schema(),
            "assets": _array_schema(ledger_item),
        },
        ["episodeIndex", "overflow", "assets"],
    )


def _agent_b_prompt_response_schema() -> dict[str, Any]:
    prompt_variant = _object_schema(
        {
            "variant": _string_schema(),
            "prompt": _string_schema(),
        },
        ["variant", "prompt"],
    )
    asset_prompt = _object_schema(
        {
            "id": _string_schema(),
            "type": _string_schema(),
            "name": _string_schema(),
            "episodes": _array_schema({"type": "integer"}),
            "reference": _nullable_string_schema(),
            "tier": {"type": "integer"},
            "prompts": _array_schema(prompt_variant),
            "prompt": _string_schema(),
        },
        ["id", "type", "name", "episodes", "reference", "tier"],
    )
    return _object_schema({"assets": _array_schema(asset_prompt)}, ["assets"])


def _assets_response_schema() -> dict[str, Any]:
    asset = _asset_schema()
    return _object_schema(
        {
            "characters": _array_schema(asset),
            "scenes": _array_schema(asset),
            "items": _array_schema(asset),
            "story_context": _object_schema(
                {
                    "summary": _string_schema(),
                    "story_era": _string_schema(),
                    "story_genre": _string_schema(),
                    "visual_medium": _string_schema(),
                    "source_region": _string_schema(),
                    "story_background": _string_schema(),
                    "visual_style": _string_schema(),
                },
                ["summary", "story_era", "story_genre", "visual_medium", "source_region", "story_background", "visual_style"],
            ),
        },
        ["characters", "scenes", "items", "story_context"],
    )


def _split_response_schema() -> dict[str, Any]:
    asset = _asset_schema()
    sub_shot = _object_schema(
        {
            "id": _string_schema(),
            "duration": _number_schema(),
            "content": _string_schema(),
            "scene": _string_schema(),
            "characters": _array_schema(_string_schema()),
            "items": _array_schema(_string_schema()),
            "shot_type": _string_schema(),
            "camera_movement": _string_schema(),
            "entry_state": _string_schema(),
            "performance": _string_schema(),
            "exit_state": _string_schema(),
            "dialogue": _object_schema(
                {
                    "speaker": _string_schema(),
                    "type": _string_schema(),
                    "source_content": _string_schema(),
                    "content": _string_schema(),
                },
                ["speaker", "type", "source_content", "content"],
            ),
            "continuity_hint": _string_schema(),
            "min_duration_reason": _string_schema(),
            "indivisible": {"type": "boolean"},
        },
        ["id", "duration", "content", "scene", "characters", "shot_type", "entry_state", "performance", "exit_state"],
    )
    segment = _object_schema(
        {
            "segment_id": _string_schema(),
            "start": _string_schema(),
            "end": _string_schema(),
            "duration": _number_schema(),
            "scene": _string_schema(),
            "scene_phase": _string_schema(),
            "frame_background": _string_schema(),
            "characters": _array_schema(_string_schema()),
            "shot_type": _string_schema(),
            "camera_movement": _string_schema(),
            "transition_from_previous": _string_schema(),
            "entry_state": _string_schema(),
            "performance": _string_schema(),
            "exit_state": _string_schema(),
            "dialogue": _object_schema({}, []),
            "emotion": _string_schema(),
            "vfx": _string_schema(),
            "items": _array_schema(_string_schema()),
            "sub_shots": _array_schema(sub_shot),
        },
        [
            "segment_id",
            "start",
            "end",
            "duration",
            "scene",
            "frame_background",
            "characters",
            "shot_type",
            "camera_movement",
            "transition_from_previous",
            "entry_state",
            "performance",
            "exit_state",
            "dialogue",
            "emotion",
            "vfx",
            "sub_shots",
        ],
    )
    return _object_schema(
        {
            "characters": _array_schema(asset),
            "scenes": _array_schema(asset),
            "items": _array_schema(asset),
            "story_context": _object_schema(
                {
                    "summary": _string_schema(),
                    "story_era": _string_schema(),
                    "story_genre": _string_schema(),
                    "visual_medium": _string_schema(),
                    "source_region": _string_schema(),
                    "story_background": _string_schema(),
                    "visual_style": _string_schema(),
                },
                ["summary", "story_era", "story_genre", "visual_medium", "source_region", "story_background", "visual_style"],
            ),
            "segments": _array_schema(segment),
        },
        ["characters", "scenes", "items", "story_context", "segments"],
    )


def _storyboard_response_schema() -> dict[str, Any]:
    schema = _split_response_schema()
    return _object_schema(
        {
            "story_context": schema["properties"]["story_context"],
            "segments": schema["properties"]["segments"],
        },
        ["story_context", "segments"],
    )


def _analysis_response_schema() -> dict[str, Any]:
    group = _object_schema(
        {
            "group_id": _string_schema(),
            "group_type": {"type": "string", "enum": ["continuous_take", "min_duration_pack", "independent"]},
            "source_segment_ids": _array_schema(_string_schema()),
            "sub_shot_ids": _array_schema(_string_schema()),
            "duration": _number_schema(),
            "reason": _string_schema(),
            "entry_prompt_zh": _string_schema(),
            "exit_prompt_zh": _string_schema(),
        },
        ["group_id", "group_type", "source_segment_ids", "sub_shot_ids", "duration", "reason", "entry_prompt_zh", "exit_prompt_zh"],
    )
    return _object_schema(
        {
            "summary": _string_schema(),
            "shot_groups": _array_schema(group),
        },
        ["summary", "shot_groups"],
    )


def _call_openrouter_json(
    system_text: str,
    user_payload: dict[str, Any],
    schema_name: str,
    schema: dict[str, Any],
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.openrouter_api_key:
        raise RuntimeError("未配置 OPENROUTER_API_KEY")
    request_body = {
        "model": settings.openrouter_director_model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "max_tokens": max_tokens or settings.openrouter_max_output_tokens,
        "reasoning": _openrouter_reasoning(settings.openrouter_reasoning_effort),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": False,
                "schema": schema,
            },
        },
    }
    log_payload(
        logger,
        "llm.openrouter.request",
        {
            "schema_name": schema_name,
            "model": settings.openrouter_director_model,
            "max_tokens": request_body["max_tokens"],
            "reasoning": request_body.get("reasoning"),
            "system_text": system_text,
            "user_payload": user_payload,
            "schema": schema,
        },
    )
    response_data, response_id_header = post_json(
        f"{settings.openrouter_base_url}/chat/completions",
        request_body,
        f"Bearer {settings.openrouter_api_key}",
        {
            "HTTP-Referer": "http://127.0.0.1:9001",
            "X-OpenRouter-Title": "oenflow AutoFlow Demo",
        },
    )
    log_payload(
        logger,
        "llm.openrouter.raw_response",
        {"schema_name": schema_name, "response": response_data},
    )
    parsed = _parse_json_text(_extract_openrouter_text(response_data), "OpenRouter")
    meta = {
        "response_id": response_data.get("id") or response_id_header,
        "provider": "openrouter",
        "model": response_data.get("model") or settings.openrouter_director_model,
        "usage": response_data.get("usage"),
        "finish_reason": ((response_data.get("choices") or [{}])[0] or {}).get("finish_reason"),
    }
    log_payload(
        logger,
        "llm.openrouter.parsed_response",
        {"schema_name": schema_name, "meta": meta, "parsed": parsed},
    )
    return parsed, meta


def _call_asset_llm_json(
    system_text: str,
    user_payload: dict[str, Any],
    schema_name: str,
    schema: dict[str, Any],
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if settings.director_provider == "openrouter":
        return _call_openrouter_json(
            system_text, user_payload, schema_name, schema, max_tokens=max_tokens
        )
    if settings.director_provider != "claude_converse":
        raise RuntimeError(
            f"AutoFlow 大模型调用不支持 DIRECTOR_PROVIDER={settings.director_provider}；"
            "请使用 claude_converse 或 openrouter。"
        )
    if not settings.claude_converse_url:
        raise RuntimeError("未配置 CLAUDE_CONVERSE_URL")
    if not settings.claude_converse_api_key:
        raise RuntimeError("未配置 CLAUDE_CONVERSE_API_KEY")

    request_body: dict[str, Any] = {
        "system": [{"text": system_text}],
        "messages": [
            {
                "role": "user",
                "content": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
            }
        ],
        "inferenceConfig": _bedrock_inference_config(
            max_tokens or settings.claude_max_output_tokens,
            settings.claude_director_model,
        ),
    }
    additional_fields = _bedrock_additional_model_fields(
        settings.claude_director_model, settings.claude_thinking_effort
    )
    if additional_fields:
        request_body["additionalModelRequestFields"] = additional_fields
    log_payload(
        logger,
        "llm.claude_converse.request",
        {
            "schema_name": schema_name,
            "model": settings.claude_director_model,
            "system_text": system_text,
            "user_payload": user_payload,
            "schema": schema,
            "request_body": request_body,
        },
    )
    try:
        response_data, response_id = post_json(
            _bedrock_converse_url(
                settings.claude_converse_url,
                settings.claude_director_model,
                settings.claude_region,
            ),
            request_body,
            f"Bearer {settings.claude_converse_api_key}",
            {"x-request-id": uuid.uuid4().hex},
        )
    except LongTimeHttpError as exc:
        raise RuntimeError(
            f"Claude Converse AutoFlow 请求失败: HTTP {exc.status_code}; {exc.body}"
        ) from exc
    response_data = _unwrap_gateway_body(response_data)
    log_payload(
        logger,
        "llm.claude_converse.raw_response",
        {"schema_name": schema_name, "response_id": response_id, "response": response_data},
    )
    parsed = _parse_json_text(_extract_claude_text(response_data), "Claude Converse")
    meta = {
        "response_id": response_id,
        "provider": "claude_converse",
        "model": settings.claude_director_model,
        "usage": response_data.get("usage") if isinstance(response_data, dict) else None,
        "stop_reason": response_data.get("stopReason") if isinstance(response_data, dict) else None,
    }
    log_payload(
        logger,
        "llm.claude_converse.parsed_response",
        {"schema_name": schema_name, "meta": meta, "parsed": parsed},
    )
    return parsed, meta


def _clean_id(value: Any, prefix: str, index: int) -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"{prefix}{index:03d}"
    return re.sub(r"\s+", "_", raw)


def _unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _to_seconds(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(1, int(round(float(value))))
    text = str(value or "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return max(1, int(round(float(match.group(1))))) if match else 3


def _image_prompt_models(image_models: list[str] | None = None) -> list[str]:
    models = _unique(image_models or [])
    return models[:3] if models else DEFAULT_IMAGE_PROMPT_MODELS


def _image_prompts_for_asset(
    name: str,
    prompt: str,
    prefix: str,
    image_models: list[str] | None = None,
    existing: Any = None,
) -> dict[str, str]:
    prompts = {
        str(key): str(value)
        for key, value in (existing or {}).items()
        if value is not None
    } if isinstance(existing, dict) else {}
    kind = "角色定妆照" if prefix == "ch" else "场景空镜图" if prefix == "sc" else "关键道具单体图"
    for model in _image_prompt_models(image_models):
        if prompts.get(model):
            continue
        if model == "gpt_image_2":
            prompts[model] = f"{kind}，{name}。{prompt}。电影级写实质感，主体清晰，9:16，避免文字和水印。"
        elif model == "seedream_4":
            prompts[model] = f"{name}，{kind}参考图，保留身份/材质/轮廓稳定，短剧竖屏电影感，光影统一，无字幕无文字。"
        elif model == "flux_kontext":
            prompts[model] = f"clean cinematic reference image of {name}, {kind}, {prompt}, consistent identity, sharp details, no text, no watermark"
        else:
            prompts[model] = f"{name}，{kind}，{prompt}，主体明确，适合作为视频生成资产参考。"
    return prompts


def _asset_record(
    raw: Any,
    prefix: str,
    index: int,
    fallback_name: str,
    image_models: list[str] | None = None,
) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {"name": str(raw or fallback_name)}
    name = str(data.get("name") or data.get("localized_name") or data.get("description") or fallback_name).strip()
    asset_id = _clean_id(data.get("id") or data.get("asset_id") or name, prefix, index)
    prompt = str(
        data.get("asset_prompt")
        or data.get("localized_prompt")
        or data.get("localized_appearance_prompt")
        or data.get("localized_scene_prompt")
        or data.get("prompt")
        or data.get("description")
        or data.get("appearance")
        or name
        or asset_id
    )
    return {
        **copy.deepcopy(data),
        "id": asset_id,
        "gid": str(data.get("gid") or asset_id),
        "name": name or asset_id,
        "asset_prompt": prompt,
        "image_prompts": _image_prompts_for_asset(
            name or asset_id,
            prompt,
            prefix,
            image_models,
            data.get("image_prompts") or data.get("model_prompts"),
        ),
        "description": str(data.get("description") or prompt),
    }


def _asset_identity_record(
    raw: Any,
    prefix: str,
    index: int,
    fallback_name: str,
) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {"name": str(raw or fallback_name)}
    name = str(
        data.get("name")
        or data.get("localized_name")
        or data.get("description")
        or fallback_name
    ).strip()
    asset_id = _clean_id(data.get("id") or data.get("asset_id") or name, prefix, index)
    record = {
        "id": asset_id,
        "gid": str(data.get("gid") or asset_id),
        "name": name or asset_id,
        "description": str(data.get("description") or name or asset_id),
    }
    for key in ("anchor_timestamp", "importance_reason"):
        if data.get(key):
            record[key] = str(data[key])
    return record


def _normalize_asset_identities(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    characters = [
        _asset_identity_record(item, "ch", index + 1, f"角色{index + 1}")
        for index, item in enumerate(data.get("characters") or [])
    ]
    scenes = [
        _asset_identity_record(item, "sc", index + 1, f"场景{index + 1}")
        for index, item in enumerate(data.get("scenes") or [])
    ]
    items = [
        _asset_identity_record(item, "it", index + 1, f"物品{index + 1}")
        for index, item in enumerate(data.get("items") or data.get("props") or [])
    ]
    return {"characters": characters, "scenes": scenes, "items": items}


def _episode_index_from_script(script: str) -> list[dict[str, int]]:
    matches = list(EPISODE_TITLE_RE.finditer(script))
    if not matches:
        return [{"ep": 1, "scenes": len(SCENE_TITLE_RE.findall(script))}]
    episode_index: list[dict[str, int]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script)
        body = script[start:end]
        episode_index.append({"ep": int(match.group(1)), "scenes": len(SCENE_TITLE_RE.findall(body))})
    return episode_index


def _default_batch_info(script: str) -> dict[str, Any]:
    episode_index = _episode_index_from_script(script)
    episode_numbers = [item["ep"] for item in episode_index] or [1]
    return {
        "batch": 1,
        "batchTotal": 1,
        "episodeStart": min(episode_numbers),
        "episodeEnd": max(episode_numbers),
        "isFirst": True,
        "isLast": True,
        "episodeIndex": episode_index,
        "mode": "single_batch",
    }


def _default_id_range() -> dict[str, str]:
    return {
        "character": "C01-C200",
        "character_group": "C01-C200",
        "scene": "S01-S120",
        "prop": "P01-P200",
    }


def _format_template_variable(value: Any) -> str:
    if value is None or value == "":
        return "空"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _render_asset_prompt_template(
    asset_prompt: str,
    project_params: dict[str, Any],
    script: str,
    batch_info: dict[str, Any] | None,
    id_range: dict[str, Any] | None,
    existing_assets: Any,
) -> tuple[str, dict[str, Any]]:
    resolved_batch_info = batch_info or _default_batch_info(script)
    resolved_id_range = id_range or _default_id_range()
    variables = {
        "batchInfo": resolved_batch_info,
        "idRange": resolved_id_range,
        "existingAssets": existing_assets or "",
        "episodeScripts": script,
        "projectParams": project_params,
    }
    rendered = asset_prompt
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", _format_template_variable(value))
    if "{episodeScripts}" not in asset_prompt:
        rendered = (
            f"{rendered}\n\n运行时输入\n"
            f"<批次信息>{_format_template_variable(resolved_batch_info)}</批次信息>\n\n"
            f"<可用编号区间>{_format_template_variable(resolved_id_range)}</可用编号区间>\n\n"
            f"<已有资产清单>{_format_template_variable(existing_assets)}</已有资产清单>\n\n"
            f"<分集剧本>{script}</分集剧本>"
        )
    return rendered, variables


def _ledger_visual_description(item: dict[str, Any]) -> str:
    visual_spec = item.get("visualSpec")
    if isinstance(visual_spec, dict) and visual_spec:
        parts = [f"{key}: {value}" for key, value in visual_spec.items() if value not in (None, "", [])]
        if parts:
            return "；".join(parts)
    if visual_spec:
        return str(visual_spec)
    return str(item.get("name") or item.get("id") or "资产")


def _assets_from_agent_a_ledger(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    assets: dict[str, list[dict[str, Any]]] = {"characters": [], "scenes": [], "items": []}
    for index, item in enumerate(raw.get("assets") or [], start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        asset_id = str(item.get("id") or f"A{index:03d}").strip()
        record = {
            "id": asset_id,
            "gid": asset_id,
            "name": str(item.get("name") or asset_id),
            "description": _ledger_visual_description(item),
            "asset_type": item_type,
            "match": item.get("match"),
            "status": item.get("status"),
            "occurrences": item.get("occurrences") or [],
            "reference": item.get("reference"),
            "possibleSameAs": item.get("possibleSameAs"),
        }
        if item_type in ("character", "character_group"):
            assets["characters"].append(record)
        elif item_type == "scene":
            assets["scenes"].append(record)
        elif item_type == "prop":
            assets["items"].append(record)
    return assets


def _story_context_from_agent_a(project_params: dict[str, Any], script: str, raw: dict[str, Any]) -> dict[str, Any]:
    episode_index = raw.get("episodeIndex") if isinstance(raw.get("episodeIndex"), list) else _episode_index_from_script(script)
    summary = re.sub(r"\s+", " ", script).strip()[:80]
    return {
        "summary": summary,
        "story_era": "架空古代",
        "story_genre": "玄幻短剧",
        "visual_medium": project_params.get("project_type") or "短剧",
        "source_region": "未明确",
        "story_background": summary,
        "visual_style": project_params.get("global_visual_lock") or "影视级短剧视觉",
        "episode_index": episode_index,
    }


def _tier_from_reference(reference: Any) -> int:
    return 2 if reference else 1


def _agent_b_row_from_asset(asset: dict[str, Any], asset_type: str, fallback_episodes: list[int]) -> dict[str, Any]:
    reference = asset.get("reference")
    occurrences = asset.get("occurrences") or asset.get("episodes") or fallback_episodes
    visual_spec = asset.get("visualSpec")
    if not isinstance(visual_spec, dict) or not visual_spec:
        visual_spec = {"description": asset.get("description") or asset.get("name") or asset.get("id")}
    return {
        "id": str(asset.get("id") or asset.get("gid") or asset.get("name")),
        "type": asset_type,
        "name": str(asset.get("name") or asset.get("id")),
        "episodes": occurrences,
        "reference": reference or None,
        "tier": int(asset.get("tier") or _tier_from_reference(reference)),
        "visualSpec": visual_spec,
    }


def _agent_b_asset_rows(
    asset_ledger: dict[str, Any] | None,
    assets: dict[str, Any],
    story_context: dict[str, Any],
) -> list[dict[str, Any]]:
    episode_index = story_context.get("episode_index") if isinstance(story_context.get("episode_index"), list) else []
    fallback_episodes = [int(item.get("ep")) for item in episode_index if isinstance(item, dict) and item.get("ep")]
    if not fallback_episodes:
        fallback_episodes = [1]

    if asset_ledger and isinstance(asset_ledger.get("assets"), list):
        rows = []
        for item in asset_ledger["assets"]:
            if not isinstance(item, dict):
                continue
            row = copy.deepcopy(item)
            row["episodes"] = row.pop("occurrences", row.get("episodes", fallback_episodes))
            row["tier"] = int(row.get("tier") or _tier_from_reference(row.get("reference")))
            rows.append(
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "name": row.get("name"),
                    "episodes": row.get("episodes") or fallback_episodes,
                    "reference": row.get("reference"),
                    "tier": row.get("tier"),
                    "visualSpec": row.get("visualSpec") or {"description": row.get("description") or row.get("name")},
                }
            )
        return rows

    normalized = _normalize_asset_identities(assets)
    rows: list[dict[str, Any]] = []
    rows.extend(_agent_b_row_from_asset(item, "character", fallback_episodes) for item in normalized["characters"])
    rows.extend(_agent_b_row_from_asset(item, "scene", fallback_episodes) for item in normalized["scenes"])
    rows.extend(_agent_b_row_from_asset(item, "prop", fallback_episodes) for item in normalized["items"])
    return rows


def _render_asset_generation_prompt_template(
    prompt_instruction: str,
    project_params: dict[str, Any],
    script: str,
    asset_rows: list[dict[str, Any]],
    story_context: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    variables = {
        "assetRows": asset_rows,
        "stylePrompt": project_params.get("global_visual_lock") or "",
        "batchInfo": {
            "assetCount": len(asset_rows),
            "episodeIndex": story_context.get("episode_index") or _episode_index_from_script(script),
        },
        "projectParams": project_params,
        "storyContext": story_context,
    }
    rendered = prompt_instruction
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", _format_template_variable(value))
    if "{assetRows}" not in prompt_instruction:
        rendered = (
            f"{rendered}\n\n运行时输入\n"
            f"<资产行>{_format_template_variable(asset_rows)}</资产行>\n\n"
            f"<项目画风>{_format_template_variable(variables['stylePrompt'])}</项目画风>"
        )
    return rendered, variables


def _agent_b_prompt_text(item: dict[str, Any]) -> tuple[str, dict[str, str]]:
    prompts = item.get("prompts")
    if isinstance(prompts, list) and prompts:
        mapped: dict[str, str] = {}
        first_prompt = ""
        for prompt_item in prompts:
            if not isinstance(prompt_item, dict):
                continue
            variant = str(prompt_item.get("variant") or f"variant{len(mapped) + 1}")
            prompt = str(prompt_item.get("prompt") or "")
            if prompt and not first_prompt:
                first_prompt = prompt
            if prompt:
                mapped[variant] = prompt
        return first_prompt or str(item.get("prompt") or ""), mapped
    prompt = str(item.get("prompt") or "")
    return prompt, {"base": prompt} if prompt else {}


def _normalize_agent_b_prompt_assets(
    raw: dict[str, Any],
    source_assets: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for collection, item_type in (("characters", "character"), ("scenes", "scene"), ("items", "prop")):
        for item in source_assets.get(collection) or []:
            by_id[str(item.get("id"))] = (collection, {**item, "asset_type": item.get("asset_type") or item_type})

    output: dict[str, list[dict[str, Any]]] = {"characters": [], "scenes": [], "items": []}
    for item in raw.get("assets") or []:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("id") or "")
        collection, base = by_id.get(asset_id, ("items", {"id": asset_id, "gid": asset_id, "name": item.get("name") or asset_id}))
        asset_prompt, image_prompts = _agent_b_prompt_text(item)
        output[collection].append(
            {
                **base,
                "id": asset_id,
                "gid": base.get("gid") or asset_id,
                "name": str(item.get("name") or base.get("name") or asset_id),
                "asset_prompt": asset_prompt,
                "image_prompts": image_prompts,
                "description": base.get("description") or asset_prompt or str(item.get("name") or asset_id),
                "reference": item.get("reference") or base.get("reference"),
                "tier": item.get("tier"),
                "episodes": item.get("episodes") or base.get("occurrences") or [],
            }
        )
    return output


def _normalize_assets(data: dict[str, Any], image_models: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    characters = [
        _asset_record(item, "ch", index + 1, f"角色{index + 1}", image_models)
        for index, item in enumerate(data.get("characters") or [])
    ]
    scenes = [
        _asset_record(item, "sc", index + 1, f"场景{index + 1}", image_models)
        for index, item in enumerate(data.get("scenes") or [])
    ]
    items = [
        _asset_record(item, "it", index + 1, f"物品{index + 1}", image_models)
        for index, item in enumerate(data.get("items") or data.get("props") or [])
    ]
    return {"characters": characters, "scenes": scenes, "items": items}


def _normalize_segments(raw_segments: list[Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = 0
    for index, raw in enumerate(raw_segments, start=1):
        data = raw if isinstance(raw, dict) else {"performance": str(raw or "")}
        sub_shots = data.get("sub_shots") if isinstance(data.get("sub_shots"), list) else []
        if not sub_shots:
            sub_shots = [
                {
                    "id": f"c{index:02d}",
                    "duration": data.get("duration") or 3,
                    "content": data.get("performance") or data.get("entry_state") or data.get("frame_background") or "",
                    "scene": data.get("scene"),
                    "characters": data.get("characters") or [],
                    "items": data.get("items") or [],
                    "shot_type": data.get("shot_type") or "中景",
                    "camera_movement": data.get("camera_movement") or "固定镜头",
                    "entry_state": data.get("entry_state") or "",
                    "performance": data.get("performance") or "",
                    "exit_state": data.get("exit_state") or "",
                    "dialogue": data.get("dialogue") or {},
                }
            ]
        normalized_subs: list[dict[str, Any]] = []
        duration = 0
        for sub_index, sub in enumerate(sub_shots, start=1):
            sub_data = sub if isinstance(sub, dict) else {"content": str(sub or "")}
            sub_duration = _to_seconds(sub_data.get("duration") or sub_data.get("durationS") or sub_data.get("duration_s"))
            duration += sub_duration
            normalized_subs.append(
                {
                    **copy.deepcopy(sub_data),
                    "id": str(sub_data.get("id") or f"c{index:02d}_{sub_index:02d}"),
                    "duration": sub_duration,
                    "content": str(sub_data.get("content") or sub_data.get("performance") or data.get("performance") or ""),
                    "scene": str(sub_data.get("scene") or data.get("scene") or "主场景"),
                    "characters": _unique(list(sub_data.get("characters") or data.get("characters") or [])),
                    "items": _unique(list(sub_data.get("items") or data.get("items") or [])),
                    "shot_type": str(sub_data.get("shot_type") or data.get("shot_type") or "中景"),
                    "camera_movement": str(sub_data.get("camera_movement") or data.get("camera_movement") or "固定镜头"),
                    "entry_state": str(sub_data.get("entry_state") or data.get("entry_state") or ""),
                    "performance": str(sub_data.get("performance") or sub_data.get("content") or data.get("performance") or ""),
                    "exit_state": str(sub_data.get("exit_state") or data.get("exit_state") or ""),
                    "dialogue": sub_data.get("dialogue") or data.get("dialogue") or {},
                    "indivisible": bool(sub_data.get("indivisible") or data.get("indivisible")),
                }
            )
        start = str(data.get("start") or f"{cursor}s")
        cursor += duration
        end = str(data.get("end") or f"{cursor}s")
        segments.append(
            {
                **copy.deepcopy(data),
                "segment_id": str(data.get("segment_id") or f"s{index:03d}"),
                "start": start,
                "end": end,
                "duration": duration,
                "scene": str(data.get("scene") or normalized_subs[0]["scene"] or "主场景"),
                "scene_phase": str(data.get("scene_phase") or "剧情推进"),
                "frame_background": str(data.get("frame_background") or data.get("scene") or normalized_subs[0]["scene"] or "主场景"),
                "characters": _unique(list(data.get("characters") or []) + [c for sub in normalized_subs for c in sub.get("characters", [])]),
                "items": _unique(list(data.get("items") or []) + [p for sub in normalized_subs for p in sub.get("items", [])]),
                "shot_type": str(data.get("shot_type") or normalized_subs[0]["shot_type"]),
                "camera_movement": str(data.get("camera_movement") or normalized_subs[0]["camera_movement"]),
                "transition_from_previous": str(data.get("transition_from_previous") or ("scene_start" if index == 1 else "hard_cut")),
                "entry_state": str(data.get("entry_state") or normalized_subs[0]["entry_state"]),
                "performance": str(data.get("performance") or "；".join(sub["performance"] for sub in normalized_subs if sub.get("performance"))),
                "exit_state": str(data.get("exit_state") or normalized_subs[-1]["exit_state"]),
                "dialogue": data.get("dialogue") or {},
                "emotion": str(data.get("emotion") or "克制真实"),
                "vfx": str(data.get("vfx") or "无特殊特效"),
                "sub_shots": normalized_subs,
            }
        )
    return segments


def _extract_names(script: str) -> list[str]:
    names = [m.group(1) for line in script.splitlines() if (m := ROLE_LINE_RE.match(line.strip()))]
    bracketed = re.findall(r"[【\[]([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{0,11})[】\]]", script)
    return _unique(names + bracketed)[:8]


def _detect_assets(script: str, visual_lock: str) -> dict[str, list[dict[str, Any]]]:
    names = _extract_names(script) or ["主角", "对手"]
    scenes = [kw for kw in SCENE_KEYWORDS if kw in script] or ["主场景"]
    props = [kw for kw in PROP_KEYWORDS if kw in script]
    return {
        "characters": [
            {
                "id": f"role_{i:02d}",
                "gid": f"role_{i:02d}",
                "name": name,
                "asset_prompt": f"{name}，{visual_lock or '短剧角色造型'}，正面清晰半身照，五官稳定，服装完整。",
            }
            for i, name in enumerate(names, start=1)
        ],
        "scenes": [
            {
                "id": f"scene_{i:02d}",
                "gid": f"scene_{i:02d}",
                "name": scene,
                "asset_prompt": f"{scene}，{visual_lock or '电影感场景'}，空镜环境图，空间结构清楚，光影统一。",
            }
            for i, scene in enumerate(scenes, start=1)
        ],
        "items": [
            {
                "id": f"prop_{i:02d}",
                "gid": f"prop_{i:02d}",
                "name": prop,
                "asset_prompt": f"关键物品：{prop}，单体清晰产品图，材质和轮廓明确，适合作为视频生成参考。",
            }
            for i, prop in enumerate(props, start=1)
        ],
    }


def _fallback_split(project_params: dict[str, Any], script: str) -> dict[str, Any]:
    visual_lock = str(project_params.get("global_visual_lock") or "")
    assets = _detect_assets(script, visual_lock)
    chunks = [part.strip() for part in SCRIPT_SPLIT_RE.split(script) if part and part.strip()]
    if not chunks:
        chunks = [script.strip()]
    segments: list[dict[str, Any]] = []
    scene_names = [item["name"] for item in assets["scenes"]] or ["主场景"]
    role_names = [item["name"] for item in assets["characters"]]
    prop_names = [item["name"] for item in assets["items"]]
    cursor = 0
    for index, chunk in enumerate(chunks[:24], start=1):
        duration = 3 if len(chunk) < 45 else 4
        scene = scene_names[(index - 1) % len(scene_names)]
        visible_roles = [name for name in role_names if name in chunk] or role_names[: min(2, len(role_names))]
        visible_props = [name for name in prop_names if name in chunk]
        dialogue_match = re.match(r"([^：:]{1,12})[：:](.+)", chunk)
        dialogue = {
            "speaker": dialogue_match.group(1).strip() if dialogue_match else "",
            "type": "dialogue" if dialogue_match else "none",
            "source_content": dialogue_match.group(2).strip() if dialogue_match else "",
            "content": dialogue_match.group(2).strip() if dialogue_match else "",
        }
        sub_shot = {
            "id": f"c{index:02d}",
            "duration": duration,
            "content": chunk,
            "scene": scene,
            "characters": visible_roles,
            "items": visible_props,
            "shot_type": "近景" if dialogue_match else "中景",
            "camera_movement": "固定镜头",
            "entry_state": f"{scene}中，{('、'.join(visible_roles) or '主体')}处于动作开始状态",
            "performance": chunk,
            "exit_state": f"{('、'.join(visible_roles) or '主体')}完成本句动作后的停顿状态",
            "dialogue": dialogue,
            "indivisible": False,
        }
        start = cursor
        cursor += duration
        segments.append(
            {
                "segment_id": f"s{index:03d}",
                "start": f"{start}s",
                "end": f"{cursor}s",
                "duration": duration,
                "scene": scene,
                "scene_phase": "剧情推进",
                "frame_background": scene,
                "characters": visible_roles,
                "items": visible_props,
                "shot_type": sub_shot["shot_type"],
                "camera_movement": "固定镜头",
                "transition_from_previous": "scene_start" if index == 1 else "hard_cut",
                "entry_state": sub_shot["entry_state"],
                "performance": chunk,
                "exit_state": sub_shot["exit_state"],
                "dialogue": dialogue,
                "emotion": "紧张" if any(x in chunk for x in ("惊", "怒", "冲", "杀")) else "克制",
                "vfx": "无特殊特效",
                "sub_shots": [sub_shot],
            }
        )
    return {
        **assets,
        "story_context": {
            "summary": chunks[0][:120],
            "story_era": project_params.get("project_type") or "短剧",
            "story_genre": project_params.get("project_type") or "短剧",
            "visual_medium": "真人短剧",
            "source_region": "中文",
            "story_background": visual_lock or "按剧本设定",
            "visual_style": visual_lock or "电影感、统一光影",
        },
        "segments": segments,
    }


def split_script_assets_and_segments(
    project_params: dict[str, Any],
    script: str,
    split_prompt: str,
    asset_prompt: str | None = None,
    storyboard_prompt: str | None = None,
    assets: dict[str, Any] | None = None,
    story_context: dict[str, Any] | None = None,
    image_models: list[str] | None = None,
    use_ai: bool = True,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.split_assets_and_segments.start",
        use_ai=use_ai,
        script_length=len(script),
        split_prompt_length=len(split_prompt),
        asset_prompt_length=len(asset_prompt or ""),
        storyboard_prompt_length=len(storyboard_prompt or ""),
        provided_assets=bool(assets),
        image_models=image_models or [],
        project_params=project_params,
    )
    asset_result = (
        {
            "assets": _normalize_assets(assets or {}, image_models),
            "story_context": story_context or {},
            "llm": {"provider": "provided", "model": None},
        }
        if assets
        else split_script_assets(
            project_params,
            script,
            asset_prompt or split_prompt,
            None,
            None,
            None,
            image_models or [],
            use_ai,
        )
    )
    storyboard_result = split_script_storyboard(
        project_params,
        script,
        asset_result["assets"],
        asset_result.get("story_context") or {},
        storyboard_prompt or split_prompt,
        use_ai,
    )
    result = {
        "assets": asset_result["assets"],
        "story_context": storyboard_result.get("story_context") or asset_result.get("story_context") or {},
        "segments": storyboard_result["segments"],
        "llm": {
            "assets": asset_result.get("llm"),
            "storyboard": storyboard_result.get("llm"),
        },
        "contract": "ai_video_compatible_autoflow_v1",
    }
    log_payload(logger, "autoflow.split_assets_and_segments.result", result)
    return result


def split_script_assets(
    project_params: dict[str, Any],
    script: str,
    asset_prompt: str,
    batch_info: dict[str, Any] | None,
    id_range: dict[str, Any] | None,
    existing_assets: Any,
    image_models: list[str] | None,
    use_ai: bool,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.assets.split.start",
        use_ai=use_ai,
        script_length=len(script),
        asset_prompt_length=len(asset_prompt),
        image_models=image_models or [],
        project_params=project_params,
    )
    if not use_ai:
        raise RuntimeError("资产识别必须调用大模型，不能使用本地模板回退。")

    rendered_prompt, prompt_variables = _render_asset_prompt_template(
        asset_prompt,
        project_params,
        script,
        batch_info,
        id_range,
        existing_assets,
    )
    system_text = (
        "请严格执行用户提供的 Agent A 剧本资产台账提取提示词。"
        "调用前变量已经替换完成。输出必须是可 JSON.parse 的裸 JSON 对象，"
        "顶层必须包含 episodeIndex、overflow、assets。不得输出 Markdown、解释或分析过程。"
    )
    raw, meta = _call_asset_llm_json(
        system_text,
        {
            "asset_prompt": rendered_prompt,
            "image_prompt_models": _image_prompt_models(image_models),
            "format_notes": "只输出 Agent A 扁平资产台账 JSON：episodeIndex、overflow、assets。",
        },
        "autoflow_assets_identify",
        _agent_a_ledger_response_schema(),
    )
    log_payload(logger, "autoflow.assets.split.raw_llm", raw)

    if isinstance(raw.get("assets"), list):
        assets = _assets_from_agent_a_ledger(raw)
        story_context = _story_context_from_agent_a(project_params, script, raw)
    else:
        assets = _normalize_asset_identities(raw)
        story_context = raw.get("story_context") if isinstance(raw.get("story_context"), dict) else {}
    result = {
        "assets": assets,
        "story_context": story_context,
        "asset_ledger": raw if isinstance(raw.get("assets"), list) else None,
        "prompt_variables": {
            "batchInfo": prompt_variables["batchInfo"],
            "idRange": prompt_variables["idRange"],
            "existingAssets": prompt_variables["existingAssets"],
        },
        "llm": meta,
        "contract": "agent_a_asset_ledger_v2_compat",
    }
    log_event(
        logger,
        "autoflow.assets.split.normalized",
        character_count=len(assets["characters"]),
        scene_count=len(assets["scenes"]),
        item_count=len(assets["items"]),
        story_context_keys=list(story_context.keys()),
        llm=meta,
    )
    _save_step_result(AUTOFLOW_ASSET_IDENTIFY_RESULT_PATH, result, "autoflow.assets.identify.saved")
    _save_asset_split_result(result)
    log_payload(logger, "autoflow.assets.split.result", result)
    return result


def generate_asset_prompts(
    project_params: dict[str, Any],
    script: str,
    assets: dict[str, Any],
    asset_ledger: dict[str, Any] | None,
    story_context: dict[str, Any],
    prompt_instruction: str,
    image_models: list[str] | None,
    use_ai: bool,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.assets.prompts.start",
        use_ai=use_ai,
        script_length=len(script),
        prompt_instruction_length=len(prompt_instruction),
        image_models=image_models or [],
        project_params=project_params,
    )
    if not use_ai:
        raise RuntimeError("资产提示词生成必须调用大模型，不能使用本地模板回退。")
    asset_identities = _normalize_asset_identities(assets)
    asset_rows = _agent_b_asset_rows(asset_ledger, assets, story_context)
    rendered_prompt, prompt_variables = _render_asset_generation_prompt_template(
        prompt_instruction,
        project_params,
        script,
        asset_rows,
        story_context,
    )
    system_text = (
        "请严格执行用户提供的 Agent B 资产生图提示词模板。"
        "调用前变量已经替换完成。输出必须是可 JSON.parse 的裸 JSON 对象，顶层只包含 assets。"
        "不得合并、拆分、增删资产行，不得输出 Markdown、解释或分析过程。"
    )
    raw, meta = _call_asset_llm_json(
        system_text,
        {
            "prompt_instruction": rendered_prompt,
            "image_prompt_models": _image_prompt_models(image_models),
            "format_notes": "只输出 Agent B JSON：assets 数组；tier=1 且非 prop 用 prompts，其余用 prompt。",
        },
        "autoflow_asset_prompts",
        _agent_b_prompt_response_schema(),
    )
    log_payload(logger, "autoflow.assets.prompts.raw_llm", raw)

    if isinstance(raw.get("assets"), list):
        prompted_assets = _normalize_agent_b_prompt_assets(raw, asset_identities)
    else:
        prompted_assets = _normalize_assets(raw, image_models)
    merged_context = copy.deepcopy(story_context)
    if isinstance(raw.get("story_context"), dict):
        merged_context.update(raw["story_context"])
    result = {
        "assets": prompted_assets,
        "story_context": merged_context,
        "asset_prompt_result": raw if isinstance(raw.get("assets"), list) else None,
        "prompt_variables": {
            "assetRows": prompt_variables["assetRows"],
            "stylePrompt": prompt_variables["stylePrompt"],
        },
        "llm": meta,
        "contract": "agent_b_asset_prompts_v2_compat",
    }
    _save_step_result(AUTOFLOW_ASSET_PROMPT_RESULT_PATH, result, "autoflow.assets.prompts.saved")
    _save_asset_split_result(result)
    log_event(
        logger,
        "autoflow.assets.prompts.normalized",
        character_count=len(prompted_assets["characters"]),
        scene_count=len(prompted_assets["scenes"]),
        item_count=len(prompted_assets["items"]),
        llm=meta,
    )
    log_payload(logger, "autoflow.assets.prompts.result", result)
    return result


def _save_step_result(path: Path, result: dict[str, Any], event_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_path.replace(path)
    log_event(logger, event_name, path=str(path))


def _load_step_result(path: Path, *, missing_message: str, invalid_message: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(missing_message)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(invalid_message) from exc
    if not isinstance(result, dict):
        raise RuntimeError(invalid_message)
    return result


def _save_asset_split_result(result: dict[str, Any]) -> None:
    _save_step_result(AUTOFLOW_ASSET_RESULT_PATH, result, "autoflow.assets.saved")


def load_latest_asset_split_result() -> dict[str, Any]:
    result = _load_step_result(
        AUTOFLOW_ASSET_IDENTIFY_RESULT_PATH,
        missing_message="尚未保存大模型资产识别结果，请先点击“识别资产”。",
        invalid_message="保存的资产识别结果不是有效 JSON。",
    )
    if not isinstance(result, dict) or not isinstance(result.get("assets"), dict):
        raise RuntimeError("保存的资产识别结果结构无效。")
    log_event(logger, "autoflow.assets.latest.loaded", path=str(AUTOFLOW_ASSET_IDENTIFY_RESULT_PATH))
    return result


def load_latest_asset_prompt_result() -> dict[str, Any]:
    result = _load_step_result(
        AUTOFLOW_ASSET_PROMPT_RESULT_PATH,
        missing_message="尚未保存大模型资产提示词结果，请先点击“生成资产提示词”。",
        invalid_message="保存的资产提示词结果不是有效 JSON。",
    )
    if not isinstance(result.get("assets"), dict):
        raise RuntimeError("保存的资产提示词结果结构无效。")
    log_event(logger, "autoflow.assets.prompts.latest.loaded", path=str(AUTOFLOW_ASSET_PROMPT_RESULT_PATH))
    return result


def split_script_storyboard(
    project_params: dict[str, Any],
    script: str,
    assets: dict[str, Any],
    story_context: dict[str, Any],
    storyboard_prompt: str,
    use_ai: bool,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.storyboard.split.start",
        use_ai=use_ai,
        script_length=len(script),
        storyboard_prompt_length=len(storyboard_prompt),
        character_count=len((assets or {}).get("characters") or []),
        scene_count=len((assets or {}).get("scenes") or []),
        item_count=len((assets or {}).get("items") or []),
    )
    normalized_assets = _normalize_assets(assets)
    meta: dict[str, Any] = {"provider": "deterministic", "model": None}
    if use_ai:
        system_text = (
            "你是 Seedance 2.0 短剧分镜导演。请基于用户给定的资产清单和分镜提示词，"
            "只完成分镜结构组织与子镜头规划。禁止新增未在资产清单中的核心角色、场景、关键道具；"
            "每个 segment 必须包含 sub_shots，sub_shots 是后续连续拍摄/4秒拼接/独立镜头组分析的基本单位。"
            "输出需要保留 originalText、dialogues、animationPrompt、characters、scenes、items 等 ai-video 自动流兼容信息；"
            "同时规整成 segments/sub_shots 字段供后续步骤消费。必须只返回 JSON。"
        )
        try:
            raw, meta = _call_asset_llm_json(
                system_text,
                {
                    "project_params": project_params,
                    "script": script,
                    "assets": normalized_assets,
                    "story_context": story_context,
                    "storyboard_prompt": storyboard_prompt,
                    "format_notes": "只输出 story_context 和 segments；每个 segment 内必须有 sub_shots。",
                },
                "autoflow_storyboard_split",
                _storyboard_response_schema(),
                max_tokens=32000,
            )
        except Exception as exc:
            logger.exception("autoflow.storyboard.split.llm_failed fallback_reason=%s", exc)
            raise RuntimeError(f"拆分镜大模型调用失败: {exc}") from exc
    else:
        raw = _fallback_split(project_params, script)

    merged_context = story_context.copy()
    if isinstance(raw.get("story_context"), dict):
        merged_context.update(raw["story_context"])
    segments = _normalize_segments(raw.get("segments") or [])
    result = {
        "assets": normalized_assets,
        "story_context": merged_context,
        "segments": segments,
        "llm": meta,
        "contract": "ai_video_compatible_storyboard_v1",
    }
    log_event(
        logger,
        "autoflow.storyboard.split.normalized",
        segment_count=len(segments),
        sub_shot_count=sum(len(item.get("sub_shots") or []) for item in segments),
        llm=meta,
    )
    _save_step_result(AUTOFLOW_STORYBOARD_RESULT_PATH, result, "autoflow.storyboard.saved")
    log_payload(logger, "autoflow.storyboard.split.result", result)
    return result


def load_latest_storyboard_result() -> dict[str, Any]:
    result = _load_step_result(
        AUTOFLOW_STORYBOARD_RESULT_PATH,
        missing_message="尚未保存大模型拆分镜结果，请先点击“基于资产拆分镜”。",
        invalid_message="保存的拆分镜结果不是有效 JSON。",
    )
    if not isinstance(result.get("segments"), list):
        raise RuntimeError("保存的拆分镜结果结构无效。")
    log_event(logger, "autoflow.storyboard.latest.loaded", path=str(AUTOFLOW_STORYBOARD_RESULT_PATH))
    return result


def _flatten_sub_shots(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments, start=1):
        for sub_index, sub in enumerate(segment.get("sub_shots") or [], start=1):
            sub_id = str(sub.get("id") or f"c{segment_index:02d}_{sub_index:02d}")
            flattened.append(
                {
                    **copy.deepcopy(sub),
                    "id": sub_id,
                    "segment_id": segment.get("segment_id") or f"s{segment_index:03d}",
                    "duration": _to_seconds(sub.get("duration") or segment.get("duration")),
                    "scene": sub.get("scene") or segment.get("scene"),
                    "characters": _unique(list(sub.get("characters") or segment.get("characters") or [])),
                    "items": _unique(list(sub.get("items") or segment.get("items") or [])),
                    "shot_type": sub.get("shot_type") or segment.get("shot_type") or "中景",
                    "camera_movement": sub.get("camera_movement") or segment.get("camera_movement") or "固定镜头",
                    "entry_state": sub.get("entry_state") or segment.get("entry_state") or "",
                    "performance": sub.get("performance") or sub.get("content") or segment.get("performance") or "",
                    "exit_state": sub.get("exit_state") or segment.get("exit_state") or "",
                    "dialogue": sub.get("dialogue") or segment.get("dialogue") or {},
                    "transition_from_previous": segment.get("transition_from_previous") or "hard_cut",
                }
            )
    return flattened


def _needs_continuity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("indivisible") or right.get("indivisible"):
        return True
    left_text = " ".join(str(left.get(k) or "") for k in ("performance", "exit_state", "continuity_hint"))
    right_text = " ".join(str(right.get(k) or "") for k in ("entry_state", "performance", "continuity_hint"))
    continuity_tokens = ("继续", "连续", "同一动作", "不可切", "跟拍", "一镜", "转身", "走向", "冲向", "抬手", "落下")
    if any(token in left_text + right_text for token in continuity_tokens):
        return True
    return bool(set(left.get("characters") or []) & set(right.get("characters") or [])) and left.get("scene") == right.get("scene") and left.get("duration", 0) < 4


def _group_prompt(group: dict[str, Any], state: str) -> str:
    sub_shots = group.get("sub_shots") or []
    first = sub_shots[0] if sub_shots else {}
    last = sub_shots[-1] if sub_shots else {}
    base = first if state == "entry" else last
    label = "首帧" if state == "entry" else "尾帧"
    characters = "、".join(_unique([c for sub in sub_shots for c in sub.get("characters", [])])) or "主体"
    items = "、".join(_unique([p for sub in sub_shots for p in sub.get("items", [])]))
    state_text = base.get("entry_state") if state == "entry" else base.get("exit_state")
    return (
        f"{label}普通参考图，9:16短剧画面。场景：{base.get('scene') or group.get('scene_asset') or '主场景'}；"
        f"人物：{characters}；"
        f"{'物品：' + items + '；' if items else ''}"
        f"状态：{state_text or base.get('performance') or '保持当前剧情动作状态'}；"
        "要求构图清晰、身份稳定、可作为后续视频生成的普通图片参考。"
    )


def _finalize_group(items: list[dict[str, Any]], index: int, group_type: str, reason: str) -> dict[str, Any]:
    duration = sum(_to_seconds(item.get("duration")) for item in items)
    group = {
        "group_id": f"g{index:03d}",
        "group_type": group_type,
        "source_segment_ids": _unique([item.get("segment_id") for item in items]),
        "sub_shot_ids": _unique([item.get("id") for item in items]),
        "duration": duration,
        "reason": reason,
        "scene_asset": str(items[0].get("scene") or "主场景"),
        "sub_shots": copy.deepcopy(items),
    }
    group["entry_prompt_zh"] = _group_prompt(group, "entry")
    group["exit_prompt_zh"] = _group_prompt(group, "exit")
    return group


def _fallback_analyze(segments: list[dict[str, Any]]) -> dict[str, Any]:
    subs = _flatten_sub_shots(segments)
    groups: list[dict[str, Any]] = []
    index = 1
    cursor = 0
    while cursor < len(subs):
        current = subs[cursor]
        bucket = [current]
        duration = _to_seconds(current.get("duration"))
        group_type = "independent" if duration >= 4 else "min_duration_pack"
        reason = "单个子镜头已满足最小 4 秒，可以独立拍摄。" if duration >= 4 else "单个子镜头不足 4 秒，按最小时长规则向后拼接。"
        while cursor + len(bucket) < len(subs):
            nxt = subs[cursor + len(bucket)]
            if _needs_continuity(bucket[-1], nxt):
                group_type = "continuous_take"
                reason = "相邻子镜头存在动作/空间/人物连续性，作为不可分割连续拍摄镜头组。"
                bucket.append(nxt)
                duration += _to_seconds(nxt.get("duration"))
                continue
            if duration < 4:
                group_type = "min_duration_pack"
                reason = "前段累计不足 4 秒，向后拼接形成可生成镜头组。"
                bucket.append(nxt)
                duration += _to_seconds(nxt.get("duration"))
                continue
            break
        groups.append(_finalize_group(bucket, index, group_type, reason))
        cursor += len(bucket)
        index += 1
    return {"summary": f"共分析 {len(subs)} 个子镜头，形成 {len(groups)} 个镜头组。", "shot_groups": groups}


def analyze_shot_groups(
    project_params: dict[str, Any],
    assets: dict[str, Any],
    story_context: dict[str, Any],
    segments: list[dict[str, Any]],
    analysis_prompt: str,
    use_ai: bool,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.analyze_shot_groups.start",
        use_ai=use_ai,
        segment_count=len(segments),
        analysis_prompt_length=len(analysis_prompt),
    )
    normalized_segments = _normalize_segments(segments)
    fallback = _fallback_analyze(normalized_segments)
    meta: dict[str, Any] = {"provider": "deterministic", "model": None}
    raw_groups = fallback
    if use_ai:
        system_text = (
            "你是短剧镜头组分析助手。你的任务是判断哪些子镜头必须连续拍摄不可分割，"
            "哪些因不足最小4秒需要向后拼接，哪些可以独立成为镜头组。"
            "只返回 JSON，不得改写剧情顺序。"
        )
        try:
            raw_groups, meta = _call_asset_llm_json(
                system_text,
                {
                    "project_params": project_params,
                    "assets": assets,
                    "story_context": story_context,
                    "segments": normalized_segments,
                    "analysis_prompt": analysis_prompt,
                    "deterministic_baseline": fallback,
                },
                "autoflow_shot_group_analysis",
                _analysis_response_schema(),
                max_tokens=24000,
            )
        except Exception as exc:
            meta = {"provider": "deterministic_fallback", "model": None, "fallback_reason": str(exc)}
            logger.exception("autoflow.analyze_shot_groups.llm_failed fallback_reason=%s", exc)
            raw_groups = fallback

    by_sub_id = {str(item.get("id")): item for item in _flatten_sub_shots(normalized_segments)}
    groups: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_groups.get("shot_groups") or [], start=1):
        ids = [str(x) for x in raw.get("sub_shot_ids") or []]
        items = [by_sub_id[x] for x in ids if x in by_sub_id]
        if not items:
            continue
        group = _finalize_group(
            items,
            index,
            str(raw.get("group_type") or "independent"),
            str(raw.get("reason") or "模型分析结果"),
        )
        if raw.get("entry_prompt_zh"):
            group["entry_prompt_zh"] = str(raw["entry_prompt_zh"])
        if raw.get("exit_prompt_zh"):
            group["exit_prompt_zh"] = str(raw["exit_prompt_zh"])
        groups.append(group)
    if not groups:
        groups = fallback["shot_groups"]
    result = {
        "assets": _normalize_assets(assets),
        "story_context": story_context,
        "segments": normalized_segments,
        "summary": raw_groups.get("summary") or fallback["summary"],
        "shot_groups": groups,
        "llm": meta,
    }
    log_event(
        logger,
        "autoflow.analyze_shot_groups.result_summary",
        group_count=len(groups),
        llm=meta,
    )
    _save_step_result(AUTOFLOW_ANALYSIS_RESULT_PATH, result, "autoflow.analysis.saved")
    log_payload(logger, "autoflow.analyze_shot_groups.result", result)
    return result


def load_latest_analysis_result() -> dict[str, Any]:
    result = _load_step_result(
        AUTOFLOW_ANALYSIS_RESULT_PATH,
        missing_message="尚未保存大模型镜头组分析结果，请先点击“提交分析”。",
        invalid_message="保存的镜头组分析结果不是有效 JSON。",
    )
    if not isinstance(result.get("shot_groups"), list):
        raise RuntimeError("保存的镜头组分析结果结构无效。")
    log_event(logger, "autoflow.analysis.latest.loaded", path=str(AUTOFLOW_ANALYSIS_RESULT_PATH))
    return result


def _load_script_module(name: str) -> ModuleType:
    if name in _SCRIPT_MODULE_CACHE:
        return _SCRIPT_MODULE_CACHE[name]
    scripts_dir = settings.pipeline_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    path = scripts_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载流水线脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SCRIPT_MODULE_CACHE[name] = module
    return module


def _asset_name_to_id_maps(assets: dict[str, Any]) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {"characters": {}, "scenes": {}, "items": {}}
    normalized = _normalize_assets(assets)
    for kind, items in normalized.items():
        for item in items:
            asset_id = str(item.get("id") or "")
            if not asset_id:
                continue
            maps[kind][asset_id] = asset_id
            maps[kind][str(item.get("name") or asset_id)] = asset_id
            maps[kind][str(item.get("gid") or asset_id)] = asset_id
    return maps


def _asset_catalog(assets: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized = _normalize_assets(assets)
    return {
        "roles": [{"id": item["id"], "asset_id": item["id"], "name": item["name"]} for item in normalized["characters"]],
        "scenes": [{"id": item["id"], "asset_id": item["id"], "name": item["name"]} for item in normalized["scenes"]],
        "props": [{"id": item["id"], "asset_id": item["id"], "name": item["name"]} for item in normalized["items"]],
    }


def _reference_assets(scene_id: str, role_ids: list[str], prop_ids: list[str]) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    if scene_id:
        images.append({"asset_id": scene_id, "asset_type": "scene", "purpose": "scene_reference"})
    images.extend({"asset_id": rid, "asset_type": "role", "purpose": "character_reference"} for rid in role_ids)
    images.extend({"asset_id": pid, "asset_type": "prop", "purpose": "prop_reference"} for pid in prop_ids)
    return {"required": {"images": images}, "optional": {"images": []}}


def _requirements_for_group(group: dict[str, Any]) -> dict[str, str]:
    text = json.dumps(group, ensure_ascii=False)
    req = {key: "low" for key in ROUTING_DIMENSIONS}
    req["identity_consistency"] = "high"
    req["temporal_continuity"] = "high" if group.get("group_type") == "continuous_take" else "medium"
    if any(token in text for token in ("台词", "说", "喊", "问", "答")):
        req["dialogue_lipsync"] = "high"
        req["acting_precision"] = "high"
    if any(token in text for token in ("打", "冲", "飞", "跑", "挥", "跌", "追")):
        req["motion_action"] = "high"
        req["camera_control"] = "medium"
    if group.get("duration", 0) >= 8:
        req["temporal_continuity"] = "critical"
    return req


def _complexity_for_group(group: dict[str, Any]) -> dict[str, str]:
    count = len(_unique([c for sub in group.get("sub_shots", []) for c in sub.get("characters", [])]))
    duration = _to_seconds(group.get("duration"))
    level = "high" if count >= 3 or duration >= 8 else "medium" if count == 2 or duration >= 5 else "low"
    return {key: level for key in COMPLEXITY_FIELDS}


def _to_generation_unit(group: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    maps = _asset_name_to_id_maps(assets)
    role_ids = _unique([maps["characters"].get(str(c), str(c)) for sub in group.get("sub_shots", []) for c in sub.get("characters", [])])
    prop_ids = _unique([maps["items"].get(str(p), str(p)) for sub in group.get("sub_shots", []) for p in sub.get("items", [])])
    scene_name = str(group.get("scene_asset") or (group.get("sub_shots") or [{}])[0].get("scene") or "主场景")
    scene_id = maps["scenes"].get(scene_name, scene_name)
    cursor = 0
    timeline: list[dict[str, Any]] = []
    for index, sub in enumerate(group.get("sub_shots") or [], start=1):
        duration = _to_seconds(sub.get("duration"))
        start, end = cursor, cursor + duration
        cursor = end
        timeline.append(
            {
                "type": "atomic",
                "atomic_id": str(sub.get("id") or f"{group.get('group_id')}_c{index:02d}"),
                "start": start,
                "end": end,
                "scene_asset": scene_id,
                "narrative_class": "dialogue" if (sub.get("dialogue") or {}).get("content") else "action",
                "narrative_function": sub.get("content") or sub.get("performance") or "剧情推进",
                "camera_plan": {
                    "shot_size": sub.get("shot_type") or "中景",
                    "angle": "平视",
                    "composition": "主体清晰居中，保持短剧竖屏构图",
                    "movement": sub.get("camera_movement") or "固定镜头",
                },
                "prompt_core": {
                    "timeline_local": sub.get("performance") or sub.get("content") or "保持本镜动作",
                    "guardrail": "不新增剧本以外的角色、道具和动作。",
                },
                "asset_refs": {"roles": role_ids, "props": prop_ids},
                "reference_assets": _reference_assets(scene_id, role_ids, prop_ids),
                "continuity": {"entry": sub.get("entry_state") or "", "exit": sub.get("exit_state") or "", "los": "保持动作和视线连续"},
                "spatial_state": {
                    "screen_positions": {
                        role: {"zone": "center", "depth": "midground"} for role in role_ids
                    },
                    "entry_world_positions": {
                        role: {"position": "当前场景中景区域", "facing": "表演对象", "visibility": "visible"} for role in role_ids
                    },
                    "exit_world_positions": {
                        role: {"position": "当前场景中景区域", "facing": "表演对象", "visibility": "visible"} for role in role_ids
                    },
                },
                "scale_plan": {
                    "shot_size": sub.get("shot_type") or "中景",
                    "perspective_mode": "standard_depth",
                    "lens_style": "standard",
                    "subjects": {role: {"depth": "midground", "frame_height_ratio": 0.55} for role in role_ids},
                    "environment_relation": "人物与场景比例自然稳定",
                },
            }
        )
    group_type = str(group.get("group_type") or "independent")
    return {
        "unit_id": str(group.get("group_id") or uuid.uuid4().hex[:8]),
        "atomic_ids": [seg["atomic_id"] for seg in timeline],
        "group_ids": [str(group.get("group_id") or "")],
        "scene_asset": scene_id,
        "story_priority": "key" if group_type == "continuous_take" else "normal",
        "narrative_classes": _unique([seg["narrative_class"] for seg in timeline]),
        "narrative_functions": [seg["narrative_function"] for seg in timeline],
        "content_duration": cursor,
        "duration": cursor,
        "padding_plan": {"before": 0, "after": 0},
        "asset_refs": {"roles": role_ids, "props": prop_ids},
        "routing_requirements": _requirements_for_group(group),
        "complexity": _complexity_for_group(group),
        "continuity": {
            "entry": group.get("entry_prompt_zh") or "",
            "exit": group.get("exit_prompt_zh") or "",
            "los": str(group.get("reason") or ""),
        },
        "timeline_segments": timeline,
        "single_take": False,
        "indivisible": False,
        "independent_generation": True,
        "autoflow_group": copy.deepcopy(group),
    }


def _ensure_reference_assets(final_video_plan: dict[str, Any]) -> None:
    for shot in final_video_plan.get("shots", []) or []:
        plan = shot.get("reference_image_plan") or {}
        output_ids = plan.get("output_asset_ids") or {}
        refs = shot.setdefault("references", [])
        existing = {str(ref.get("asset_id")) for ref in refs if isinstance(ref, dict)}
        for role in ("entry", "exit"):
            asset_id = output_ids.get(role) or f"shotref::{shot.get('shot_id')}::{role}"
            if asset_id in existing:
                continue
            refs.append(
                {
                    "asset_id": asset_id,
                    "media_type": "image",
                    "asset_type": "derived_shot_reference",
                    "purpose": "style_reference",
                    "required": True,
                    "derived": True,
                    "derived_role": f"{role}_state_reference",
                }
            )


def _build_routing_analysis(routed_plan: dict[str, Any]) -> dict[str, Any]:
    shots = []
    for unit in routed_plan.get("routed_units", []) or []:
        decision = copy.deepcopy(unit.get("routing_decision") or {})
        candidates = []
        for candidate in decision.get("candidates") or []:
            compact = {
                key: value
                for key, value in candidate.items()
                if key
                in {
                    "model",
                    "preset",
                    "qualified",
                    "fit_quality",
                    "reliability",
                    "call_points",
                    "expected_usable_points",
                    "tier_score",
                    "hard_reasons",
                    "margins",
                    "request_duration",
                    "padding_seconds",
                }
            }
            compact["selected"] = candidate.get("model") == decision.get("selected_model") and candidate.get("preset") == decision.get("selected_preset")
            candidates.append(compact)
        decision["candidates"] = candidates
        shots.append(
            {
                "shot_id": unit.get("unit_id"),
                "atomic_ids": unit.get("atomic_ids", []),
                "source_group": (unit.get("autoflow_group") or {}).get("group_id"),
                "duration": unit.get("duration"),
                "routing_requirements": unit.get("routing_requirements", {}),
                "routing_decision": decision,
            }
        )
    return {
        "tier": routed_plan.get("routing_tier"),
        "target_resolution": routed_plan.get("target_resolution"),
        "routing_meta": routed_plan.get("routing_meta", {}),
        "shots": shots,
    }


def _generate_reference_for_shot(
    episode_id: str,
    shot: dict[str, Any],
    generation_mode: str,
    image_model: str | None,
) -> dict[str, Any]:
    image_plan = shot.get("reference_image_plan") or {}
    output_ids = image_plan.get("output_asset_ids") or {}
    input_ids = [str(value) for value in image_plan.get("input_asset_ids", []) if value]
    log_event(
        logger,
        "autoflow.reference.generate_shot.start",
        shot_id=shot.get("shot_id"),
        generation_mode=generation_mode,
        image_model=image_model,
        input_asset_ids=input_ids,
    )
    missing = missing_asset_ids(input_ids)
    if missing:
        result = {"shot_id": shot.get("shot_id"), "status": "blocked", "missing_asset_ids": missing}
        log_payload(logger, "autoflow.reference.generate_shot.blocked", result)
        return result
    payload = {
        "episode_id": episode_id,
        "shot_id": shot.get("shot_id"),
        "entry_prompt_zh": image_plan.get("entry_state_reference_prompt_zh") or "",
        "exit_prompt_zh": image_plan.get("exit_state_reference_edit_prompt_zh") or "",
        "entry_asset_id": output_ids.get("entry"),
        "exit_asset_id": output_ids.get("exit"),
        "continuity_source_shot_id": image_plan.get("continuity_source_shot_id"),
        "demo_case": generation_mode == "demo",
        "image_model": image_model,
        "aspect_ratio": "9:16",
    }
    if not payload["entry_prompt_zh"] or not payload["exit_prompt_zh"]:
        result = {"shot_id": shot.get("shot_id"), "status": "blocked", "detail": "缺少首帧或尾帧提示词"}
        log_payload(logger, "autoflow.reference.generate_shot.blocked", result)
        return result
    if generation_mode == "provider":
        manifest = create_reference_image_pair_provider_job(payload, asset_reference_data_urls(input_ids))
    else:
        manifest = create_reference_image_pair_job(payload)
    manifest["input_asset_ids"] = input_ids
    manifest["registry"] = register_reference_pair(manifest)
    log_payload(logger, "autoflow.reference.generate_shot.result", manifest)
    return manifest


def route_and_generate_references(
    project_params: dict[str, Any],
    assets: dict[str, Any],
    story_context: dict[str, Any],
    shot_groups: list[dict[str, Any]],
    generation_mode: str,
    image_model: str | None,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.route_and_generate_refs.start",
        shot_group_count=len(shot_groups),
        generation_mode=generation_mode,
        image_model=image_model,
        project_params=project_params,
    )
    video_router = _load_script_module("video_router")
    prompt_compiler = _load_script_module("prompt_compiler")
    registry, policy, config_source = video_router.load_config(str(settings.model_registry_path))
    doc = {
        "routing_tier": str(project_params.get("routing_tier") or "medium"),
        "aspect_ratio": str(project_params.get("aspect_ratio") or "9:16"),
        "scene_contexts": [
            {
                "scene_asset": scene.get("id"),
                "state": scene.get("description") or scene.get("name"),
                "lighting": "统一短剧光影",
                "style_lock": story_context.get("visual_style") or project_params.get("global_visual_lock") or "",
                "spatial_bible": {},
            }
            for scene in _normalize_assets(assets)["scenes"]
        ],
        "generation_units": [_to_generation_unit(group, assets) for group in shot_groups],
    }
    catalog = _asset_catalog(assets)
    routed_plan = video_router.route_document(
        doc,
        registry,
        policy,
        str(project_params.get("routing_tier") or "medium"),
        str(project_params.get("resolution") or "720P"),
        config_source,
        catalog,
        "autoflow_assets",
    )
    final_video_plan = prompt_compiler.compile_document(routed_plan, "hard_cut", True)
    _ensure_reference_assets(final_video_plan)
    references: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    episode_id = str(project_params.get("episode_id") or "EP001")
    max_workers = min(4, max(1, len(final_video_plan.get("shots", []) or [])))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_generate_reference_for_shot, episode_id, shot, generation_mode, image_model)
            for shot in final_video_plan.get("shots", []) or []
        ]
        for future in as_completed(futures):
            result = future.result()
            if result.get("status") == "blocked":
                blocked.append(result)
            else:
                references.append(result)
    result = {
        "routing_analysis": _build_routing_analysis(routed_plan),
        "final_video_plan": final_video_plan,
        "reference_generation": {
            "completed_count": len(references),
            "blocked_count": len(blocked),
            "completed": references,
            "blocked": blocked,
            "generation_mode": generation_mode,
        },
    }
    log_event(
        logger,
        "autoflow.route_and_generate_refs.result_summary",
        shot_count=len(final_video_plan.get("shots", []) or []),
        completed_count=len(references),
        blocked_count=len(blocked),
    )
    log_payload(logger, "autoflow.route_and_generate_refs.result", result)
    return result


def submit_autoflow_video_jobs(final_video_plan: dict[str, Any]) -> dict[str, Any]:
    return submit_video_jobs(final_video_plan)
