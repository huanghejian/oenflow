from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .director_service import validate_director_plan_contract


ROUTING_CANDIDATE_FIELDS = {
    "model",
    "preset",
    "qualified",
    "request_duration",
    "padding_seconds",
    "fit_quality",
    "base_fit_quality",
    "preset_quality_adjust",
    "shot_quality_adjust",
    "reliability",
    "call_points",
    "expected_usable_points",
    "pricing_formula",
    "margins",
    "preset_output_resolution",
    "reference_counts",
    "cost_efficiency",
    "reliability_score",
    "tier_score",
    "hard_reasons",
}


def _build_routing_analysis(routed_plan: dict[str, Any]) -> dict[str, Any]:
    shots: list[dict[str, Any]] = []
    for unit in routed_plan.get("routed_units", []):
        if not isinstance(unit, dict):
            continue
        decision = unit.get("routing_decision") or {}
        candidates = decision.get("candidates") or []
        selected_model = decision.get("selected_model")
        selected_preset = decision.get("selected_preset")
        compact_candidates = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            compact = {
                key: value
                for key, value in candidate.items()
                if key in ROUTING_CANDIDATE_FIELDS
            }
            compact["selected"] = (
                candidate.get("model") == selected_model
                and candidate.get("preset") == selected_preset
            )
            compact_candidates.append(compact)
        compact_decision = {
            key: value
            for key, value in decision.items()
            if key != "candidates"
        }
        compact_decision["candidates"] = compact_candidates
        shots.append(
            {
                "shot_id": unit.get("unit_id"),
                "atomic_ids": unit.get("atomic_ids", []),
                "scene_asset": unit.get("scene_asset"),
                "story_priority": unit.get("story_priority"),
                "narrative_classes": unit.get("narrative_classes", []),
                "narrative_functions": unit.get("narrative_functions", []),
                "duration": unit.get("duration"),
                "routing_requirements": unit.get("routing_requirements", {}),
                "reference_summary": unit.get("reference_summary", {}),
                "routing_decision": compact_decision,
            }
        )
    return {
        "tier": routed_plan.get("routing_tier"),
        "target_resolution": routed_plan.get("target_resolution"),
        "routing_meta": routed_plan.get("routing_meta", {}),
        "shots": shots,
    }


def _safe_job_dir(job_id: str, tier: str) -> Path:
    job_dir = (settings.work_root / job_id / tier).resolve()
    if settings.work_root != job_dir and settings.work_root not in job_dir.parents:
        raise RuntimeError("非法任务输出路径")
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def compile_video_plan(
    director_plan: dict[str, Any], tier: str, target_resolution: str
) -> dict[str, Any]:
    validate_director_plan_contract(director_plan)
    job_id = uuid.uuid4().hex
    job_dir = _safe_job_dir(job_id, tier)
    input_path = job_dir / "director_plan.json"
    input_path.write_text(
        json.dumps(director_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    run_pipeline = settings.pipeline_root / "scripts" / "run_pipeline.py"
    if not run_pipeline.is_file():
        raise RuntimeError(f"流水线入口不存在: {run_pipeline}")
    command = [
        sys.executable,
        str(run_pipeline),
        str(input_path),
        "--output-dir",
        str(job_dir),
        "--tier",
        tier,
        "--target-resolution",
        target_resolution,
        "--model-config",
        str(settings.model_registry_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        timeout=settings.pipeline_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "后端流水线失败\n"
            f"exit_code={result.returncode}\n"
            f"stdout={result.stdout[-6000:]}\n"
            f"stderr={result.stderr[-6000:]}"
        )

    final_path = job_dir / "director_plan_final_video_shots.json"
    validation_path = job_dir / "director_plan_validation.json"
    routed_path = job_dir / "director_plan_routed_units.json"
    if not final_path.is_file() or not validation_path.is_file() or not routed_path.is_file():
        raise RuntimeError("流水线完成但缺少 final、routing 或 validation 文件")

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if not validation.get("ok"):
        raise RuntimeError(f"最终验收失败: {validation.get('errors', [])}")
    final_plan = json.loads(final_path.read_text(encoding="utf-8"))
    routed_plan = json.loads(routed_path.read_text(encoding="utf-8"))
    return {
        "job_id": job_id,
        "tier": tier,
        "target_resolution": target_resolution,
        "final_video_plan": final_plan,
        "routing_analysis": _build_routing_analysis(routed_plan),
        "validation": validation,
        "artifacts": {
            "job_dir": str(job_dir),
            "final_json": str(final_path),
            "routed_json": str(routed_path),
            "validation_json": str(validation_path),
        },
    }
