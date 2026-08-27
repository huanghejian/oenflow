from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import time
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
    create_reference_image_pair_xingtu_job,
)
from .workflow_service import (
    asset_reference_data_urls,
    missing_asset_ids,
    register_reference_pair,
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
AUTOFLOW_ROUTE_RESULT_PATH = settings.work_root / "autoflow_routing" / "latest.json"
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
            "group_type": {
                "type": "string",
                "enum": ["continuous_take", "min_duration_pack", "independent"],
            },
            "sub_shot_ids": _array_schema(_string_schema()),
            "reason": _string_schema(),
        },
        ["group_id", "group_type", "sub_shot_ids", "reason"],
    )
    return _object_schema(
        {
            "summary": _string_schema(),
            "shot_groups": _array_schema(group),
        },
        ["summary", "shot_groups"],
    )


def _routing_difficulty_response_schema() -> dict[str, Any]:
    requirement_level = {"type": "string", "enum": ["low", "medium", "high", "critical"]}
    complexity_level = {"type": "string", "enum": ["low", "medium", "high"]}
    score = {"type": "integer", "minimum": 0, "maximum": 100}
    sub_shot_score = _object_schema(
        {
            "sub_shot_id": _string_schema(),
            "difficulty_score": copy.deepcopy(score),
            "overall_difficulty": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "dimension_scores": _object_schema(
                {key: copy.deepcopy(score) for key in ROUTING_DIMENSIONS},
                ROUTING_DIMENSIONS,
            ),
            "reason": _string_schema(),
            "risks": _array_schema(_string_schema()),
        },
        [
            "sub_shot_id",
            "difficulty_score",
            "overall_difficulty",
            "dimension_scores",
            "reason",
            "risks",
        ],
    )
    shot = _object_schema(
        {
            "group_id": _string_schema(),
            "story_priority": {"type": "string", "enum": ["normal", "key", "climax"]},
            "difficulty_score": copy.deepcopy(score),
            "overall_difficulty": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "routing_requirements": _object_schema(
                {key: copy.deepcopy(requirement_level) for key in ROUTING_DIMENSIONS},
                ROUTING_DIMENSIONS,
            ),
            "complexity": _object_schema(
                {key: copy.deepcopy(complexity_level) for key in COMPLEXITY_FIELDS},
                COMPLEXITY_FIELDS,
            ),
            "reason": _string_schema(),
            "risks": _array_schema(_string_schema()),
            "sub_shot_scores": _array_schema(sub_shot_score),
        },
        [
            "group_id",
            "story_priority",
            "difficulty_score",
            "overall_difficulty",
            "routing_requirements",
            "complexity",
            "reason",
            "risks",
            "sub_shot_scores",
        ],
    )
    return _object_schema(
        {
            "summary": _string_schema(),
            "shots": _array_schema(shot),
        },
        ["summary", "shots"],
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
    use_network_proxy: bool = False,
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
    if use_network_proxy and not settings.claude_http_proxy_url:
        raise RuntimeError(
            "已选择网络代理，但后端未配置 CLAUDE_HTTP_PROXY_URL。"
        )

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
        response_data, response_id, transient_retries = _post_claude_autoflow_with_retry(
            _bedrock_converse_url(
                settings.claude_converse_url,
                settings.claude_director_model,
                settings.claude_region,
            ),
            request_body,
            f"Bearer {settings.claude_converse_api_key}",
            proxy_url=(
                settings.claude_http_proxy_url if use_network_proxy else None
            ),
            force_direct=not use_network_proxy,
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
        "network_mode": "proxy" if use_network_proxy else "direct",
        "model": settings.claude_director_model,
        "transient_retries": transient_retries,
        "usage": response_data.get("usage") if isinstance(response_data, dict) else None,
        "stop_reason": response_data.get("stopReason") if isinstance(response_data, dict) else None,
    }
    log_payload(
        logger,
        "llm.claude_converse.parsed_response",
        {"schema_name": schema_name, "meta": meta, "parsed": parsed},
    )
    return parsed, meta


CLAUDE_TRANSIENT_RETRY_DELAYS_SECONDS = (2.0, 6.0)


def _is_transient_claude_failure(exc: Exception) -> bool:
    if isinstance(exc, LongTimeHttpError):
        if exc.status_code in {502, 503, 504}:
            return True
        body = str(exc.body or "").lower()
        if exc.status_code == 500 and any(
            marker in body
            for marker in (
                "bedrock api 返回 503",
                "bedrock is unable to process your request",
                'bedrock api 调用失败: bedrock api 返回 503',
                '\\"statuscode\\":503',
            )
        ):
            return True
        return False
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "server disconnected without sending a response",
            "longtimehttp 连接失败",
            "connection reset by peer",
        )
    )


def _post_claude_autoflow_with_retry(
    url: str,
    payload: dict[str, Any],
    token: str,
    *,
    proxy_url: str | None,
    force_direct: bool,
    post_func: Any = post_json,
    sleep_func: Any = time.sleep,
) -> tuple[dict[str, Any], str | None, int]:
    attempts = len(CLAUDE_TRANSIENT_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            data, response_id = post_func(
                url,
                payload,
                token,
                {"x-request-id": uuid.uuid4().hex},
                proxy_url=proxy_url,
                force_direct=force_direct,
            )
            return data, response_id, attempt
        except (LongTimeHttpError, RuntimeError) as exc:
            if not _is_transient_claude_failure(exc):
                raise
            if attempt >= attempts - 1:
                raise RuntimeError(
                    f"Claude/Bedrock 服务暂时繁忙，已自动重试 {attempts} 次仍失败；"
                    "请稍后再试，或在页面切换直连/网络代理后重试当前环节。"
                ) from exc
            delay = CLAUDE_TRANSIENT_RETRY_DELAYS_SECONDS[attempt]
            log_event(
                logger,
                "llm.claude_converse.transient_retry",
                attempt=attempt + 1,
                next_attempt=attempt + 2,
                delay_seconds=delay,
                status_code=(exc.status_code if isinstance(exc, LongTimeHttpError) else None),
                reason=str(exc)[:500],
            )
            sleep_func(delay)
    raise RuntimeError("Claude/Bedrock 短暂错误重试流程异常结束。")


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
                # An omitted boundary is unknown and must be judged by the
                # shot-group analyzer; it is not automatically a hard cut.
                "transition_from_previous": str(data.get("transition_from_previous") or ("scene_start" if index == 1 else "")),
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
    use_network_proxy: bool = False,
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
            use_network_proxy,
        )
    )
    storyboard_result = split_script_storyboard(
        project_params,
        script,
        asset_result["assets"],
        asset_result.get("story_context") or {},
        storyboard_prompt or split_prompt,
        use_ai,
        use_network_proxy,
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
    use_network_proxy: bool = False,
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
        use_network_proxy=use_network_proxy,
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
    use_network_proxy: bool = False,
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
        use_network_proxy=use_network_proxy,
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


def _asset_matches(item: Any, asset_id: str) -> bool:
    return isinstance(item, dict) and asset_id in {
        str(item.get("id") or ""),
        str(item.get("gid") or ""),
        str(item.get("asset_id") or ""),
    }


def _apply_asset_binding(item: dict[str, Any], binding: dict[str, Any]) -> None:
    for key in (
        "url",
        "image_url",
        "public_url",
        "s3_key",
        "file_id",
        "mime_type",
        "size_bytes",
        "original_filename",
        "source",
    ):
        if binding.get(key) is not None:
            item[key] = binding[key]


def _sync_asset_container(container: Any, asset_id: str, binding: dict[str, Any]) -> bool:
    updated = False
    if isinstance(container, dict):
        assets = container.get("assets")
        if isinstance(assets, dict):
            for key in ("characters", "scenes", "items"):
                items = assets.get(key)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if _asset_matches(item, asset_id):
                        _apply_asset_binding(item, binding)
                        updated = True
        elif isinstance(assets, list):
            for item in assets:
                if _asset_matches(item, asset_id):
                    _apply_asset_binding(item, binding)
                    updated = True
        raw_prompt_result = container.get("asset_prompt_result")
        if isinstance(raw_prompt_result, dict):
            updated = _sync_asset_container(raw_prompt_result, asset_id, binding) or updated
    elif isinstance(container, list):
        for item in container:
            if _asset_matches(item, asset_id):
                _apply_asset_binding(item, binding)
                updated = True
    return updated


def sync_uploaded_asset_reference(asset_id: str, binding: dict[str, Any]) -> dict[str, Any]:
    updated_files: list[str] = []
    for path in (
        AUTOFLOW_ASSET_RESULT_PATH,
        AUTOFLOW_ASSET_IDENTIFY_RESULT_PATH,
        AUTOFLOW_ASSET_PROMPT_RESULT_PATH,
    ):
        if not path.is_file():
            continue
        result = _load_step_result(
            path,
            missing_message="资产数据文件不存在。",
            invalid_message=f"资产数据文件无效：{path}",
        )
        if _sync_asset_container(result, asset_id, binding):
            _save_step_result(path, result, "autoflow.assets.upload.synced")
            updated_files.append(str(path))
    return {"updated_files": updated_files}


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
    use_network_proxy: bool = False,
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
            "每个 segment 必须包含 sub_shots，sub_shots 是后续判断连续拍摄与真实切镜边界的基本单位。"
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
                max_tokens=64000,
                use_network_proxy=use_network_proxy,
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
                    "transition_from_previous": (
                        sub.get("transition_from_previous")
                        or sub.get("cut_in")
                        or (
                            segment.get("transition_from_previous")
                            if sub_index == 1
                            else ""
                        )
                    ),
                }
            )
    return flattened


