#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_final.py - V7 最终短剧视频 JSON 确定性校验器。

V7 允许最终输出只有逻辑 references，不要求真实 URL/file_id/source。
真实文件映射属于后续 video executor。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


DEPTH_RANK = {"foreground": 0, "midground": 1, "background": 2}
VALID_CUT_TYPES = {
    "scene_start", "scene_end", "hard_cut", "concealed_cut",
    "match_cut_action", "match_cut_shape", "fade",
}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def scale_prompt_required(plan: Dict[str, Any]) -> bool:
    subjects = plan.get("subjects") or {}
    depths = {
        str(v.get("depth") or "")
        for v in subjects.values()
        if isinstance(v, dict) and v.get("depth")
    }
    shot_size = str(plan.get("shot_size") or "")
    return len(depths) > 1 or any(x in shot_size for x in ("极远景", "中远景", "远景", "全景", "中景"))


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_config(config_path: Optional[str]) -> Path:
    if config_path:
        return Path(config_path)
    return Path(__file__).resolve().parent.parent / "resources" / "model_registry.json"


def catalog_ids(asset_catalog: Any) -> Optional[Set[str]]:
    if not asset_catalog:
        return None
    ids: Set[str] = set()
    if isinstance(asset_catalog, dict):
        for vals in asset_catalog.values():
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


def purpose_mode(purpose: str) -> str:
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
    return aliases.get(purpose, purpose)


