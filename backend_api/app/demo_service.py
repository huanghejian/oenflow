from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from .autoflow_service import _build_routing_analysis


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = WORKSPACE_ROOT / "work" / "EP001_V73"
DIRECTOR_PLAN_PATH = DEMO_ROOT / "EP001_V73_A导演输出.json"

DEMO_SCRIPT = """第 1 集《一刀到账》

叶家山门外，秦族神子秦放以金色巨剑击碎护山大阵，逼迫叶家交出叶澜。叶灵带领叶家弟子迎战，却被秦放以威压镇住。

刚穿越而来的叶澜躲在石柱后，发现自己毫无修为，正准备溜走时意外激活“并夕夕系统”：只要让秦放砍中一刀，就能领取筑基大圆满修为，但领取时间只剩十秒。

叶澜只好走到广场中央，故意挑衅秦放。秦放先是错愕，随即暴怒，以金色剑气斩向叶澜。剑气命中后，叶澜不但没有倒下，反而露出得逞的笑容——系统奖励到账，气势瞬间逆转。"""


def _tier_paths(tier: str) -> tuple[Path, Path, Path]:
    tier_root = DEMO_ROOT / f"pipeline_{tier}"
    return (
        tier_root / "EP001_V73_final_video_shots.json",
        tier_root / "EP001_V73_validation.json",
        tier_root / "EP001_V73_routed_units.json",
    )


def demo_case_available() -> bool:
    paths = [DIRECTOR_PLAN_PATH]
    for tier in ("low", "medium", "high"):
        paths.extend(_tier_paths(tier))
    return all(path.is_file() for path in paths)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_demo_case() -> dict[str, Any]:
    if not demo_case_available():
        raise RuntimeError("本地演示案例文件不完整，请确认 work/EP001_V73 已保留。")

    director_plan = _read_json(DIRECTOR_PLAN_PATH)
    asset_catalog = director_plan.get("asset_catalog", {})
    registered_assets = {
        category: [{"asset_id": asset_id} for asset_id in asset_catalog.get(category, [])]
        for category in ("scenes", "roles", "props")
    }

    return {
        "demo": {
            "title": "EP001 · 一刀到账",
            "description": "东方玄幻竖屏短剧，已通过 V7.3 三档流水线验收",
            "source": "bundled_demo_case",
        },
        "input": {
            "episode_id": "EP001",
            "project_type": "短剧",
            "aspect_ratio": "9:16",
            "resolution": "720P",
            "global_visual_lock": "东方玄幻真人短剧，冷青灰电影质感",
            "feedback": "节奏紧凑，强化开场压迫感、系统喜剧反差与结尾反转。",
            "registered_assets": registered_assets,
            "script": DEMO_SCRIPT,
        },
        "director_plan": director_plan,
        "llm": {
            "provider": "local_demo",
            "model": "bundled-v7.3-result",
            "finish_reason": "demo",
        },
    }


@lru_cache(maxsize=3)
def load_demo_tier(tier: str) -> dict[str, Any]:
    if tier not in {"low", "medium", "high"}:
        raise ValueError(f"不支持的 Demo 档位: {tier}")
    final_path, validation_path, routed_path = _tier_paths(tier)
    for path in (final_path, validation_path, routed_path):
        if not path.is_file():
            raise RuntimeError(f"Demo 文件缺失: {path.name}")
    routed = _read_json(routed_path)
    return {
        "job_id": f"demo-ep001-v73-{tier}",
        "tier": tier,
        "target_resolution": "720P",
        "final_video_plan": _read_json(final_path),
        "routing_analysis": _build_routing_analysis(routed),
        "validation": _read_json(validation_path),
        "artifacts": {"source": "bundled_demo_case"},
    }


DEBUG_STAGES: dict[str, dict[str, str]] = {
    "director": {
        "title": "A 导演输出",
        "description": "检查场景空间母版、原子分镜、镜头语言、素材选择与连续性。",
        "input": "页面参数 + 注册资产 + 剧本 + 导演 Prompt",
    },
    "spatial": {
        "title": "空间连续性校验",
        "description": "独立检查世界站位、摄影轴线、屏幕位置与人物景深比例。",
        "input": "EP001_V73_A导演输出.json",
    },
    "packer": {
        "title": "原子分镜打包",
        "description": "独立检查每个不可拆分 atomic 是否形成合法 generation unit。",
        "input": "EP001_V73_A_spatial_enriched.json",
    },
    "router": {
        "title": "模型与 Preset 路由",
        "description": "独立检查接口准入、候选评分、可靠性、积分和最终模型选择。",
        "input": "EP001_V73_generation_units.json",
    },
    "compiler": {
        "title": "最终提示词编译",
        "description": "独立检查每镜 prompt_zh、逻辑 references、空间锁与普通图片参考任务。",
        "input": "EP001_V73_routed_units.json",
    },
    "validator": {
        "title": "Final JSON 验收",
        "description": "独立检查最终结构、模型参数、素材容量、提示词和连续性合同。",
        "input": "EP001_V73_final_video_shots.json",
    },
}


