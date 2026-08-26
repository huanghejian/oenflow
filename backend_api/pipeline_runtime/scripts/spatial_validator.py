#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spatial_validator.py

A阶段导演 JSON 的空间连续性展开与校验器。

目的：
1. 把场景级 spatial_bible + 原子镜头 spatial_plan 展开成每镜可验证的 spatial_state。
2. 世界空间位置只能通过显式 position_changes 改变。
3. 区分 world position / screen position / camera axis，防止换机位被误解成人物走位。
4. 为旧 A JSON 确定性补全 scale_plan，并校验新 A JSON 的镜内人物比例与近大远小。
5. 检查同一轴线无声明越轴、无依据锚点跳变、非法 anchor_id 等问题。
6. 输出 enriched A JSON，供 shot_packer.py / prompt_compiler.py 后续使用。

推荐新格式：
scene_contexts[].spatial_bible = {
  "anchor_catalog": {
    "A01": {"landmark": "已注册 landmark", "description": "相对该地标的具体局部位置"}
  },
  "axis_catalog": {
    "AX01": {
      "between": ["角色A", "角色B"],
      "default_side": "south",
      "cross_axis_allowed": false
    }
  },
  "initial_world_positions": {
    "角色A": {
      "anchor_id": "A01",
      "position": "具体世界位置",
      "facing": "朝向角色B/某锚点",
      "pose_height": "standing",
      "visibility": "visible"
    }
  }
}

atomic_shots[].spatial_plan = {
  "camera_axis": {"axis_id": "AX01", "side": "south", "crossed": false},
  "screen_positions": {
    "角色A": {"zone": "right_third", "depth": "foreground", "facing_screen": "left"}
  },
  "position_changes": [
    {
      "role_id": "角色A",
      "from_anchor": "A01",
      "to_anchor": "A02",
      "path": "沿石阶向前两步",
      "reason": "剧本明确上前"
    }
  ]
}

atomic_shots[].scale_plan = {
  "perspective_mode": "strong_depth",
  "lens_style": "standard",
  "subjects": {
    "角色A": {
      "depth": "foreground",
      "frame_height_ratio": 0.48,
      "relative_scale": 1.0
    }
  },
  "environment_relation": "中景中人物与场景共同可读，不放大成近景"
}

position_changes 没有时必须省略；不能用空数组伪装“检查过”。
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def role_refs(shot: Dict[str, Any]) -> List[str]:
    refs = (shot.get("asset_refs") or {}).get("roles") or []
    out: List[str] = []
    for r in refs:
        if r and r not in out:
            out.append(str(r))
    sp = shot.get("spatial_plan") or {}
    for r in (sp.get("screen_positions") or {}).keys():
        if r and r not in out:
            out.append(str(r))
    for ch in sp.get("position_changes") or []:
        r = ch.get("role_id") if isinstance(ch, dict) else None
        if r and r not in out:
            out.append(str(r))
    return out


