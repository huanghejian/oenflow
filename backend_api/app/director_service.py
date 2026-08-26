from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from typing import Any

from openai import OpenAI

from .compact_director import (
    COMPACT_DIRECTOR_OUTPUT_SCHEMA,
    COMPACT_OUTPUT_INSTRUCTIONS,
    expand_compact_director_plan,
)
from .config import settings
from .long_time_http import LongTimeHttpError, post_json


CUT_TYPES = [
    "scene_start",
    "scene_end",
    "hard_cut",
    "concealed_cut",
    "match_cut_action",
    "match_cut_shape",
    "fade",
]
REQUIREMENT_LEVELS = ["none", "low", "medium", "high", "critical"]
COMPLEXITY_LEVELS = ["low", "medium", "high"]
ROUTING_REQUIREMENT_FIELDS = [
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
ATOMIC_REQUIRED_FIELDS = [
    "atomic_id",
    "group_id",
    "scene_asset",
    "story_priority",
    "narrative_class",
    "narrative_function",
    "atomic_duration",
    "asset_refs",
    "reference_assets",
    "camera_plan",
    "spatial_plan",
    "scale_plan",
    "complexity",
    "routing_requirements",
    "prompt_core",
    "continuity",
    "single_take",
    "indivisible",
    "cut_in",
    "cut_out",
]

REFERENCE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asset_id": {"type": "string", "minLength": 1},
        "asset_type": {"type": "string"},
        "purpose": {"type": "string"},
        "duration_seconds": {"type": "number", "minimum": 0},
        "priority": {"type": "integer"},
    },
    "required": ["asset_id", "purpose"],
    "additionalProperties": True,
}
REFERENCE_BUCKET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        media: {"type": "array", "items": REFERENCE_ITEM_SCHEMA}
        for media in ("images", "videos", "audios")
    },
    "additionalProperties": True,
}

DIRECTOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "routing_tier": {"type": "string", "enum": ["low", "medium", "high"]},
        "aspect_ratio": {"type": "string", "minLength": 1},
        "asset_catalog": {
            "type": "object",
            "properties": {
                "scenes": {"type": "array", "items": {"type": "string"}},
                "roles": {"type": "array", "items": {"type": "string"}},
                "props": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["scenes", "roles", "props"],
            "additionalProperties": True,
        },
        "scene_contexts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "scene_asset": {"type": "string", "minLength": 1},
                    "state": {"type": "string", "minLength": 1},
                    "lighting": {"type": "string", "minLength": 1},
                    "style_lock": {"type": "string", "minLength": 1},
                    "spatial_bible": {
                        "type": "object",
                        "properties": {
                            "anchor_catalog": {
                                "type": "object",
                                "minProperties": 1,
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "landmark": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["landmark", "description"],
                                    "additionalProperties": True,
                                },
                            },
                            "axis_catalog": {"type": "object"},
                            "initial_world_positions": {
                                "type": "object",
                                "minProperties": 1,
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "anchor_id": {"type": "string"},
                                        "position": {"type": "string"},
                                        "facing": {"type": "string"},
                                        "pose_height": {"type": "string"},
                                        "visibility": {"type": "string"},
                                    },
                                    "required": [
                                        "anchor_id",
                                        "position",
                                        "facing",
                                        "pose_height",
                                        "visibility",
                                    ],
                                    "additionalProperties": True,
                                },
                            },
                        },
                        "required": [
                            "anchor_catalog",
                            "axis_catalog",
                            "initial_world_positions",
                        ],
                        "additionalProperties": True,
                    },
                },
                "required": [
                    "scene_asset",
                    "state",
                    "lighting",
                    "style_lock",
                    "spatial_bible",
                ],
                "additionalProperties": True,
            },
        },
        "atomic_shots": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "atomic_id": {"type": "string", "minLength": 1},
                    "group_id": {"type": "string", "minLength": 1},
                    "scene_asset": {"type": "string", "minLength": 1},
                    "story_priority": {
                        "type": "string",
                        "enum": ["normal", "key", "climax"],
                    },
                    "narrative_class": {
                        "type": "string",
                        "enum": [
                            "dialogue",
                            "reaction",
                            "action",
                            "cinematic",
                            "environment_vfx",
                            "prop_info",
                            "complex_narrative",
                        ],
                    },
                    "narrative_function": {"type": "string", "minLength": 1},
                    "atomic_duration": {"type": "integer", "minimum": 1},
                    "asset_refs": {
                        "type": "object",
                        "properties": {
                            "roles": {"type": "array", "items": {"type": "string"}},
                            "props": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": True,
                    },
                    "reference_assets": {
                        "type": "object",
                        "properties": {
                            "required": REFERENCE_BUCKET_SCHEMA,
                            "optional": REFERENCE_BUCKET_SCHEMA,
                        },
                        "required": ["required"],
                        "additionalProperties": True,
                    },
                    "camera_plan": {
                        "type": "object",
                        "properties": {
                            "shot_size": {"type": "string"},
                            "angle": {"type": "string"},
                            "composition": {"type": "string"},
                            "movement": {"type": "string"},
                        },
                        "required": ["shot_size", "angle", "composition", "movement"],
                        "additionalProperties": True,
                    },
                    "spatial_plan": {
                        "type": "object",
                        "properties": {
                            "camera_axis": {"type": "object"},
                            "screen_positions": {"type": "object"},
                            "position_changes": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["screen_positions"],
                        "additionalProperties": True,
                    },
                    "scale_plan": {
                        "type": "object",
                        "properties": {
                            "perspective_mode": {
                                "type": "string",
                                "enum": ["standard_depth", "strong_depth"],
                            },
                            "lens_style": {
                                "type": "string",
                                "enum": ["wide_angle", "standard", "portrait"],
                            },
                            "subjects": {"type": "object"},
                            "environment_relation": {"type": "string"},
                        },
                        "required": [
                            "perspective_mode",
                            "lens_style",
                            "subjects",
                            "environment_relation",
                        ],
                        "additionalProperties": True,
                    },
                    "complexity": {
                        "type": "object",
                        "properties": {
                            key: {"type": "string", "enum": COMPLEXITY_LEVELS}
                            for key in ("m", "c", "e", "cam")
                        },
                        "required": ["m", "c", "e", "cam"],
                        "additionalProperties": True,
                    },
                    "routing_requirements": {
                        "type": "object",
                        "properties": {
                            key: {"type": "string", "enum": REQUIREMENT_LEVELS}
                            for key in ROUTING_REQUIREMENT_FIELDS
                        },
                        "required": ROUTING_REQUIREMENT_FIELDS,
                        "additionalProperties": True,
                    },
                    "prompt_core": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": [
                                    "performance",
                                    "action",
                                    "environment",
                                    "info",
                                    "general",
                                ],
                            },
                            "spatial_anchor": {"type": "string"},
                            "timeline_local": {"type": "string"},
                            "guardrail": {"type": "string"},
                        },
                        "required": [
                            "mode",
                            "spatial_anchor",
                            "timeline_local",
                            "guardrail",
                        ],
                        "additionalProperties": True,
                    },
                    "continuity": {
                        "type": "object",
                        "properties": {
                            "entry": {"type": "string"},
                            "exit": {"type": "string"},
                            "los": {"type": "string"},
                        },
                        "required": ["entry", "exit", "los"],
                        "additionalProperties": True,
                    },
                    "tts": {"type": "string"},
                    "safe_padding": {
                        "type": "object",
                        "properties": {
                            "before": {"type": "integer", "minimum": 0},
                            "after": {"type": "integer", "minimum": 0},
                        },
                        "additionalProperties": True,
                    },
                    "independent_generation": {"type": "boolean"},
                    "merge_relation": {
                        "type": "string",
                        "enum": ["preferred", "allowed", "forbidden"],
                    },
                    "transition_hint": {"type": "string"},
                    "single_take": {"type": "boolean", "enum": [True]},
                    "indivisible": {"type": "boolean", "enum": [True]},
                    "cut_in": {"type": "string", "enum": CUT_TYPES},
                    "cut_out": {"type": "string", "enum": CUT_TYPES},
                    "beats": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "integer", "minimum": 0},
                                "end": {"type": "integer", "minimum": 1},
                                "action": {"type": "string"},
                            },
                            "required": ["start", "end", "action"],
                            "additionalProperties": True,
                        },
                    },
                },
                "required": ATOMIC_REQUIRED_FIELDS,
                "additionalProperties": True,
            },
        },
    },
    "required": [
        "routing_tier",
        "aspect_ratio",
        "asset_catalog",
        "scene_contexts",
        "atomic_shots",
    ],
    "additionalProperties": True,
}

