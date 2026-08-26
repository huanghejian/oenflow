#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短剧原子分镜打包器（A阶段 JSON -> generation_units）

目标：
1. 不再次调用 LLM。
2. 尊重 A 阶段给出的 merge_relation / independent_generation / continuity。
3. 以确定性规则把 atomic_shots 向后扫描并合并为 generation_units。
4. 汇总 routing_requirements / complexity / asset_refs / continuity / tts，
   供后续“模型路由器 + 模型 Prompt 编译器”直接消费。

默认策略（balanced）：
- preferred：只要硬约束通过且不超过 max_duration，优先合并。
- allowed：当当前单元不足 min_unit_duration，或合并后不超过 target_duration 时合并。
- forbidden / 缺失：停止。
- independent_generation=true：强制独立。

说明：
- 本脚本只做“导演已经允许范围内的确定性打包”，不选择 H3/S2/Wan。
- max_duration 默认 15 秒，是保守值，便于后续仍保留 H3/S2.0 候选资格。
  如果你的后端路由器支持先评估 S2.5/Wan 的长单元，可以通过 --max-duration 30 放宽。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REQ_LEVEL = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
REQ_LEVEL_REV = {v: k for k, v in REQ_LEVEL.items()}
COMPLEXITY_LEVEL = {"low": 1, "medium": 2, "high": 3}
COMPLEXITY_LEVEL_REV = {v: k for k, v in COMPLEXITY_LEVEL.items()}
PRIORITY_LEVEL = {"normal": 1, "key": 2, "climax": 3}
PRIORITY_LEVEL_REV = {v: k for k, v in PRIORITY_LEVEL.items()}

VALID_MERGE_RELATIONS = {"preferred", "allowed", "forbidden"}
VALID_CUT_TYPES = {
    "scene_start", "scene_end", "hard_cut", "concealed_cut",
    "match_cut_action", "match_cut_shape", "fade",
}
SPATIAL_RISK_LEVEL = {"low": 1, "medium": 2, "high": 3, "unknown": 2}


@dataclass
class PackerConfig:
    mode: str = "balanced"  # balanced | max_safe | preferred_only
    min_unit_duration: int = 4
    target_duration: int = 15
    max_duration: int = 30
    allow_cross_group: bool = True
    strict_scene_asset: bool = True
    strict_missing_merge_relation: bool = True
    keep_debug_trace: bool = True
    max_spatial_cut_risk: str = "medium"


@dataclass
class MergeDecision:
    can_merge: bool
    reason: str
    relation: Optional[str] = None


