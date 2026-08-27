from __future__ import annotations

from app.autoflow_service import (
    _fallback_analyze,
    _flatten_sub_shots,
    _merge_short_analysis_groups,
    _normalize_segments,
    _validate_group_partition,
)


def _segment(*sub_shots: dict) -> list[dict]:
    return [
        {
            "segment_id": "s001",
            "scene": "主殿外",
            "characters": ["叶澜"],
            "transition_from_previous": "scene_start",
            "sub_shots": list(sub_shots),
        }
    ]


def main() -> None:
    normalized_unknown_boundary = _normalize_segments(
        [
            {"segment_id": "s001", "scene": "主殿外", "sub_shots": [{"id": "c01", "duration": 2}]},
            {"segment_id": "s002", "scene": "主殿外", "sub_shots": [{"id": "c02", "duration": 2}]},
        ]
    )
    assert normalized_unknown_boundary[1]["transition_from_previous"] == ""

    # indivisible protects each small shot internally. Two unrelated short
    # shots are still packaged together to satisfy the hard 4-second minimum.
    independent_segments = _segment(
        {"id": "c01_01", "duration": 2, "performance": "叶澜回头", "indivisible": True},
        {"id": "c01_02", "duration": 2, "performance": "秦放冷笑", "indivisible": True},
    )
    independent = _fallback_analyze(independent_segments)
    assert [group["sub_shot_ids"] for group in independent["shot_groups"]] == [
        ["c01_01", "c01_02"],
    ]
    assert independent["shot_groups"][0]["group_type"] == "min_duration_pack"
    assert "不足 4 秒" in independent["shot_groups"][0]["reason"]

    long_single = _fallback_analyze(
        _segment({"id": "c01_01", "duration": 5, "performance": "叶澜完成一句台词"})
    )
    assert long_single["shot_groups"][0]["group_type"] == "independent"
    assert "已达到 4 秒" in long_single["shot_groups"][0]["reason"]

    # An explicit same-take boundary joins adjacent small shots into one generation group.
    continuous_segments = _segment(
        {"id": "c01_01", "duration": 2, "performance": "叶澜抬手", "indivisible": True},
        {
            "id": "c01_02",
            "duration": 2,
            "performance": "动作继续至落剑",
            "transition_from_previous": "continuous",
            "indivisible": True,
        },
    )
    continuous = _fallback_analyze(continuous_segments)
    assert len(continuous["shot_groups"]) == 1
    assert continuous["shot_groups"][0]["group_type"] == "continuous_take"
    assert continuous["shot_groups"][0]["sub_shot_ids"] == ["c01_01", "c01_02"]
    assert "总时长 4 秒" in continuous["shot_groups"][0]["reason"]

    # A model result may never merge across an explicit edit boundary.
    cut_segments = _segment(
        {"id": "c01_01", "duration": 2, "performance": "叶澜抬手"},
        {
            "id": "c01_02",
            "duration": 2,
            "performance": "秦放反应镜头",
            "transition_from_previous": "hard_cut",
        },
    )
    flattened = _flatten_sub_shots(cut_segments)
    invalid = {
        "shot_groups": [
            {
                "group_id": "g001",
                "group_type": "continuous_take",
                "sub_shot_ids": ["c01_01", "c01_02"],
                "reason": "错误跨切镜合并",
            }
        ]
    }
    try:
        _validate_group_partition(invalid, flattened)
    except RuntimeError as exc:
        assert "真实切镜边界" in str(exc)
    else:
        raise AssertionError("hard_cut boundary should reject the merged model group")

    valid_pack = {
        "shot_groups": [
            {
                "group_id": "g001",
                "group_type": "min_duration_pack",
                "sub_shot_ids": ["c01_01", "c01_02"],
                "reason": "不足 4 秒，保留组内切镜并相邻打包",
            }
        ]
    }
    _validate_group_partition(valid_pack, flattened)

    repaired = _merge_short_analysis_groups(
        {
            "summary": "模型返回两个短组",
            "shot_groups": [
                {
                    "group_id": "g001",
                    "group_type": "independent",
                    "sub_shot_ids": ["c01_01"],
                    "reason": "短组一",
                },
                {
                    "group_id": "g002",
                    "group_type": "independent",
                    "sub_shot_ids": ["c01_02"],
                    "reason": "短组二",
                },
            ],
        },
        flattened,
    )
    assert len(repaired["shot_groups"]) == 1
    assert repaired["shot_groups"][0]["group_type"] == "min_duration_pack"
    assert repaired["shot_groups"][0]["sub_shot_ids"] == ["c01_01", "c01_02"]
    _validate_group_partition(repaired, flattened)

    invalid_short = {
        "shot_groups": [
            {
                "group_id": "g001",
                "group_type": "independent",
                "sub_shot_ids": ["c01_01"],
                "reason": "错误保留短镜头",
            },
            {
                "group_id": "g002",
                "group_type": "independent",
                "sub_shot_ids": ["c01_02"],
                "reason": "错误保留短镜头",
            },
        ]
    }
    try:
        _validate_group_partition(invalid_short, flattened)
    except RuntimeError as exc:
        assert "不足 4 秒" in str(exc)
    else:
        raise AssertionError("short groups must be merged with adjacent shots")

    print("shot group boundary contract: PASS")


if __name__ == "__main__":
    main()
