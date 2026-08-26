from __future__ import annotations

import json
import uuid
from typing import Any

from .config import settings
from .director_service import (
    _bedrock_additional_model_fields,
    _bedrock_converse_url,
    _bedrock_inference_config,
    _extract_claude_text,
    _parse_json_text,
)
from .long_time_http import LongTimeHttpError, post_json


def _world_positions(shot: dict[str, Any] | None, state: str) -> dict[str, Any]:
    if not shot:
        return {}
    spatial_lock = shot.get("spatial_lock") or {}
    value = spatial_lock.get(f"{state}_world_positions") or {}
    return value if isinstance(value, dict) else {}


def _axis(shot: dict[str, Any] | None, end: bool = False) -> dict[str, Any] | None:
    if not shot:
        return None
    sequence = (shot.get("spatial_lock") or {}).get("camera_axis_sequence") or []
    if not isinstance(sequence, list) or not sequence:
        return None
    value = sequence[-1] if end else sequence[0]
    return value if isinstance(value, dict) else None


def _boundary_checks(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    label: str,
) -> list[dict[str, str]]:
    if not left or not right:
        return []
    checks: list[dict[str, str]] = []
    left_id = str(left.get("shot_id") or "上一镜")
    right_id = str(right.get("shot_id") or "下一镜")

    cut_matches = left.get("cut_out") == right.get("cut_in")
    checks.append(
        {
            "dimension": "剪辑边界",
            "status": "pass" if cut_matches else "fail",
            "detail": (
                f"{left_id} 的 {left.get('cut_out')} 与 {right_id} 的 "
                f"{right.get('cut_in')} {'一致' if cut_matches else '不一致'}。"
            ),
            "scope": label,
        }
    )

    left_positions = _world_positions(left, "exit")
    right_positions = _world_positions(right, "entry")
    shared = sorted(set(left_positions) & set(right_positions))
    changed: list[str] = []
    for subject in shared:
        before = left_positions[subject] if isinstance(left_positions[subject], dict) else {}
        after = right_positions[subject] if isinstance(right_positions[subject], dict) else {}
        changed_fields = [
            key
            for key in ("anchor_id", "position", "facing", "pose_height", "visibility")
            if before.get(key) != after.get(key)
        ]
        if changed_fields:
            changed.append(f"{subject}（{', '.join(changed_fields)}）")
    checks.append(
        {
            "dimension": "世界站位",
            "status": "warning" if changed else "pass",
            "detail": (
                "共享主体的世界站位保持一致。"
                if not changed
                else "边界两侧存在站位字段变化：" + "、".join(changed)
            ),
            "scope": label,
        }
    )

    left_axis = _axis(left, end=True)
    right_axis = _axis(right)
    if left_axis and right_axis and left_axis.get("axis_id") == right_axis.get("axis_id"):
        side_matches = left_axis.get("side") == right_axis.get("side")
        explicitly_crossed = bool(right_axis.get("crossed"))
        checks.append(
            {
                "dimension": "摄影轴线",
                "status": "pass" if side_matches or explicitly_crossed else "fail",
                "detail": (
                    "同轴线保持在同一侧。"
                    if side_matches
                    else "轴线侧发生变化，且未声明 crossed=true。"
                    if not explicitly_crossed
                    else "已显式声明越轴。"
                ),
                "scope": label,
            }
        )
    return checks


def _deterministic_report(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    next_shot: dict[str, Any] | None,
) -> dict[str, Any]:
    checks = _boundary_checks(previous, current, "前一镜 → 当前镜")
    checks.extend(_boundary_checks(current, next_shot, "当前镜 → 后一镜"))

    plan = current.get("reference_image_plan") or {}
    prompts_ready = bool(
        plan.get("entry_state_reference_prompt_zh")
        and plan.get("exit_state_reference_edit_prompt_zh")
    )
    checks.append(
        {
            "dimension": "站位图提示词",
            "status": "pass" if prompts_ready else "fail",
            "detail": "开始与结束状态提示词均已编译。" if prompts_ready else "缺少开始或结束状态提示词。",
            "scope": "当前镜",
        }
    )
    if previous:
        source_id = plan.get("continuity_source_shot_id")
        source_ok = source_id in (None, previous.get("shot_id"))
        checks.append(
            {
                "dimension": "图片连续性来源",
                "status": "pass" if source_ok else "warning",
                "detail": (
                    f"结束/开始图连续性来源指向 {source_id or previous.get('shot_id')}。"
                    if source_ok
                    else f"连续性来源为 {source_id}，但前一镜是 {previous.get('shot_id')}。"
                ),
                "scope": "当前镜",
            }
        )

    fail_count = sum(check["status"] == "fail" for check in checks)
    warning_count = sum(check["status"] == "warning" for check in checks)
    status = "fail" if fail_count else "warning" if warning_count else "pass"
    score = max(0, 100 - fail_count * 30 - warning_count * 10)
    return {
        "shot_id": current.get("shot_id"),
        "status": status,
        "score": score,
        "summary": (
            "结构连续性检查通过。"
            if status == "pass"
            else f"发现 {fail_count} 个错误、{warning_count} 个需人工确认项。"
        ),
        "checks": checks,
        "suggestions": [],
        "analysis_source": "deterministic",
    }