# The canonical schema remains documented above and is still validated after expansion.
# Only the model-facing wire format is compact so downstream V7.3 stages stay unchanged.
CANONICAL_DIRECTOR_OUTPUT_SCHEMA = DIRECTOR_OUTPUT_SCHEMA
DIRECTOR_OUTPUT_SCHEMA = COMPACT_DIRECTOR_OUTPUT_SCHEMA


def _director_system_text(director_prompt: str) -> str:
    return f"{director_prompt}\n\n{COMPACT_OUTPUT_INSTRUCTIONS}"


def _expand_model_plan(
    raw_plan: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    plan, internal_format = expand_compact_director_plan(raw_plan, payload)
    _check_minimum_contract(plan)
    return plan, internal_format


def _missing_fields(value: Any, required: list[str]) -> list[str]:
    if not isinstance(value, dict):
        return required
    return [field for field in required if field not in value]


def _check_minimum_contract(plan: dict[str, Any]) -> None:
    errors: list[str] = []
    top_required = [
        "routing_tier",
        "aspect_ratio",
        "asset_catalog",
        "scene_contexts",
        "atomic_shots",
    ]
    missing_top = _missing_fields(plan, top_required)
    if missing_top:
        errors.append(f"顶层缺少必填字段: {missing_top}")

    catalog = plan.get("asset_catalog")
    catalog_missing = _missing_fields(catalog, ["scenes", "roles", "props"])
    if catalog_missing:
        errors.append(f"asset_catalog 缺少必填字段: {catalog_missing}")
    catalog_scenes = set(catalog.get("scenes") or []) if isinstance(catalog, dict) else set()

    contexts = plan.get("scene_contexts")
    context_scene_ids: set[str] = set()
    if not isinstance(contexts, list) or not contexts:
        errors.append("scene_contexts 必须是非空数组")
    else:
        for index, context in enumerate(contexts):
            prefix = f"scene_contexts[{index}]"
            missing = _missing_fields(
                context,
                ["scene_asset", "state", "lighting", "style_lock", "spatial_bible"],
            )
            if missing:
                errors.append(f"{prefix} 缺少必填字段: {missing}")
                continue
            scene_asset = context.get("scene_asset")
            if isinstance(scene_asset, str):
                context_scene_ids.add(scene_asset)
            bible = context.get("spatial_bible")
            bible_missing = _missing_fields(
                bible,
                ["anchor_catalog", "axis_catalog", "initial_world_positions"],
            )
            if bible_missing:
                errors.append(f"{prefix}.spatial_bible 缺少必填字段: {bible_missing}")

    shots = plan.get("atomic_shots")
    if not isinstance(shots, list) or not shots:
        errors.append("atomic_shots 必须是非空数组")
        shots = []
    valid_cuts = set(CUT_TYPES)
    for index, shot in enumerate(shots):
        prefix = f"atomic_shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        missing = _missing_fields(shot, ATOMIC_REQUIRED_FIELDS)
        if missing:
            errors.append(f"{prefix} 缺少必填字段: {missing}")
            continue
        if shot.get("single_take") is not True or shot.get("indivisible") is not True:
            errors.append(f"{prefix} 必须 single_take=true 且 indivisible=true")
        if shot.get("cut_in") not in valid_cuts or shot.get("cut_out") not in valid_cuts:
            errors.append(f"{prefix} 缺少合法 cut_in/cut_out")
        scene_asset = shot.get("scene_asset")
        if catalog_scenes and scene_asset not in catalog_scenes:
            errors.append(f"{prefix}.scene_asset 不在 asset_catalog.scenes 中: {scene_asset}")
        if context_scene_ids and scene_asset not in context_scene_ids:
            errors.append(f"{prefix}.scene_asset 没有对应 scene_context: {scene_asset}")

        nested_requirements = [
            ("camera_plan", ["shot_size", "angle", "composition", "movement"]),
            ("spatial_plan", ["screen_positions"]),
            (
                "scale_plan",
                ["perspective_mode", "lens_style", "subjects", "environment_relation"],
            ),
            ("complexity", ["m", "c", "e", "cam"]),
            ("routing_requirements", ROUTING_REQUIREMENT_FIELDS),
            ("prompt_core", ["mode", "spatial_anchor", "timeline_local", "guardrail"]),
            ("continuity", ["entry", "exit", "los"]),
        ]
        for field, required in nested_requirements:
            nested_missing = _missing_fields(shot.get(field), required)
            if nested_missing:
                errors.append(f"{prefix}.{field} 缺少必填字段: {nested_missing}")
        reference_missing = _missing_fields(shot.get("reference_assets"), ["required"])
        if reference_missing:
            errors.append(f"{prefix}.reference_assets 缺少 required")

        previous = shots[index - 1] if index else None
        if isinstance(previous, dict):
            same_scene = previous.get("scene_asset") == scene_asset
            if same_scene and previous.get("cut_out") != shot.get("cut_in"):
                errors.append(f"{prefix}.cut_in 必须与上一镜 cut_out 一致")
            if not same_scene and (
                previous.get("cut_out") != "scene_end"
                or shot.get("cut_in") != "scene_start"
            ):
                errors.append(f"{prefix} 跨场景边界必须为 scene_end → scene_start")

    if errors:
        preview = errors[:12]
        if len(errors) > len(preview):
            preview.append(f"……另有 {len(errors) - len(preview)} 处错误")
        raise ValueError("导演 JSON 字段契约失败：\n- " + "\n- ".join(preview))


def validate_director_plan_contract(plan: dict[str, Any]) -> None:
    """Validate an A-stage plan before any deterministic pipeline process starts."""
    _check_minimum_contract(plan)


def director_is_configured() -> bool:
    if settings.director_provider == "claude_converse":
        return bool(settings.claude_converse_url and settings.claude_converse_api_key)
    if settings.director_provider == "openrouter":
        return bool(settings.openrouter_api_key and settings.openrouter_director_model)
    if settings.director_provider == "openai":
        return bool(settings.openai_api_key and settings.openai_director_model)
    return False


def _create_openai_director_plan(
    payload: dict[str, Any], director_prompt: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")
    if not settings.openai_director_model:
        raise RuntimeError("未配置 OPENAI_DIRECTOR_MODEL")

    client = OpenAI(api_key=settings.openai_api_key)
    episode_id = str((payload.get("script") or {}).get("episode_id") or "unknown")
    response = client.responses.create(
        model=settings.openai_director_model,
        instructions=_director_system_text(director_prompt),
        input=json.dumps(payload, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "short_drama_director_plan",
                "schema": DIRECTOR_OUTPUT_SCHEMA,
                "strict": False,
            }
        },
        max_output_tokens=settings.openai_max_output_tokens,
        store=False,
        metadata={"episode_id": episode_id, "stage": "director_plan"},
    )

    if response.status != "completed":
        detail = getattr(response, "incomplete_details", None)
        raise RuntimeError(f"导演 API 未完成: status={response.status}, detail={detail}")
    if not response.output_text:
        raise RuntimeError("导演 API 没有返回 output_text")

    raw_plan = json.loads(response.output_text)
    plan, internal_format = _expand_model_plan(raw_plan, payload)
    usage = getattr(response, "usage", None)
    meta = {
        "response_id": response.id,
        "model": response.model,
        "usage": usage.model_dump() if usage and hasattr(usage, "model_dump") else None,
        "internal_output_format": internal_format,
    }
    return plan, meta


def _unwrap_gateway_body(data: Any) -> Any:
    if isinstance(data, dict) and isinstance(data.get("body"), str):
        try:
            return json.loads(data["body"])
        except json.JSONDecodeError:
            return data
    return data


def _extract_claude_text(data: Any) -> str:
    data = _unwrap_gateway_body(data)
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("output_text"),
                data.get("completion"),
                ((data.get("output") or {}).get("message") or {}).get("content")
                if isinstance(data.get("output"), dict)
                else None,
                data.get("content"),
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if isinstance(data.get("choices"), list) and data.get("choices")
                else None,
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, list):
            parts = [
                item.get("text", "")
                for item in candidate
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if any(part.strip() for part in parts):
                return "\n".join(parts).strip()
    raise RuntimeError("Claude Converse 响应中未找到文本内容")


def _parse_json_text(
    text: str, provider_label: str = "Claude Converse"
) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{provider_label} 未返回合法 JSON: "
            f"line={exc.lineno}, column={exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{provider_label} 返回的导演计划必须是 JSON 对象")
    return value


