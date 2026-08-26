from __future__ import annotations

import json

from app.compact_director import COMPACT_VERSION, expand_compact_director_plan
from app.director_service import _check_minimum_contract
from app.pipeline_service import compile_video_plan


PAYLOAD = {
    "user_params": {"routing_tier": "medium", "aspect_ratio": "9:16"},
    "global_visual_lock": "真人竖屏短剧",
    "registered_assets": {
        "scenes": [{"asset_id": "scene-1"}],
        "roles": [{"role_id": "role-1"}],
        "props": [],
    },
}

COMPACT_PLAN = {
    "v": "A1c",
    "sc": [
        {
            "id": "scene-1",
            "st": "完整状态",
            "li": "右侧冷白主光",
            "sty": "真人竖屏短剧",
            "b": {
                "a": {"A01": ["门口", "门口内侧"]},
                "x": {},
                "p": {
                    "role-1": [
                        "A01",
                        "门口内侧",
                        "朝向镜头左侧",
                        "standing",
                        "visible",
                    ]
                },
            },
        }
    ],
    "sh": [
        {
            "id": "s001",
            "g": "g001",
            "s": "scene-1",
            "p": "n",
            "n": "r",
            "f": "普通反应",
            "d": 3,
            "cut": ["scene_start", "scene_end"],
            "cam": ["近景", "平拍", "fixed"],
            "pos": {"role-1": ["right_third", "foreground"]},
            "scale": {"role-1": ["foreground", 0.75, 1.0]},
            "ref": {"ri": ["role-1"]},
            "rr": "2030101012",
            "tl": [[0, 3, "固定近景，角色抬眼。"]],
            "state": ["角色低头", "角色抬眼", "角色看向镜头左侧"],
        }
    ],
}


def main() -> None:
    expanded, internal_format = expand_compact_director_plan(COMPACT_PLAN, PAYLOAD)
    assert internal_format == COMPACT_VERSION
    _check_minimum_contract(expanded)

    assert expanded["asset_catalog"] == {
        "scenes": ["scene-1"],
        "roles": ["role-1"],
        "props": [],
    }
    shot = expanded["atomic_shots"][0]
    assert shot["single_take"] is True and shot["indivisible"] is True
    assert shot["routing_requirements"]["identity_consistency"] == "high"
    assert shot["routing_requirements"]["temporal_continuity"] == "medium"
    assert shot["prompt_core"]["timeline_local"].startswith("0-3秒：")
    assert shot["beats"] == [
        {"start": 0, "end": 3, "action": "固定近景，角色抬眼。"}
    ]
    required_ids = {
        item["asset_id"]
        for item in shot["reference_assets"]["required"]["images"]
    }
    assert required_ids == {"role-1", "scene-1"}

    compact_size = len(json.dumps(COMPACT_PLAN, ensure_ascii=False, separators=(",", ":")))
    expanded_size = len(json.dumps(expanded, ensure_ascii=False, separators=(",", ":")))
    assert compact_size < expanded_size * 0.65, (compact_size, expanded_size)

    canonical, canonical_format = expand_compact_director_plan(expanded, PAYLOAD)
    assert canonical_format == "canonical"
    assert canonical == expanded
    compiled = compile_video_plan(expanded, "medium", "720P")
    assert compiled["validation"]["ok"] is True
    assert len(compiled["final_video_plan"]["shots"]) == 1
    print(
        f"compact director: PASS ({compact_size} chars -> {expanded_size} canonical chars)"
    )


if __name__ == "__main__":
    main()