def _analysis_payload(shot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not shot:
        return None
    plan = shot.get("reference_image_plan") or {}
    spatial_lock = shot.get("spatial_lock") or {}
    return {
        "shot_id": shot.get("shot_id"),
        "cut_in": shot.get("cut_in"),
        "cut_out": shot.get("cut_out"),
        "continuity": shot.get("continuity"),
        "spatial_lock": {
            "entry_world_positions": spatial_lock.get("entry_world_positions"),
            "exit_world_positions": spatial_lock.get("exit_world_positions"),
            "camera_axis_sequence": spatial_lock.get("camera_axis_sequence"),
        },
        "reference_image_plan": {
            "entry_prompt_ready": bool(plan.get("entry_state_reference_prompt_zh")),
            "exit_prompt_ready": bool(plan.get("exit_state_reference_edit_prompt_zh")),
            "continuity_source_shot_id": plan.get("continuity_source_shot_id"),
            "continuity_rule": plan.get("continuity_rule"),
        },
    }


def _ai_report(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    next_shot: dict[str, Any] | None,
) -> dict[str, Any]:
    if settings.director_provider != "claude_converse":
        raise RuntimeError("当前导演提供方不是 claude_converse")
    if not settings.claude_converse_url or not settings.claude_converse_api_key:
        raise RuntimeError("Claude Converse 未配置")

    system_text = """你是短剧逐镜连续性审片员。只分析给定的前一镜、当前镜和后一镜，不改写剧情。
重点核对：动作状态衔接、人物世界站位、摄影轴线、视线方向、身份服装、道具状态、光线、景别比例，以及开始/结束普通参考图提示词是否忠实。
screen position 改变不等于 world position 改变；只有剧情明确走位才允许世界锚点改变。
只返回 JSON：{"status":"pass|warning|fail","score":0-100,"summary":"...","checks":[{"dimension":"...","status":"pass|warning|fail","detail":"...","scope":"..."}],"suggestions":["..."]}。"""
    user_text = json.dumps(
        {
            "previous_shot": _analysis_payload(previous),
            "current_shot": _analysis_payload(current),
            "next_shot": _analysis_payload(next_shot),
        },
        ensure_ascii=False,
    )
    body: dict[str, Any] = {
        "system": [{"text": system_text}],
        "messages": [{"role": "user", "content": [{"text": user_text}]}],
        "inferenceConfig": _bedrock_inference_config(
            8000, settings.claude_director_model
        ),
    }
    additional_fields = _bedrock_additional_model_fields(
        settings.claude_director_model, settings.claude_thinking_effort
    )
    if additional_fields:
        body["additionalModelRequestFields"] = additional_fields
    try:
        response_data, _ = post_json(
            _bedrock_converse_url(
                settings.claude_converse_url,
                settings.claude_director_model,
                settings.claude_region,
            ),
            body,
            f"Bearer {settings.claude_converse_api_key}",
            {"x-request-id": uuid.uuid4().hex},
        )
    except LongTimeHttpError as exc:
        raise RuntimeError(
            f"连续性 AI 分析失败: HTTP {exc.status_code}; {exc.body}"
        ) from exc

    if isinstance(response_data, dict) and response_data.get("stopReason") == "max_tokens":
        raise RuntimeError("连续性 AI 分析响应不完整: stopReason=max_tokens")
    report = _parse_json_text(_extract_claude_text(response_data))
    if report.get("status") not in {"pass", "warning", "fail"}:
        raise RuntimeError("连续性 AI 分析返回了无效 status")
    report["shot_id"] = current.get("shot_id")
    report["analysis_source"] = "opus-5"
    return report


def analyze_shot_continuity(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    next_shot: dict[str, Any] | None,
    use_ai: bool,
) -> dict[str, Any]:
    deterministic = _deterministic_report(previous, current, next_shot)
    if not use_ai:
        return deterministic
    try:
        ai_report = _ai_report(previous, current, next_shot)
    except Exception as exc:
        deterministic["ai_warning"] = str(exc)
        return deterministic

    structural_fails = [
        check for check in deterministic["checks"] if check.get("status") == "fail"
    ]
    ai_report["checks"] = deterministic["checks"] + list(ai_report.get("checks") or [])
    if structural_fails:
        ai_report["status"] = "fail"
        ai_report["score"] = min(int(ai_report.get("score", 100)), deterministic["score"])
    return ai_report