def validate(doc: Dict[str, Any], config: Dict[str, Any], allow_debug: bool = False) -> List[str]:
    errors: List[str] = []
    registry = config.get("model_registry", {}) or {}
    known_ids = catalog_ids(doc.get("asset_catalog"))
    shots = doc.get("shots")
    if not isinstance(shots, list) or not shots:
        return ["shots 必须是非空数组"]

    seen = set()
    target_resolution = str(doc.get("target_resolution", "720P")).upper()
    for i, shot in enumerate(shots):
        p = f"shots[{i}]"
        sid = shot.get("shot_id")
        if not sid:
            errors.append(f"{p}.shot_id 缺失")
        elif sid in seen:
            errors.append(f"shot_id 重复: {sid}")
        else:
            seen.add(sid)

        cut_in = shot.get("cut_in")
        cut_out = shot.get("cut_out")
        if cut_in not in VALID_CUT_TYPES:
            errors.append(f"{p}.cut_in 非法或缺失: {cut_in}")
        if cut_out not in VALID_CUT_TYPES:
            errors.append(f"{p}.cut_out 非法或缺失: {cut_out}")
        if shot.get("transition") != cut_in:
            errors.append(f"{p}.transition 必须与 cut_in 一致")
        if i > 0 and isinstance(shots[i - 1], dict):
            previous = shots[i - 1]
            same_scene = previous.get("scene_asset") == shot.get("scene_asset")
            if same_scene and previous.get("cut_out") != cut_in:
                errors.append(f"{p}.cut_in 必须与上一镜 cut_out 一致")
            if not same_scene and (previous.get("cut_out") != "scene_end" or cut_in != "scene_start"):
                errors.append(f"{p}: 跨场景边界必须是 scene_end → scene_start")
        if bool(shot.get("single_take")) != bool(shot.get("indivisible")):
            errors.append(f"{p}: single_take 与 indivisible 必须同时为 true 或同时为 false")
        atomic_ids = shot.get("atomic_ids")
        if not isinstance(atomic_ids, list) or not atomic_ids:
            errors.append(f"{p}.atomic_ids 必须是非空数组")
        elif shot.get("indivisible") and len(atomic_ids) != 1:
            errors.append(f"{p}: 不可拆分连续镜头必须只包含一个 atomic_id")

        image_plan = shot.get("reference_image_plan")
        if not isinstance(image_plan, dict):
            errors.append(f"{p}.reference_image_plan 必须是对象")
        else:
            if image_plan.get("usage") != "ordinary_image_reference":
                errors.append(f"{p}.reference_image_plan.usage 必须为 ordinary_image_reference")
            if image_plan.get("generation_strategy") != "same_image_model_generate_then_edit":
                errors.append(f"{p}.reference_image_plan.generation_strategy 非法")
            output_ids = image_plan.get("output_asset_ids")
            if not isinstance(output_ids, dict) or not output_ids.get("entry") or not output_ids.get("exit"):
                errors.append(f"{p}.reference_image_plan.output_asset_ids 必须包含 entry/exit")
            for key in ("entry_state_reference_prompt_zh", "exit_state_reference_edit_prompt_zh"):
                value = image_plan.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{p}.reference_image_plan.{key} 缺失或为空")
                elif "普通图片参考" not in value:
                    errors.append(f"{p}.reference_image_plan.{key} 未声明普通图片参考用途")
            source_id = image_plan.get("continuity_source_shot_id")
            if source_id and (source_id not in seen or source_id == sid):
                errors.append(f"{p}.reference_image_plan.continuity_source_shot_id 必须指向前序镜头")
            if source_id and image_plan.get("depends_on_output_asset_id") != f"shotref::{source_id}::exit":
                errors.append(f"{p}.reference_image_plan.depends_on_output_asset_id 与前序镜头不一致")

        model = shot.get("model")
        if model not in registry:
            errors.append(f"{p}.model 未注册: {model}")
            continue
        mcfg = registry[model]

        dur = shot.get("duration")
        if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
            errors.append(f"{p}.duration 必须是正整数")
        else:
            mn, mx = int(mcfg.get("min_duration", 1)), int(mcfg.get("max_duration", 999))
            if dur < mn or dur > mx:
                errors.append(f"{p}.duration={dur} 不在 {model} 合法区间 {mn}-{mx}")

        params = shot.get("model_params")
        if not isinstance(params, dict):
            errors.append(f"{p}.model_params 必须是对象")
            params = {}
        oc = params.get("output_count")
        if not isinstance(oc, int) or isinstance(oc, bool) or not (1 <= oc <= 5):
            errors.append(f"{p}.model_params.output_count 必须为1-5整数")

        if model == "seedance-2.0":
            if not isinstance(params.get("human_mode"), bool):
                errors.append(f"{p}: Seedance2.0 必须显式输出 boolean human_mode")
        elif "human_mode" in params:
            errors.append(f"{p}: {model} 不应输出 human_mode")

        presets = mcfg.get("preset_profiles", {}) or {}
        preset = params.get("resolution_preset")
        if preset is not None:
            if preset not in presets:
                errors.append(f"{p}.resolution_preset 未注册: {preset}")
            else:
                pcfg = presets[preset]
                if not pcfg.get("enabled", True):
                    errors.append(f"{p}.resolution_preset 已禁用: {preset}")
                output_resolution = str(pcfg.get("output_resolution", "")).upper()
                if not output_resolution:
                    errors.append(f"{p}.resolution_preset={preset} 缺少 output_resolution")
                elif output_resolution != target_resolution:
                    errors.append(
                        f"{p}.resolution_preset={preset} 输出 {output_resolution}，"
                        f"必须严格等于 target_resolution={target_resolution}"
                    )
                allowed = [str(x).upper() for x in pcfg.get("allowed_target_resolutions", []) or []]
                if allowed and target_resolution not in allowed:
                    errors.append(f"{p}.resolution_preset={preset} 不支持 target_resolution={target_resolution}")
        else:
            explicit = [name for name, pcfg in presets.items() if pcfg.get("enabled", True) and pcfg.get("emit_resolution_preset", True)]
            implicit = [name for name, pcfg in presets.items() if pcfg.get("enabled", True) and not pcfg.get("emit_resolution_preset", True)]
            if explicit and not implicit:
                errors.append(f"{p}.model_params.resolution_preset 缺失")

        # V7：逻辑素材引用校验。source/url/file_id 不属于本阶段。
        refs = shot.get("references", [])
        if not isinstance(refs, list):
            errors.append(f"{p}.references 必须是数组")
            refs = []
        if shot.get("reference_binding_status") not in (None, "logical_only"):
            errors.append(f"{p}.reference_binding_status 非法: {shot.get('reference_binding_status')}")

        caps = mcfg.get("input_capabilities", {}) or {}
        modes = mcfg.get("reference_modes", {}) or {}
        counts = {"image": 0, "video": 0, "audio": 0}
        dedupe = set()
        for ri, ref in enumerate(refs):
            rp = f"{p}.references[{ri}]"
            if not isinstance(ref, dict):
                errors.append(f"{rp} 必须是对象")
                continue
            aid = str(ref.get("asset_id") or "")
            mt = str(ref.get("media_type", "image")).lower()
            if not aid:
                errors.append(f"{rp}.asset_id 缺失")
            elif not ref.get("derived") and known_ids is not None and aid not in known_ids:
                errors.append(f"{rp}.asset_id 未在 A阶段 asset_catalog 注册: {aid}")
            if ref.get("derived"):
                if ref.get("asset_type") != "derived_shot_reference":
                    errors.append(f"{rp}.asset_type 必须为 derived_shot_reference")
                if ref.get("binding_status") != "derived_pending":
                    errors.append(f"{rp}.binding_status 必须为 derived_pending")
            key = (aid, mt)
            if key in dedupe:
                errors.append(f"{rp}: 逻辑素材重复: {aid}/{mt}")
            dedupe.add(key)
            if mt not in counts:
                errors.append(f"{rp}.media_type 非法: {mt}")
                continue
            counts[mt] += 1
            cap = caps.get(mt + "s", {}) or {}
            if not cap.get("supported", False):
                errors.append(f"{rp}: 模型 {model} 不支持 {mt} 素材")
            purposes = ref.get("purposes") or ([ref.get("purpose")] if ref.get("purpose") else [])
            for purpose in purposes:
                mode = purpose_mode(str(purpose))
                if mode and not modes.get(mode, False):
                    errors.append(f"{rp}: 模型 {model} 不支持素材用途 {mode}")
            max_dur = cap.get("max_duration_per_file")
            dur_ref = ref.get("duration_seconds")
            if max_dur is not None and isinstance(dur_ref, (int, float)) and float(dur_ref) > float(max_dur):
                errors.append(f"{rp}.duration_seconds={dur_ref} 超过 {model} 单文件上限 {max_dur}")
            # 明确禁止把真实路径作为本阶段硬要求；有也不报错，但 pipeline 不依赖它。

        for mt, cnt in counts.items():
            cap = caps.get(mt + "s", {}) or {}
            mx = int(cap.get("max_count", 0) or 0) if cap.get("supported", False) else 0
            if cnt > mx:
                errors.append(f"{p}: {mt} 逻辑素材 {cnt} 个超过 {model} 上限 {mx}")
        max_total = caps.get("max_total_files")
        if isinstance(max_total, int) and sum(counts.values()) > max_total:
            errors.append(f"{p}: 总逻辑素材 {sum(counts.values())} 个超过 {model} 上限 {max_total}")
        if isinstance(image_plan, dict) and isinstance(image_plan.get("output_asset_ids"), dict):
            expected_derived = set(image_plan["output_asset_ids"].values())
            actual_derived = {str(x.get("asset_id")) for x in refs if isinstance(x, dict) and x.get("derived")}
            if shot.get("indivisible") and expected_derived != actual_derived:
                errors.append(f"{p}: 派生普通图片参考资产与 reference_image_plan.output_asset_ids 不一致")

        prompt = shot.get("prompt_zh")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{p}.prompt_zh 缺失或为空")
        else:
            subtitle_rule = "画面无字幕、字卡和其他文字"
            if subtitle_rule not in prompt:
                errors.append(f"{p}.prompt_zh 缺少统一字幕禁令")
            if prompt.count(subtitle_rule) > 1:
                errors.append(f"{p}.prompt_zh 字幕禁令重复")
            if shot.get("single_take"):
                if "连续镜头规则：" not in prompt or "内部不切镜" not in prompt:
                    errors.append(f"{p}.prompt_zh 缺少不可拆分连续镜头规则")
                if re.search(r"第\d+秒(?:硬切|切入环境缓冲空镜|淡入淡出转场|以.+匹配剪辑|按情绪反应切镜)", prompt):
                    errors.append(f"{p}.prompt_zh 的不可拆分连续镜头内部出现剪辑指令")
            forbidden_debug_patterns = {
                "锚点编号": r"锚点A\d+",
                "摄影轴编号": r"\bAX\d+\b",
                "摄影轴枚举": r"\b(?:side|crossed)=",
                "屏幕位置枚举": r"\b(?:lower_left|lower_right|upper_left|upper_right|left_third|right_third|foreground|background)\b",
                "素材后台描述": r":(?:image|video|audio):",
                "路由评分标签": r"表演精度需求为(?:none|low|medium|high|critical)",
                "比例结构字段": r"\b(?:frame_height_ratio|relative_scale|perspective_mode|lens_style)\b",
            }
            for label, pattern in forbidden_debug_patterns.items():
                if re.search(pattern, prompt):
                    errors.append(f"{p}.prompt_zh 泄漏{label}")

            spatial_lock = shot.get("spatial_lock") or {}
            spatial_prompt = shot.get("spatial_prompt")
            if spatial_lock:
                if not isinstance(spatial_prompt, str) or not spatial_prompt.strip():
                    errors.append(f"{p}.spatial_prompt 缺失")
                elif spatial_prompt not in prompt:
                    errors.append(f"{p}.prompt_zh 未包含自然语言空间约束")

        spatial_segments = shot.get("spatial_segments")
        if not isinstance(spatial_segments, list) or not spatial_segments:
            errors.append(f"{p}.spatial_segments 必须是非空数组")

        scale_segments = shot.get("scale_segments")
        scale_sensitive = False
        if not isinstance(scale_segments, list) or not scale_segments:
            errors.append(f"{p}.scale_segments 必须是非空数组")
            scale_segments = []
        elif isinstance(spatial_segments, list) and len(scale_segments) != len(spatial_segments):
            errors.append(f"{p}.scale_segments 与 spatial_segments 数量不一致")

        for si, item in enumerate(scale_segments):
            sp = f"{p}.scale_segments[{si}]"
            if not isinstance(item, dict):
                errors.append(f"{sp} 必须是对象")
                continue
            plan = item.get("scale_plan")
            if not isinstance(plan, dict):
                errors.append(f"{sp}.scale_plan 必须是对象")
                continue
            scale_sensitive = scale_sensitive or scale_prompt_required(plan)
            subjects = plan.get("subjects") or {}
            if not isinstance(subjects, dict):
                errors.append(f"{sp}.scale_plan.subjects 必须是对象")
                continue
            parsed = []
            ratios = []
            for role, cfg_item in subjects.items():
                rp = f"{sp}.scale_plan.subjects[{role}]"
                if not isinstance(cfg_item, dict):
                    errors.append(f"{rp} 必须是对象")
                    continue
                depth = str(cfg_item.get("depth") or "")
                ratio = cfg_item.get("frame_height_ratio")
                relative = cfg_item.get("relative_scale")
                if depth not in DEPTH_RANK:
                    errors.append(f"{rp}.depth 非法: {depth}")
                if not is_number(ratio) or not (0.01 <= float(ratio) <= 1.10):
                    errors.append(f"{rp}.frame_height_ratio 必须在 0.01-1.10")
                    continue
                if not is_number(relative) or not (0.01 <= float(relative) <= 1.50):
                    errors.append(f"{rp}.relative_scale 必须在 0.01-1.50")
                    continue
                if depth in DEPTH_RANK:
                    parsed.append((str(role), DEPTH_RANK[depth], float(ratio)))
                ratios.append((str(role), float(ratio), float(relative)))
            if ratios:
                largest = max(x[1] for x in ratios)
                for role, ratio, relative in ratios:
                    if abs(relative - ratio / largest) > 0.12:
                        errors.append(f"{sp}: role={role} relative_scale 与 frame_height_ratio 不一致")
            for ai, (role_a, rank_a, ratio_a) in enumerate(parsed):
                for role_b, rank_b, ratio_b in parsed[ai + 1:]:
                    if rank_a < rank_b and ratio_a <= ratio_b:
                        errors.append(f"{sp}: 近大远小失效，{role_a} 应大于 {role_b}")
                    elif rank_b < rank_a and ratio_b <= ratio_a:
                        errors.append(f"{sp}: 近大远小失效，{role_b} 应大于 {role_a}")

        if scale_sensitive:
            scale_prompt = shot.get("scale_prompt")
            if not isinstance(scale_prompt, str) or not scale_prompt.strip():
                errors.append(f"{p}.scale_prompt 缺失")
            if isinstance(prompt, str):
                if "比例关系：" not in prompt:
                    errors.append(f"{p}.prompt_zh 未注入镜内比例约束")
                if any(
                    len({str(v.get('depth') or '') for v in ((x.get('scale_plan') or {}).get('subjects') or {}).values() if isinstance(v, dict)}) > 1
                    for x in scale_segments if isinstance(x, dict)
                ) and "近大远小" not in prompt:
                    errors.append(f"{p}.prompt_zh 缺少近大远小约束")
                if "不复制参考图的取景范围、人物大小或背景构图" not in prompt:
                    errors.append(f"{p}.prompt_zh 缺少参考图比例解耦约束")

        continuity = shot.get("continuity")
        if not isinstance(continuity, dict):
            errors.append(f"{p}.continuity 必须是对象")
        else:
            for key in ("entry", "exit", "los"):
                if not continuity.get(key):
                    errors.append(f"{p}.continuity.{key} 缺失")

        if not shot.get("scene_asset"):
            errors.append(f"{p}.scene_asset 缺失")
        if not isinstance(shot.get("complexity"), dict):
            errors.append(f"{p}.complexity 必须是对象")
        if not allow_debug and "routing_decision" in shot:
            errors.append(f"{p}: 生产输出不应保留 routing_decision（调试模式除外）")

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate V7 final video shots JSON with logical references")
    ap.add_argument("input", help="Final video shots JSON")
    ap.add_argument("--model-config", default=None, help="model_registry.json path")
    ap.add_argument("--allow-debug", action="store_true", help="Allow routing_decision in final shots")
    ap.add_argument("--report", default=None, help="Optional validation report JSON path")
    args = ap.parse_args()

    cfg_path = resolve_config(args.model_config)
    if not cfg_path.exists():
        print(f"ERROR: model config not found: {cfg_path}")
        return 2
    doc = load_json(args.input)
    cfg = load_json(cfg_path)
    errors = validate(doc, cfg, args.allow_debug)
    report = {"ok": not errors, "input": str(args.input), "error_count": len(errors), "errors": errors}
    if args.report:
        save_json(args.report, report)
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"- {e}")
        return 1
    print(f"VALIDATION OK: {len(doc.get('shots', []))} shots; logical references validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