HARD_CUT_MARKERS = {
    "hard_cut",
    "match_cut_action",
    "match_cut_shape",
    "concealed_cut",
    "fade",
    "emotional_cut",
    "empty_shot",
    "scene_start",
    "scene_end",
    "reaction_cut",
    "reverse_shot",
    "pov_cut",
    "camera_cut",
}
CONTINUOUS_MARKERS = {"continuous", "no_cut", "same_take", "single_take"}


def _boundary_marker(right: dict[str, Any]) -> str:
    return str(
        right.get("transition_from_previous") or right.get("cut_in") or ""
    ).strip().lower()


def _is_hard_cut_boundary(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("scene") or "") != str(right.get("scene") or ""):
        return True
    marker = _boundary_marker(right)
    if marker in HARD_CUT_MARKERS:
        return True
    if marker in CONTINUOUS_MARKERS:
        return False
    return any(
        token in marker
        for token in ("硬切", "切镜", "反打", "机位切换", "视点切换", "匹配切", "隐藏切", "淡入", "淡出", "转场")
    )


def _needs_continuity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    # indivisible only protects the inside of one sub-shot. It does not mean
    # that the boundary to its neighbor must be removed.
    if _is_hard_cut_boundary(left, right):
        return False
    if _boundary_marker(right) in CONTINUOUS_MARKERS:
        return True
    if left.get("continuous_with_next") or right.get("continuous_from_previous"):
        return True
    left_text = " ".join(str(left.get(k) or "") for k in ("performance", "exit_state", "continuity_hint"))
    right_text = " ".join(str(right.get(k) or "") for k in ("entry_state", "performance", "continuity_hint"))
    continuity_tokens = (
        "继续",
        "接着",
        "紧接",
        "随即",
        "动作延续",
        "无切镜",
        "连续运镜",
        "同一长镜头",
        "一镜到底",
        "镜头继续",
        "承接同一动作",
        "动作尚未完成",
        "动作未完成",
        "不可在此切",
        "必须连续拍摄",
    )
    return any(token in left_text + right_text for token in continuity_tokens)


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
    buckets: list[list[dict[str, Any]]] = []
    for sub in subs:
        if buckets and _needs_continuity(buckets[-1][-1], sub):
            buckets[-1].append(sub)
        else:
            buckets.append([sub])

    def bucket_duration(bucket: list[dict[str, Any]]) -> float:
        return sum(_to_seconds(item.get("duration")) for item in bucket)

    # Enforce the user's minimum generation-unit rule. A short unit first
    # prefers a genuinely continuous neighbor; otherwise it is explicitly
    # packaged across the nearest edit boundary as min_duration_pack.
    while len(buckets) > 1:
        short_index = next(
            (index for index, bucket in enumerate(buckets) if bucket_duration(bucket) < 4),
            None,
        )
        if short_index is None:
            break
        options: list[tuple[int, int, int]] = []
        if short_index > 0:
            left = buckets[short_index - 1]
            current = buckets[short_index]
            continuity = int(_needs_continuity(left[-1], current[0]))
            same_scene = int(str(left[-1].get("scene") or "") == str(current[0].get("scene") or ""))
            options.append((continuity * 2 + same_scene, 0, short_index - 1))
        if short_index + 1 < len(buckets):
            current = buckets[short_index]
            right = buckets[short_index + 1]
            continuity = int(_needs_continuity(current[-1], right[0]))
            same_scene = int(str(current[-1].get("scene") or "") == str(right[0].get("scene") or ""))
            options.append((continuity * 2 + same_scene, 1, short_index + 1))
        _, _, neighbor_index = max(options)
        if neighbor_index < short_index:
            buckets[neighbor_index].extend(buckets[short_index])
            buckets.pop(short_index)
        else:
            buckets[short_index].extend(buckets[neighbor_index])
            buckets.pop(neighbor_index)

    groups: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets, start=1):
        duration = bucket_duration(bucket)
        continuous = len(bucket) > 1 and all(
            _needs_continuity(left, right) for left, right in zip(bucket, bucket[1:])
        )
        if continuous:
            group_type = "continuous_take"
            reason = (
                "相邻小镜头属于同一段连续表演，动作、机位与主体状态能够直接承接；"
                f"镜头组总时长 {duration:g} 秒。"
            )
        elif len(bucket) > 1:
            group_type = "min_duration_pack"
            reason = (
                "组内并非全部属于同一段连续表演，但不足 4 秒的小镜头不能独立输出，"
                f"已按剧情顺序与相邻镜头打包；组内保留真实切镜，总时长 {duration:g} 秒。"
            )
        elif duration >= 4:
            group_type = "independent"
            reason = f"单个小镜头时长 {duration:g} 秒，已达到 4 秒，可以独立生成。"
        else:
            group_type = "independent"
            reason = f"整份输入仅有该镜头且总时长 {duration:g} 秒，没有其他相邻镜头可供合并。"
        groups.append(_finalize_group(bucket, index, group_type, reason))
    return {"summary": f"共分析 {len(subs)} 个子镜头，形成 {len(groups)} 个镜头组。", "shot_groups": groups}