@dataclass
class UnitBuilder:
    shots: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def content_duration(self) -> int:
        return sum(int(s.get("atomic_duration", 0)) for s in self.shots)

    @property
    def first(self) -> Dict[str, Any]:
        return self.shots[0]

    @property
    def last(self) -> Dict[str, Any]:
        return self.shots[-1]

    def add(self, shot: Dict[str, Any]) -> None:
        self.shots.append(shot)


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def validate_input(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    shots = data.get("atomic_shots")
    if not isinstance(shots, list) or not shots:
        errors.append("atomic_shots 必须是非空数组")
        return errors

    seen = set()
    for idx, shot in enumerate(shots):
        prefix = f"atomic_shots[{idx}]"
        atomic_id = shot.get("atomic_id")
        if not atomic_id:
            errors.append(f"{prefix}.atomic_id 缺失")
        elif atomic_id in seen:
            errors.append(f"atomic_id 重复: {atomic_id}")
        else:
            seen.add(atomic_id)

        dur = shot.get("atomic_duration")
        if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
            errors.append(f"{prefix}.atomic_duration 必须是正整数")

        if not shot.get("scene_asset"):
            errors.append(f"{prefix}.scene_asset 缺失")

        relation = shot.get("merge_relation")
        if relation is not None and relation not in VALID_MERGE_RELATIONS:
            errors.append(f"{prefix}.merge_relation 非法: {relation}")

        for key in ("cut_in", "cut_out"):
            value = shot.get(key)
            if value is not None and value not in VALID_CUT_TYPES:
                errors.append(f"{prefix}.{key} 非法: {value}")

        if shot.get("single_take") and not shot.get("indivisible"):
            errors.append(f"{prefix}: single_take=true 时必须同时 indivisible=true")

        continuity = shot.get("continuity", {})
        if not isinstance(continuity, dict):
            errors.append(f"{prefix}.continuity 必须是对象")

    return errors


def is_independent(shot: Dict[str, Any]) -> bool:
    return bool(shot.get("independent_generation"))


def is_indivisible(shot: Dict[str, Any]) -> bool:
    """V7.3: a cut-to-cut single take is one immutable video request."""
    return bool(shot.get("indivisible") or shot.get("single_take"))


def max_requirement(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, str]:
    keys = set(a) | set(b)
    out: Dict[str, str] = {}
    for k in sorted(keys):
        av = a.get(k, "none")
        bv = b.get(k, "none")
        ai = REQ_LEVEL.get(av, 0)
        bi = REQ_LEVEL.get(bv, 0)
        out[k] = REQ_LEVEL_REV[max(ai, bi)]
    return out


def max_complexity(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, str]:
    keys = set(a) | set(b)
    out: Dict[str, str] = {}
    for k in sorted(keys):
        av = a.get(k, "low")
        bv = b.get(k, "low")
        ai = COMPLEXITY_LEVEL.get(av, 1)
        bi = COMPLEXITY_LEVEL.get(bv, 1)
        out[k] = COMPLEXITY_LEVEL_REV[max(ai, bi)]
    return out


def max_story_priority(shots: List[Dict[str, Any]]) -> str:
    level = 1
    for s in shots:
        level = max(level, PRIORITY_LEVEL.get(s.get("story_priority", "normal"), 1))
    return PRIORITY_LEVEL_REV[level]


def unique_in_order(values: List[Any]) -> List[Any]:
    seen = set()
    out = []
    for v in values:
        key = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out



def _screen_side(zone: Any) -> str:
    z = str(zone or "").strip().lower()
    if any(x in z for x in ("left", "左")):
        return "left"
    if any(x in z for x in ("right", "右")):
        return "right"
    if any(x in z for x in ("center", "middle", "中")):
        return "center"
    return "other"


def spatial_cut_risk(cur: Dict[str, Any], nxt: Dict[str, Any]) -> Tuple[str, List[str]]:
    """评估相邻原子镜头在同一 generation_unit 内快切的空间跳变风险。"""
    a = cur.get("spatial_state") or {}
    b = nxt.get("spatial_state") or {}
    reasons: List[str] = []
    if not a or not b:
        return "unknown", ["missing_structured_spatial_state"]

    # 世界 entry/exit 必须严格可继承；若空间校验器正常运行，这里应相等。
    a_exit = a.get("exit_world_positions") or {}
    b_entry = b.get("entry_world_positions") or {}
    common_world = set(a_exit) & set(b_entry)
    for role in common_world:
        aa = (a_exit.get(role) or {}).get("anchor_id")
        bb = (b_entry.get(role) or {}).get("anchor_id")
        if aa and bb and aa != bb:
            reasons.append(f"world_anchor_jump:{role}:{aa}->{bb}")
            return "high", reasons

    axis_a = a.get("camera_axis") or {}
    axis_b = b.get("camera_axis") or {}
    if axis_a and axis_b:
        if axis_a.get("axis_id") == axis_b.get("axis_id"):
            sa = str(axis_a.get("side") or "").lower()
            sb = str(axis_b.get("side") or "").lower()
            if sa and sb and sa != sb:
                reasons.append(f"same_axis_side_change:{sa}->{sb}")
                return "high", reasons
        elif axis_a.get("axis_id") and axis_b.get("axis_id"):
            reasons.append("camera_axis_changed")

    scr_a = a.get("screen_positions") or {}
    scr_b = b.get("screen_positions") or {}
    common = set(scr_a) & set(scr_b)
    flips = 0
    for role in common:
        za = _screen_side((scr_a.get(role) or {}).get("zone") if isinstance(scr_a.get(role), dict) else scr_a.get(role))
        zb = _screen_side((scr_b.get(role) or {}).get("zone") if isinstance(scr_b.get(role), dict) else scr_b.get(role))
        if {za, zb} == {"left", "right"}:
            flips += 1
    # 同轴同侧且两名以上角色同时左右翻转，通常意味着视频模型会误读为站位互换。
    if flips >= 2 and axis_a and axis_b and axis_a.get("axis_id") == axis_b.get("axis_id") and axis_a.get("side") == axis_b.get("side"):
        reasons.append("multi_role_screen_side_flip_same_axis")
        return "high", reasons

    changes_a = a.get("position_changes") or []
    changes_b = b.get("position_changes") or []
    if changes_a or changes_b:
        reasons.append("explicit_world_position_change_near_cut")

    if reasons or set(scr_a) != set(scr_b):
        if set(scr_a) != set(scr_b):
            reasons.append("visible_subject_set_changed")
        return "medium", reasons
    return "low", ["stable_world_axis_screen_relation"]


def aggregate_spatial_lock(shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not shots:
        return {}
    first = shots[0].get("spatial_state") or {}
    last = shots[-1].get("spatial_state") or {}
    if not first and not last:
        return {}
    axes = []
    screen_by_atomic: Dict[str, Any] = {}
    changes: List[Dict[str, Any]] = []
    for shot in shots:
        st = shot.get("spatial_state") or {}
        if st.get("camera_axis"):
            axes.append(copy.deepcopy(st["camera_axis"]))
        if st.get("screen_positions"):
            screen_by_atomic[str(shot.get("atomic_id"))] = copy.deepcopy(st["screen_positions"])
        for ch in st.get("position_changes") or []:
            item = copy.deepcopy(ch)
            item["atomic_id"] = shot.get("atomic_id")
            changes.append(item)
    out: Dict[str, Any] = {
        "entry_world_positions": copy.deepcopy(first.get("entry_world_positions") or {}),
        "exit_world_positions": copy.deepcopy(last.get("exit_world_positions") or {}),
        "camera_axis_sequence": unique_in_order(axes),
        "screen_positions_by_atomic": screen_by_atomic,
    }
    if changes:
        out["position_changes"] = changes
    return out


def aggregate_asset_refs(shots: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    roles: List[str] = []
    props: List[str] = []
    for s in shots:
        refs = s.get("asset_refs", {}) or {}
        roles.extend(refs.get("roles", []) or [])
        props.extend(refs.get("props", []) or [])
    result: Dict[str, List[str]] = {}
    roles = unique_in_order(roles)
    props = unique_in_order(props)
    if roles:
        result["roles"] = roles
    if props:
        result["props"] = props
    return result


def aggregate_requirements(shots: List[Dict[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for s in shots:
        result = max_requirement(result, s.get("routing_requirements", {}) or {})
    return result


def aggregate_complexity(shots: List[Dict[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for s in shots:
        result = max_complexity(result, s.get("complexity", {}) or {})
    return result


def relation_between(current: Dict[str, Any], nxt: Dict[str, Any], cfg: PackerConfig) -> Optional[str]:
    # A 阶段约定：当前 shot 的 merge_relation 表示“当前 -> 下一镜”的关系。
    relation = current.get("merge_relation")
    if relation is None and not cfg.strict_missing_merge_relation:
        return "allowed"
    return relation


def hard_merge_check(builder: UnitBuilder, nxt: Dict[str, Any], cfg: PackerConfig) -> MergeDecision:
    cur = builder.last

    if is_independent(cur):
        return MergeDecision(False, "current_independent_generation")
    if is_independent(nxt):
        return MergeDecision(False, "next_independent_generation")

    relation = relation_between(cur, nxt, cfg)
    if relation is None:
        return MergeDecision(False, "missing_merge_relation", None)
    if relation == "forbidden":
        return MergeDecision(False, "merge_relation_forbidden", relation)

    if cfg.strict_scene_asset and cur.get("scene_asset") != nxt.get("scene_asset"):
        return MergeDecision(False, "scene_asset_changed", relation)

    if not cfg.allow_cross_group and cur.get("group_id") != nxt.get("group_id"):
        return MergeDecision(False, "group_id_changed", relation)

    candidate_duration = builder.content_duration + int(nxt.get("atomic_duration", 0))
    if candidate_duration > cfg.max_duration:
        return MergeDecision(False, "max_duration_exceeded", relation)

    # continuity 的语义可否衔接由 A 阶段 merge_relation 负责；
    # 此处仅做字段存在性保护，不尝试用字符串相似度“猜”语义。
    if not isinstance(cur.get("continuity", {}), dict) or not isinstance(nxt.get("continuity", {}), dict):
        return MergeDecision(False, "continuity_missing_or_invalid", relation)

    risk, risk_reasons = spatial_cut_risk(cur, nxt)
    max_allowed = SPATIAL_RISK_LEVEL.get(cfg.max_spatial_cut_risk, 2)
    if SPATIAL_RISK_LEVEL.get(risk, 2) > max_allowed:
        return MergeDecision(False, "spatial_cut_risk_high:" + ",".join(risk_reasons), relation)

    return MergeDecision(True, "hard_checks_passed", relation)


def soft_merge_check(builder: UnitBuilder, nxt: Dict[str, Any], hard: MergeDecision, cfg: PackerConfig) -> MergeDecision:
    if not hard.can_merge:
        return hard

    relation = hard.relation
    candidate_duration = builder.content_duration + int(nxt.get("atomic_duration", 0))

    if cfg.mode == "max_safe":
        return MergeDecision(True, "max_safe_accept", relation)

    if cfg.mode == "preferred_only":
        if relation == "preferred":
            return MergeDecision(True, "preferred_only_accept", relation)
        return MergeDecision(False, "preferred_only_reject_allowed", relation)

    # balanced
    if relation == "preferred":
        return MergeDecision(True, "preferred_accept", relation)

    if relation == "allowed":
        # 单元还没达到最短生成时长，优先吸收。
        if builder.content_duration < cfg.min_unit_duration:
            return MergeDecision(True, "allowed_needed_for_min_duration", relation)
        # 在目标甜蜜区间内允许继续吸收；达到后自然停止，避免无意义长卷。
        if candidate_duration <= cfg.target_duration:
            return MergeDecision(True, "allowed_within_target_duration", relation)
        return MergeDecision(False, "allowed_beyond_target_duration", relation)

    return MergeDecision(False, "unknown_relation", relation)


def build_padding_plan(shots: List[Dict[str, Any]], min_unit_duration: int) -> Tuple[int, Dict[str, int]]:
    content_duration = sum(int(s.get("atomic_duration", 0)) for s in shots)
    before = 0
    after = 0

    # 独立镜头可能由 A 阶段给了安全 padding，例如 2秒内容 + 前1 + 后1 = 4秒。
    if len(shots) == 1:
        safe_padding = shots[0].get("safe_padding") or {}
        if isinstance(safe_padding, dict):
            before = max(0, int(safe_padding.get("before", 0) or 0))
            after = max(0, int(safe_padding.get("after", 0) or 0))

    duration = content_duration + before + after
    if duration < min_unit_duration:
        # 不新增剧情，只在末尾增加状态保持。真正的视频模型最短时长（如 H3=5）
        # 由后续路由器在 model 锁定后再二次补足。
        after += min_unit_duration - duration
        duration = min_unit_duration

    return duration, {"before": before, "after": after}


def build_timeline_segments(shots: List[Dict[str, Any]], padding: Dict[str, int]) -> List[Dict[str, Any]]:
    cursor = int(padding.get("before", 0))
    segments: List[Dict[str, Any]] = []

    if cursor > 0:
        segments.append({
            "type": "safe_padding_before",
            "start": 0,
            "end": cursor,
            "instruction": "保持首个原子镜头合法进入状态，仅允许呼吸、衣发、光尘等低风险微动，不新增剧情。",
        })

    for s in shots:
        dur = int(s.get("atomic_duration", 0))
        start = cursor
        end = cursor + dur
        seg: Dict[str, Any] = {
            "type": "atomic",
            "atomic_id": s.get("atomic_id"),
            "group_id": s.get("group_id"),
            "start": start,
            "end": end,
            "narrative_class": s.get("narrative_class"),
            "narrative_function": s.get("narrative_function"),
            "story_priority": s.get("story_priority", "normal"),
            "camera_plan": copy.deepcopy(s.get("camera_plan", {})),
            "prompt_core": copy.deepcopy(s.get("prompt_core", {})),
            "routing_requirements": copy.deepcopy(s.get("routing_requirements", {})),
            "complexity": copy.deepcopy(s.get("complexity", {})),
            "asset_refs": copy.deepcopy(s.get("asset_refs", {})),
            **({"reference_requirements": copy.deepcopy(s.get("reference_requirements"))} if s.get("reference_requirements") else {}),
            **({"reference_assets": copy.deepcopy(s.get("reference_assets"))} if s.get("reference_assets") else {}),
            "continuity": copy.deepcopy(s.get("continuity", {})),
        }
        for key in (
            "single_take", "indivisible", "cut_in", "cut_out", "beats",
            "transition_hint",
        ):
            if s.get(key) is not None:
                seg[key] = copy.deepcopy(s.get(key))
        if s.get("spatial_state"):
            seg["spatial_state"] = copy.deepcopy(s.get("spatial_state"))
        elif s.get("spatial_plan"):
            seg["spatial_plan"] = copy.deepcopy(s.get("spatial_plan"))
        if s.get("scale_plan"):
            seg["scale_plan"] = copy.deepcopy(s.get("scale_plan"))
        if s.get("tts"):
            seg["tts"] = s["tts"]
        segments.append(seg)
        cursor = end

    after = int(padding.get("after", 0))
    if after > 0:
        segments.append({
            "type": "safe_padding_after",
            "start": cursor,
            "end": cursor + after,
            "instruction": "保持最后一个原子镜头真实结束状态，仅允许呼吸、衣发、光尘等低风险微动，不新增剧情。",
        })

    return segments


def finalize_unit(unit_index: int, shots: List[Dict[str, Any]], cfg: PackerConfig) -> Dict[str, Any]:
    duration, padding = build_padding_plan(shots, cfg.min_unit_duration)
    content_duration = sum(int(s.get("atomic_duration", 0)) for s in shots)

    routing_requirements = aggregate_requirements(shots)
    complexity = aggregate_complexity(shots)
    asset_refs = aggregate_asset_refs(shots)

    tts_values = [s.get("tts", "") for s in shots]
    # 保留原子顺序；没有台词的原子不插入空占位，最终 Prompt 编译器可通过 timeline_segments 对齐。
    tts_nonempty = [t for t in tts_values if t]

    los_values = unique_in_order([
        (s.get("continuity") or {}).get("los")
        for s in shots
        if (s.get("continuity") or {}).get("los")
    ])

    group_ids = unique_in_order([s.get("group_id") for s in shots if s.get("group_id")])
    narrative_classes = unique_in_order([s.get("narrative_class") for s in shots if s.get("narrative_class")])
    narrative_functions = [s.get("narrative_function") for s in shots if s.get("narrative_function")]

    unit: Dict[str, Any] = {
        "unit_id": f"u{unit_index:03d}",
        "atomic_ids": [s.get("atomic_id") for s in shots],
        "group_ids": group_ids,
        "scene_asset": shots[0].get("scene_asset"),
        "story_priority": max_story_priority(shots),
        "narrative_classes": narrative_classes,
        "narrative_functions": narrative_functions,
        "content_duration": content_duration,
        "duration": duration,
        "padding_plan": padding,
        "asset_refs": asset_refs,
        "routing_requirements": routing_requirements,
        "complexity": complexity,
        "continuity": {
            "entry": (shots[0].get("continuity") or {}).get("entry", ""),
            "exit": (shots[-1].get("continuity") or {}).get("exit", ""),
            "los": " | ".join(los_values),
        },
        "timeline_segments": build_timeline_segments(shots, padding),
    }
    spatial_lock = aggregate_spatial_lock(shots)
    if spatial_lock:
        unit["spatial_lock"] = spatial_lock

    if tts_nonempty:
        unit["tts"] = "|".join(tts_nonempty)

    if len(shots) == 1 and is_independent(shots[0]):
        unit["independent_generation"] = True

    if len(shots) == 1 and is_indivisible(shots[0]):
        unit["single_take"] = True
        unit["indivisible"] = True
        unit["cut_in"] = shots[0].get("cut_in", "scene_start" if unit_index == 1 else "hard_cut")
        unit["cut_out"] = shots[0].get("cut_out", "scene_end")
        if shots[0].get("beats"):
            unit["beats"] = copy.deepcopy(shots[0]["beats"])

    return unit


def pack_shots(data: Dict[str, Any], cfg: PackerConfig) -> Dict[str, Any]:
    shots: List[Dict[str, Any]] = data["atomic_shots"]
    units: List[Dict[str, Any]] = []
    debug_trace: List[Dict[str, Any]] = []

    i = 0
    unit_index = 1
    while i < len(shots):
        current = shots[i]

        # 独立/不可拆分连续镜头直接封包，不与前后合并。
        if is_independent(current) or is_indivisible(current):
            units.append(finalize_unit(unit_index, [current], cfg))
            if cfg.keep_debug_trace:
                debug_trace.append({
                    "from": current.get("atomic_id"),
                    "to": None,
                    "action": "isolate",
                    "reason": "indivisible_single_take" if is_indivisible(current) else "independent_generation",
                })
            i += 1
            unit_index += 1
            continue

        builder = UnitBuilder([current])
        j = i + 1

        while j < len(shots):
            nxt = shots[j]
            hard = hard_merge_check(builder, nxt, cfg)
            decision = soft_merge_check(builder, nxt, hard, cfg)

            if cfg.keep_debug_trace:
                debug_trace.append({
                    "from": builder.last.get("atomic_id"),
                    "to": nxt.get("atomic_id"),
                    "current_unit_atomic_ids": [s.get("atomic_id") for s in builder.shots],
                    "current_content_duration": builder.content_duration,
                    "candidate_content_duration": builder.content_duration + int(nxt.get("atomic_duration", 0)),
                    "relation": decision.relation,
                    "spatial_cut_risk": spatial_cut_risk(builder.last, nxt)[0],
                    "spatial_cut_risk_reasons": spatial_cut_risk(builder.last, nxt)[1],
                    "action": "merge" if decision.can_merge else "stop",
                    "reason": decision.reason,
                })

            if not decision.can_merge:
                break

            builder.add(nxt)
            j += 1

        units.append(finalize_unit(unit_index, builder.shots, cfg))
        unit_index += 1
        i = j

    output: Dict[str, Any] = {
        "routing_tier": data.get("routing_tier"),
        "aspect_ratio": data.get("aspect_ratio"),
        "scene_contexts": copy.deepcopy(data.get("scene_contexts", [])),
        "packer_meta": {
            "mode": cfg.mode,
            "min_unit_duration": cfg.min_unit_duration,
            "target_duration": cfg.target_duration,
            "max_duration": cfg.max_duration,
            "max_spatial_cut_risk": cfg.max_spatial_cut_risk,
            "atomic_shot_count": len(shots),
            "generation_unit_count": len(units),
            "atomic_content_duration": sum(int(s.get("atomic_duration", 0)) for s in shots),
            "generation_request_duration": sum(int(u.get("duration", 0)) for u in units),
            "cut_take_contract": any(is_indivisible(s) for s in shots),
        },
        "generation_units": units,
    }
    if data.get("asset_catalog"):
        output["asset_catalog"] = copy.deepcopy(data.get("asset_catalog"))

    if cfg.keep_debug_trace:
        output["merge_trace"] = debug_trace

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="短剧 atomic_shots 确定性合并打包器")
    parser.add_argument("input", type=Path, help="A阶段导演 JSON 文件")
    parser.add_argument("output", type=Path, help="输出 generation_units JSON 文件")
    parser.add_argument(
        "--mode",
        choices=["balanced", "max_safe", "preferred_only"],
        default="balanced",
        help="合并模式：balanced(默认) / max_safe / preferred_only",
    )
    parser.add_argument("--min-unit-duration", type=int, default=4, help="通用最短生成单元时长，默认4")
    parser.add_argument("--target-duration", type=int, default=15, help="balanced 模式语义安全块目标时长，默认15；最终调用可由路由器再次按价格/能力拆分")
    parser.add_argument("--max-duration", type=int, default=30, help="语义安全块最大时长，默认30；为S2.5/wan长时与后续动态分区保留空间")
    parser.add_argument("--no-cross-group", action="store_true", help="禁止跨 group_id 合并")
    parser.add_argument("--max-spatial-cut-risk", choices=["low", "medium", "high"], default="medium", help="允许封装进同一生成单元的最高空间切换风险，默认 medium")
    parser.add_argument("--missing-relation-allowed", action="store_true", help="merge_relation 缺失时按 allowed 处理；默认按硬边界")
    parser.add_argument("--no-debug-trace", action="store_true", help="不输出 merge_trace")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.min_unit_duration <= 0:
        print("ERROR: --min-unit-duration 必须 > 0", file=sys.stderr)
        return 2
    if args.target_duration < args.min_unit_duration:
        print("ERROR: --target-duration 不能小于 --min-unit-duration", file=sys.stderr)
        return 2
    if args.max_duration < args.target_duration:
        print("ERROR: --max-duration 不能小于 --target-duration", file=sys.stderr)
        return 2

    data = read_json(args.input)
    errors = validate_input(data)
    if errors:
        print("输入 JSON 校验失败：", file=sys.stderr)
        for e in errors:
            print(f"- {e}", file=sys.stderr)
        return 1

    cfg = PackerConfig(
        mode=args.mode,
        min_unit_duration=args.min_unit_duration,
        target_duration=args.target_duration,
        max_duration=args.max_duration,
        allow_cross_group=not args.no_cross_group,
        strict_missing_merge_relation=not args.missing_relation_allowed,
        keep_debug_trace=not args.no_debug_trace,
        max_spatial_cut_risk=args.max_spatial_cut_risk,
    )

    output = pack_shots(data, cfg)
    write_json(args.output, output)

    meta = output["packer_meta"]
    print(
        f"OK: {meta['atomic_shot_count']} atomic_shots -> "
        f"{meta['generation_unit_count']} generation_units; "
        f"content={meta['atomic_content_duration']}s, request={meta['generation_request_duration']}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