def _debug_artifact_path(stage: str, tier: str) -> Path:
    if stage not in DEBUG_STAGES:
        raise ValueError(f"不支持的 Demo 调试环节: {stage}")
    if tier not in {"low", "medium", "high"}:
        raise ValueError(f"不支持的 Demo 档位: {tier}")
    if stage == "director":
        return DIRECTOR_PLAN_PATH
    tier_root = DEMO_ROOT / f"pipeline_{tier}"
    filenames = {
        "spatial": "EP001_V73_A_spatial_enriched.json",
        "packer": "EP001_V73_generation_units.json",
        "router": "EP001_V73_routed_units.json",
        "compiler": "EP001_V73_final_video_shots.json",
        "validator": "EP001_V73_validation.json",
    }
    return tier_root / filenames[stage]


def demo_debug_artifact_path(stage: str, tier: str) -> Path:
    path = _debug_artifact_path(stage, tier)
    if not path.is_file():
        raise RuntimeError(f"Demo 调试制品缺失: {path.name}")
    return path


def _debug_summary(stage: str, data: dict[str, Any], tier: str) -> dict[str, Any]:
    if stage == "director":
        shots = data.get("atomic_shots") or []
        catalog = data.get("asset_catalog") or {}
        return {
            "原子分镜": len(shots),
            "场景上下文": len(data.get("scene_contexts") or []),
            "总时长": f"{sum(int(x.get('atomic_duration') or 0) for x in shots)}s",
            "逻辑资产": sum(len(catalog.get(key) or []) for key in ("scenes", "roles", "props")),
        }
    if stage == "spatial":
        report_path = DEMO_ROOT / f"pipeline_{tier}" / "EP001_V73_spatial_validation.json"
        report = _read_json(report_path)
        return {
            "校验状态": "PASS" if report.get("ok") else "FAIL",
            "已展开原子": report.get("enriched_atomic_count", 0),
            "错误": report.get("error_count", 0),
            "警告": report.get("warning_count", 0),
        }
    if stage == "packer":
        return {
            "生成单元": len(data.get("generation_units") or []),
            "原子分镜": (data.get("packer_meta") or {}).get("atomic_shot_count", 0),
            "不可拆分": (data.get("packer_meta") or {}).get("indivisible_unit_count", 0),
            "档位": tier.upper(),
        }
    if stage == "router":
        units = data.get("routed_units") or []
        models = Counter(
            str((unit.get("routing_decision") or {}).get("selected_model") or "unknown")
            for unit in units
        )
        return {
            "已路由单元": len(units),
            "模型分布": " / ".join(f"{key}:{value}" for key, value in sorted(models.items())),
            "目标分辨率": data.get("target_resolution", "—"),
            "档位": tier.upper(),
        }
    if stage == "compiler":
        shots = data.get("shots") or []
        return {
            "Final 分镜": len(shots),
            "已编译 prompt_zh": sum(bool(x.get("prompt_zh")) for x in shots),
            "图片参考任务": len(data.get("reference_image_jobs") or []),
            "档位": tier.upper(),
        }
    return {
        "验收状态": "PASS" if data.get("ok") else "FAIL",
        "错误数": data.get("error_count", 0),
        "输入制品": data.get("input", "—"),
        "档位": tier.upper(),
    }


def _debug_preview(stage: str, data: dict[str, Any], tier: str) -> dict[str, Any]:
    array_limits = {
        "scene_contexts": 1,
        "atomic_shots": 3,
        "generation_units": 3,
        "merge_trace": 3,
        "routed_units": 3,
        "shots": 3,
        "reference_image_jobs": 3,
        "errors": 10,
        "warnings": 10,
    }
    preview: dict[str, Any] = {}
    truncated: dict[str, dict[str, int]] = {}
    for key, value in data.items():
        if isinstance(value, list) and key in array_limits:
            limit = array_limits[key]
            preview[key] = value[:limit]
            if len(value) > limit:
                truncated[key] = {"shown": limit, "total": len(value)}
        else:
            preview[key] = value
    if stage == "spatial":
        report_path = DEMO_ROOT / f"pipeline_{tier}" / "EP001_V73_spatial_validation.json"
        preview["spatial_validation_report"] = _read_json(report_path)
    if truncated:
        preview["_debug_preview"] = {
            "note": "页面仅展示前几项；下载制品包含完整数据",
            "truncated_arrays": truncated,
        }
    return preview


@lru_cache(maxsize=18)
def load_demo_debug_stage(stage: str, tier: str) -> dict[str, Any]:
    path = demo_debug_artifact_path(stage, tier)
    data = _read_json(path)
    config = DEBUG_STAGES[stage]
    return {
        "stage": stage,
        "title": config["title"],
        "description": config["description"],
        "tier": tier,
        "input_artifact": config["input"],
        "output_artifact": path.name,
        "output_size_bytes": path.stat().st_size,
        "summary": _debug_summary(stage, data, tier),
        "preview": _debug_preview(stage, data, tier),
        "download_url": f"/v1/demo/debug/{stage}/download?tier={tier}",
    }