def _merge_short_analysis_groups(
    raw_groups: dict[str, Any], subs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Preserve the model's semantic groups while enforcing the 4-second floor."""
    result = copy.deepcopy(raw_groups)
    groups = [group for group in result.get("shot_groups") or [] if isinstance(group, dict)]
    by_id = {str(item.get("id")): item for item in subs}

    def group_items(group: dict[str, Any]) -> list[dict[str, Any]]:
        return [by_id[str(sub_id)] for sub_id in group.get("sub_shot_ids") or [] if str(sub_id) in by_id]

    def group_duration(group: dict[str, Any]) -> float:
        return sum(_to_seconds(item.get("duration")) for item in group_items(group))

    while len(groups) > 1:
        short_index = next(
            (index for index, group in enumerate(groups) if group_duration(group) < 4),
            None,
        )
        if short_index is None:
            break
        options: list[tuple[int, int, int]] = []
        current_items = group_items(groups[short_index])
        if short_index > 0:
            neighbor_items = group_items(groups[short_index - 1])
            continuity = int(bool(neighbor_items and current_items) and _needs_continuity(neighbor_items[-1], current_items[0]))
            same_scene = int(bool(neighbor_items and current_items) and str(neighbor_items[-1].get("scene") or "") == str(current_items[0].get("scene") or ""))
            options.append((continuity * 2 + same_scene, 0, short_index - 1))
        if short_index + 1 < len(groups):
            neighbor_items = group_items(groups[short_index + 1])
            continuity = int(bool(neighbor_items and current_items) and _needs_continuity(current_items[-1], neighbor_items[0]))
            same_scene = int(bool(neighbor_items and current_items) and str(current_items[-1].get("scene") or "") == str(neighbor_items[0].get("scene") or ""))
            options.append((continuity * 2 + same_scene, 1, short_index + 1))
        _, _, neighbor_index = max(options)
        left_index, right_index = sorted((short_index, neighbor_index))
        left_group, right_group = groups[left_index], groups[right_index]
        left_items, right_items = group_items(left_group), group_items(right_group)
        boundary_continuous = bool(left_items and right_items) and _needs_continuity(left_items[-1], right_items[0])
        merged_type = (
            "continuous_take"
            if boundary_continuous
            and left_group.get("group_type") != "min_duration_pack"
            and right_group.get("group_type") != "min_duration_pack"
            else "min_duration_pack"
        )
        merged_ids = [
            str(sub_id)
            for group in (left_group, right_group)
            for sub_id in group.get("sub_shot_ids") or []
        ]
        merged_duration = sum(
            _to_seconds(by_id[sub_id].get("duration"))
            for sub_id in merged_ids
            if sub_id in by_id
        )
        merged_reason = (
            f"不足 4 秒的镜头组已与相邻同一段连续表演合并，总时长 {merged_duration:g} 秒。"
            if merged_type == "continuous_take"
            else f"不足 4 秒的镜头组已按剧情顺序与相邻镜头打包，组内保留真实切镜，总时长 {merged_duration:g} 秒。"
        )
        groups[left_index] = {
            "group_id": left_group.get("group_id"),
            "group_type": merged_type,
            "sub_shot_ids": merged_ids,
            "reason": merged_reason,
        }
        groups.pop(right_index)

    for index, group in enumerate(groups, start=1):
        group["group_id"] = f"g{index:03d}"
    result["shot_groups"] = groups
    result["summary"] = f"共分析 {len(subs)} 个子镜头，按 4 秒最小时长形成 {len(groups)} 个镜头组。"
    return result


def _validate_group_partition(raw_groups: dict[str, Any], subs: list[dict[str, Any]]) -> None:
    """Ensure the model returns one ordered, lossless partition of the sub-shots."""
    expected_ids = [str(item.get("id")) for item in subs]
    position_by_id = {sub_id: index for index, sub_id in enumerate(expected_ids)}
    returned_ids: list[str] = []
    total_duration = sum(_to_seconds(item.get("duration")) for item in subs)
    groups = raw_groups.get("shot_groups")
    if not isinstance(groups, list) or not groups:
        raise RuntimeError("镜头组分析结果未返回 shot_groups。")

    for group_index, raw_group in enumerate(groups, start=1):
        ids = [str(item) for item in raw_group.get("sub_shot_ids") or []]
        group_type = str(raw_group.get("group_type") or "")
        if not ids:
            raise RuntimeError(f"第 {group_index} 个镜头组没有子镜头。")
        unknown_ids = [sub_id for sub_id in ids if sub_id not in position_by_id]
        if unknown_ids:
            raise RuntimeError(f"镜头组包含未知子镜头：{unknown_ids}")
        positions = [position_by_id[sub_id] for sub_id in ids]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise RuntimeError(f"镜头组 {ids} 不是原始顺序中的相邻子镜头。")
        for left_position, right_position in zip(positions, positions[1:]):
            if group_type != "min_duration_pack" and _is_hard_cut_boundary(subs[left_position], subs[right_position]):
                raise RuntimeError(
                    f"镜头组跨越了真实切镜边界：{expected_ids[left_position]} -> {expected_ids[right_position]}"
                )
        group_duration = sum(_to_seconds(subs[position].get("duration")) for position in positions)
        if total_duration >= 4 and group_duration < 4:
            raise RuntimeError(
                f"镜头组 {ids} 总时长仅 {group_duration:g} 秒；不足 4 秒的镜头组必须与相邻镜头合并。"
            )
        returned_ids.extend(ids)

    if returned_ids != expected_ids:
        missing_ids = [sub_id for sub_id in expected_ids if sub_id not in returned_ids]
        duplicate_ids = sorted(
            sub_id for sub_id in set(returned_ids) if returned_ids.count(sub_id) > 1
        )
        raise RuntimeError(
            "镜头组必须按原顺序完整覆盖全部子镜头："
            f"缺失={missing_ids or '无'}，重复={duplicate_ids or '无'}"
        )


def _materialize_analysis_groups(
    raw_groups: dict[str, Any], ordered_sub_shots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_sub_id = {str(item.get("id")): item for item in ordered_sub_shots}
    groups: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_groups.get("shot_groups") or [], start=1):
        ids = [str(value) for value in raw.get("sub_shot_ids") or []]
        items = [by_sub_id[sub_id] for sub_id in ids if sub_id in by_sub_id]
        if not items:
            continue
        raw_group_type = str(raw.get("group_type") or "")
        group_type = (
            "independent"
            if len(items) == 1
            else "min_duration_pack"
            if raw_group_type == "min_duration_pack"
            else "continuous_take"
        )
        group = _finalize_group(
            items,
            index,
            group_type,
            str(raw.get("reason") or "模型分析结果"),
        )
        if raw.get("entry_prompt_zh"):
            group["entry_prompt_zh"] = str(raw["entry_prompt_zh"])
        if raw.get("exit_prompt_zh"):
            group["exit_prompt_zh"] = str(raw["exit_prompt_zh"])
        groups.append(group)
    return groups


def analyze_shot_groups(
    project_params: dict[str, Any],
    assets: dict[str, Any],
    story_context: dict[str, Any],
    segments: list[dict[str, Any]],
    analysis_prompt: str,
    reanalysis_prompt: str | None,
    previous_analysis: dict[str, Any] | None,
    use_ai: bool,
    use_network_proxy: bool = False,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.analyze_shot_groups.start",
        use_ai=use_ai,
        segment_count=len(segments),
        analysis_prompt_length=len(analysis_prompt),
        reanalysis_prompt_length=len(reanalysis_prompt or ""),
        has_previous_analysis=bool(previous_analysis),
    )
    normalized_segments = _normalize_segments(segments)
    ordered_sub_shots = _flatten_sub_shots(normalized_segments)
    fallback = _fallback_analyze(normalized_segments)
    meta: dict[str, Any] = {"provider": "deterministic", "model": None}
    raw_groups = fallback
    if use_ai:
        system_text = (
            "你是短剧视频镜头组分析器。ordered_sub_shots 中的小镜头已经是最小分割单元，禁止继续拆解；"
            "必须阅读每个小镜头的完整内容、时长、动作、机位、视点、场景、人物及进出状态后再分组。"
            "核心判断是相邻小镜头是否属于同一段连续表演：动作、台词、呼吸、视线、情绪、行为意图和身体状态是否自然延续，"
            "演员是否无需停下、复位、改变表演目标或重新起拍。景别或运镜名称变化不等于真实切镜；"
            "只要摄影机能通过连续推拉、摇移、跟拍或变焦完成画面变化，就仍应按连续表演合并。"
            "同一动作的准备、发生、结果，以及一句台词前后的连续动作反应，应优先组成同一个 continuous_take。"
            "单个小镜头时长达到 4 秒时可以独立成为 independent。单镜头或镜头组小于 4 秒时禁止独立输出，"
            "必须优先与属于同一段连续表演的前后相邻镜头合并，直到总时长达到或超过 4 秒；"
            "如果动作、机位、视点、时空和主体状态连续，并且边界处没有真实切镜点，就按原顺序合并为 continuous_take，"
            "可继续吸收后续连续镜头，使整组时长达到或超过 4 秒。"
            "明确硬切、反打、主体视点跳转、无法连续完成的机位切换、匹配切、隐藏切、淡入淡出、时空跳跃、"
            "主体状态不连续，或演员必须复位和改变表演目标时才切开；"
            "如果不足 4 秒且前后都存在真实切镜点，仍必须与剧情关系更紧密的相邻镜头打包，group_type 使用 min_duration_pack，"
            "并在 reason 中明确组内保留真实切镜，不得伪装成 continuous_take。"
            "除非整份输入总时长本身不足 4 秒，否则最终不得出现时长小于 4 秒的镜头组。"
            "人物或场景相同、小于 4 秒都不能单独证明可合并；必须同时满足连续拍摄条件。"
            "结果必须按输入顺序完整覆盖每个小镜头且不重不漏。只返回 JSON，不生成首尾帧提示词，不改写剧情。"
        )
        if previous_analysis and reanalysis_prompt:
            system_text += (
                "这是一次修订任务。请以现有镜头组为基线，严格执行重新分析要求；"
                "要求中可用 s001 或 g001 等编号指定目标。未被点名的内容尽量保持不变，"
                "但最终仍须返回覆盖全部子镜头的完整 shot_groups，不得只返回局部结果。"
            )
        try:
            raw_groups, meta = _call_asset_llm_json(
                system_text,
                {
                    "project_constraints": {
                        "aspect_ratio": project_params.get("aspect_ratio"),
                        "resolution": project_params.get("resolution"),
                        "global_visual_lock": project_params.get("global_visual_lock"),
                        "minimum_generation_duration_seconds": 4,
                    },
                    "ordered_sub_shots": ordered_sub_shots,
                    "analysis_prompt": analysis_prompt,
                    "reanalysis_prompt": reanalysis_prompt or "",
                    "previous_analysis": {
                        "summary": previous_analysis.get("summary"),
                        "shot_groups": [
                            {
                                "group_id": group.get("group_id"),
                                "group_type": group.get("group_type"),
                                "sub_shot_ids": group.get("sub_shot_ids") or [],
                                "reason": group.get("reason"),
                            }
                            for group in previous_analysis.get("shot_groups") or []
                        ],
                    }
                    if previous_analysis
                    else None,
                },
                "autoflow_shot_group_analysis",
                _analysis_response_schema(),
                max_tokens=24000,
                use_network_proxy=use_network_proxy,
            )
            raw_groups = _merge_short_analysis_groups(raw_groups, ordered_sub_shots)
            _validate_group_partition(raw_groups, ordered_sub_shots)
        except Exception as exc:
            if previous_analysis and reanalysis_prompt:
                logger.exception("autoflow.analyze_shot_groups.reanalysis_failed")
                raise RuntimeError(f"重新分析镜头组失败: {exc}") from exc
            meta = {"provider": "deterministic_fallback", "model": None, "fallback_reason": str(exc)}
            logger.exception("autoflow.analyze_shot_groups.llm_failed fallback_reason=%s", exc)
            raw_groups = fallback

    by_sub_id = {str(item.get("id")): item for item in ordered_sub_shots}
    groups = _materialize_analysis_groups(raw_groups, ordered_sub_shots)
    if previous_analysis and reanalysis_prompt:
        returned_ids = [
            str(sub_id)
            for group in groups
            for sub_id in group.get("sub_shot_ids") or []
        ]
        missing_ids = sorted(set(by_sub_id) - set(returned_ids))
        duplicate_ids = sorted(
            sub_id for sub_id in set(returned_ids) if returned_ids.count(sub_id) > 1
        )
        if missing_ids or duplicate_ids:
            raise RuntimeError(
                "重新分析结果未完整覆盖子镜头："
                f"缺失={missing_ids or '无'}，重复={duplicate_ids or '无'}"
            )
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
    if isinstance(result.get("segments"), list):
        normalized_segments = _normalize_segments(result["segments"])
        ordered_sub_shots = _flatten_sub_shots(normalized_segments)
        raw_groups = {
            "summary": result.get("summary"),
            "shot_groups": [
                {
                    "group_id": group.get("group_id"),
                    "group_type": group.get("group_type"),
                    "sub_shot_ids": group.get("sub_shot_ids") or [],
                    "reason": group.get("reason"),
                }
                for group in result.get("shot_groups") or []
                if isinstance(group, dict)
            ],
        }
        raw_groups = _merge_short_analysis_groups(raw_groups, ordered_sub_shots)
        _validate_group_partition(raw_groups, ordered_sub_shots)
        result["segments"] = normalized_segments
        result["shot_groups"] = _materialize_analysis_groups(
            raw_groups, ordered_sub_shots
        )
        result["summary"] = raw_groups["summary"]
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


ROUTING_REQUIREMENT_LEVELS = {"low", "medium", "high", "critical"}
ROUTING_COMPLEXITY_LEVELS = {"low", "medium", "high"}
ROUTING_LEVEL_SCORES = {"low": 25, "medium": 50, "high": 75, "critical": 95}


def _score_to_difficulty(score: int) -> str:
    if score >= 86:
        return "critical"
    if score >= 66:
        return "high"
    if score >= 41:
        return "medium"
    return "low"


def _dimension_scores_from_requirements(requirements: dict[str, str]) -> dict[str, int]:
    return {
        key: ROUTING_LEVEL_SCORES.get(str(requirements.get(key) or "low"), 25)
        for key in ROUTING_DIMENSIONS
    }


def _overall_numeric_score(dimension_scores: dict[str, int]) -> int:
    values = [int(dimension_scores.get(key) or 0) for key in ROUTING_DIMENSIONS]
    if not values:
        return 0
    # 既体现整体生成负担，也让单项极难维度能够拉高路由风险。
    return max(0, min(100, round((sum(values) / len(values)) * 0.7 + max(values) * 0.3)))


def _fallback_sub_shot_score(group: dict[str, Any], sub: dict[str, Any]) -> dict[str, Any]:
    sub_group = {
        "group_type": "independent",
        "duration": _to_seconds(sub.get("duration")),
        "sub_shots": [sub],
    }
    requirements = _requirements_for_group(sub_group)
    dimension_scores = _dimension_scores_from_requirements(requirements)
    score = _overall_numeric_score(dimension_scores)
    risks = [
        f"{ROUTING_DIMENSION_LABELS.get(key, key)} {value} 分"
        for key, value in dimension_scores.items()
        if value >= 75
    ]
    return {
        "sub_shot_id": str(sub.get("id") or ""),
        "difficulty_score": score,
        "overall_difficulty": _score_to_difficulty(score),
        "dimension_scores": dimension_scores,
        "reason": "根据该小镜头的人物、台词、动作、运镜、道具与时长独立评分。",
        "risks": risks,
    }


def _compact_group_for_difficulty(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": group.get("group_id"),
        "group_type": group.get("group_type"),
        "duration": group.get("duration"),
        "reason": group.get("reason"),
        "scene": group.get("scene_asset"),
        "sub_shots": [
            {
                "id": sub.get("id"),
                "duration": sub.get("duration"),
                "content": sub.get("content"),
                "performance": sub.get("performance"),
                "shot_type": sub.get("shot_type"),
                "camera_movement": sub.get("camera_movement"),
                "characters": sub.get("characters") or [],
                "items": sub.get("items") or [],
                "dialogue": sub.get("dialogue") or {},
                "entry_state": sub.get("entry_state"),
                "exit_state": sub.get("exit_state"),
            }
            for sub in group.get("sub_shots") or []
        ],
    }


def _fallback_routing_difficulty(shot_groups: list[dict[str, Any]]) -> dict[str, Any]:
    shots: list[dict[str, Any]] = []
    for group in shot_groups:
        requirements = _requirements_for_group(group)
        complexity = _complexity_for_group(group)
        sub_shot_scores = [
            _fallback_sub_shot_score(group, sub)
            for sub in group.get("sub_shots") or []
        ]
        dimension_scores = _dimension_scores_from_requirements(requirements)
        group_score = _overall_numeric_score(dimension_scores)
        if sub_shot_scores:
            group_score = max(group_score, max(item["difficulty_score"] for item in sub_shot_scores))
        overall = _score_to_difficulty(group_score)
        shots.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "story_priority": "key" if group.get("group_type") == "continuous_take" else "normal",
                "difficulty_score": group_score,
                "overall_difficulty": overall,
                "routing_requirements": requirements,
                "complexity": complexity,
                "reason": "根据镜头时长、人物数量、动作、台词和连续性规则确定性评估。",
                "risks": [],
                "sub_shot_scores": sub_shot_scores,
            }
        )
    sub_count = sum(len(item.get("sub_shot_scores") or []) for item in shots)
    return {"summary": f"已对 {sub_count} 个小镜头逐镜打分，并汇总为 {len(shots)} 个镜头组路由难度。", "shots": shots}


