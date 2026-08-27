from __future__ import annotations

from app.autoflow_service import (
    COMPLEXITY_FIELDS,
    ROUTING_DIMENSIONS,
    _aggregate_sub_shot_difficulty,
    _fallback_routing_difficulty,
    _to_generation_unit,
    _validate_routing_difficulty,
)


def main() -> None:
    groups = [
        {
            "group_id": "g001",
            "group_type": "continuous_take",
            "duration": 8,
            "scene_asset": "山门",
            "sub_shots": [
                {
                    "id": "c01",
                    "duration": 4,
                    "content": "两人高速交手并伴随镜头环绕",
                    "performance": "两人冲刺、挥剑、碰撞",
                    "scene": "山门",
                    "characters": ["秦放", "叶澜", "长剑"],
                    "items": ["长剑"],
                    "shot_type": "中景",
                    "camera_movement": "环绕跟拍",
                    "dialogue": {},
                },
                {
                    "id": "c02",
                    "duration": 4,
                    "content": "两人短暂停下并对视",
                    "performance": "保持戒备姿态",
                    "scene": "山门",
                    "characters": ["秦放", "叶澜"],
                    "items": ["长剑"],
                    "shot_type": "近景",
                    "camera_movement": "固定镜头",
                    "dialogue": {},
                },
            ],
        }
    ]
    fallback = _fallback_routing_difficulty(groups)
    _validate_routing_difficulty(fallback, groups)
    assert fallback["shots"][0]["group_id"] == "g001"
    assert set(fallback["shots"][0]["routing_requirements"]) == set(ROUTING_DIMENSIONS)
    assert set(fallback["shots"][0]["complexity"]) == set(COMPLEXITY_FIELDS)
    assert fallback["shots"][0]["difficulty_score"] >= 0
    assert len(fallback["shots"][0]["sub_shot_scores"]) == 2
    sub_score = fallback["shots"][0]["sub_shot_scores"][0]
    assert sub_score["sub_shot_id"] == "c01"
    assert 0 <= sub_score["difficulty_score"] <= 100
    assert set(sub_score["dimension_scores"]) == set(ROUTING_DIMENSIONS)
    assert [item["sub_shot_id"] for item in fallback["shots"][0]["sub_shot_scores"]] == ["c01", "c02"]

    forced = _aggregate_sub_shot_difficulty(
        {
            "shots": [
                {
                    "difficulty_score": 20,
                    "overall_difficulty": "low",
                    "routing_requirements": {key: "low" for key in ROUTING_DIMENSIONS},
                    "sub_shot_scores": [
                        {
                            "difficulty_score": 91,
                            "dimension_scores": {
                                key: (92 if key == "motion_action" else 20)
                                for key in ROUTING_DIMENSIONS
                            },
                        }
                    ],
                }
            ]
        }
    )
    assert forced["shots"][0]["difficulty_score"] == 91
    assert forced["shots"][0]["overall_difficulty"] == "critical"
    assert forced["shots"][0]["routing_requirements"]["motion_action"] == "critical"

    override = fallback["shots"][0]
    override["story_priority"] = "climax"
    override["routing_requirements"]["motion_action"] = "critical"
    unit = _to_generation_unit(
        groups[0],
        {
            "characters": [{"id": "秦放", "name": "秦放"}, {"id": "叶澜", "name": "叶澜"}],
            "scenes": [{"id": "山门", "name": "山门"}],
            "items": [{"id": "长剑", "name": "长剑"}],
        },
        override,
    )
    assert unit["story_priority"] == "climax"
    assert unit["routing_requirements"]["motion_action"] == "critical"
    assert unit["difficulty_analysis"]["reason"]
    assert unit["atomic_ids"] == ["g001"]
    assert unit["source_sub_shot_ids"] == ["c01", "c02"]
    assert len(unit["timeline_segments"]) == 1
    assert [beat["sub_shot_id"] for beat in unit["beats"]] == ["c01", "c02"]
    assert set(unit["asset_refs"]["roles"]) == {"秦放", "叶澜"}
    assert unit["asset_refs"]["props"] == ["长剑"]
    print("routing difficulty contract: PASS")


if __name__ == "__main__":
    main()
