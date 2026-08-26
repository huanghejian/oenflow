#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_planner.py - V7 逻辑素材参考规划器

不读取真实 URL / file_id / 本地文件路径。
只处理 A 阶段 LLM 选择的逻辑素材 ID，并依据 model_registry.json 中的：
- input_capabilities
- reference_modes
- 图片/视频/音频数量
- 总文件数
- 可选单文件时长
进行候选模型硬过滤。

真实素材绑定属于后续 video executor / 业务后端职责，不阻塞 prompt_zh 编译。
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

MEDIA_TYPES = ("image", "video", "audio")


def load_json(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def unique(values: Iterable[Any]) -> List[Any]:
    out, seen = [], set()
    for v in values:
        key = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def media_cap(model_cfg: Dict[str, Any], media_type: str) -> Dict[str, Any]:
    caps = model_cfg.get("input_capabilities", {}) or {}
    raw = caps.get(media_type + "s") or caps.get(media_type) or {}
    return raw if isinstance(raw, dict) else {}


def mode_supported(model_cfg: Dict[str, Any], mode: str) -> bool:
    modes = model_cfg.get("reference_modes", {}) or {}
    return bool(modes.get(mode, False))


def atomic_segments(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in (unit.get("timeline_segments") or []) if isinstance(s, dict) and s.get("type") == "atomic"]


def infer_purpose(media_type: str, asset_type: Optional[str] = None) -> str:
    if media_type == "image":
        return {
            "role": "character_reference",
            "scene": "scene_reference",
            "prop": "prop_reference",
            "style": "style_reference",
        }.get(str(asset_type or ""), "style_reference")
    if media_type == "video":
        return "video_motion_reference"
    if media_type == "audio":
        return "audio_voice_reference"
    return ""


def normalize_ref_item(raw: Any, media_type: str, required: bool, default_asset_type: Optional[str] = None, default_purpose: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        aid = raw.strip()
        if not aid:
            return None
        return {
            "asset_id": aid,
            "media_type": media_type,
            "asset_type": default_asset_type,
            "purpose": default_purpose or infer_purpose(media_type, default_asset_type),
            "required": required,
        }
    if not isinstance(raw, dict):
        return None
    aid = str(raw.get("asset_id") or raw.get("id") or raw.get("ref_id") or "").strip()
    if not aid:
        return None
    mt = str(raw.get("media_type") or media_type).lower().strip()
    purpose = raw.get("purpose") or raw.get("mode") or default_purpose or infer_purpose(mt, raw.get("asset_type") or default_asset_type)
    item: Dict[str, Any] = {
        "asset_id": aid,
        "media_type": mt,
        "asset_type": raw.get("asset_type") or default_asset_type,
        "purpose": str(purpose or ""),
        "required": bool(raw.get("required", required)),
    }
    if raw.get("duration_seconds") is not None:
        item["duration_seconds"] = raw.get("duration_seconds")
    if raw.get("priority") is not None:
        item["priority"] = raw.get("priority")
    if raw.get("note"):
        item["note"] = raw.get("note")
    return item


def _parse_reference_assets_container(container: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for bucket_name, required in (("required", True), ("optional", False)):
        bucket = container.get(bucket_name) or {}
        if isinstance(bucket, list):
            # 兼容 [{asset_id, media_type, ...}]
            for raw in bucket:
                mt = str(raw.get("media_type", "image")).lower() if isinstance(raw, dict) else "image"
                item = normalize_ref_item(raw, mt, required)
                if item:
                    out.append(item)
            continue
        if not isinstance(bucket, dict):
            continue
        for plural, mt in (("images", "image"), ("videos", "video"), ("audios", "audio")):
            vals = bucket.get(plural) or []
            if not isinstance(vals, list):
                vals = [vals]
            for raw in vals:
                item = normalize_ref_item(raw, mt, required)
                if item:
                    out.append(item)
    return out


def collect_reference_assets(unit: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """返回逻辑参考项 + warnings。

    新格式优先：atomic/reference_assets。
    旧格式兼容：scene_asset + asset_refs.roles/props 自动视为 required image。
    """
    out: List[Dict[str, Any]] = []
    warnings: List[str] = []
    found_new = False
    for seg in atomic_segments(unit):
        ra = seg.get("reference_assets")
        if isinstance(ra, dict):
            found_new = True
            out.extend(_parse_reference_assets_container(ra))

    if not found_new:
        # V6/旧A JSON兼容。这里只统计逻辑资产，不要求真实文件。
        scene = unit.get("scene_asset")
        if scene:
            out.append(normalize_ref_item(scene, "image", True, "scene", "scene_reference"))
        refs = unit.get("asset_refs", {}) or {}
        for rid in refs.get("roles", []) or []:
            out.append(normalize_ref_item(rid, "image", True, "role", "character_reference"))
        for pid in refs.get("props", []) or []:
            out.append(normalize_ref_item(pid, "image", True, "prop", "prop_reference"))
        warnings.append("legacy_reference_assets_derived_from_asset_refs")

    # V7.3：为同一图片模型生成的动作开始/结束状态普通参考图预留两个图片槽位。
    # 它们是流水线派生资产，不要求出现在用户 registered_assets 中。
    if unit.get("single_take") or unit.get("indivisible"):
        unit_id = str(unit.get("unit_id") or (unit.get("atomic_ids") or ["shot"])[0])
        for state in ("entry", "exit"):
            out.append({
                "asset_id": f"shotref::{unit_id}::{state}",
                "media_type": "image",
                "asset_type": "derived_shot_reference",
                "purpose": "style_reference",
                "required": True,
                "derived": True,
                "derived_role": f"{state}_state_reference",
            })

    # 合并同 asset_id+media_type，required 优先，purpose 合并成最强/首个（一个逻辑素材可同时服务多个用途）。
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    purpose_sets: Dict[Tuple[str, str], List[str]] = {}
    for item in out:
        if not item:
            continue
        key = (str(item.get("asset_id")), str(item.get("media_type", "image")))
        if key not in merged:
            merged[key] = copy.deepcopy(item)
            purpose_sets[key] = []
        merged[key]["required"] = bool(merged[key].get("required")) or bool(item.get("required"))
        p = str(item.get("purpose") or "")
        if p and p not in purpose_sets[key]:
            purpose_sets[key].append(p)
        if item.get("duration_seconds") is not None:
            prev = merged[key].get("duration_seconds")
            cur = item.get("duration_seconds")
            if prev is None or (isinstance(cur, (int, float)) and isinstance(prev, (int, float)) and cur > prev):
                merged[key]["duration_seconds"] = cur
        # optional 的 priority 供容量不足时排序；required 不依赖 priority。
        if item.get("priority") is not None:
            merged[key]["priority"] = max(float(merged[key].get("priority", 0) or 0), float(item.get("priority", 0) or 0))
    result = []
    for key, item in merged.items():
        purposes = purpose_sets[key]
        if purposes:
            item["purposes"] = purposes
            item["purpose"] = purposes[0]
        result.append(item)
    # required 保持原序优先，optional 高 priority 优先。
    result.sort(key=lambda x: (0 if x.get("required") else 1, -float(x.get("priority", 50) or 50)))
    return result, warnings


def catalog_ids(asset_catalog: Any) -> Optional[set[str]]:
    if not asset_catalog:
        return None
    ids: set[str] = set()
    if isinstance(asset_catalog, dict):
        for key, vals in asset_catalog.items():
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, str):
                        ids.add(v)
                    elif isinstance(v, dict):
                        aid = v.get("asset_id") or v.get("role_id") or v.get("prop_id") or v.get("id")
                        if aid:
                            ids.add(str(aid))
    elif isinstance(asset_catalog, list):
        for v in asset_catalog:
            if isinstance(v, str):
                ids.add(v)
            elif isinstance(v, dict):
                aid = v.get("asset_id") or v.get("role_id") or v.get("prop_id") or v.get("id")
                if aid:
                    ids.add(str(aid))
    return ids or None


def purpose_mode(purpose: str, media_type: str) -> str:
    p = str(purpose or "")
    aliases = {
        "character_identity": "character_reference",
        "identity_face": "character_reference",
        "scene_master": "scene_reference",
        "environment_reference": "scene_reference",
        "prop_identity": "prop_reference",
        "object_reference": "prop_reference",
        "motion_reference": "video_motion_reference",
        "camera_reference": "video_camera_reference",
        "voice_reference": "audio_voice_reference",
    }
    if p in aliases:
        return aliases[p]
    if p:
        return p
    return infer_purpose(media_type)


def check_item(item: Dict[str, Any], model_cfg: Dict[str, Any], known_ids: Optional[set[str]]) -> Tuple[bool, Optional[str]]:
    aid = str(item.get("asset_id") or "")
    mt = str(item.get("media_type", "image")).lower()
    if not aid:
        return False, "logical_asset_id_missing"
    if not item.get("derived") and known_ids is not None and aid not in known_ids:
        return False, f"logical_asset_not_registered:{aid}"
    if mt not in MEDIA_TYPES:
        return False, f"unsupported_media_type:{mt}"
    cap = media_cap(model_cfg, mt)
    if not cap or not bool(cap.get("supported", False)):
        return False, f"model_does_not_support_{mt}:{aid}"
    purposes = item.get("purposes") or [item.get("purpose")]
    for p in purposes:
        mode = purpose_mode(str(p or ""), mt)
        if mode and not mode_supported(model_cfg, mode):
            return False, f"reference_mode_unsupported:{aid}:{mode}"
    max_dur = cap.get("max_duration_per_file")
    dur = item.get("duration_seconds")
    if max_dur is not None and isinstance(dur, (int, float)) and float(dur) > float(max_dur):
        return False, f"{mt}_duration_exceeds_cap:{aid}:{dur}>{max_dur}"
    return True, None


def plan_references(unit: Dict[str, Any], model_cfg: Dict[str, Any], asset_catalog: Any = None) -> Dict[str, Any]:
    """为候选模型选择最小充分逻辑参考集。

    required：必须全部兼容并装入容量，否则候选 invalid。
    optional：只在模型支持且容量剩余时按 priority 选择；不足时直接丢弃，不升级模型。
    """
    caps = model_cfg.get("input_capabilities", {}) or {}
    known_ids = catalog_ids(asset_catalog)
    items, warnings = collect_reference_assets(unit)
    hard: List[str] = []
    selected: List[Dict[str, Any]] = []

    max_counts: Dict[str, int] = {}
    for mt in MEDIA_TYPES:
        cap = media_cap(model_cfg, mt)
        max_counts[mt] = int(cap.get("max_count", 0) or 0) if cap.get("supported", False) else 0
    max_total = caps.get("max_total_files")
    max_total_i = int(max_total) if isinstance(max_total, int) else sum(max_counts.values())
    used = {"image": 0, "video": 0, "audio": 0, "total": 0}

    required_items = [x for x in items if x.get("required")]
    optional_items = [x for x in items if not x.get("required")]

    # required 必须全部过能力/用途/数量门槛。
    for item in required_items:
        ok, reason = check_item(item, model_cfg, known_ids)
        if not ok:
            hard.append(reason or "required_reference_invalid")
            continue
        mt = str(item.get("media_type", "image")).lower()
        if used[mt] + 1 > max_counts.get(mt, 0):
            hard.append(f"required_{mt}_count_exceeded:{used[mt]+1}>{max_counts.get(mt,0)}")
            continue
        if used["total"] + 1 > max_total_i:
            hard.append(f"required_total_files_exceeded:{used['total']+1}>{max_total_i}")
            continue
        selected.append(copy.deepcopy(item))
        used[mt] += 1
        used["total"] += 1

    # optional 不阻塞候选；容量不足或用途不支持就丢弃并 warning。
    for item in optional_items:
        ok, reason = check_item(item, model_cfg, known_ids)
        if not ok:
            warnings.append("optional_dropped:" + str(reason))
            continue
        mt = str(item.get("media_type", "image")).lower()
        if used[mt] + 1 > max_counts.get(mt, 0) or used["total"] + 1 > max_total_i:
            warnings.append(f"optional_dropped_capacity:{item.get('asset_id')}:{mt}")
            continue
        selected.append(copy.deepcopy(item))
        used[mt] += 1
        used["total"] += 1

    # 输出只保留逻辑绑定，不包含 source/url/file_id。
    for r in selected:
        r.pop("source", None)
        r.pop("file_id", None)
        r.pop("path", None)
        r["binding_status"] = "derived_pending" if r.get("derived") else "logical_only"

    counts = {mt: sum(1 for r in selected if str(r.get("media_type", "image")).lower() == mt) for mt in MEDIA_TYPES}
    counts["total"] = sum(counts.values())
    return {
        "qualified": not hard,
        "logical_references": selected,
        "selected_references": selected,  # 保持 router 兼容字段名
        "counts": counts,
        "input_caps": copy.deepcopy(caps),
        "binding_status": "logical_only",
        **({"hard_reasons": unique(hard)} if hard else {}),
        **({"warnings": unique(warnings)} if warnings else {}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan logical model-compatible references for one generation unit")
    ap.add_argument("unit_json")
    ap.add_argument("model_registry")
    ap.add_argument("model_id")
    ap.add_argument("output_json")
    ap.add_argument("--asset-catalog", default=None, help="Optional JSON containing A-stage asset_catalog; no real file mapping required")
    args = ap.parse_args()
    udoc = load_json(args.unit_json)
    unit = udoc.get("generation_unit", udoc)
    mdoc = load_json(args.model_registry)
    model_cfg = (mdoc.get("model_registry", {}) or {}).get(args.model_id)
    if not model_cfg:
        raise SystemExit(f"unknown model_id: {args.model_id}")
    catalog = load_json(args.asset_catalog) if args.asset_catalog else udoc.get("asset_catalog")
    result = plan_references(unit, model_cfg, catalog)
    save_json(args.output_json, result)
    print(json.dumps({"qualified": result["qualified"], "counts": result["counts"], "hard_reasons": result.get("hard_reasons", [])}, ensure_ascii=False))
    return 0 if result["qualified"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