def scene_context_map(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    m: Dict[str, List[Dict[str, Any]]] = {}
    for ctx in doc.get("scene_contexts", []) or []:
        sid = ctx.get("scene_asset")
        if sid:
            m.setdefault(str(sid), []).append(ctx)
    return m


def choose_context(scene_asset: str, contexts: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    candidates = contexts.get(scene_asset) or []
    if not candidates:
        return None
    # 空间母版原则上同一 scene_asset 共用；若存在状态变体，优先第一个带 spatial_bible 的。
    for c in candidates:
        if isinstance(c.get("spatial_bible"), dict):
            return c
    return candidates[0]


def _dict_copy(x: Any) -> Dict[str, Any]:
    return copy.deepcopy(x) if isinstance(x, dict) else {}


def _anchor_catalog(bible: Dict[str, Any]) -> Dict[str, Any]:
    cat = bible.get("anchor_catalog") or {}
    if isinstance(cat, list):
        out = {}
        for item in cat:
            if isinstance(item, dict) and item.get("anchor_id"):
                out[str(item["anchor_id"])] = {k: copy.deepcopy(v) for k, v in item.items() if k != "anchor_id"}
        return out
    return _dict_copy(cat)


def _axis_catalog(bible: Dict[str, Any]) -> Dict[str, Any]:
    cat = bible.get("axis_catalog") or {}
    if isinstance(cat, list):
        out = {}
        for item in cat:
            if isinstance(item, dict) and item.get("axis_id"):
                out[str(item["axis_id"])] = {k: copy.deepcopy(v) for k, v in item.items() if k != "axis_id"}
        return out
    return _dict_copy(cat)


def _initial_world(bible: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = bible.get("initial_world_positions") or {}
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def _normalize_side(v: Any) -> str:
    return str(v or "").strip().lower()


DEPTH_RANK = {"foreground": 0, "midground": 1, "background": 2}
DEPTH_SCALE_BY_DISTANCE = {0: 1.0, 1: 0.62, 2: 0.30}
SHOT_FRAME_HEIGHT_RATIO = {
    "极远景": 0.06,
    "远景": 0.13,
    "全景": 0.22,
    "中远景": 0.30,
    "中景": 0.48,
    "中近景": 0.62,
    "近景": 0.75,
    "特写": 0.90,
    "大特写": 1.05,
}


def normalize_shot_size(raw: Any) -> str:
    text = str(raw or "").strip()
    for token in ("大特写", "极远景", "中远景", "中近景", "全景", "特写", "近景", "中景", "远景"):
        if token in text:
            return token
    return "中景"


def lens_style_for_shot(shot_size: str) -> str:
    if shot_size in {"极远景", "远景", "全景", "中远景"}:
        return "wide_angle"
    if shot_size in {"近景", "特写", "大特写"}:
        return "portrait"
    return "standard"


def derive_scale_plan(shot: Dict[str, Any], screen_positions: Dict[str, Any]) -> Dict[str, Any]:
    shot_size = normalize_shot_size((shot.get("camera_plan") or {}).get("shot_size"))
    base_ratio = SHOT_FRAME_HEIGHT_RATIO[shot_size]
    valid_depths = [
        DEPTH_RANK.get(str(v.get("depth") or "midground"), 1)
        for v in screen_positions.values()
        if isinstance(v, dict)
    ]
    closest_rank = min(valid_depths) if valid_depths else 1
    subjects: Dict[str, Any] = {}
    distinct_depths = set()
    for role, val in screen_positions.items():
        if not isinstance(val, dict):
            continue
        depth = str(val.get("depth") or "midground")
        rank = DEPTH_RANK.get(depth, 1)
        distinct_depths.add(depth)
        distance = max(0, min(2, rank - closest_rank))
        relative = DEPTH_SCALE_BY_DISTANCE[distance]
        subjects[str(role)] = {
            "depth": depth,
            "frame_height_ratio": round(base_ratio * relative, 2),
            "relative_scale": round(relative, 2),
        }

    if len(distinct_depths) > 1:
        environment_relation = "严格保持近大远小和前中后三层空间，不得把不同景深主体生成为等大同平面站位"
    elif shot_size in {"极远景", "远景", "全景", "中远景"}:
        environment_relation = "环境尺度占主导，人物保持对应远中景尺寸，不得放大成近景"
    else:
        environment_relation = "人物大小严格服从当前景别，不复制参考图的取景比例"
    return {
        "source": "derived_default",
        "shot_size": shot_size,
        "perspective_mode": "strong_depth" if len(distinct_depths) > 1 else "standard_depth",
        "lens_style": lens_style_for_shot(shot_size),
        "subjects": subjects,
        "environment_relation": environment_relation,
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_scale_plan(
    atomic_id: str,
    shot: Dict[str, Any],
    screen_positions: Dict[str, Any],
    raw_plan: Any,
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate an explicit director scale plan, or derive one for V7.1 data."""
    if raw_plan is None:
        return derive_scale_plan(shot, screen_positions), []
    errors: List[str] = []
    if not isinstance(raw_plan, dict):
        return {}, [f"{atomic_id}: scale_plan 必须是对象"]

    plan = copy.deepcopy(raw_plan)
    plan.setdefault("source", "director")
    plan.setdefault("shot_size", normalize_shot_size((shot.get("camera_plan") or {}).get("shot_size")))
    plan.setdefault("lens_style", lens_style_for_shot(str(plan.get("shot_size"))))
    subjects = plan.get("subjects")
    if not isinstance(subjects, dict) or not subjects:
        return plan, [f"{atomic_id}: scale_plan.subjects 必须是非空对象"]

    visible = {str(k) for k, v in screen_positions.items() if isinstance(v, dict)}
    missing = visible - set(subjects)
    if missing:
        errors.append(f"{atomic_id}: scale_plan.subjects 缺少可见角色: {sorted(missing)}")

    parsed: Dict[str, Tuple[int, float]] = {}
    ratios: List[float] = []
    for role, cfg in subjects.items():
        if not isinstance(cfg, dict):
            errors.append(f"{atomic_id}: scale_plan.subjects[{role}] 必须是对象")
            continue
        screen_depth = str((screen_positions.get(role) or {}).get("depth") or "") if isinstance(screen_positions.get(role), dict) else ""
        depth = str(cfg.get("depth") or screen_depth)
        if depth not in DEPTH_RANK:
            errors.append(f"{atomic_id}: scale_plan.subjects[{role}].depth 非法: {depth}")
            continue
        if screen_depth and depth != screen_depth:
            errors.append(f"{atomic_id}: scale_plan.subjects[{role}].depth={depth} 与 screen_positions={screen_depth} 不一致")
        ratio = cfg.get("frame_height_ratio")
        relative = cfg.get("relative_scale")
        if not _is_number(ratio) or not (0.01 <= float(ratio) <= 1.10):
            errors.append(f"{atomic_id}: scale_plan.subjects[{role}].frame_height_ratio 必须在 0.01-1.10")
            continue
        if not _is_number(relative) or not (0.01 <= float(relative) <= 1.50):
            errors.append(f"{atomic_id}: scale_plan.subjects[{role}].relative_scale 必须在 0.01-1.50")
            continue
        parsed[str(role)] = (DEPTH_RANK[depth], float(ratio))
        ratios.append(float(ratio))

    if ratios:
        largest = max(ratios)
        for role, (_, ratio) in parsed.items():
            rel = float((subjects.get(role) or {}).get("relative_scale", 0))
            expected = ratio / largest
            if abs(rel - expected) > 0.12:
                errors.append(f"{atomic_id}: scale_plan.subjects[{role}].relative_scale 与 frame_height_ratio 不一致")
        items = list(parsed.items())
        for i, (role_a, (rank_a, ratio_a)) in enumerate(items):
            for role_b, (rank_b, ratio_b) in items[i + 1:]:
                if rank_a < rank_b and ratio_a <= ratio_b:
                    errors.append(f"{atomic_id}: 景深比例违反近大远小: {role_a} 应大于 {role_b}")
                elif rank_b < rank_a and ratio_b <= ratio_a:
                    errors.append(f"{atomic_id}: 景深比例违反近大远小: {role_b} 应大于 {role_a}")
    return plan, errors


def validate_bible(scene_asset: str, bible: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    anchors = _anchor_catalog(bible)
    axes = _axis_catalog(bible)
    initial = _initial_world(bible)

    if not anchors:
        errors.append(f"scene={scene_asset}: spatial_bible.anchor_catalog 缺失或为空")
    if not initial:
        errors.append(f"scene={scene_asset}: spatial_bible.initial_world_positions 缺失或为空")

    for role, pos in initial.items():
        if not isinstance(pos, dict):
            errors.append(f"scene={scene_asset}: initial_world_positions[{role}] 必须是对象")
            continue
        aid = pos.get("anchor_id")
        if not aid:
            errors.append(f"scene={scene_asset}: initial_world_positions[{role}].anchor_id 缺失")
        elif aid not in anchors and str(aid).lower() not in {"offscreen", "outside", "unknown"}:
            errors.append(f"scene={scene_asset}: role={role} 使用未注册 anchor_id={aid}")

    for axis_id, axis in axes.items():
        if not isinstance(axis, dict):
            errors.append(f"scene={scene_asset}: axis_catalog[{axis_id}] 必须是对象")
            continue
        between = axis.get("between") or []
        if not isinstance(between, list) or len(between) < 2:
            errors.append(f"scene={scene_asset}: axis={axis_id}.between 至少包含两个空间端点/角色")
    return errors


def filter_world(world: Dict[str, Dict[str, Any]], relevant_roles: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    rel = list(relevant_roles)
    if not rel:
        return copy.deepcopy(world)
    out: Dict[str, Dict[str, Any]] = {}
    for r in rel:
        if r in world:
            out[r] = copy.deepcopy(world[r])
    return out


def apply_position_changes(
    scene_asset: str,
    atomic_id: str,
    world: Dict[str, Dict[str, Any]],
    changes: List[Dict[str, Any]],
    anchors: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    for idx, ch in enumerate(changes):
        if not isinstance(ch, dict):
            errors.append(f"{atomic_id}.position_changes[{idx}] 必须是对象")
            continue
        role = ch.get("role_id")
        from_anchor = ch.get("from_anchor")
        to_anchor = ch.get("to_anchor")
        reason = ch.get("reason")
        if not role or not to_anchor:
            errors.append(f"{atomic_id}.position_changes[{idx}] 缺少 role_id/to_anchor")
            continue
        role = str(role)
        to_anchor = str(to_anchor)
        if to_anchor not in anchors and to_anchor.lower() not in {"offscreen", "outside"}:
            errors.append(f"{atomic_id}: role={role} 目标 anchor_id 未注册: {to_anchor}")
            continue
        current = world.get(role)
        if current is None:
            # 新进入场景角色必须从 offscreen/outside 明确进入。
            if str(from_anchor or "").lower() not in {"offscreen", "outside"}:
                errors.append(f"{atomic_id}: role={role} 无初始世界位置，from_anchor 必须显式为 offscreen/outside")
                continue
            current = {"anchor_id": str(from_anchor), "visibility": "offscreen"}
        cur_anchor = str(current.get("anchor_id", ""))
        if from_anchor and str(from_anchor) != cur_anchor:
            errors.append(
                f"{atomic_id}: role={role} position_change.from_anchor={from_anchor} 与当前世界锚点={cur_anchor} 不一致"
            )
            continue
        if not reason:
            errors.append(f"{atomic_id}: role={role} position_change 缺少 reason，必须由剧本显式走位触发")
            continue

        nxt = copy.deepcopy(current)
        nxt["anchor_id"] = to_anchor
        if ch.get("to_position"):
            nxt["position"] = ch.get("to_position")
        elif to_anchor in anchors:
            desc = anchors[to_anchor].get("description") if isinstance(anchors[to_anchor], dict) else None
            if desc:
                nxt["position"] = desc
        if ch.get("facing_after"):
            nxt["facing"] = ch.get("facing_after")
        if ch.get("pose_height_after"):
            nxt["pose_height"] = ch.get("pose_height_after")
        if to_anchor.lower() in {"offscreen", "outside"}:
            nxt["visibility"] = "offscreen"
        else:
            nxt["visibility"] = ch.get("visibility_after", nxt.get("visibility", "visible"))
        world[role] = nxt
    return errors


def validate_axis_transition(
    scene_asset: str,
    atomic_id: str,
    prev_axis: Optional[Dict[str, Any]],
    cur_axis: Optional[Dict[str, Any]],
    axes: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    if not cur_axis:
        return errors
    axis_id = cur_axis.get("axis_id")
    if axis_id and axis_id not in axes:
        errors.append(f"{atomic_id}: camera_axis.axis_id 未在 scene={scene_asset} 注册: {axis_id}")
        return errors
    if not prev_axis:
        return errors
    if prev_axis.get("axis_id") != axis_id:
        return errors

    prev_side = _normalize_side(prev_axis.get("side"))
    cur_side = _normalize_side(cur_axis.get("side"))
    if prev_side and cur_side and prev_side != cur_side:
        axis_cfg = axes.get(axis_id, {}) or {}
        allowed = bool(axis_cfg.get("cross_axis_allowed"))
        crossed = bool(cur_axis.get("crossed"))
        if not crossed:
            errors.append(
                f"{atomic_id}: 同轴 {axis_id} camera side {prev_side}->{cur_side}，但 crossed=false/缺失；禁止无声明越轴"
            )
        elif not allowed:
            errors.append(f"{atomic_id}: axis={axis_id} 配置 cross_axis_allowed=false，禁止越轴")
        elif not cur_axis.get("transition_reason"):
            errors.append(f"{atomic_id}: 合法越轴必须提供 camera_axis.transition_reason")
    return errors


def enrich_document(doc: Dict[str, Any], allow_legacy: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    out = copy.deepcopy(doc)
    errors: List[str] = []
    warnings: List[str] = []
    contexts = scene_context_map(out)
    shots = out.get("atomic_shots") or []

    worlds: Dict[str, Dict[str, Dict[str, Any]]] = {}
    prev_axis_by_scene: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_scale_by_scene: Dict[str, Optional[Dict[str, Any]]] = {}
    bibles: Dict[str, Dict[str, Any]] = {}

    for scene_asset, candidates in contexts.items():
        ctx = choose_context(scene_asset, contexts)
        bible = (ctx or {}).get("spatial_bible") if ctx else None
        if not isinstance(bible, dict):
            if allow_legacy:
                warnings.append(f"scene={scene_asset}: 缺少 spatial_bible，按 legacy 模式跳过结构化空间校验")
                continue
            errors.append(f"scene={scene_asset}: 缺少 spatial_bible")
            continue
        bibles[scene_asset] = bible
        errors.extend(validate_bible(scene_asset, bible))
        worlds[scene_asset] = _initial_world(bible)
        prev_axis_by_scene[scene_asset] = None
        prev_scale_by_scene[scene_asset] = None

    enriched_count = 0
    for idx, shot in enumerate(shots):
        atomic_id = str(shot.get("atomic_id") or f"atomic[{idx}]")
        scene_asset = str(shot.get("scene_asset") or "")
        bible = bibles.get(scene_asset)
        plan = shot.get("spatial_plan")

        if bible is None:
            if allow_legacy:
                continue
            if scene_asset:
                errors.append(f"{atomic_id}: scene={scene_asset} 没有可用 spatial_bible")
            continue

        if not isinstance(plan, dict):
            if allow_legacy:
                warnings.append(f"{atomic_id}: 缺少 spatial_plan，保留 legacy 内容")
                continue
            errors.append(f"{atomic_id}: 缺少 spatial_plan")
            continue

        anchors = _anchor_catalog(bible)
        axes = _axis_catalog(bible)
        world = worlds[scene_asset]
        relevant = role_refs(shot)
        entry = filter_world(world, relevant)

        screen_positions = plan.get("screen_positions") or {}
        if not isinstance(screen_positions, dict):
            errors.append(f"{atomic_id}: spatial_plan.screen_positions 必须是对象")
            screen_positions = {}
        # 当前真正出现/参与的角色最好有 screen position；offscreen 可例外。
        for r in relevant:
            w = world.get(r, {}) or {}
            if str(w.get("visibility", "visible")) != "offscreen" and r not in screen_positions:
                warnings.append(f"{atomic_id}: role={r} 在 asset_refs 中出现但没有 screen_positions")

        explicit_scale = shot.get("scale_plan") is not None
        scale_plan, scale_errors = validate_scale_plan(
            atomic_id, shot, screen_positions, shot.get("scale_plan")
        )
        errors.extend(scale_errors)
        if scale_plan:
            shot["scale_plan"] = copy.deepcopy(scale_plan)

        # 不切镜、固定机位、无真实走位时，显式导演比例不得突变。
        prev_scale = prev_scale_by_scene.get(scene_asset) or {}
        movement = str((shot.get("camera_plan") or {}).get("movement") or "fixed")
        if explicit_scale and str(shot.get("transition_hint") or "").lower() == "continuous" and movement == "fixed":
            prev_subjects = prev_scale.get("subjects") or {}
            cur_subjects = scale_plan.get("subjects") or {}
            if not (plan.get("position_changes") or []):
                for role in set(prev_subjects) & set(cur_subjects):
                    a = (prev_subjects.get(role) or {}).get("frame_height_ratio")
                    b = (cur_subjects.get(role) or {}).get("frame_height_ratio")
                    if _is_number(a) and _is_number(b) and abs(float(a) - float(b)) > 0.12:
                        errors.append(
                            f"{atomic_id}: continuous+固定机位下 role={role} 镜内高度比例 {a}->{b} 无依据跳变"
                        )
        if scale_plan:
            prev_scale_by_scene[scene_asset] = copy.deepcopy(scale_plan)

        axis = plan.get("camera_axis")
        if axis is not None and not isinstance(axis, dict):
            errors.append(f"{atomic_id}: spatial_plan.camera_axis 必须是对象")
            axis = None
        errors.extend(validate_axis_transition(scene_asset, atomic_id, prev_axis_by_scene.get(scene_asset), axis, axes))

        changes_raw = plan.get("position_changes") or []
        if changes_raw and not isinstance(changes_raw, list):
            errors.append(f"{atomic_id}: position_changes 必须是数组")
            changes: List[Dict[str, Any]] = []
        else:
            changes = changes_raw if isinstance(changes_raw, list) else []
        errors.extend(apply_position_changes(scene_asset, atomic_id, world, changes, anchors))
        exit_world = filter_world(world, relevant)

        shot["spatial_state"] = {
            "entry_world_positions": entry,
            "exit_world_positions": exit_world,
            "screen_positions": copy.deepcopy(screen_positions),
            "scale_plan": copy.deepcopy(scale_plan),
        }
        if axis:
            shot["spatial_state"]["camera_axis"] = copy.deepcopy(axis)
            prev_axis_by_scene[scene_asset] = copy.deepcopy(axis)
        if changes:
            shot["spatial_state"]["position_changes"] = copy.deepcopy(changes)
        enriched_count += 1

    report = {
        "ok": not errors,
        "enriched_atomic_count": enriched_count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "allow_legacy": allow_legacy,
    }
    out["spatial_validation_meta"] = {
        "enriched_atomic_count": enriched_count,
        "warning_count": len(warnings),
        "mode": "legacy-compatible" if allow_legacy else "strict",
    }
    return out, report


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate/enrich A-stage spatial continuity")
    ap.add_argument("input", help="A-stage director JSON")
    ap.add_argument("output", help="Enriched A-stage JSON")
    ap.add_argument("--report", default=None, help="Optional validation report JSON")
    ap.add_argument("--allow-legacy", action="store_true", help="Allow old A JSON without spatial_bible/spatial_plan")
    args = ap.parse_args()

    doc = load_json(args.input)
    enriched, report = enrich_document(doc, allow_legacy=args.allow_legacy)
    if args.report:
        save_json(args.report, report)
    if not report["ok"]:
        print(f"SPATIAL VALIDATION FAILED: {report['error_count']} error(s)")
        for e in report["errors"]:
            print(f"- {e}")
        return 1
    save_json(args.output, enriched)
    print(
        f"SPATIAL VALIDATION OK: enriched={report['enriched_atomic_count']}, "
        f"warnings={report['warning_count']} -> {args.output}"
    )
    for w in report["warnings"][:20]:
        print(f"WARN: {w}")
    if report["warning_count"] > 20:
        print(f"WARN: ... {report['warning_count'] - 20} more warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
