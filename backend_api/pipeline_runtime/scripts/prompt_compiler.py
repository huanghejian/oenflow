#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_compiler.py

Input:
  EPxxx_routed_units.json (output of video_router.py)

Output:
  EPxxx_final_video_shots.json

Responsibilities:
  - Compile frozen A-stage prompt_core + packed timeline into a model-specific prompt_zh.
  - Preserve timing, directing, acting, continuity, assets and guardrails.
  - NEVER re-route, re-direct, or invent new story beats.

Supported logical models:
  higgsfield-h3
  seedance-2.0
  seedance-2.5
  wan-3.0
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def unique_nonempty(items: Iterable[Optional[str]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items:
        if not x:
            continue
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def atomic_segments(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in (unit.get("timeline_segments") or []) if x.get("type") == "atomic"]


def all_segments(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(unit.get("timeline_segments") or [])


def rebase_timeline(text: str, start: int, end: int) -> str:
    """Shift every local integer range so multi-beat single takes remain aligned."""
    if not text:
        return f"{start}-{end}秒：保持既定导演动作与结束状态。"
    s = text.strip()
    pattern = re.compile(r"(?P<a>\d+)\s*[-~～—]\s*(?P<b>\d+)\s*秒")
    if not pattern.search(s):
        return f"{start}-{end}秒：{s}"
    return pattern.sub(
        lambda m: f"{start + int(m.group('a'))}-{start + int(m.group('b'))}秒",
        s,
    )


def compile_padding(seg: Dict[str, Any], unit: Dict[str, Any]) -> str:
    start, end = int(seg.get("start", 0)), int(seg.get("end", 0))
    instr = seg.get("instruction") or "保持当前合法状态，仅允许低风险微动，不新增剧情。"
    if seg.get("type") == "safe_padding_before":
        prefix = "【沿用首个原子镜头机位，固定状态保持】"
    else:
        prefix = "【沿用上一原子镜头结束机位，固定状态保持】"
    return f"{start}-{end}秒：{prefix}{instr}"

SCREEN_ZONE_ZH = {
    "left": "画面左侧", "right": "画面右侧", "center": "画面中央",
    "left_third": "画面左侧三分之一", "right_third": "画面右侧三分之一",
    "upper_left": "画面左上方", "upper_right": "画面右上方",
    "lower_left": "画面左下方", "lower_right": "画面右下方",
}
DEPTH_ZH = {"foreground": "前景", "midground": "中景层", "background": "后景"}


def _role_world_sentence(role: str, pos: Dict[str, Any]) -> str:
    """Translate a structured world position into model-readable Chinese.

    Internal identifiers such as A02 and enum values are intentionally kept
    out of prompt_zh. The original structure remains available in spatial_lock.
    """
    position = str(pos.get("position") or "").strip()
    facing = str(pos.get("facing") or "").strip()
    if not position and not facing:
        return ""
    text = f"[{role}]"
    if position:
        text += f"位于{position}"
    if facing:
        if facing.startswith(("朝向", "面向", "看向", "仰视", "俯视", "从")):
            text += f"，{facing}"
        else:
            text += f"，面向{facing}"
    return text


def format_spatial_prompt(unit: Dict[str, Any]) -> str:
    """Produce a concise semantic projection of spatial_lock for the model."""
    lock = unit.get("spatial_lock") or {}
    entry = copy.deepcopy(lock.get("entry_world_positions") or {})
    # A packed unit may introduce a new visible role in a later atomic shot.
    # Preserve the first known world position for every role across the unit.
    for seg in atomic_segments(unit):
        state = seg.get("spatial_state") or {}
        for key in ("entry_world_positions", "exit_world_positions"):
            for role, pos in (state.get(key) or {}).items():
                entry.setdefault(role, copy.deepcopy(pos or {}))
    visible_roles = set(((unit.get("asset_refs") or {}).get("roles") or []))
    pieces = []
    for role, pos in entry.items():
        if visible_roles and role not in visible_roles:
            continue
        sentence = _role_world_sentence(str(role), pos or {})
        if sentence:
            pieces.append(sentence)

    axes = lock.get("camera_axis_sequence") or lock.get("camera_axes") or []
    if axes:
        if any(bool(x.get("crossed")) for x in axes if isinstance(x, dict)):
            pieces.append("仅按时间轴明确的越轴设计改变拍摄侧，其余镜头保持同侧")
        else:
            pieces.append("镜头保持在既定摄影轴线同一侧，不越轴，不反转人物左右关系")
    return "；".join(unique_nonempty(pieces))


def segment_composition_prompt(seg: Dict[str, Any]) -> str:
    """Translate screen-position enums into a short visible composition cue."""
    st = seg.get("spatial_state") or {}
    parts = []
    for role, val in (st.get("screen_positions") or {}).items():
        if not isinstance(val, dict):
            continue
        zone = SCREEN_ZONE_ZH.get(str(val.get("zone") or ""), "")
        depth = DEPTH_ZH.get(str(val.get("depth") or ""), "")
        if zone or depth:
            parts.append(f"[{role}]保持在{zone}{depth}")
    return "；".join(parts)


def segment_scale_plan(seg: Dict[str, Any]) -> Dict[str, Any]:
    plan = seg.get("scale_plan")
    if isinstance(plan, dict):
        return plan
    nested = (seg.get("spatial_state") or {}).get("scale_plan")
    return nested if isinstance(nested, dict) else {}


def scale_prompt_required(plan: Dict[str, Any]) -> bool:
    subjects = plan.get("subjects") or {}
    depths = {
        str(v.get("depth") or "")
        for v in subjects.values()
        if isinstance(v, dict) and v.get("depth")
    }
    shot_size = str(plan.get("shot_size") or "")
    return len(depths) > 1 or any(x in shot_size for x in ("极远景", "中远景", "远景", "全景", "中景"))


def _percent(value: Any) -> Optional[int]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return max(1, round(float(value) * 100))


def segment_scale_prompt(seg: Dict[str, Any]) -> str:
    """Translate structured subject scale into concise model-facing Chinese."""
    plan = segment_scale_plan(seg)
    if not plan or not scale_prompt_required(plan):
        return ""
    subjects = plan.get("subjects") or {}
    clauses: List[str] = []
    parsed: List[tuple[str, float]] = []
    depths = set()
    for role, cfg in subjects.items():
        if not isinstance(cfg, dict):
            continue
        ratio = cfg.get("frame_height_ratio")
        pct = _percent(ratio)
        depth = str(cfg.get("depth") or "")
        depths.add(depth)
        if pct is None:
            continue
        unit = "单人高度" if any(x in str(role) for x in ("群", "弟子", "人群")) else "人物高度"
        clauses.append(f"[{role}]{DEPTH_ZH.get(depth, '当前景深')}{unit}约占画高{pct}%")
        if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
            parsed.append((str(role), float(ratio)))

    prefix = "明显近大远小" if len(depths) > 1 else f"严格保持{str(plan.get('shot_size') or '当前景别')}大小"
    if len(parsed) > 1 and len(depths) > 1:
        largest_role, largest_ratio = max(parsed, key=lambda x: x[1])
        smallest_role, smallest_ratio = min(parsed, key=lambda x: x[1])
        if largest_ratio > 0 and smallest_role != largest_role:
            relative = max(1, round(smallest_ratio / largest_ratio * 100))
            clauses.append(f"[{smallest_role}]视觉高度约为[{largest_role}]的{relative}%")
    relation = str(plan.get("environment_relation") or "").strip()
    # 自动推导的多层 relation 与下方硬句同义，不重复编译。
    if relation and not (len(depths) > 1 and plan.get("source") == "derived_default"):
        clauses.append(relation)
    if len(depths) > 1:
        clauses.append("不同景深主体不得等大，不得挤在同一平面")
    return prefix + "；" + "；".join(unique_nonempty(clauses))


def format_scale_prompt(unit: Dict[str, Any]) -> str:
    lines = []
    for seg in atomic_segments(unit):
        text = segment_scale_prompt(seg)
        if text:
            lines.append(f"{int(seg.get('start', 0))}-{int(seg.get('end', 0))}秒：{text}")
    return "\n".join(lines)


def transition_text(start: int, hint: Any) -> str:
    key = str(hint or "hard_cut").strip().lower()
    mapping = {
        "hard_cut": f"第{start}秒硬切。",
        "continuous": "镜头连续，不切镜。",
        "empty_shot": f"第{start}秒切入环境缓冲空镜。",
        "fade": f"第{start}秒淡入淡出转场。",
        "match_cut_shape": f"第{start}秒以相似形状匹配剪辑。",
        "match_cut_action": f"第{start}秒以连续动作匹配剪辑。",
        "emotional_cut": f"第{start}秒按情绪反应切镜。",
    }
    return mapping.get(key, f"第{start}秒硬切。")


def compile_timeline(unit: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    atomic_index = 0
    for seg in all_segments(unit):
        if seg.get("type") == "atomic":
            if atomic_index > 0:
                lines.append(transition_text(int(seg.get("start", 0)), seg.get("transition_hint")))
            pc = seg.get("prompt_core") or {}
            local = pc.get("timeline_local") or ""
            line = rebase_timeline(local, int(seg.get("start", 0)), int(seg.get("end", 0)))
            composition = segment_composition_prompt(seg)
            if composition:
                line += " 构图保持：" + composition + "。"
            scale = segment_scale_prompt(seg)
            if scale:
                line += " 比例关系：" + scale + "。"
            lines.append(line)
            atomic_index += 1
        else:
            lines.append(compile_padding(seg, unit))
    return lines


def collect_prompt_fields(unit: Dict[str, Any], key: str) -> List[str]:
    return unique_nonempty((seg.get("prompt_core") or {}).get(key) for seg in atomic_segments(unit))


def choose_scene_context(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> Dict[str, Any]:
    candidates = [c for c in contexts if c.get("scene_asset") == unit.get("scene_asset")]
    if not candidates:
        return {}
    if len(candidates) == 1:
        return candidates[0]

    text_parts = [unit.get("continuity", {}).get("entry", ""), unit.get("continuity", {}).get("exit", "")]
    text_parts += collect_prompt_fields(unit, "guardrail")
    hay = " ".join(text_parts)
    best, best_score = candidates[0], -1
    for c in candidates:
        state = str(c.get("state", ""))
        score = 0
        # Simple keyword overlap is enough because prompt_core already carries exact state guards.
        for kw in ("完整", "破碎", "消散", "烟尘", "残光", "护山大阵"):
            if kw in state and kw in hay:
                score += 1
        if score > best_score:
            best, best_score = c, score
    return best


def compact_guardrails(unit: Dict[str, Any]) -> str:
    """Clause-level guardrail normalization and deduplication."""
    clauses: List[str] = []
    seen = set()
    for raw in collect_prompt_fields(unit, "guardrail"):
        cleaned = raw.replace("【", "").replace("】", "")
        for clause in re.split(r"[；;。]+", cleaned):
            clause = clause.strip(" ，,：:\n\t")
            if not clause:
                continue
            if ("字幕" in clause or "字卡" in clause or "文字" in clause) and any(
                token in clause for token in ("不出现", "不生成", "禁止", "无")
            ):
                clause = "画面无字幕、字卡和其他文字"
            key = re.sub(r"\s+", "", clause)
            if key not in seen:
                seen.add(key)
                clauses.append(clause)
    if not any("字幕" in x or "字卡" in x or "文字" in x for x in clauses):
        clauses.append("画面无字幕、字卡和其他文字")
    return "；".join(clauses)


def common_parts(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> Dict[str, str]:
    ctx = choose_scene_context(unit, contexts)
    anchors = collect_prompt_fields(unit, "spatial_anchor")
    sounds = collect_prompt_fields(unit, "sound")
    lights = collect_prompt_fields(unit, "lighting")
    timeline = compile_timeline(unit)

    style = str(ctx.get("style_lock", "")).strip()
    lighting = "；".join(lights) or str(ctx.get("lighting", "")).strip()
    scene_asset = str(unit.get("scene_asset") or "").strip()
    scene_bits = unique_nonempty([
        f"场景为[{scene_asset}]" if scene_asset else "",
        style,
        lighting,
    ])
    continuity = unit.get("continuity") or {}
    has_scale_prompt = any(segment_scale_prompt(seg) for seg in atomic_segments(unit))

    return {
        "scene": "；".join(scene_bits),
        "spatial": format_spatial_prompt(unit) or "；".join(anchors),
        "guard": compact_guardrails(unit),
        "sound": "；".join(sounds),
        "timeline": "\n".join(timeline),
        "entry": str(continuity.get("entry") or "").strip(),
        "exit": str(continuity.get("exit") or "").strip(),
        "reference_scale_guard": (
            "角色参考素材只用于身份、脸部、发型和服装，"
            "不复制参考图的取景范围、人物大小或背景构图"
        ) if has_scale_prompt else "",
        "take_rule": (
            "本镜为从一个剪辑点到下一个剪辑点的完整连续镜头，内部不切镜，"
            "所有动作按时间轴自然连续完成"
        ) if unit.get("single_take") or unit.get("indivisible") else "",
    }


def _camera_reference_text(unit: Dict[str, Any]) -> str:
    segs = atomic_segments(unit)
    if not segs:
        return ""
    camera = segs[0].get("camera_plan") or {}
    movement = {
        "fixed": "固定机位",
        "static": "固定机位",
        "locked": "锁定机位",
    }.get(str(camera.get("movement") or "").strip().lower(), str(camera.get("movement") or ""))
    # When a structured scale plan exists it is safer than free-form composition
    # prose.  Phrases such as “人物占画面上三分之一” are frequently interpreted
    # by image models as subject size instead of screen position.
    composition = "" if segment_scale_prompt(segs[0]) else str(camera.get("composition") or "")
    return "，".join(unique_nonempty([
        str(camera.get("shot_size") or ""),
        str(camera.get("angle") or ""),
        composition,
        movement,
    ]))


def _reference_asset_usage(refs: List[Dict[str, Any]]) -> str:
    """Explain what each logical reference is allowed to control.

    Image generators otherwise tend to inherit the crop, subject scale, pose-sheet
    background, or landscape aspect ratio from an attached asset.
    """
    grouped: Dict[str, List[str]] = {"role": [], "scene": [], "prop": []}
    for ref in refs:
        if ref.get("derived"):
            continue
        asset_type = str(ref.get("asset_type") or "")
        asset_id = str(ref.get("asset_id") or "").strip()
        if asset_id and asset_type in grouped:
            grouped[asset_type].append(asset_id)
    clauses: List[str] = []
    if grouped["role"]:
        clauses.append(
            "角色参考图仅锁定身份、脸部、发型和服装，不继承姿态表的背景、裁切、人物大小或站位"
        )
    if grouped["scene"]:
        clauses.append("场景参考图仅锁定建筑地标、材质与环境风格，不继承横版画幅")
    if grouped["prop"]:
        clauses.append("道具参考图仅锁定道具形制、颜色和材质，不继承其原图构图与尺寸")
    return "；".join(clauses)


def _reference_spatial_hard_guards(unit: Dict[str, Any]) -> str:
    """Turn structured world/screen/scale data into still-image hard guards."""
    segs = atomic_segments(unit)
    if not segs:
        return ""
    seg = segs[0]
    state = seg.get("spatial_state") or {}
    world = state.get("entry_world_positions") or {}
    clauses: List[str] = []
    for role, pos in world.items():
        if not isinstance(pos, dict):
            continue
        position = str(pos.get("position") or "")
        pose_height = str(pos.get("pose_height") or "")
        if pose_height == "elevated" or re.search(r"顶部|屋顶|高处|牌楼|檐顶|城楼", position):
            clauses.append(
                f"[{role}]必须以完整小比例人物站在[{position}]这一建筑地标上，双脚与该高处承重面接触；"
                "不得移到广场地面、前景石台或独立底座，不得生成前景巨人"
            )
    composition = segment_composition_prompt(seg)
    if composition:
        clauses.append(composition)
        clauses.append("画面方位只约束位置，不代表放大人物；人物大小必须服从下述画高比例")
    scale = segment_scale_prompt(seg)
    if scale:
        clauses.append(scale)
    return "；".join(unique_nonempty(clauses))


def _pre_result_exit_guard(exit_state: str) -> str:
    """Preserve pre-impact semantics such as approaching / about to / pre-reaction."""
    if not any(token in exit_state for token in ("逼近", "尚未", "即将", "前一刻", "预反应", "未接触")):
        return ""
    return (
        "该结束状态仍处于结果发生之前：运动物与目标之间保留清楚可见的空气间隙，"
        "间隙约占画高3%至6%，运动物整体仍位于目标外边界之外；"
        "禁止接触、刺入、碰撞闪光、爆炸、裂纹、碎片、冲击波或受伤结果"
    )


def _clean_boundary_state(value: str) -> str:
    """Accept old wrapped group prompts while compiling a single clean state clause."""
    text = str(value or "").strip()
    text = re.sub(r"^(?:首帧|尾帧)普通参考图，9:16短剧画面。", "", text)
    text = text.replace(
        "；要求构图清晰、身份稳定、可作为后续视频生成的普通图片参考。",
        "",
    )
    return text.strip("；。 ")


def _exit_staging_reserve(exit_state: str) -> str:
    """Reserve composition space in the entry still for the exit-state action."""
    if not exit_state:
        return ""
    if "顶部" in exit_state and any(token in exit_state for token in ("逼近", "落下", "压下", "降下")):
        return (
            "为同镜结束动作预留上方运动通道：目标的顶部外轮廓必须完整落在画内上方约三分之一处，"
            "其外侧上方保留不少于画高20%的无遮挡天空或云雾负空间；"
            "开始图不得提前出现随后才进入的运动物"
        )
    return "在不提前显示结束动作的前提下，为该结束动作预留清楚、无遮挡的画内运动通道"


def compile_reference_image_plan(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compile full-color entry and exit frame prompts from the same bound assets."""
    p = common_parts(unit, contexts)
    refs = [x for x in (unit.get("references") or []) if isinstance(x, dict)]
    asset_ids = unique_nonempty(
        [str(x.get("asset_id") or "") for x in refs if not x.get("derived")]
    )
    derived_ids = {
        str(x.get("derived_role") or ""): str(x.get("asset_id") or "")
        for x in refs if x.get("derived")
    }
    assets = "、".join(f"[{x}]" for x in asset_ids)
    camera = _camera_reference_text(unit)
    asset_usage = _reference_asset_usage(refs)
    spatial_hard_guards = _reference_spatial_hard_guards(unit)
    entry_state = _clean_boundary_state(p["entry"])
    exit_state = _clean_boundary_state(p["exit"])
    staging_reserve = _exit_staging_reserve(exit_state)
    stable = "；".join(unique_nonempty([p["scene"], p["spatial"], camera, spatial_hard_guards]))
    entry_prompt = (
        (f"严格参考逻辑资产：{assets}。" if assets else "")
        + (f"参考图职责：{asset_usage}。" if asset_usage else "")
        + (f"固定视觉与构图：{stable}。" if stable else "")
        + (f"结束动作预留区：{staging_reserve}。" if staging_reserve else "")
        + f"开始状态：{entry_state}。"
        + "保持角色身份、服装、道具状态、世界站位、主光方向和9:16构图准确；画面无文字字幕。"
    )
    exit_prompt = (
        (f"严格参考逻辑资产：{assets}。" if assets else "")
        + (f"参考图职责：{asset_usage}。" if asset_usage else "")
        + (f"固定视觉与构图：{stable}。" if stable else "")
        + "保持人物身份、服装、场景结构、世界站位关系、主光方向和整体风格；"
        + f"结束状态：{exit_state}。"
        + (f"{_pre_result_exit_guard(exit_state)}。" if _pre_result_exit_guard(exit_state) else "")
    )
    if unit.get("cut_out") == "concealed_cut":
        exit_prompt += "结束构图必须形成导演已指定的全屏遮挡、烟雾、闪光或甩镜模糊接缝，便于隐藏剪辑。"
    exit_prompt += "不得增加剧情、人物、道具或文字字幕。"
    return {
        "usage": "ordinary_image_reference",
        "generation_strategy": "same_image_model_generate_then_edit",
        "input_asset_ids": asset_ids,
        "output_asset_ids": {
            "entry": derived_ids.get("entry_state_reference", f"shotref::{unit.get('unit_id')}::entry"),
            "exit": derived_ids.get("exit_state_reference", f"shotref::{unit.get('unit_id')}::exit"),
        },
        "entry_state_reference_prompt_zh": entry_prompt,
        "exit_state_reference_edit_prompt_zh": exit_prompt,
    }


def compile_s25(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> str:
    p = common_parts(unit, contexts)
    lines = [
        f"场景：{p['scene']}。" if p["scene"] else "",
        f"空间关系：{p['spatial']}。" if p["spatial"] else "",
        f"连续镜头规则：{p['take_rule']}。" if p["take_rule"] else "",
        f"初始状态：{p['entry']}。" if p["entry"] else "",
        "时间轴：",
        p["timeline"],
        f"结束状态：{p['exit']}。" if p["exit"] else "",
        f"声音：{p['sound']}。" if p["sound"] else "",
        f"参考素材约束：{p['reference_scale_guard']}。" if p["reference_scale_guard"] else "",
        f"限制：{p['guard']}。" if p["guard"] else "",
    ]
    return "\n".join(x for x in lines if x)


def compile_s20(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> str:
    p = common_parts(unit, contexts)
    lines = [
        f"场景：{p['scene']}。" if p["scene"] else "",
        f"空间关系：{p['spatial']}。" if p["spatial"] else "",
        f"连续镜头规则：{p['take_rule']}。" if p["take_rule"] else "",
        "时间轴：",
        p["timeline"],
        f"声音：{p['sound']}。" if p["sound"] else "",
        f"参考素材约束：{p['reference_scale_guard']}。" if p["reference_scale_guard"] else "",
        f"限制：{p['guard']}。" if p["guard"] else "",
    ]
    return "\n".join(x for x in lines if x)


def compile_h3(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> str:
    p = common_parts(unit, contexts)
    lines = [
        f"场景：{p['scene']}。" if p["scene"] else "",
        f"空间关系：{p['spatial']}。" if p["spatial"] else "",
        f"连续镜头规则：{p['take_rule']}。" if p["take_rule"] else "",
        "镜头时间轴：",
        p["timeline"],
        f"声音：{p['sound']}。" if p["sound"] else "",
        f"参考素材约束：{p['reference_scale_guard']}。" if p["reference_scale_guard"] else "",
        f"限制：{p['guard']}。" if p["guard"] else "",
    ]
    return "\n".join(x for x in lines if x)


def compile_wan(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> str:
    p = common_parts(unit, contexts)
    lines = [
        f"场景与风格：{p['scene']}。" if p["scene"] else "",
        f"主体空间关系：{p['spatial']}。" if p["spatial"] else "",
        f"连续镜头规则：{p['take_rule']}。" if p["take_rule"] else "",
        "镜头时间轴：",
        p["timeline"],
        f"声音：{p['sound']}。" if p["sound"] else "",
        f"参考素材约束：{p['reference_scale_guard']}。" if p["reference_scale_guard"] else "",
        f"限制：{p['guard']}。" if p["guard"] else "",
    ]
    return "\n".join(x for x in lines if x)


def compile_prompt(unit: Dict[str, Any], contexts: List[Dict[str, Any]]) -> str:
    model = unit.get("model")
    if model == "seedance-2.5":
        return compile_s25(unit, contexts)
    if model == "seedance-2.0":
        return compile_s20(unit, contexts)
    if model == "higgsfield-h3":
        return compile_h3(unit, contexts)
    if model == "wan-3.0":
        return compile_wan(unit, contexts)
    raise ValueError(f"Unsupported model: {model}")


def validate_timeline(unit: Dict[str, Any]) -> None:
    duration = int(unit.get("duration", 0))
    segs = all_segments(unit)
    if not segs:
        raise ValueError(f"{unit.get('unit_id')}: missing timeline_segments")
    if (unit.get("single_take") or unit.get("indivisible")) and len(atomic_segments(unit)) != 1:
        raise ValueError(f"{unit.get('unit_id')}: 不可拆分连续镜头必须且只能包含一个 atomic segment")
    cursor = 0
    for seg in segs:
        s, e = int(seg.get("start", -1)), int(seg.get("end", -1))
        if s != cursor:
            raise ValueError(f"{unit.get('unit_id')}: timeline gap/overlap at {cursor}->{s}")
        if e <= s:
            raise ValueError(f"{unit.get('unit_id')}: invalid segment {s}-{e}")
        cursor = e
    if cursor != duration:
        raise ValueError(f"{unit.get('unit_id')}: timeline end {cursor} != duration {duration}")




def _shot_size_categories(raw_size: Any) -> List[str]:
    s = str(raw_size or "").strip()
    if not s:
        return []
    pairs = [
        ("大特写", "大特写"), ("极远景", "极远景"), ("中远景", "中远景"),
        ("远景", "远景"), ("大全景", "全景"), ("全景", "全景"),
        ("中近景", "中近景"), ("中景", "中景"), ("近景", "近景"), ("特写", "特写"),
    ]
    cats: List[str] = []
    for token, cat in pairs:
        if token in s and cat not in cats:
            cats.append(cat)
    if "大特写" in cats and "特写" in cats:
        residual = s.replace("大特写", "")
        if "特写" not in residual:
            cats = [c for c in cats if c != "特写"]
    return cats


def assert_sr_shot_sizes(unit: Dict[str, Any]) -> None:
    preset = str((unit.get("model_params") or {}).get("resolution_preset", ""))
    if "SR" not in preset.upper():
        return
    allowed = {"特写", "大特写"}
    bad = []
    for seg in atomic_segments(unit):
        raw = (seg.get("camera_plan") or {}).get("shot_size", "")
        cats = _shot_size_categories(raw)
        if len(cats) != 1 or not set(cats).issubset(allowed):
            bad.append({"atomic_id": seg.get("atomic_id"), "shot_size": raw, "categories": cats})
    if bad or not atomic_segments(unit):
        raise ValueError(
            f"{unit.get('unit_id')}: SR preset {preset} 仅允许所有原子段均为特写/大特写；违规段={bad}"
        )

def compile_document(doc: Dict[str, Any], default_transition: str = "hard_cut", keep_routing_debug: bool = False) -> Dict[str, Any]:
    contexts = doc.get("scene_contexts", []) or []
    units = doc.get("routed_units", []) or []
    shots = []

    for i, unit in enumerate(units):
        validate_timeline(unit)
        assert_sr_shot_sizes(unit)
        prompt = compile_prompt(unit, contexts)
        previous_unit = units[i - 1] if i > 0 else None
        next_unit = units[i + 1] if i + 1 < len(units) else None
        same_as_previous = bool(previous_unit and previous_unit.get("scene_asset") == unit.get("scene_asset"))
        same_as_next = bool(next_unit and next_unit.get("scene_asset") == unit.get("scene_asset"))
        cut_in = unit.get("cut_in") or (default_transition if same_as_previous else "scene_start")
        cut_out = unit.get("cut_out") or ((next_unit or {}).get("cut_in") if same_as_next else "scene_end") or default_transition
        reference_image_plan = compile_reference_image_plan(unit, contexts)
        if same_as_previous and cut_in not in ("scene_start", "fade"):
            reference_image_plan["continuity_source_shot_id"] = previous_unit.get("unit_id")
            reference_image_plan["depends_on_output_asset_id"] = f"shotref::{previous_unit.get('unit_id')}::exit"
            reference_image_plan["continuity_rule"] = (
                "使用上一镜结束状态参考图作为图片编辑参考，只改变本镜明确要求的机位、景别和动作状态"
            )
        shot: Dict[str, Any] = {
            "shot_id": unit.get("unit_id"),
            "atomic_ids": copy.deepcopy(unit.get("atomic_ids", [])),
            "group_id": "|".join(unit.get("group_ids", []) or []),
            "model": unit.get("model"),
            "model_params": copy.deepcopy(unit.get("model_params", {})),
            "duration": int(unit.get("duration", 0)),
            "transition": cut_in,
            "cut_in": cut_in,
            "cut_out": cut_out,
            "single_take": bool(unit.get("single_take") or unit.get("indivisible")),
            "indivisible": bool(unit.get("indivisible") or unit.get("single_take")),
            "scene_asset": unit.get("scene_asset"),
            "complexity": copy.deepcopy(unit.get("complexity", {})),
            "references": copy.deepcopy(unit.get("references", [])),
            "reference_binding_status": "logical_only",
            "reference_summary": copy.deepcopy(unit.get("reference_summary", {})),
            "spatial_lock": copy.deepcopy(unit.get("spatial_lock", {})),
            "spatial_segments": [
                {
                    "atomic_id": seg.get("atomic_id"),
                    "start": int(seg.get("start", 0)),
                    "end": int(seg.get("end", 0)),
                    "spatial_state": copy.deepcopy(seg.get("spatial_state", {})),
                }
                for seg in atomic_segments(unit)
            ],
            "spatial_prompt": format_spatial_prompt(unit),
            "scale_segments": [
                {
                    "atomic_id": seg.get("atomic_id"),
                    "start": int(seg.get("start", 0)),
                    "end": int(seg.get("end", 0)),
                    "scale_plan": copy.deepcopy(segment_scale_plan(seg)),
                }
                for seg in atomic_segments(unit)
            ],
            "scale_prompt": format_scale_prompt(unit),
            "prompt_zh": prompt,
            "reference_image_plan": reference_image_plan,
            "continuity": copy.deepcopy(unit.get("continuity", {})),
        }
        if unit.get("beats"):
            shot["beats"] = copy.deepcopy(unit["beats"])
        if unit.get("tts"):
            shot["tts"] = unit["tts"]
        if keep_routing_debug and unit.get("routing_decision"):
            shot["routing_decision"] = copy.deepcopy(unit["routing_decision"])
        shots.append(shot)

    result = {
        "contract_version": "cut_take_v1",
        "routing_tier": doc.get("routing_tier", "medium"),
        "aspect_ratio": doc.get("aspect_ratio", "9:16"),
        "target_resolution": doc.get("target_resolution", "720P"),
        "scene_contexts": copy.deepcopy(contexts),
        "shots": shots,
    }
    if doc.get("asset_catalog"):
        result["asset_catalog"] = copy.deepcopy(doc.get("asset_catalog"))
    result["reference_image_jobs"] = [
        {
            "shot_id": shot.get("shot_id"),
            **copy.deepcopy(shot.get("reference_image_plan", {})),
        }
        for shot in shots
    ]
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile routed generation units into model-specific prompt_zh video shots")
    ap.add_argument("input", help="Input routed_units JSON")
    ap.add_argument("output", help="Output final video shots JSON")
    ap.add_argument("--default-transition", default="hard_cut", help="Default transition value")
    ap.add_argument("--keep-routing-debug", action="store_true", help="Keep routing_decision in final shots for debugging")
    args = ap.parse_args()

    doc = load_json(args.input)
    final_doc = compile_document(doc, args.default_transition, args.keep_routing_debug)
    save_json(args.output, final_doc)
    print(f"Compiled {len(final_doc['shots'])} final video prompts -> {args.output}")


if __name__ == "__main__":
    main()
