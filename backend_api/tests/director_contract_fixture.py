from __future__ import annotations


PLAN = {
    "routing_tier": "medium",
    "aspect_ratio": "9:16",
    "asset_catalog": {
        "scenes": ["scene-1"],
        "roles": ["role-1"],
        "props": [],
    },
    "scene_contexts": [
        {
            "scene_asset": "scene-1",
            "state": "完整状态",
            "lighting": "右侧冷白主光",
            "style_lock": "真人竖屏短剧",
            "spatial_bible": {
                "anchor_catalog": {
                    "A01": {"landmark": "门口", "description": "门口内侧"}
                },
                "axis_catalog": {},
                "initial_world_positions": {
                    "role-1": {
                        "anchor_id": "A01",
                        "position": "门口内侧",
                        "facing": "朝向镜头左侧",
                        "pose_height": "standing",
                        "visibility": "visible",
                    }
                },
            },
        }
    ],
    "atomic_shots": [
        {
            "atomic_id": "s001",
            "group_id": "g001",
            "scene_asset": "scene-1",
            "story_priority": "normal",
            "narrative_class": "reaction",
            "narrative_function": "普通反应",
            "atomic_duration": 3,
            "asset_refs": {"roles": ["role-1"]},
            "reference_assets": {
                "required": {
                    "images": [
                        {
                            "asset_id": "scene-1",
                            "asset_type": "scene",
                            "purpose": "scene_reference",
                        }
                    ]
                }
            },
            "camera_plan": {
                "shot_size": "近景",
                "angle": "平拍",
                "composition": "主体位于画面右三分之一",
                "movement": "fixed",
            },
            "spatial_plan": {
                "screen_positions": {
                    "role-1": {
                        "zone": "right_third",
                        "depth": "foreground",
                    }
                }
            },
            "scale_plan": {
                "perspective_mode": "standard_depth",
                "lens_style": "portrait",
                "subjects": {
                    "role-1": {
                        "depth": "foreground",
                        "frame_height_ratio": 0.75,
                        "relative_scale": 1.0,
                    }
                },
                "environment_relation": "人物近景，环境保持稳定",
            },
            "complexity": {"m": "low", "c": "medium", "e": "low", "cam": "low"},
            "routing_requirements": {
                "acting_precision": "medium",
                "dialogue_lipsync": "none",
                "identity_consistency": "high",
                "multi_character_control": "none",
                "motion_action": "low",
                "physical_interaction": "none",
                "camera_control": "low",
                "prop_precision": "none",
                "vfx_environment": "low",
                "temporal_continuity": "medium",
            },
            "prompt_core": {
                "mode": "performance",
                "spatial_anchor": "角色位于门口内侧",
                "timeline_local": "0-3秒：固定近景，角色抬眼。",
                "guardrail": "【不出现任何文字字幕】",
            },
            "continuity": {
                "entry": "角色低头",
                "exit": "角色抬眼",
                "los": "角色看向镜头左侧",
            },
            "single_take": True,
            "indivisible": True,
            "cut_in": "scene_start",
            "cut_out": "scene_end",
        }
    ],
}