def _aggregate_sub_shot_difficulty(result: dict[str, Any]) -> dict[str, Any]:
    """把逐镜头分数确定性汇总到镜头组，确保真实路由不会忽略组内高难镜头。"""
    normalized = copy.deepcopy(result)
    for shot in normalized.get("shots") or []:
        sub_scores = [item for item in shot.get("sub_shot_scores") or [] if isinstance(item, dict)]
        if not sub_scores:
            continue
        max_sub_score = max(int(item.get("difficulty_score") or 0) for item in sub_scores)
        shot["difficulty_score"] = max(int(shot.get("difficulty_score") or 0), max_sub_score)
        shot["overall_difficulty"] = _score_to_difficulty(int(shot["difficulty_score"]))
        requirements = shot.setdefault("routing_requirements", {})
        for key in ROUTING_DIMENSIONS:
            max_dimension_score = max(
                int((item.get("dimension_scores") or {}).get(key) or 0)
                for item in sub_scores
            )
            sub_level = _score_to_difficulty(max_dimension_score)
            current_level = str(requirements.get(key) or "low")
            requirements[key] = max(
                (current_level, sub_level),
                key=lambda value: ROUTING_LEVEL_ORDER.get(value, 0),
            )
    return normalized


def _validate_routing_difficulty(
    result: dict[str, Any], shot_groups: list[dict[str, Any]]
) -> None:
    expected_ids = [str(group.get("group_id") or "") for group in shot_groups]
    shots = result.get("shots")
    if not isinstance(shots, list):
        raise RuntimeError("镜头难度分析未返回 shots。")
    returned_ids = [str(shot.get("group_id") or "") for shot in shots]
    if returned_ids != expected_ids:
        raise RuntimeError("镜头难度分析必须按原顺序完整覆盖全部镜头组。")
    group_by_id = {str(group.get("group_id") or ""): group for group in shot_groups}
    for shot in shots:
        requirements = shot.get("routing_requirements") or {}
        complexity = shot.get("complexity") or {}
        if set(requirements) != set(ROUTING_DIMENSIONS):
            raise RuntimeError(f"镜头 {shot.get('group_id')} 的路由需求维度不完整。")
        if set(complexity) != set(COMPLEXITY_FIELDS):
            raise RuntimeError(f"镜头 {shot.get('group_id')} 的复杂度维度不完整。")
        if any(value not in ROUTING_REQUIREMENT_LEVELS for value in requirements.values()):
            raise RuntimeError(f"镜头 {shot.get('group_id')} 返回了无效路由需求等级。")
        if any(value not in ROUTING_COMPLEXITY_LEVELS for value in complexity.values()):
            raise RuntimeError(f"镜头 {shot.get('group_id')} 返回了无效复杂度等级。")
        group_score = shot.get("difficulty_score")
        if not isinstance(group_score, int) or isinstance(group_score, bool) or not 0 <= group_score <= 100:
            raise RuntimeError(f"镜头组 {shot.get('group_id')} 的难度分必须是 0-100 整数。")
        group = group_by_id.get(str(shot.get("group_id") or "")) or {}
        expected_sub_ids = [str(sub.get("id") or "") for sub in group.get("sub_shots") or []]
        sub_scores = shot.get("sub_shot_scores")
        if not isinstance(sub_scores, list):
            raise RuntimeError(f"镜头组 {shot.get('group_id')} 未返回逐镜头评分。")
        returned_sub_ids = [str(item.get("sub_shot_id") or "") for item in sub_scores]
        if returned_sub_ids != expected_sub_ids:
            raise RuntimeError(f"镜头组 {shot.get('group_id')} 必须按原顺序完整覆盖每个小镜头。")
        for item in sub_scores:
            score = item.get("difficulty_score")
            if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
                raise RuntimeError(f"小镜头 {item.get('sub_shot_id')} 的难度分必须是 0-100 整数。")
            dimension_scores = item.get("dimension_scores") or {}
            if set(dimension_scores) != set(ROUTING_DIMENSIONS):
                raise RuntimeError(f"小镜头 {item.get('sub_shot_id')} 的逐维度分数不完整。")
            if any(
                not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100
                for value in dimension_scores.values()
            ):
                raise RuntimeError(f"小镜头 {item.get('sub_shot_id')} 返回了无效的维度分数。")
        if sub_scores and group_score < max(int(item["difficulty_score"]) for item in sub_scores):
            raise RuntimeError(f"镜头组 {shot.get('group_id')} 的汇总难度分不得低于组内最难小镜头。")


