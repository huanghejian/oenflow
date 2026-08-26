from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from app.pipeline_service import compile_video_plan


def upgrade_fixture(plan: dict) -> dict:
    upgraded = copy.deepcopy(plan)
    shots = upgraded["atomic_shots"]
    for index, shot in enumerate(shots):
        scene = shot.get("scene_asset")
        previous_scene = shots[index - 1].get("scene_asset") if index else None
        next_scene = shots[index + 1].get("scene_asset") if index + 1 < len(shots) else None
        shot["single_take"] = True
        shot["indivisible"] = True
        shot["cut_in"] = "scene_start" if index == 0 or previous_scene != scene else "hard_cut"
        shot["cut_out"] = "scene_end" if index + 1 == len(shots) or next_scene != scene else "hard_cut"
        shot["beats"] = [{
            "start": 0,
            "end": shot["atomic_duration"],
            "action": shot.get("narrative_function", "连续镜头节拍"),
        }]
        if index + 1 < len(shots):
            shot["merge_relation"] = "forbidden"
    return upgraded


def main() -> int:
    parser = argparse.ArgumentParser(description="V7.3 cut-to-cut atomic contract regression")
    parser.add_argument("director_json", type=Path)
    args = parser.parse_args()

    plan = upgrade_fixture(json.loads(args.director_json.read_text(encoding="utf-8")))
    expected_count = len(plan["atomic_shots"])
    for tier in ("low", "medium", "high"):
        result = compile_video_plan(copy.deepcopy(plan), tier, "720P")
        assert result["validation"]["ok"] is True
        final = result["final_video_plan"]
        assert final["contract_version"] == "cut_take_v1"
        assert len(final["shots"]) == expected_count
        assert len(final["reference_image_jobs"]) == expected_count
        for shot in final["shots"]:
            assert shot["single_take"] is True and shot["indivisible"] is True
            assert len(shot["atomic_ids"]) == 1
            assert "内部不切镜" in shot["prompt_zh"]
            derived = [ref for ref in shot["references"] if ref.get("derived")]
            assert len(derived) == 2
            assert shot["reference_image_plan"]["usage"] == "ordinary_image_reference"
        print(f"{tier}: {expected_count} indivisible shots PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
