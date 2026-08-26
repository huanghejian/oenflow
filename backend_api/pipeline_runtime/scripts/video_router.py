#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_router.py - 精确积分 + Minimum Sufficient 中档 + 模型/preset 二级动态路由 + 自动分区优化

输入：shot_packer.py 输出的 generation_units JSON。
输出：routed_units JSON。

核心规则：
1. 先接口准入，后质量与价格；价格绝不能绕过素材容量、时长、分辨率等真实接口禁区。
2. 每个 (model, preset) 作为独立候选。
3. 积分使用精确公式：
     points = base_points + (duration - base_duration_seconds) * extra_points_per_second
     total_points = points * output_count * output_count_multiplier
4. 如配置了 first_pass_usable_rate，则：
     expected_usable_points = total_points / first_pass_usable_rate
   否则用能力适配度 + base_reliability 推导冷启动首轮可用率。
5. LOW / MEDIUM / HIGH 不再绑定固定模型等级。四个模型均可进入候选。
   MEDIUM 采用 Minimum Sufficient：达到当前镜头目标质量/可靠率后，选预计可用积分最低方案；能力准入始终优先。
6. 所有名称含 SR 的 preset 受统一硬门槛：生成单元内每个原子段都必须是
   “特写”或“大特写”类别；混入近景、中景、全景、远景或混合景别时 SR 直接失效。
7. 图片/视频/音频逻辑素材类型、用途、数量与总文件上限属于硬门槛，先于质量与价格。
   多主体、表演、口型、动作、物理、镜头、特效与时序能力只参与质量和可靠率评分，不构成硬淘汰。
8. target_resolution 是严格输出锁：preset 的 output_resolution 必须与其完全一致；
   720P 项目不得使用 480P、1080P、1080-SR、2K 或其他输出分辨率。
9. shot_packer 产出的是“语义安全块”。本路由器允许在原子边界重新分区，
   用动态规划同时比较：长合并 vs 自然拆分，以适应 S2.5 1080-SR 等有固定调用项的价格结构。
10. 不修改导演语义、不重写 prompt_core、不改变原子顺序。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from reference_planner import plan_references

LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
LEVEL_SCORE = {"none": 0, "low": 45, "medium": 65, "high": 80, "critical": 90}
COMPLEXITY_ORDER = {"low": 1, "medium": 2, "high": 3}
PRIORITY_ORDER = {"normal": 1, "key": 2, "climax": 3}
PRIORITY_REV = {v: k for k, v in PRIORITY_ORDER.items()}
DIMENSIONS = [
    "acting_precision", "dialogue_lipsync", "identity_consistency",
    "multi_character_control", "motion_action", "physical_interaction",
    "camera_control", "prop_precision", "vfx_environment", "temporal_continuity",
]
BASE_WEIGHTS = {
    "acting_precision": 1.0, "dialogue_lipsync": 1.0, "identity_consistency": 1.1,
    "multi_character_control": 1.0, "motion_action": 1.0, "physical_interaction": 1.0,
    "camera_control": 1.0, "prop_precision": 1.0, "vfx_environment": 1.0,
    "temporal_continuity": 1.1,
}
NARRATIVE_BOOSTS = {
    "dialogue": {"dialogue_lipsync": 1.6, "acting_precision": 1.4, "identity_consistency": 1.2},
    "reaction": {"acting_precision": 1.7, "identity_consistency": 1.4},
    "action": {"motion_action": 1.6, "physical_interaction": 1.5, "camera_control": 1.2},
    "cinematic": {"camera_control": 1.8, "identity_consistency": 1.2},
    "environment_vfx": {"vfx_environment": 1.8, "camera_control": 1.2},
    "prop_info": {"prop_precision": 2.0, "identity_consistency": 1.1},
    "complex_narrative": {"temporal_continuity": 1.7, "multi_character_control": 1.5, "acting_precision": 1.3},
}
DEFAULT_ROUTING_POLICY = {
    "tier_model_allowlist": {
        "low": ["higgsfield-h3", "seedance-2.0", "seedance-2.5", "wan-3.0"],
        "medium": ["higgsfield-h3", "seedance-2.0", "seedance-2.5", "wan-3.0"],
        "high": ["higgsfield-h3", "seedance-2.0", "seedance-2.5", "wan-3.0"],
    },
    "tier_quality_floor": {"low": 76.0, "medium": 82.0, "high": 88.0},
    "tier_weights": {
        "low": {"quality": 0.10, "reliability": 0.10, "cost_efficiency": 0.80},
        "medium": {"quality": 0.45, "reliability": 0.25, "cost_efficiency": 0.30},
        "high": {"quality": 0.85, "reliability": 0.15, "cost_efficiency": 0.00},
    },
    "low_near_cost_ratio": 1.03,
    "quality_score_min": 0.0,
    "quality_score_max": 100.0,
    "high_quality_gain_threshold": 2.5,
    "high_near_quality_strategy": "lowest_expected_usable_points",
    "partition_optimizer": {
        "enabled": True,
        "prefer_fewer_calls_when_expected_points_within": 0.5,
        "max_atomic_segments_per_block": 40,
    },
    "medium_minimum_sufficient_policy": {
        "enabled": True,
        "quality_target_by_story_priority": {"normal": 86.0, "key": 89.0, "climax": 92.0},
        "reliability_floor_by_story_priority": {"normal": 0.78, "key": 0.82, "climax": 0.85},
        "critical_requirement_quality_boost": 0.5,
        "max_critical_quality_boost": 1.5,
        "pro_last_resort": True,
        "pro_preset_tokens": ["pro"],
        "near_cost_ratio": 1.02,
        "fallback_when_target_unmet": "best_available_quality_then_reliability_then_points",
    },
    "sr_hard_policy": {
        "enabled": True,
        "allowed_shot_size_categories": ["特写", "大特写"],
        "require_all_atomic_segments_match": True,
        "reject_mixed_shot_size_segment": True,
    },
}


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def unique_in_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for v in values:
        key = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def max_requirement(items: Iterable[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for d in DIMENSIONS:
        best = 0
        for item in items:
            best = max(best, LEVEL_ORDER.get(str(item.get(d, "none")).lower(), 0))
        out[d] = next((k for k, v in LEVEL_ORDER.items() if v == best), "none")
    return out


def max_complexity(items: Iterable[Dict[str, str]]) -> Dict[str, str]:
    keys = set()
    vals = list(items)
    for x in vals:
        keys.update(x.keys())
    out: Dict[str, str] = {}
    for k in keys:
        best = 1
        for x in vals:
            best = max(best, COMPLEXITY_ORDER.get(str(x.get(k, "low")).lower(), 1))
        out[k] = {1: "low", 2: "medium", 3: "high"}.get(best, "low")
    return out


def requirement_scores(unit: Dict[str, Any]) -> Dict[str, int]:
    req = unit.get("routing_requirements", {}) or {}
    return {d: LEVEL_SCORE.get(str(req.get(d, "none")).lower(), 0) for d in DIMENSIONS}


def weights_for_unit(unit: Dict[str, Any]) -> Dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    for cls in unit.get("narrative_classes", []) or []:
        for dim, mul in NARRATIVE_BOOSTS.get(cls, {}).items():
            weights[dim] *= mul
    return weights


def has_people(unit: Dict[str, Any]) -> bool:
    return bool(((unit.get("asset_refs") or {}).get("roles") or []))


def atomic_segments(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in (unit.get("timeline_segments") or []) if x.get("type") == "atomic"]


SHOT_SIZE_CATEGORY_TOKENS = [
    ("大特写", "大特写"),
    ("极远景", "极远景"),
    ("中远景", "中远景"),
    ("远景", "远景"),
    ("大全景", "全景"),
    ("全景", "全景"),
    ("中近景", "中近景"),
    ("中景", "中景"),
    ("近景", "近景"),
    ("特写", "特写"),
]


def shot_size_categories(raw_size: Any) -> List[str]:
    """Map free-form shot_size text to one or more semantic categories.

    Examples:
      手部特写 -> [特写]
      大特写 -> [大特写, 特写] (later normalized to 大特写 only)
      近景→特写 -> [近景, 特写] and therefore fails SR hard gate.
    """
    s = str(raw_size or "").strip()
    if not s:
        return []
    cats: List[str] = []
    for token, cat in SHOT_SIZE_CATEGORY_TOKENS:
        if token in s and cat not in cats:
            cats.append(cat)
    # “大特写” itself contains “特写”; keep only the more specific category
    # unless the raw value also explicitly carries a second shot-size category.
    if "大特写" in cats and "特写" in cats:
        residual = s.replace("大特写", "")
        if "特写" not in residual:
            cats = [c for c in cats if c != "特写"]
    return cats


def atomic_shot_size_categories(unit: Dict[str, Any]) -> List[List[str]]:
    return [shot_size_categories((seg.get("camera_plan") or {}).get("shot_size", "")) for seg in atomic_segments(unit)]


def all_segments_match_shot_categories(unit: Dict[str, Any], allowed: Iterable[str], reject_mixed: bool = True) -> bool:
    allowed_set = {str(x) for x in allowed}
    per_seg = atomic_shot_size_categories(unit)
    if not per_seg:
        return False
    for cats in per_seg:
        if not cats:
            return False
        if reject_mixed and len(cats) != 1:
            return False
        if not set(cats).issubset(allowed_set):
            return False
    return True


def all_closeup(unit: Dict[str, Any]) -> bool:
    # Backward-compatible helper. Current SR rules are stricter and use
    # allowed_shot_size_categories + require_all_segments_match_shot_size.
    return all_segments_match_shot_categories(unit, ("特写", "大特写"), reject_mixed=True)


def shot_quality_adjustment(preset_cfg: Dict[str, Any], unit: Dict[str, Any]) -> float:
    """Return config-driven quality adjustment for the actual shot-size mix.

    `shot_quality_profiles` lives in model_registry.json, e.g.
      {"特写": 5.5, "大特写": 6.5}.

    For multi-atomic units we average the per-atomic applicable adjustment.
    This keeps empirical findings such as Seedance close-up SR > fast > mini
    entirely in JSON rather than hard-coding preset ordering here.
    """
    profiles = preset_cfg.get("shot_quality_profiles", {}) or {}
    if not profiles:
        return 0.0
    per_seg = atomic_shot_size_categories(unit)
    if not per_seg:
        return 0.0
    vals: List[float] = []
    for cats in per_seg:
        applicable = [float(profiles[c]) for c in cats if c in profiles]
        vals.append(max(applicable) if applicable else 0.0)
    return sum(vals) / len(vals) if vals else 0.0


def medium_targets(unit: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[float, float]:
    cfg = policy.get("medium_minimum_sufficient_policy", {}) or {}
    priority = str(unit.get("story_priority", "normal"))
    qmap = cfg.get("quality_target_by_story_priority", {}) or {}
    rmap = cfg.get("reliability_floor_by_story_priority", {}) or {}
    target_q = float(qmap.get(priority, qmap.get("normal", (policy.get("tier_quality_floor", {}) or {}).get("medium", 0.0))))
    critical_count = count_req(unit, ("critical",))
    boost_each = float(cfg.get("critical_requirement_quality_boost", 0.0))
    max_boost = float(cfg.get("max_critical_quality_boost", 0.0))
    target_q += min(max_boost, critical_count * boost_each)
    rel_floor = float(rmap.get(priority, rmap.get("normal", 0.0)))
    return target_q, rel_floor


def has_wide_shot(unit: Dict[str, Any]) -> bool:
    for seg in atomic_segments(unit):
        size = str((seg.get("camera_plan") or {}).get("shot_size", ""))
        if any(t in size for t in ("全景", "远景", "大全景", "中远景")):
            return True
    return False


def count_req(unit: Dict[str, Any], levels: Iterable[str]) -> int:
    levels = set(levels)
    req = unit.get("routing_requirements", {}) or {}
    return sum(1 for d in DIMENSIONS if str(req.get(d, "none")).lower() in levels)


def model_hard_constraints(model_name: str, model_cfg: Dict[str, Any], unit: Dict[str, Any], request_duration: int) -> List[str]:
    """Return only actual model/API hard constraints.

    Performance dimensions (including multi-character control, acting,
    lipsync, motion, physics, camera, VFX and temporal continuity) describe
    expected output quality. They must never make a model ineligible by
    themselves; reference_planner handles the real material input limits.
    """
    reasons: List[str] = []
    min_d = int(model_cfg.get("min_duration", 1))
    max_d = int(model_cfg.get("max_duration", 999))
    if request_duration < min_d:
        reasons.append(f"duration<{min_d}")
    if request_duration > max_d:
        reasons.append(f"duration>{max_d}")

    return reasons


def dimension_fit(model_cfg: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, float, List[str], Dict[str, float]]:
    """Score capability fit without turning a quality margin into a hard gate."""
    req_scores = requirement_scores(unit)
    caps = model_cfg.get("capabilities", {}) or {}
    weights = weights_for_unit(unit)
    weighted = total_w = 0.0
    reasons: List[str] = []
    margins: Dict[str, float] = {}
    for dim in DIMENSIONS:
        req = req_scores[dim]
        if req <= 0:
            continue
        cap = float(caps.get(dim, 0))
        margin = cap - req
        margins[dim] = round(margin, 2)
        local = clamp(88.0 + margin * 1.3, 0.0, 100.0)
        w = weights.get(dim, 1.0)
        weighted += local * w
        total_w += w
    fit = weighted / total_w if total_w else 90.0
    return not reasons, round(fit, 2), reasons, margins


def estimate_base_reliability(model_cfg: Dict[str, Any], fit_quality: float, unit: Dict[str, Any]) -> float:
    explicit = model_cfg.get("first_pass_usable_rate")
    if isinstance(explicit, (int, float)) and 0 < float(explicit) <= 1:
        return float(explicit)
    base = float(model_cfg.get("base_reliability", 0.8))
    rel = base + (fit_quality - 85.0) * 0.004
    rel -= max(0, count_req(unit, ("high", "critical")) - 3) * 0.015
    if unit.get("story_priority") == "climax":
        rel -= 0.01
    return clamp(rel, 0.50, 0.98)


def preset_constraints(preset_name: str, preset_cfg: Dict[str, Any], unit: Dict[str, Any], target_resolution: str, request_duration: int, policy: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    if not preset_cfg.get("enabled", True):
        return ["preset_disabled"]
    normalized_target = target_resolution.upper()
    output_resolution = str(preset_cfg.get("output_resolution", "")).upper()
    if not output_resolution:
        reasons.append("preset_output_resolution_missing")
    elif output_resolution != normalized_target:
        reasons.append(f"preset_output_resolution_mismatch({output_resolution}!={normalized_target})")
    allowed = [str(x).upper() for x in preset_cfg.get("allowed_target_resolutions", []) or []]
    if allowed and normalized_target not in allowed:
        reasons.append(f"target_resolution_not_allowed({target_resolution})")
    pricing = preset_cfg.get("pricing", {}) or {}
    pmin = int(pricing.get("min_duration_seconds", 1))
    pmax = int(pricing.get("max_duration_seconds", 999))
    if request_duration < pmin:
        reasons.append(f"preset_duration<{pmin}")
    if request_duration > pmax:
        reasons.append(f"preset_duration>{pmax}")

    c = preset_cfg.get("constraints", {}) or {}
    # These flags describe actual preset modes. Semantic difficulty limits such
    # as allowed_story_priority/max_level/max_*_requirement_count are soft
    # quality priors and therefore intentionally do not participate here.
    if c.get("forbid_has_people") and has_people(unit):
        reasons.append("has_people_forbidden")
    if c.get("all_closeup") and not all_closeup(unit):
        reasons.append("requires_all_closeup")
    if c.get("forbid_wide_shot") and has_wide_shot(unit):
        reasons.append("wide_shot_forbidden")

    # SR hard gate: config may state it explicitly, and the global policy also
    # protects against accidentally forgetting the constraint on a new SR preset.
    global_sr = policy.get("sr_hard_policy", {}) or {}
    is_sr = "SR" in str(preset_name).upper() or bool(c.get("sr_only"))
    if is_sr and global_sr.get("enabled", True):
        allowed_sizes = c.get("allowed_shot_size_categories") or global_sr.get("allowed_shot_size_categories") or ["特写", "大特写"]
        require_all = c.get("require_all_segments_match_shot_size", global_sr.get("require_all_atomic_segments_match", True))
        reject_mixed = c.get("reject_mixed_shot_size_segment", global_sr.get("reject_mixed_shot_size_segment", True))
        if require_all and not all_segments_match_shot_categories(unit, allowed_sizes, reject_mixed=bool(reject_mixed)):
            actual = atomic_shot_size_categories(unit)
            reasons.append(f"sr_shot_size_forbidden(actual={actual};allowed={list(allowed_sizes)})")
    return reasons


def request_duration_for(unit: Dict[str, Any], model_cfg: Dict[str, Any], preset_cfg: Dict[str, Any]) -> int:
    base = int(unit.get("duration", unit.get("content_duration", 0)) or 0)
    pricing = preset_cfg.get("pricing", {}) or {}
    min_d = max(int(model_cfg.get("min_duration", 1)), int(pricing.get("min_duration_seconds", 1)))
    return max(base, min_d)


def exact_points(preset_cfg: Dict[str, Any], duration: int, output_count: int) -> Tuple[float, str, str]:
    p = preset_cfg.get("pricing", {}) or {}
    base_d = int(p["base_duration_seconds"])
    base_points = float(p["base_points"])
    inc = float(p["extra_points_per_second"])
    multiplier = float(p.get("output_count_multiplier", 1))
    points = (base_points + (duration - base_d) * inc) * output_count * multiplier
    formula = f"({base_points:g} + ({duration}-{base_d})×{inc:g}) × {output_count} × {multiplier:g}"
    return round(points, 4), formula, str(p.get("price_version", ""))


def build_candidate(model_name: str, model_cfg: Dict[str, Any], preset_name: str, preset_cfg: Dict[str, Any], unit: Dict[str, Any], target_resolution: str, policy: Dict[str, Any], tier: str, asset_catalog: Dict[str, Any]) -> Dict[str, Any]:
    output_count = int((model_cfg.get("params", {}) or {}).get("output_count", 1))
    request_duration = request_duration_for(unit, model_cfg, preset_cfg)
    hard = model_hard_constraints(model_name, model_cfg, unit, request_duration)
    hard += preset_constraints(preset_name, preset_cfg, unit, target_resolution, request_duration, policy)

    # V7 逻辑素材输入硬门槛：先检查逻辑图片/视频/音频类型、用途、数量、总文件数和可选单文件时长。
    # 素材不兼容时候选直接 invalid，价格再低也不能进入后续裁决。
    reference_plan = plan_references(unit, model_cfg, asset_catalog)
    if not reference_plan.get("qualified", False):
        hard += list(reference_plan.get("hard_reasons", []) or [])

    _ok, base_fit, _fit_reasons, margins = dimension_fit(model_cfg, unit)

    qmin = float(policy.get("quality_score_min", 0.0))
    qmax = float(policy.get("quality_score_max", 100.0))
    shot_q_adjust = shot_quality_adjustment(preset_cfg, unit)
    fit_quality = clamp(base_fit + float(preset_cfg.get("quality_adjust", 0.0)) + shot_q_adjust, qmin, qmax)
    rel = estimate_base_reliability(model_cfg, base_fit, unit)
    explicit_preset_rate = preset_cfg.get("first_pass_usable_rate")
    if isinstance(explicit_preset_rate, (int, float)) and 0 < float(explicit_preset_rate) <= 1:
        rel = float(explicit_preset_rate)
    else:
        rel = clamp(rel + float(preset_cfg.get("reliability_adjust", 0.0)), 0.50, 0.98)

    try:
        call_points, formula, price_version = exact_points(preset_cfg, request_duration, output_count)
    except Exception as exc:
        hard.append(f"invalid_pricing:{exc}")
        call_points, formula, price_version = 10**9, "invalid", ""
    expected = call_points / max(0.01, rel)
    return {
        "model": model_name,
        "preset": preset_name,
        "qualified": not hard,
        "request_duration": request_duration,
        "padding_seconds": max(0, request_duration - int(unit.get("duration", 0) or 0)),
        "fit_quality": round(fit_quality, 2),
        "base_fit_quality": round(base_fit, 2),
        "preset_quality_adjust": round(float(preset_cfg.get("quality_adjust", 0.0)), 2),
        "shot_quality_adjust": round(shot_q_adjust, 2),
        "reliability": round(rel, 4),
        "call_points": round(call_points, 4),
        "expected_usable_points": round(expected, 4),
        "pricing_formula": formula,
        "price_version": price_version,
        "margins": margins,
        "preset_output_resolution": preset_cfg.get("output_resolution"),
        "atomic_shot_size_categories": atomic_shot_size_categories(unit),
        "reference_counts": copy.deepcopy(reference_plan.get("counts", {})),
        "selected_references": copy.deepcopy(reference_plan.get("selected_references", [])),
        **({"reference_warnings": copy.deepcopy(reference_plan.get("warnings", []))} if reference_plan.get("warnings") else {}),
        **({"hard_reasons": list(dict.fromkeys(hard))} if hard else {}),
    }


def normalize_scores(candidates: List[Dict[str, Any]], tier: str, policy: Dict[str, Any]) -> None:
    q = [c for c in candidates if c.get("qualified")]
    if not q:
        return
    costs = [float(c["expected_usable_points"]) for c in q]
    cmin, cmax = min(costs), max(costs)
    weights = (policy.get("tier_weights", {}) or {}).get(tier, {}) or {}
    for c in q:
        if math.isclose(cmin, cmax):
            ce = 100.0
        else:
            ce = 100.0 * (cmax - float(c["expected_usable_points"])) / (cmax - cmin)
        rs = float(c["reliability"]) * 100.0
        c["cost_efficiency"] = round(ce, 2)
        c["reliability_score"] = round(rs, 2)
        c["tier_score"] = round(
            float(weights.get("quality", 0)) * float(c["fit_quality"])
            + float(weights.get("reliability", 0)) * rs
            + float(weights.get("cost_efficiency", 0)) * ce,
            3,
        )


def select_candidate(candidates: List[Dict[str, Any]], tier: str, policy: Dict[str, Any], unit: Dict[str, Any]) -> Dict[str, Any]:
    qualified = [copy.deepcopy(c) for c in candidates if c.get("qualified")]
    if not qualified:
        raise RuntimeError("No qualified model+preset candidate")
    normalize_scores(qualified, tier, policy)

    if tier == "low":
        qualified.sort(key=lambda x: (x["expected_usable_points"], -x["fit_quality"], -x["reliability"]))
        best = float(qualified[0]["expected_usable_points"])
        ratio = float(policy.get("low_near_cost_ratio", 1.03))
        near = [x for x in qualified if float(x["expected_usable_points"]) <= best * ratio]
        near.sort(key=lambda x: (x["expected_usable_points"], -x["fit_quality"], -x["reliability"]))
        return near[0]

    if tier == "high":
        qualified.sort(key=lambda x: (x["fit_quality"], x["reliability"]), reverse=True)
        top_q = float(qualified[0]["fit_quality"])
        threshold = float(policy.get("high_quality_gain_threshold", 2.5))
        near = [x for x in qualified if top_q - float(x["fit_quality"]) <= threshold]
        if policy.get("high_near_quality_strategy") == "lowest_expected_usable_points":
            near.sort(key=lambda x: (x["expected_usable_points"], -x["fit_quality"], -x["reliability"]))
            return near[0]
        near.sort(key=lambda x: (x.get("tier_score", 0), x["fit_quality"], x["reliability"]), reverse=True)
        return near[0]

    # MEDIUM = Minimum Sufficient, not highest blended score.
    mcfg = policy.get("medium_minimum_sufficient_policy", {}) or {}
    if tier == "medium" and mcfg.get("enabled", True):
        target_q, rel_floor = medium_targets(unit, policy)
        meeting = [
            x for x in qualified
            if float(x["fit_quality"]) >= target_q and float(x["reliability"]) >= rel_floor
        ]

        pro_tokens = [str(x).lower() for x in (mcfg.get("pro_preset_tokens", ["pro"]) or [])]
        def is_pro(c: Dict[str, Any]) -> bool:
            pn = str(c.get("preset", "")).lower()
            return any(t in pn for t in pro_tokens)

        # “pro迫不得已”：只要存在非pro方案已经达到中档目标，pro不参与最终竞争。
        if meeting and mcfg.get("pro_last_resort", True):
            non_pro = [x for x in meeting if not is_pro(x)]
            if non_pro:
                meeting = non_pro

        if meeting:
            meeting.sort(key=lambda x: (x["expected_usable_points"], -x["fit_quality"], -x["reliability"]))
            best_cost = float(meeting[0]["expected_usable_points"])
            ratio = float(mcfg.get("near_cost_ratio", 1.02))
            near = [x for x in meeting if float(x["expected_usable_points"]) <= best_cost * ratio]
            near.sort(key=lambda x: (x["expected_usable_points"], -x["fit_quality"], -x["reliability"]))
            chosen = near[0]
            chosen["medium_target_quality"] = round(target_q, 2)
            chosen["medium_reliability_floor"] = round(rel_floor, 4)
            chosen["medium_target_met"] = True
            chosen["medium_selection_mode"] = "minimum_sufficient"
            return chosen

        # No candidate reached the Medium target. Do not silently pretend it did.
        # Pick the best available quality, then reliability, then lower expected points.
        qualified.sort(key=lambda x: (-float(x["fit_quality"]), -float(x["reliability"]), float(x["expected_usable_points"])))
        chosen = qualified[0]
        chosen["medium_target_quality"] = round(target_q, 2)
        chosen["medium_reliability_floor"] = round(rel_floor, 4)
        chosen["medium_target_met"] = False
        chosen["medium_selection_mode"] = "fallback_best_available"
        return chosen

    qualified.sort(key=lambda x: (x.get("tier_score", 0), x["fit_quality"], x["reliability"]), reverse=True)
    return qualified[0]

def tier_models(registry: Dict[str, Any], policy: Dict[str, Any], tier: str) -> List[str]:
    allow = (policy.get("tier_model_allowlist", {}) or {}).get(tier)
    if not allow:
        return list(registry)
    return [m for m in allow if m in registry]


def iter_candidates(unit: Dict[str, Any], registry: Dict[str, Any], target_resolution: str, policy: Dict[str, Any], tier: str, asset_catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for model_name in tier_models(registry, policy, tier):
        model_cfg = registry[model_name]
        for preset_name, preset_cfg in (model_cfg.get("preset_profiles", {}) or {}).items():
            out.append(build_candidate(model_name, model_cfg, preset_name, preset_cfg, unit, target_resolution, policy, tier, asset_catalog))
    normalize_scores(out, tier, policy)
    return out


def build_model_params(model_cfg: Dict[str, Any], preset_name: str, preset_cfg: Dict[str, Any], unit: Dict[str, Any]) -> Dict[str, Any]:
    raw = copy.deepcopy(model_cfg.get("params", {}) or {})
    params: Dict[str, Any] = {}
    for k, v in raw.items():
        if k == "human_mode" and v == "auto_people":
            params[k] = has_people(unit)
        else:
            params[k] = v
    if preset_cfg.get("emit_resolution_preset", True):
        params["resolution_preset"] = preset_name
    if model_cfg.get("api_model_id"):
        params["api_model_id"] = model_cfg["api_model_id"]
    return params


def add_padding_after(unit: Dict[str, Any], seconds: int) -> Dict[str, Any]:
    if seconds <= 0:
        return unit
    out = copy.deepcopy(unit)
    start = int(out.get("duration", 0))
    out.setdefault("timeline_segments", []).append({
        "type": "safe_padding_after", "start": start, "end": start + seconds,
        "instruction": "保持最后一个原子镜头真实结束状态，仅允许呼吸、衣发、光尘等低风险微动，不新增剧情。",
    })
    out["duration"] = start + seconds
    pp = out.setdefault("padding_plan", {"before": 0, "after": 0})
    pp["after"] = int(pp.get("after", 0)) + seconds
    return out


def aggregate_spatial_lock_from_segments(segs: List[Dict[str, Any]]) -> Dict[str, Any]:
    states = [s.get("spatial_state") for s in segs if isinstance(s.get("spatial_state"), dict)]
    if not states:
        return {}
    first, last = states[0], states[-1]
    out = {
        "entry_world_positions": copy.deepcopy(first.get("entry_world_positions", {})),
        "exit_world_positions": copy.deepcopy(last.get("exit_world_positions", {})),
    }
    axes = unique_in_order([s.get("camera_axis") for s in states if s.get("camera_axis")])
    if axes:
        out["camera_axes"] = axes
    return out


def slice_unit(parent: Dict[str, Any], segs: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    cursor = 0
    rebased: List[Dict[str, Any]] = []
    for seg in segs:
        c = copy.deepcopy(seg)
        dur = int(seg.get("end", 0)) - int(seg.get("start", 0))
        c["start"] = cursor
        c["end"] = cursor + dur
        cursor += dur
        rebased.append(c)
    reqs = [s.get("routing_requirements", {}) or {} for s in segs]
    comps = [s.get("complexity", {}) or {} for s in segs]
    roles, props = [], []
    for s in segs:
        refs = s.get("asset_refs", {}) or {}
        roles += refs.get("roles", []) or []
        props += refs.get("props", []) or []
    priorities = [PRIORITY_ORDER.get(str(s.get("story_priority", "normal")), 1) for s in segs]
    los = unique_in_order([(s.get("continuity") or {}).get("los") for s in segs if (s.get("continuity") or {}).get("los")])
    first_cont = segs[0].get("continuity", {}) or {}
    last_cont = segs[-1].get("continuity", {}) or {}
    out: Dict[str, Any] = {
        "unit_id": label,
        "atomic_ids": [s.get("atomic_id") for s in segs],
        "group_ids": unique_in_order([s.get("group_id") for s in segs if s.get("group_id")]),
        "scene_asset": parent.get("scene_asset"),
        "story_priority": PRIORITY_REV[max(priorities) if priorities else 1],
        "narrative_classes": unique_in_order([s.get("narrative_class") for s in segs if s.get("narrative_class")]),
        "narrative_functions": [s.get("narrative_function") for s in segs if s.get("narrative_function")],
        "content_duration": cursor,
        "duration": cursor,
        "padding_plan": {"before": 0, "after": 0},
        "asset_refs": {k: v for k, v in {"roles": unique_in_order(roles), "props": unique_in_order(props)}.items() if v},
        "routing_requirements": max_requirement(reqs),
        "complexity": max_complexity(comps),
        "continuity": {
            "entry": first_cont.get("entry", parent.get("continuity", {}).get("entry", "")),
            "exit": last_cont.get("exit", parent.get("continuity", {}).get("exit", "")),
            "los": " | ".join(los) or parent.get("continuity", {}).get("los", ""),
        },
        "timeline_segments": rebased,
    }
    if cursor < 4:
        out = add_padding_after(out, 4 - cursor)
    tts = [s.get("tts") for s in segs if s.get("tts")]
    if tts:
        out["tts"] = "|".join(tts)
    spatial_lock = aggregate_spatial_lock_from_segments(segs)
    if spatial_lock:
        out["spatial_lock"] = spatial_lock
    return out


def direct_route(unit: Dict[str, Any], registry: Dict[str, Any], policy: Dict[str, Any], tier: str, target_resolution: str, asset_catalog: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    candidates = iter_candidates(unit, registry, target_resolution, policy, tier, asset_catalog)
    chosen = select_candidate(candidates, tier, policy, unit)
    model_cfg = registry[chosen["model"]]
    preset_cfg = model_cfg["preset_profiles"][chosen["preset"]]
    routed_unit = add_padding_after(copy.deepcopy(unit), int(chosen.get("padding_seconds", 0)))
    routed_unit["model"] = chosen["model"]
    routed_unit["model_params"] = build_model_params(model_cfg, chosen["preset"], preset_cfg, routed_unit)
    routed_unit["references"] = copy.deepcopy(chosen.get("selected_references", []))
    routed_unit["reference_summary"] = {
        "counts": copy.deepcopy(chosen.get("reference_counts", {})),
        **({"warnings": copy.deepcopy(chosen.get("reference_warnings", []))} if chosen.get("reference_warnings") else {}),
    }
    routed_unit["routing_decision"] = {
        "tier": tier,
        "selected_model": chosen["model"],
        "selected_display_name": model_cfg.get("display_name", chosen["model"]),
        "selected_preset": chosen["preset"],
        "fit_quality": chosen["fit_quality"],
        "reliability": chosen["reliability"],
        "call_points": chosen["call_points"],
        "expected_usable_points": chosen["expected_usable_points"],
        "pricing_formula": chosen["pricing_formula"],
        "price_version": chosen["price_version"],
        "native_output_resolution": chosen.get("preset_output_resolution"),
        "request_duration": chosen["request_duration"],
        **({"medium_target_quality": chosen.get("medium_target_quality"),
            "medium_reliability_floor": chosen.get("medium_reliability_floor"),
            "medium_target_met": chosen.get("medium_target_met"),
            "medium_selection_mode": chosen.get("medium_selection_mode")}
           if tier == "medium" else {}),
        "reference_counts": copy.deepcopy(chosen.get("reference_counts", {})),
        "candidates": candidates,
    }
    return routed_unit, candidates


def can_partition(unit: Dict[str, Any], policy: Dict[str, Any]) -> bool:
    if not (policy.get("partition_optimizer", {}) or {}).get("enabled", True):
        return False
    if unit.get("independent_generation"):
        return False
    if unit.get("indivisible") or unit.get("single_take"):
        return False
    segs = atomic_segments(unit)
    if any(s.get("indivisible") or s.get("single_take") for s in segs):
        return False
    if len(segs) <= 1:
        return False
    if any(s.get("type") != "atomic" for s in (unit.get("timeline_segments") or [])):
        return False
    max_n = int((policy.get("partition_optimizer", {}) or {}).get("max_atomic_segments_per_block", 40))
    return len(segs) <= max_n


def optimize_partition(parent: Dict[str, Any], registry: Dict[str, Any], policy: Dict[str, Any], tier: str, target_resolution: str, asset_catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    segs = atomic_segments(parent)
    n = len(segs)
    # dp[i] = (expected_points, call_count, list[(j, routed_unit)]) for covering [i:n)
    dp: List[Optional[Tuple[float, int, List[Dict[str, Any]]]]] = [None] * (n + 1)
    dp[n] = (0.0, 0, [])
    near = float((policy.get("partition_optimizer", {}) or {}).get("prefer_fewer_calls_when_expected_points_within", 0.5))

    for i in range(n - 1, -1, -1):
        best: Optional[Tuple[float, int, List[Dict[str, Any]]]] = None
        content = 0
        for j in range(i + 1, n + 1):
            content += int(segs[j - 1].get("end", 0)) - int(segs[j - 1].get("start", 0))
            if content > 30:
                break
            candidate_unit = slice_unit(parent, segs[i:j], f"{parent.get('unit_id','u')}_p{i+1}_{j}")
            try:
                routed, _ = direct_route(candidate_unit, registry, policy, tier, target_resolution, asset_catalog)
            except RuntimeError:
                continue
            if dp[j] is None:
                continue
            cost = float((routed.get("routing_decision") or {}).get("expected_usable_points", 10**9)) + dp[j][0]
            calls = 1 + dp[j][1]
            plan = [routed] + dp[j][2]
            if best is None or cost < best[0] - 1e-9 or (abs(cost - best[0]) <= near and calls < best[1]):
                best = (cost, calls, plan)
        dp[i] = best
    if dp[0] is None:
        # fall back to parent direct route, allowing clear error from direct_route
        return [direct_route(parent, registry, policy, tier, target_resolution, asset_catalog)[0]]
    return dp[0][2]


def route_document(doc: Dict[str, Any], registry: Dict[str, Any], policy: Dict[str, Any], tier_override: Optional[str], target_resolution: str, config_source: str, asset_catalog: Dict[str, Any], asset_catalog_source: str) -> Dict[str, Any]:
    tier = str(tier_override or doc.get("routing_tier") or "medium").strip().lower()
    if tier not in ("low", "medium", "high"):
        tier = "medium"
    routed: List[Dict[str, Any]] = []
    source_map: List[Dict[str, Any]] = []
    counter = 1
    for parent in doc.get("generation_units", []) or []:
        try:
            parts = optimize_partition(parent, registry, policy, tier, target_resolution, asset_catalog) if can_partition(parent, policy) else [direct_route(parent, registry, policy, tier, target_resolution, asset_catalog)[0]]
        except RuntimeError as exc:
            allowed = tier_models(registry, policy, tier)
            boundary_hint = (
                "；该镜头为不可拆分连续镜头，禁止自动分区。请换用可承载完整时长的模型，"
                "或由导演在遮挡/烟雾/闪光/甩镜处显式设计 concealed_cut"
                if parent.get("indivisible") or parent.get("single_take") else ""
            )
            raise RuntimeError(f"{parent.get('unit_id')}: 当前 {tier} 档无可胜任候选；allowed_models={allowed}; {exc}{boundary_hint}") from exc
        ids = []
        for part in parts:
            part["unit_id"] = f"u{counter:03d}"
            ids.append(part["unit_id"])
            routed.append(part)
            counter += 1
        source_map.append({"semantic_unit_id": parent.get("unit_id"), "routed_unit_ids": ids})

    total_points = sum(float((u.get("routing_decision") or {}).get("call_points", 0)) for u in routed)
    total_expected = sum(float((u.get("routing_decision") or {}).get("expected_usable_points", 0)) for u in routed)
    result = {
        "routing_tier": tier,
        "aspect_ratio": doc.get("aspect_ratio", "9:16"),
        "target_resolution": target_resolution,
        "scene_contexts": copy.deepcopy(doc.get("scene_contexts", [])),
        "routing_meta": {
            "strategy": "cut_take_indivisible_gate -> semantic_safe_block -> optional_atomic_partition_DP -> logical_material_hard_filter -> capability/preset_gate -> tier_quality_goal -> exact_points -> expected_usable_points -> minimum_sufficient/near_best selection",
            "model_config": config_source,
            "asset_catalog": asset_catalog_source,
            "logical_material_input_policy": "hard_filter_before_quality_and_price",
            "price_version": policy.get("price_version"),
            "semantic_unit_count": len(doc.get("generation_units", []) or []),
            "routed_unit_count": len(routed),
            "total_call_points": round(total_points, 4),
            "total_expected_usable_points": round(total_expected, 4),
            "source_partition_map": source_map,
        },
        "routed_units": routed,
    }
    if asset_catalog:
        result["asset_catalog"] = copy.deepcopy(asset_catalog)
    return result


def load_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    p = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "resources" / "model_registry.json"
    if not p.exists():
        raise FileNotFoundError(f"model config not found: {p}")
    doc = load_json(p)
    registry = doc.get("model_registry")
    if not isinstance(registry, dict) or not registry:
        raise ValueError("model_registry.json 必须包含非空 model_registry 对象")
    policy = copy.deepcopy(DEFAULT_ROUTING_POLICY)
    for k, v in (doc.get("routing_policy", {}) or {}).items():
        if isinstance(v, dict) and isinstance(policy.get(k), dict):
            policy[k].update(copy.deepcopy(v))
        else:
            policy[k] = copy.deepcopy(v)
    return registry, policy, str(p)


def main() -> None:
    ap = argparse.ArgumentParser(description="Exact-points logical-material-aware router with Minimum Sufficient Medium and partition optimization")
    ap.add_argument("input", help="Input generation_units JSON")
    ap.add_argument("output", help="Output routed_units JSON")
    ap.add_argument("--tier", choices=["low", "medium", "high"], default=None)
    ap.add_argument("--target-resolution", default="720P", choices=["480P", "720P", "1080P", "2K", "4K"])
    ap.add_argument("--model-config", default=None)
    ap.add_argument("--asset-catalog", default=None, help="可选：逻辑 asset_catalog JSON；默认从A阶段/打包JSON顶层读取，不需要真实文件映射")
    args = ap.parse_args()

    registry, policy, source = load_config(args.model_config)
    doc = load_json(args.input)
    if args.asset_catalog:
        asset_path = Path(args.asset_catalog)
        if not asset_path.exists():
            raise FileNotFoundError(f"asset catalog not found: {asset_path}")
        asset_catalog = load_json(asset_path)
        asset_catalog_source = str(asset_path)
    else:
        asset_catalog = copy.deepcopy(doc.get("asset_catalog") or {})
        asset_catalog_source = "embedded:A-stage asset_catalog" if asset_catalog else "legacy:no_catalog_strict_check_disabled"
    routed = route_document(doc, registry, policy, args.tier, args.target_resolution, source, asset_catalog, asset_catalog_source)
    save_json(args.output, routed)
    print(f"Routed semantic={routed['routing_meta']['semantic_unit_count']} -> final={routed['routing_meta']['routed_unit_count']} units -> {args.output}")
    print(f"Total points: {routed['routing_meta']['total_call_points']}")
    print(f"Expected usable points: {routed['routing_meta']['total_expected_usable_points']}")
    counts: Dict[Tuple[str, str], int] = {}
    for u in routed["routed_units"]:
        rd = u.get("routing_decision", {}) or {}
        key = (u.get("model", "?"), rd.get("selected_preset", "default"))
        counts[key] = counts.get(key, 0) + 1
    print("Model/preset distribution:")
    for (m, p), c in sorted(counts.items()):
        print(f"  {m} / {p}: {c}")


if __name__ == "__main__":
    main()