def _openrouter_reasoning(effort: str) -> dict[str, str]:
    allowed = {"low", "medium", "high"}
    if effort not in allowed:
        raise RuntimeError(
            f"无效 OPENROUTER_REASONING_EFFORT={effort}; "
            f"可选值为 {sorted(allowed)}"
        )
    return {"effort": effort}


def _extract_openrouter_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter 响应顶层必须是 JSON 对象")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            raise RuntimeError(f"OpenRouter 服务错误: {error['message']}")
        raise RuntimeError("OpenRouter 响应中没有 choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if any(part.strip() for part in parts):
            return "\n".join(parts).strip()
    refusal = message.get("refusal") if isinstance(message, dict) else None
    if isinstance(refusal, str) and refusal.strip():
        raise RuntimeError(f"OpenRouter 模型拒绝生成: {refusal.strip()}")
    raise RuntimeError("OpenRouter 响应中未找到文本内容")


def _openrouter_credit_retry_max_tokens(
    error: LongTimeHttpError, requested_max_tokens: int
) -> int | None:
    """Return one conservative retry limit for OpenRouter credit preflight 402s."""
    if error.status_code != 402:
        return None
    match = re.search(r"can only afford\s+(\d+)", error.body, flags=re.IGNORECASE)
    if not match:
        return None
    affordable = int(match.group(1))
    retry_limit = min(requested_max_tokens - 1, int(affordable * 0.9))
    if retry_limit < 32_000:
        return None
    return retry_limit


def _create_openrouter_director_plan(
    payload: dict[str, Any], director_prompt: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.openrouter_api_key:
        raise RuntimeError("未配置 OPENROUTER_API_KEY")
    if not settings.openrouter_director_model:
        raise RuntimeError("未配置 OPENROUTER_DIRECTOR_MODEL")

    system_text = _director_system_text(director_prompt)
    request_body: dict[str, Any] = {
        "model": settings.openrouter_director_model,
        "messages": [
            {"role": "system", "content": system_text},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ],
        "max_tokens": settings.openrouter_max_output_tokens,
        "reasoning": _openrouter_reasoning(
            settings.openrouter_reasoning_effort
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "short_drama_director_plan",
                "strict": False,
                "schema": DIRECTOR_OUTPUT_SCHEMA,
            },
        },
    }
    request_url = f"{settings.openrouter_base_url}/chat/completions"
    request_headers = {
        "HTTP-Referer": "http://localhost:3000",
        "X-OpenRouter-Title": "Short Drama Director Demo",
    }
    requested_max_tokens = request_body["max_tokens"]
    effective_max_tokens = requested_max_tokens
    credit_retry = False
    try:
        response_data, response_id_header = post_json(
            request_url,
            request_body,
            f"Bearer {settings.openrouter_api_key}",
            request_headers,
        )
    except LongTimeHttpError as exc:
        retry_max_tokens = _openrouter_credit_retry_max_tokens(
            exc, requested_max_tokens
        )
        if retry_max_tokens is None:
            raise RuntimeError(
                f"OpenRouter 请求失败: HTTP {exc.status_code}; {exc.body}"
            ) from exc
        request_body["max_tokens"] = retry_max_tokens
        effective_max_tokens = retry_max_tokens
        credit_retry = True
        try:
            response_data, response_id_header = post_json(
                request_url,
                request_body,
                f"Bearer {settings.openrouter_api_key}",
                request_headers,
            )
        except LongTimeHttpError as retry_exc:
            raise RuntimeError(
                "OpenRouter 自动降低 max_tokens 后仍然失败: "
                f"HTTP {retry_exc.status_code}; {retry_exc.body}"
            ) from retry_exc

    choices = response_data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    if finish_reason == "length":
        raise RuntimeError("OpenRouter 响应不完整: finish_reason=length")
    raw_plan = _parse_json_text(
        _extract_openrouter_text(response_data), "OpenRouter"
    )
    plan, internal_format = _expand_model_plan(raw_plan, payload)
    meta = {
        "response_id": response_data.get("id") or response_id_header,
        "provider": "openrouter",
        "model": response_data.get("model") or settings.openrouter_director_model,
        "usage": response_data.get("usage"),
        "finish_reason": finish_reason,
        "max_tokens_requested": requested_max_tokens,
        "max_tokens_effective": effective_max_tokens,
        "credit_retry": credit_retry,
        "internal_output_format": internal_format,
    }
    return plan, meta


def _bedrock_converse_url(
    url: str, model: str | None, region: str | None = None
) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    if region:
        query["region"] = region
    if model:
        query["model"] = model
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def _bedrock_inference_config(max_tokens: int, model: str | None) -> dict[str, Any]:
    config: dict[str, Any] = {"maxTokens": max_tokens}
    # BedrockClaudeChatService: opus-5 默认启用 extended thinking，temperature
    # 必须为 1 或省略；原 Java 实现只对 opus-4 显式设置 0.01。
    if model and "opus-4" in model:
        config["temperature"] = 0.01
    return config


def _bedrock_additional_model_fields(
    model: str | None, effort: str
) -> dict[str, Any] | None:
    if not model or "opus-5" not in model:
        return None
    allowed = {"low", "medium", "high", "xhigh", "max"}
    if effort not in allowed:
        raise RuntimeError(
            f"无效 CLAUDE_THINKING_EFFORT={effort}; 可选值为 {sorted(allowed)}"
        )
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }


def _create_claude_director_plan(
    payload: dict[str, Any], director_prompt: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.claude_converse_url:
        raise RuntimeError("未配置 CLAUDE_CONVERSE_URL")
    if not settings.claude_converse_api_key:
        raise RuntimeError("未配置 CLAUDE_CONVERSE_API_KEY")

    system_text = _director_system_text(director_prompt)
    request_body: dict[str, Any] = {
        "system": [{"text": system_text}],
        "messages": [
            {
                "role": "user",
                "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
            }
        ],
        "inferenceConfig": _bedrock_inference_config(
            settings.claude_max_output_tokens, settings.claude_director_model
        ),
    }
    additional_fields = _bedrock_additional_model_fields(
        settings.claude_director_model, settings.claude_thinking_effort
    )
    if additional_fields:
        request_body["additionalModelRequestFields"] = additional_fields

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
            f"Claude Converse 请求失败: HTTP {exc.status_code}; {exc.body}"
        ) from exc
    response_data = _unwrap_gateway_body(response_data)
    if isinstance(response_data, dict) and response_data.get("stopReason") == "max_tokens":
        raise RuntimeError("Claude Converse 响应不完整: stopReason=max_tokens")
    raw_plan = _parse_json_text(_extract_claude_text(response_data))
    plan, internal_format = _expand_model_plan(raw_plan, payload)
    meta = {
        "response_id": response_id,
        "provider": "claude_converse",
        "model": settings.claude_director_model,
        "usage": response_data.get("usage") if isinstance(response_data, dict) else None,
        "stop_reason": response_data.get("stopReason")
        if isinstance(response_data, dict)
        else None,
        "internal_output_format": internal_format,
    }
    return plan, meta


def load_default_director_prompt() -> str:
    if not settings.director_prompt_path.is_file():
        raise RuntimeError(f"导演提示词不存在: {settings.director_prompt_path}")
    return settings.director_prompt_path.read_text(encoding="utf-8")


def create_director_plan(
    payload: dict[str, Any], director_prompt_override: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    director_prompt = (
        director_prompt_override.strip()
        if director_prompt_override and director_prompt_override.strip()
        else load_default_director_prompt()
    )
    if settings.director_provider == "claude_converse":
        return _create_claude_director_plan(payload, director_prompt)
    if settings.director_provider == "openrouter":
        return _create_openrouter_director_plan(payload, director_prompt)
    if settings.director_provider == "openai":
        return _create_openai_director_plan(payload, director_prompt)
    raise RuntimeError(
        f"不支持的 DIRECTOR_PROVIDER: {settings.director_provider}; "
        "可选值为 openai、openrouter 或 claude_converse"
    )