def _analyze_routing_difficulty(
    project_params: dict[str, Any],
    shot_groups: list[dict[str, Any]],
    routing_analysis_prompt: str,
    use_ai: bool,
    use_network_proxy: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fallback = _aggregate_sub_shot_difficulty(_fallback_routing_difficulty(shot_groups))
    if not use_ai:
        return fallback, {"provider": "deterministic", "model": None}
    system_text = (
        "你是短剧视频生成难度分析器。必须对每个镜头组内的每一个 sub_shot 分别独立打分，"
        "每个小镜头返回 0-100 难度总分、十项 0-100 维度分、难度等级、理由和风险；"
        "再为镜头组返回 0-100 汇总难度分与路由能力要求。组分不得低于组内最难的小镜头。"
        "但绝对不要选择、推荐或输出任何具体模型和 preset；模型选择由后续确定性路由器完成。"
        "必须根据实际动作、表演、口型、多角色控制、身份一致性、物理交互、运镜、道具、特效和时序连续性评估，"
        "不得因为用户指定了某档位而虚高或压低难度。按输入顺序完整覆盖全部 group_id 及其 sub_shot.id，不得遗漏或重复，只返回 JSON。"
    )
    try:
        result, meta = _call_asset_llm_json(
            system_text,
            {
                "project_constraints": {
                    "routing_tier": project_params.get("routing_tier"),
                    "resolution": project_params.get("resolution"),
                    "aspect_ratio": project_params.get("aspect_ratio"),
                },
                "routing_analysis_prompt": routing_analysis_prompt,
                "shot_groups": [_compact_group_for_difficulty(group) for group in shot_groups],
                "dimension_guide": {
                    "routing_requirements": ROUTING_DIMENSIONS,
                    "complexity": COMPLEXITY_FIELDS,
                    "requirement_levels": ["low", "medium", "high", "critical"],
                    "complexity_levels": ["low", "medium", "high"],
                    "score_range": "所有 difficulty_score 和 dimension_scores 都是 0-100 整数",
                },
            },
            "autoflow_routing_difficulty",
            _routing_difficulty_response_schema(),
            max_tokens=24000,
            use_network_proxy=use_network_proxy,
        )
        result = _aggregate_sub_shot_difficulty(result)
        _validate_routing_difficulty(result, shot_groups)
        return result, meta
    except Exception as exc:
        logger.exception("autoflow.routing_difficulty.llm_failed fallback_reason=%s", exc)
        return fallback, {
            "provider": "deterministic_fallback",
            "model": None,
            "fallback_reason": str(exc),
        }


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


def _to_generation_unit(
    group: dict[str, Any],
    assets: dict[str, Any],
    difficulty_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    maps = _asset_name_to_id_maps(assets)
    role_ids = _unique(
        [
            maps["characters"][str(character)]
            for sub in group.get("sub_shots", [])
            for character in sub.get("characters", [])
            if str(character) in maps["characters"]
        ]
    )
    prop_ids = _unique(
        [
            maps["items"][str(prop)]
            for sub in group.get("sub_shots", [])
            for prop in sub.get("items", [])
            if str(prop) in maps["items"]
        ]
    )
    scene_name = str(group.get("scene_asset") or (group.get("sub_shots") or [{}])[0].get("scene") or "主场景")
    scene_id = maps["scenes"].get(scene_name, scene_name)
    cursor = 0
    sub_timelines: list[dict[str, Any]] = []
    for index, sub in enumerate(group.get("sub_shots") or [], start=1):
        duration = _to_seconds(sub.get("duration"))
        start, end = cursor, cursor + duration
        cursor = end
        sub_timelines.append(
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
    difficulty = difficulty_analysis or {}
    group_id = str(group.get("group_id") or uuid.uuid4().hex[:8])
    narrative_classes = _unique([seg["narrative_class"] for seg in sub_timelines])
    narrative_functions = [seg["narrative_function"] for seg in sub_timelines]
    beats = [
        {
            "sub_shot_id": seg["atomic_id"],
            "start": seg["start"],
            "end": seg["end"],
            "content": seg["narrative_function"],
            "shot_size": (seg.get("camera_plan") or {}).get("shot_size"),
            "camera_movement": (seg.get("camera_plan") or {}).get("movement"),
        }
        for seg in sub_timelines
    ]
    first_segment = sub_timelines[0] if sub_timelines else {}
    last_segment = sub_timelines[-1] if sub_timelines else {}
    timeline_lines = [
        f"{seg['start']:g}-{seg['end']:g}秒：{(seg.get('prompt_core') or {}).get('timeline_local') or seg.get('narrative_function') or '保持本镜动作'}"
        for seg in sub_timelines
    ]
    if group_type == "min_duration_pack" and len(timeline_lines) > 1:
        timeline_lines.insert(0, "本生成单元包含多个编辑镜头，按下列时间节拍保留组内真实切镜。")
    combined_segment = {
        "type": "atomic",
        "atomic_id": group_id,
        "start": 0,
        "end": cursor,
        "scene_asset": scene_id,
        "narrative_class": narrative_classes[0] if len(narrative_classes) == 1 else "mixed",
        "narrative_function": "；".join(narrative_functions) or "剧情推进",
        "camera_plan": {
            "shot_size": " → ".join(_unique([(seg.get("camera_plan") or {}).get("shot_size") for seg in sub_timelines])) or "中景",
            "angle": "按各小镜头设定",
            "composition": "主体清晰，保持短剧竖屏构图与组内站位连续",
            "movement": " → ".join(_unique([(seg.get("camera_plan") or {}).get("movement") for seg in sub_timelines])) or "固定镜头",
        },
        "prompt_core": {
            "timeline_local": "\n".join(timeline_lines) or "保持本镜动作",
            "guardrail": "不新增剧本以外的角色、道具和动作。",
        },
        "asset_refs": {"roles": role_ids, "props": prop_ids},
        "reference_assets": _reference_assets(scene_id, role_ids, prop_ids),
        "continuity": {
            "entry": (first_segment.get("continuity") or {}).get("entry") or "",
            "exit": (last_segment.get("continuity") or {}).get("exit") or "",
            "los": "按小镜头时间节拍保持动作与视线关系",
        },
        "spatial_state": copy.deepcopy(first_segment.get("spatial_state") or {}),
        "scale_plan": copy.deepcopy(first_segment.get("scale_plan") or {}),
    }
    is_single_take = group_type != "min_duration_pack"
    return {
        "unit_id": group_id,
        "atomic_ids": [group_id],
        "source_sub_shot_ids": [seg["atomic_id"] for seg in sub_timelines],
        "group_ids": [group_id],
        "scene_asset": scene_id,
        "story_priority": difficulty.get("story_priority") or ("key" if group_type == "continuous_take" else "normal"),
        "narrative_classes": narrative_classes,
        "narrative_functions": narrative_functions,
        "content_duration": cursor,
        "duration": cursor,
        "padding_plan": {"before": 0, "after": 0},
        "asset_refs": {"roles": role_ids, "props": prop_ids},
        "routing_requirements": difficulty.get("routing_requirements") or _requirements_for_group(group),
        "complexity": difficulty.get("complexity") or _complexity_for_group(group),
        "difficulty_analysis": copy.deepcopy(difficulty),
        "continuity": {
            "entry": group.get("entry_prompt_zh") or "",
            "exit": group.get("exit_prompt_zh") or "",
            "los": str(group.get("reason") or ""),
        },
        "timeline_segments": [combined_segment],
        "beats": beats,
        "single_take": is_single_take,
        "indivisible": is_single_take,
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


ROUTING_MODEL_ORDER = ["seedance-2.0", "seedance-2.5", "higgsfield-h3", "wan-3.0"]
ROUTING_MODEL_LABELS = {
    "seedance-2.0": "Seedance 2.0",
    "seedance-2.5": "Seedance 2.5",
    "higgsfield-h3": "MiniMax H3",
    "wan-3.0": "Wan 3.0",
}
ROUTING_MODEL_STRENGTHS = {
    "seedance-2.0": "口型、人物身份一致性和连续表演较均衡",
    "seedance-2.5": "复杂表演、多人互动、动作与长时序连续性最强",
    "higgsfield-h3": "运镜和动作表现突出，并兼顾低成本生成",
    "wan-3.0": "环境特效和较长镜头生成更有优势",
}
ROUTING_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ROUTING_DIMENSION_LABELS = {
    "acting_precision": "表演精度",
    "dialogue_lipsync": "台词口型",
    "identity_consistency": "身份一致性",
    "multi_character_control": "多人控制",
    "motion_action": "动作强度",
    "physical_interaction": "物理互动",
    "camera_control": "运镜控制",
    "prop_precision": "道具精度",
    "vfx_environment": "特效环境",
    "temporal_continuity": "时序连续性",
}


def _difficulty_for_routing_unit(unit: dict[str, Any]) -> dict[str, Any]:
    difficulty = copy.deepcopy(unit.get("difficulty_analysis") or {})
    if difficulty:
        return difficulty
    requirements = unit.get("routing_requirements") or {}
    levels = [
        str(value)
        for value in requirements.values()
        if str(value) in ROUTING_LEVEL_ORDER
    ]
    overall = max(levels, key=lambda value: ROUTING_LEVEL_ORDER[value]) if levels else "low"
    risks = [
        f"{ROUTING_DIMENSION_LABELS.get(key, key)}为{('关键高难' if value == 'critical' else '高难')}"
        for key, value in requirements.items()
        if value in {"high", "critical"}
    ]
    return {
        "story_priority": unit.get("story_priority") or "normal",
        "overall_difficulty": overall,
        "reason": "根据该镜头十项路由需求中的最高等级生成确定性难度结论。",
        "risks": risks,
    }


def _human_hard_reason(reason: str) -> str:
    value = str(reason or "")
    if value.startswith("preset_output_resolution_mismatch"):
        return "输出分辨率与项目要求不一致"
    if value.startswith("target_resolution_not_allowed"):
        return "该 preset 不支持项目分辨率"
    if value.startswith("preset_duration>") or value.startswith("duration>"):
        return "镜头时长超过接口上限"
    if value.startswith("preset_duration<") or value.startswith("duration<"):
        return "镜头时长低于接口下限"
    if value.startswith("required_image_count_exceeded"):
        return "必需参考图片数量超过接口容量"
    if value.startswith("required_video_count_exceeded"):
        return "必需参考视频数量超过接口容量"
    if value.startswith("required_audio_count_exceeded"):
        return "必需参考音频数量超过接口容量"
    if value.startswith("required_total_files_exceeded"):
        return "必需素材总数超过接口容量"
    if value.startswith("sr_shot_size_forbidden") or value == "requires_all_closeup":
        return "SR 仅支持全段特写或大特写"
    if value == "wide_shot_forbidden":
        return "该 preset 不支持宽景别"
    if value == "has_people_forbidden":
        return "该 preset 不支持人物镜头"
    if value == "preset_disabled":
        return "该 preset 当前已停用"
    if value.startswith("invalid_pricing"):
        return "价格配置无效"
    return value or "不满足接口硬约束"


def _representative_candidate(
    model_candidates: list[dict[str, Any]],
    selected_model: str,
    selected_preset: str,
) -> dict[str, Any] | None:
    for candidate in model_candidates:
        if candidate.get("model") == selected_model and candidate.get("preset") == selected_preset:
            return candidate
    qualified = [candidate for candidate in model_candidates if candidate.get("qualified")]
    if qualified:
        return max(
            qualified,
            key=lambda item: (
                float(item.get("tier_score") or 0),
                float(item.get("fit_quality") or 0),
                float(item.get("reliability") or 0),
                -float(item.get("expected_usable_points") or 10**9),
            ),
        )
    if not model_candidates:
        return None
    return min(
        model_candidates,
        key=lambda item: (
            len(item.get("hard_reasons") or []),
            -float(item.get("fit_quality") or 0),
        ),
    )


def _selected_model_reason(
    decision: dict[str, Any],
    difficulty: dict[str, Any],
    representative_by_model: dict[str, dict[str, Any] | None],
) -> str:
    selected_model = str(decision.get("selected_model") or "")
    selected = representative_by_model.get(selected_model) or {}
    label = ROUTING_MODEL_LABELS.get(selected_model, selected_model or "当前模型")
    preset = str(decision.get("selected_preset") or selected.get("preset") or "默认 preset")
    quality = float(decision.get("fit_quality") or selected.get("fit_quality") or 0)
    reliability = float(decision.get("reliability") or selected.get("reliability") or 0)
    points = float(decision.get("expected_usable_points") or selected.get("expected_usable_points") or 0)
    level = {
        "low": "低难度",
        "medium": "中等难度",
        "high": "高难度",
        "critical": "关键高难",
    }.get(str(difficulty.get("overall_difficulty") or ""), "当前难度")
    tier = str(decision.get("tier") or "medium")
    if tier == "low":
        policy_reason = "在通过接口硬约束与低档质量底线的方案中，预计可用积分更低"
    elif tier == "high":
        policy_reason = "处于接近最高质量的候选集合，并在质量、可靠性和成本之间更优"
    elif decision.get("medium_target_met"):
        target = decision.get("medium_target_quality")
        floor = decision.get("medium_reliability_floor")
        policy_reason = f"达到中档目标质量 {target} 和可靠性底线 {floor}，且在达标方案中预计可用积分更优"
    else:
        policy_reason = "当前没有候选同时达到中档目标，选择了最接近目标且成本可控的方案"
    return (
        f"该镜头判定为{level}。{label} 的优势是{ROUTING_MODEL_STRENGTHS.get(selected_model, '综合能力与当前镜头匹配')}。"
        f"选择 {label} / {preset}：适配分 {quality:.2f}，"
        f"可靠性 {reliability * 100:.1f}%，预计可用积分 {points:.2f}；{policy_reason}。"
    )


def _model_comparison(
    decision: dict[str, Any], difficulty: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    raw_candidates = [
        candidate
        for candidate in decision.get("candidates") or []
        if isinstance(candidate, dict)
    ]
    selected_model = str(decision.get("selected_model") or "")
    selected_preset = str(decision.get("selected_preset") or "")
    representative_by_model = {
        model: _representative_candidate(
            [candidate for candidate in raw_candidates if candidate.get("model") == model],
            selected_model,
            selected_preset,
        )
        for model in ROUTING_MODEL_ORDER
    }
    selected_reason = _selected_model_reason(
        decision, difficulty, representative_by_model
    )
    selected = representative_by_model.get(selected_model) or {}
    rows: list[dict[str, Any]] = []
    for model in ROUTING_MODEL_ORDER:
        candidate = representative_by_model.get(model)
        if candidate is None:
            rows.append(
                {
                    "model": model,
                    "display_name": ROUTING_MODEL_LABELS[model],
                    "qualified": False,
                    "selected": False,
                    "verdict": "unavailable",
                    "why": "当前路由配置未返回该模型候选。",
                    "hard_reasons": ["model_candidate_unavailable"],
                }
            )
            continue
        qualified = bool(candidate.get("qualified"))
        is_selected = model == selected_model and candidate.get("preset") == selected_preset
        reasons = [_human_hard_reason(reason) for reason in candidate.get("hard_reasons") or []]
        if is_selected:
            why = selected_reason
            verdict = "selected"
        elif not qualified:
            why = "；".join(reasons) or "未通过接口硬约束。"
            verdict = "rejected"
        else:
            quality_delta = float(candidate.get("fit_quality") or 0) - float(selected.get("fit_quality") or 0)
            cost_delta = float(candidate.get("expected_usable_points") or 0) - float(selected.get("expected_usable_points") or 0)
            reliability_delta = float(candidate.get("reliability") or 0) - float(selected.get("reliability") or 0)
            comparisons = []
            if quality_delta < -0.01:
                comparisons.append(f"适配分低 {abs(quality_delta):.2f}")
            elif quality_delta > 0.01:
                comparisons.append(f"适配分高 {quality_delta:.2f}，但未赢得当前档位综合裁决")
            if cost_delta > 0.01:
                comparisons.append(f"预计积分高 {cost_delta:.2f}")
            if reliability_delta < -0.001:
                comparisons.append(f"可靠性低 {abs(reliability_delta) * 100:.1f} 个百分点")
            why = "；".join(comparisons) or "模型可用，但当前档位综合得分未超过入选方案。"
            verdict = "qualified"
        rows.append(
            {
                "model": model,
                "display_name": ROUTING_MODEL_LABELS[model],
                "preset": candidate.get("preset"),
                "qualified": qualified,
                "selected": is_selected,
                "verdict": verdict,
                "fit_quality": candidate.get("fit_quality"),
                "reliability": candidate.get("reliability"),
                "call_points": candidate.get("call_points"),
                "expected_usable_points": candidate.get("expected_usable_points"),
                "hard_reasons": reasons,
                "why": why,
            }
        )
    return rows, selected_reason


def _build_routing_analysis(routed_plan: dict[str, Any]) -> dict[str, Any]:
    shots = []
    for unit in routed_plan.get("routed_units", []) or []:
        decision = copy.deepcopy(unit.get("routing_decision") or {})
        difficulty = _difficulty_for_routing_unit(unit)
        comparison, selected_reason = _model_comparison(decision, difficulty)
        selected_model = str(decision.get("selected_model") or "")
        if selected_model in ROUTING_MODEL_LABELS:
            decision["selected_display_name"] = ROUTING_MODEL_LABELS[selected_model]
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
        decision["model_comparison"] = comparison
        decision["selection_reason"] = selected_reason
        shots.append(
            {
                "shot_id": unit.get("unit_id"),
                "atomic_ids": unit.get("atomic_ids", []),
                "source_sub_shot_ids": unit.get("source_sub_shot_ids", []),
                "source_group": (unit.get("autoflow_group") or {}).get("group_id"),
                "duration": unit.get("duration"),
                "routing_requirements": unit.get("routing_requirements", {}),
                "complexity": unit.get("complexity", {}),
                "difficulty_analysis": difficulty,
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
    aspect_ratio: str,
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
    # 星图站位线稿为纯文生图，不消费输入资产图；只有
    # OpenRouter/provider 的图生图编辑模式才必须先完成资产绑定。
    if missing and generation_mode in {"provider", "openrouter"}:
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
        "aspect_ratio": aspect_ratio or "9:16",
    }
    if not payload["entry_prompt_zh"] or not payload["exit_prompt_zh"]:
        result = {"shot_id": shot.get("shot_id"), "status": "blocked", "detail": "缺少首帧或尾帧提示词"}
        log_payload(logger, "autoflow.reference.generate_shot.blocked", result)
        return result
    if generation_mode == "xingtu":
        manifest = create_reference_image_pair_xingtu_job(payload)
    elif generation_mode in {"provider", "openrouter"}:
        manifest = create_reference_image_pair_provider_job(payload, asset_reference_data_urls(input_ids))
    else:
        manifest = create_reference_image_pair_job(payload)
    manifest["input_asset_ids"] = input_ids
    if missing and generation_mode == "xingtu":
        manifest["unused_missing_asset_ids"] = missing
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
    routing_analysis_prompt: str,
    use_ai_difficulty: bool = True,
    use_network_proxy: bool = False,
) -> dict[str, Any]:
    log_event(
        logger,
        "autoflow.route_and_generate_refs.start",
        shot_group_count=len(shot_groups),
        generation_mode=generation_mode,
        image_model=image_model,
        routing_analysis_prompt_length=len(routing_analysis_prompt),
        use_ai_difficulty=use_ai_difficulty,
        project_params=project_params,
    )
    difficulty_result, difficulty_meta = _analyze_routing_difficulty(
        project_params,
        shot_groups,
        routing_analysis_prompt,
        use_ai_difficulty,
        use_network_proxy,
    )
    difficulty_by_group = {
        str(item.get("group_id") or ""): item
        for item in difficulty_result.get("shots") or []
    }
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
        "generation_units": [
            _to_generation_unit(
                group,
                assets,
                difficulty_by_group.get(str(group.get("group_id") or "")),
            )
            for group in shot_groups
        ],
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
    aspect_ratio = str(project_params.get("aspect_ratio") or "9:16")
    max_workers = min(4, max(1, len(final_video_plan.get("shots", []) or [])))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _generate_reference_for_shot,
                episode_id,
                shot,
                generation_mode,
                image_model,
                aspect_ratio,
            ): shot
            for shot in final_video_plan.get("shots", []) or []
        }
        for future in as_completed(futures):
            shot = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "shot_id": shot.get("shot_id"),
                    "status": "blocked",
                    "detail": str(exc),
                }
                logger.exception(
                    "autoflow.reference.generate_shot.failed shot_id=%s",
                    shot.get("shot_id"),
                )
            if result.get("status") == "blocked":
                blocked.append(result)
            else:
                references.append(result)
    result = {
        "difficulty_analysis": {
            **difficulty_result,
            "llm": difficulty_meta,
        },
        "routing_analysis": _build_routing_analysis(routed_plan),
        "final_video_plan": final_video_plan,
        "reference_generation": {
            "completed_count": len(references),
            "blocked_count": len(blocked),
            "completed": references,
            "blocked": blocked,
            "generation_mode": generation_mode,
        },
        "source_context": {
            "project_params": project_params,
            "assets": assets,
            "story_context": story_context,
            "shot_groups": shot_groups,
        },
    }
    log_event(
        logger,
        "autoflow.route_and_generate_refs.result_summary",
        shot_count=len(final_video_plan.get("shots", []) or []),
        completed_count=len(references),
        blocked_count=len(blocked),
    )
    _save_step_result(AUTOFLOW_ROUTE_RESULT_PATH, result, "autoflow.routing.saved")
    log_payload(logger, "autoflow.route_and_generate_refs.result", result)
    return result


def load_latest_route_result() -> dict[str, Any]:
    try:
        result = _load_step_result(
            AUTOFLOW_ROUTE_RESULT_PATH,
            missing_message="尚未保存路由与首尾帧结果，请先点击“执行路由 + 生成首尾线稿”。",
            invalid_message="保存的路由与首尾帧结果不是有效 JSON。",
        )
    except FileNotFoundError:
        result = _restore_latest_route_result_from_debug_artifacts()
    routing_analysis = result.get("routing_analysis")
    final_video_plan = result.get("final_video_plan")
    reference_generation = result.get("reference_generation")
    if not isinstance(routing_analysis, dict) or not isinstance(routing_analysis.get("shots"), list):
        raise RuntimeError("保存的路由与首尾帧结果缺少有效的路由分析。")
    if not isinstance(final_video_plan, dict) or not isinstance(final_video_plan.get("shots"), list):
        raise RuntimeError("保存的路由与首尾帧结果缺少有效的视频镜头计划。")
    if not isinstance(reference_generation, dict):
        raise RuntimeError("保存的路由与首尾帧结果缺少有效的首尾帧生成状态。")
    if not isinstance(reference_generation.get("completed", []), list) or not isinstance(
        reference_generation.get("blocked", []), list
    ):
        raise RuntimeError("保存的路由与首尾帧结果结构无效。")
    log_event(logger, "autoflow.routing.latest.loaded", path=str(AUTOFLOW_ROUTE_RESULT_PATH))
    return result


def _restore_latest_route_result_from_debug_artifacts() -> dict[str, Any]:
    debug_root = settings.work_root / "debug_logs"
    candidates = sorted(
        debug_root.glob("*/*_autoflow.route_and_generate_refs.result.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    ) if debug_root.is_dir() else []
    for result_path in candidates:
        try:
            envelope = json.loads(result_path.read_text(encoding="utf-8"))
            result = envelope.get("payload") if isinstance(envelope, dict) else None
            if not isinstance(result, dict):
                continue
            if not isinstance(result.get("routing_analysis"), dict):
                continue
            if not isinstance(result.get("final_video_plan"), dict):
                continue
            if not isinstance(result.get("reference_generation"), dict):
                continue

            request_candidates = sorted(
                result_path.parent.glob("*_autoflow.route_and_generate_refs.request.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            if request_candidates:
                request_envelope = json.loads(request_candidates[0].read_text(encoding="utf-8"))
                request_payload = request_envelope.get("payload") if isinstance(request_envelope, dict) else None
                if isinstance(request_payload, dict):
                    result["source_context"] = {
                        "project_params": request_payload.get("project_params") or {},
                        "assets": request_payload.get("assets") or {},
                        "story_context": request_payload.get("story_context") or {},
                        "shot_groups": request_payload.get("shot_groups") or [],
                    }
            _save_step_result(AUTOFLOW_ROUTE_RESULT_PATH, result, "autoflow.routing.restored")
            log_event(logger, "autoflow.routing.restored_from_debug", source=str(result_path))
            return result
        except (OSError, json.JSONDecodeError):
            logger.warning("autoflow.routing.restore_skipped path=%s", result_path, exc_info=True)
    raise FileNotFoundError("尚未保存路由与首尾帧结果，请先点击“执行路由 + 生成首尾线稿”。")


def regenerate_latest_reference_images(
    generation_mode: str,
    image_model: str | None,
    shot_ids: list[str] | None = None,
) -> dict[str, Any]:
    result = load_latest_route_result()
    final_video_plan = result.get("final_video_plan") or {}
    all_shots = [shot for shot in final_video_plan.get("shots") or [] if isinstance(shot, dict)]
    requested_ids = {str(value).strip() for value in shot_ids or [] if str(value).strip()}
    target_shots = [
        shot for shot in all_shots
        if not requested_ids or str(shot.get("shot_id") or "") in requested_ids
    ]
    if not target_shots:
        raise ValueError("没有找到可重新生成首尾帧的视频镜头。")

    source_context = result.get("source_context") or {}
    project_params = source_context.get("project_params") or {}
    episode_id = str(project_params.get("episode_id") or "EP001")
    aspect_ratio = str(
        project_params.get("aspect_ratio")
        or final_video_plan.get("aspect_ratio")
        or "9:16"
    )
    completed_by_id = {
        str(item.get("shot_id") or ""): item
        for item in (result.get("reference_generation") or {}).get("completed") or []
        if isinstance(item, dict) and item.get("shot_id")
    }
    blocked_by_id = {
        str(item.get("shot_id") or ""): item
        for item in (result.get("reference_generation") or {}).get("blocked") or []
        if isinstance(item, dict) and item.get("shot_id")
    }
    target_ids = {str(shot.get("shot_id") or "") for shot in target_shots}
    for shot_id in target_ids:
        completed_by_id.pop(shot_id, None)
        blocked_by_id.pop(shot_id, None)

    max_workers = min(4, max(1, len(target_shots)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _generate_reference_for_shot,
                episode_id,
                shot,
                generation_mode,
                image_model,
                aspect_ratio,
            ): shot
            for shot in target_shots
        }
        for future in as_completed(futures):
            shot = futures[future]
            shot_id = str(shot.get("shot_id") or "")
            try:
                manifest = future.result()
            except Exception as exc:
                logger.exception("autoflow.reference.regenerate.failed shot_id=%s", shot_id)
                manifest = {"shot_id": shot_id, "status": "blocked", "detail": str(exc)}
            if manifest.get("status") == "blocked":
                blocked_by_id[shot_id] = manifest
            else:
                completed_by_id[shot_id] = manifest

    ordered_ids = [str(shot.get("shot_id") or "") for shot in all_shots]
    completed = [completed_by_id[shot_id] for shot_id in ordered_ids if shot_id in completed_by_id]
    blocked = [blocked_by_id[shot_id] for shot_id in ordered_ids if shot_id in blocked_by_id]
    result["reference_generation"] = {
        "completed_count": len(completed),
        "blocked_count": len(blocked),
        "completed": completed,
        "blocked": blocked,
        "generation_mode": generation_mode,
        "regenerated_only": True,
        "regenerated_shot_count": len(target_shots),
    }
    _save_step_result(AUTOFLOW_ROUTE_RESULT_PATH, result, "autoflow.references.regenerated.saved")
    log_event(
        logger,
        "autoflow.references.regenerated",
        target_count=len(target_shots),
        completed_count=len(completed),
        blocked_count=len(blocked),
    )
    return result


def submit_autoflow_video_jobs(
    final_video_plan: dict[str, Any],
    project_params: dict[str, Any] | None = None,
    *,
    regenerate_existing: bool = False,
) -> dict[str, Any]:
    from .video_generation_service import submit_video_batch

    return submit_video_batch(
        final_video_plan,
        project_params,
        regenerate_existing=regenerate_existing,
    )
