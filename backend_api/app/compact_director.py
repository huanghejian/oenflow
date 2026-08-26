from __future__ import annotations

from copy import deepcopy
from typing import Any


COMPACT_VERSION = "A1c"

ROUTING_REQUIREMENT_FIELDS = [
    "acting_precision",
    "dialogue_lipsync",
    "identity_consistency",
    "multi_character_control",
    "motion_action",
    "physical_interaction",
    "camera_control",
    "prop_precision",
    "vfx_environment",
    "temporal_continuity",
]

LEVEL_BY_CODE = {
    "0": "none",
    "1": "low",
    "2": "medium",
    "3": "high",
    "4": "critical",
}
TIER_BY_CODE = {"l": "low", "m": "medium", "h": "high"}
PRIORITY_BY_CODE = {"n": "normal", "k": "key", "c": "climax"}
NARRATIVE_BY_CODE = {
    "d": "dialogue",
    "r": "reaction",
    "a": "action",
    "c": "cinematic",
    "e": "environment_vfx",
    "p": "prop_info",
    "x": "complex_narrative",
}
PROMPT_MODE_BY_NARRATIVE = {
    "dialogue": "performance",
    "reaction": "performance",
    "action": "action",
    "cinematic": "environment",
    "environment_vfx": "environment",
    "prop_info": "info",
    "complex_narrative": "general",
}

CUT_TYPES = [
    "scene_start",
    "scene_end",
    "hard_cut",
    "concealed_cut",
    "match_cut_action",
    "match_cut_shape",
    "fade",
]


COMPACT_DIRECTOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "v": {"type": "string", "enum": [COMPACT_VERSION]},
        "sc": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "st": {"type": "string", "minLength": 1},
                    "li": {"type": "string", "minLength": 1},
                    "sty": {"type": "string"},
                    "b": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "object", "minProperties": 1},
                            "x": {"type": "object"},
                            "p": {"type": "object", "minProperties": 1},
                        },
                        "required": ["a", "x", "p"],
                        "additionalProperties": False,
                    },
                },
                "required": ["id", "st", "li", "sty", "b"],
                "additionalProperties": False,
            },
        },
        "sh": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "g": {"type": "string", "minLength": 1},
                    "s": {"type": "string", "minLength": 1},
                    "p": {"type": "string", "enum": list(PRIORITY_BY_CODE)},
                    "n": {"type": "string", "enum": list(NARRATIVE_BY_CODE)},
                    "f": {"type": "string", "minLength": 1},
                    "d": {"type": "integer", "minimum": 1},
                    "cut": {
                        "type": "array",
                        "items": {"type": "string", "enum": CUT_TYPES},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "cam": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "axis": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "side": {"type": "string"},
                            "crossed": {"type": "boolean"},
                            "why": {"type": "string"},
                        },
                        "required": ["id", "side", "crossed"],
                        "additionalProperties": False,
                    },
                    "pos": {"type": "object", "minProperties": 1},
                    "moves": {"type": "array", "items": {"type": "object"}},
                    "scale": {"type": "object", "minProperties": 1},
                    "ref": {
                        "type": "object",
                        "properties": {
                            key: {"type": "array"}
                            for key in ("ri", "rv", "ra", "oi", "ov", "oa")
                        },
                        "required": ["ri"],
                        "additionalProperties": False,
                    },
                    "rr": {"type": "string", "pattern": "^[0-4]{10}$"},
                    "tl": {"type": "array", "minItems": 1},
                    "state": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "tts": {"type": "string"},
                    "gd": {"type": "string"},
                    "li": {"type": "string"},
                    "snd": {"type": "string"},
                    "tr": {"type": "string"},
                    "pad": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                "required": [
                    "id",
                    "g",
                    "s",
                    "p",
                    "n",
                    "f",
                    "d",
                    "cut",
                    "cam",
                    "pos",
                    "scale",
                    "ref",
                    "rr",
                    "tl",
                    "state",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["v", "sc", "sh"],
    "additionalProperties": False,
}


COMPACT_OUTPUT_INSTRUCTIONS = r"""
【最高优先级：A1c 内部紧凑输出契约】
前文对导演设计、空间、比例、连续性和逻辑素材的要求仍全部有效，但最终响应不得输出前文的长字段 A JSON。
只返回一个 A1c JSON 对象，顶层仅使用 v/sc/sh。后端会将它无损展开为标准 V7.3 A JSON。

顶层：
- v 固定为 "A1c"。
- sc 是场景表：{id,st,li,sty,b}。b={a,x,p}。
  - b.a: anchor_id -> [landmark,description]
  - b.x: axis_id -> {between:[...],default_camera_side,cross_axis_allowed}
  - b.p: role_id -> [anchor_id,position,facing,pose_height,visibility]
- sh 是按时间顺序的原子镜头表。

每个 sh 必填：
- id/g/s/f/d 分别为 atomic_id/group_id/scene_asset/narrative_function/整数秒时长。
- p: n=normal,k=key,c=climax。
- n: d=dialogue,r=reaction,a=action,c=cinematic,e=environment_vfx,p=prop_info,x=complex_narrative。
- cut=[cut_in,cut_out]。
- cam=[shot_size,angle,movement]；构图不重复写，后端根据 pos 生成。
- axis 仅在存在明确摄影轴线时输出：{id,side,crossed,why?}。
- pos: role_id -> [zone,depth,facing_screen?]。只是屏幕构图，不代表世界走位。
- moves 只在真实走位时输出，项为 {r,from,to,why,pos?,face?,pose?,vis?}。
- scale: role_id -> [depth,frame_height_ratio,relative_scale]，覆盖 pos 中所有可见主体。
- ref 为逻辑参考：ri/rv/ra=必需图片/视频/音频，oi/ov/oa=可选。
  普通图片项只写 asset_id 字符串；当前场景图由后端自动加入，不要在 ri 重复。
  视频/音频或特殊用途可写短对象 {id,p,d?,q?}；p=purpose,d=秒数,q=优先级。
- rr 是 10 位数字字符串，依次为表演/口型/身份/多角色/动作/物理/运镜/道具/特效/时序；0=none,1=low,2=medium,3=high,4=critical。
- tl 是唯一动作时间轴：[[start,end,action],...]。不另外重复输出 beats 或 timeline_local。
- state=[entry,exit,los]，三项都要写真实可见状态，不得写“同上一镜”。
- 有台词才输出 tts。gd 只写当镜特有禁令，li/snd 只在覆盖场景级光线或有特殊声音时输出。

不要输出 asset_catalog、routing_tier、aspect_ratio、asset_refs、camera_plan、spatial_plan、scale_plan、complexity、routing_requirements、prompt_core、continuity、beats、single_take、indivisible、model、preset 或评分。这些全部由后端展开或后续计算。
禁止 Markdown 代码块和解释文字。
""".strip()


def _asset_id(item: Any, category: str) -> str | None:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if not isinstance(item, dict):
        return None
    preferred = {
        "scenes": ("asset_id", "scene_id", "id", "name"),
        "roles": ("role_id", "asset_id", "id", "name"),
        "props": ("prop_id", "asset_id", "id", "name"),
    }[category]
    for key in preferred:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def asset_catalog_from_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    registered = payload.get("registered_assets") or {}
    catalog: dict[str, list[str]] = {}
    for category in ("scenes", "roles", "props"):
        raw_items = registered.get(category) if isinstance(registered, dict) else []
        ids: list[str] = []
        for item in raw_items or []:
            value = _asset_id(item, category)
            if value and value not in ids:
                ids.append(value)
        catalog[category] = ids
    return catalog


def _expect_list(value: Any, field: str, length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"A1c {field} 必须是数组")
    if length is not None and len(value) != length:
        raise ValueError(f"A1c {field} 必须包含 {length} 项")
    return value


def _expand_anchor_catalog(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c scene.b.a 必须是对象")
    result: dict[str, Any] = {}
    for anchor_id, value in raw.items():
        if isinstance(value, dict):
            result[str(anchor_id)] = deepcopy(value)
            continue
        parts = _expect_list(value, f"scene.b.a[{anchor_id}]", 2)
        result[str(anchor_id)] = {
            "landmark": str(parts[0]),
            "description": str(parts[1]),
        }
    return result


def _expand_axis_catalog(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c scene.b.x 必须是对象")
    result: dict[str, Any] = {}
    for axis_id, value in raw.items():
        if isinstance(value, dict):
            result[str(axis_id)] = deepcopy(value)
            continue
        parts = _expect_list(value, f"scene.b.x[{axis_id}]")
        if len(parts) < 3:
            raise ValueError(f"A1c scene.b.x[{axis_id}] 至少需要 3 项")
        result[str(axis_id)] = {
            "between": deepcopy(parts[0]),
            "default_camera_side": str(parts[1]),
            "cross_axis_allowed": bool(parts[2]),
        }
    return result


def _expand_initial_positions(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c scene.b.p 必须是对象")
    result: dict[str, Any] = {}
    keys = ("anchor_id", "position", "facing", "pose_height", "visibility")
    for role_id, value in raw.items():
        if isinstance(value, dict):
            result[str(role_id)] = deepcopy(value)
            continue
        parts = _expect_list(value, f"scene.b.p[{role_id}]", 5)
        result[str(role_id)] = dict(zip(keys, parts))
    return result


def _expand_scene(raw: Any, global_style: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c sc[] 必须是对象")
    bible = raw.get("b")
    if not isinstance(bible, dict):
        raise ValueError("A1c sc[].b 必须是对象")
    return {
        "scene_asset": str(raw.get("id") or "").strip(),
        "state": str(raw.get("st") or "").strip(),
        "lighting": str(raw.get("li") or "").strip(),
        "style_lock": str(raw.get("sty") or global_style or "项目全局视觉锁").strip(),
        "spatial_bible": {
            "anchor_catalog": _expand_anchor_catalog(bible.get("a")),
            "axis_catalog": _expand_axis_catalog(bible.get("x", {})),
            "initial_world_positions": _expand_initial_positions(bible.get("p")),
        },
    }


def _expand_screen_positions(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c shot.pos 必须是对象")
    result: dict[str, Any] = {}
    for role_id, value in raw.items():
        if isinstance(value, dict):
            result[str(role_id)] = deepcopy(value)
            continue
        parts = _expect_list(value, f"shot.pos[{role_id}]")
        if len(parts) < 2:
            raise ValueError(f"A1c shot.pos[{role_id}] 至少需要 zone/depth")
        position = {"zone": str(parts[0]), "depth": str(parts[1])}
        if len(parts) > 2 and parts[2] not in (None, ""):
            position["facing_screen"] = str(parts[2])
        result[str(role_id)] = position
    return result


def _expand_scale(raw: Any, shot_size: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c shot.scale 必须是对象")
    subjects: dict[str, Any] = {}
    depths: set[str] = set()
    for role_id, value in raw.items():
        if isinstance(value, dict):
            subject = deepcopy(value)
        else:
            parts = _expect_list(value, f"shot.scale[{role_id}]", 3)
            subject = {
                "depth": str(parts[0]),
                "frame_height_ratio": float(parts[1]),
                "relative_scale": float(parts[2]),
            }
        depths.add(str(subject.get("depth") or ""))
        subjects[str(role_id)] = subject
    if any(token in shot_size for token in ("特写", "近景")):
        lens_style = "portrait"
    elif any(token in shot_size for token in ("全景", "远景")):
        lens_style = "wide_angle"
    else:
        lens_style = "standard"
    return {
        "perspective_mode": "strong_depth" if len(depths - {""}) > 1 else "standard_depth",
        "lens_style": lens_style,
        "subjects": subjects,
        "environment_relation": "主体尺寸严格服从结构化景深与占画高度比例，不复制参考图取景",
    }


def _expand_axis(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("A1c shot.axis 必须是对象")
    result = {
        "axis_id": str(raw.get("id") or ""),
        "side": str(raw.get("side") or ""),
        "crossed": bool(raw.get("crossed")),
    }
    if raw.get("why"):
        result["transition_reason"] = str(raw["why"])
    return result


def _expand_moves(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    moves = _expect_list(raw, "shot.moves")
    result: list[dict[str, Any]] = []
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            raise ValueError(f"A1c shot.moves[{index}] 必须是对象")
        item = {
            "role_id": move.get("r"),
            "from_anchor": move.get("from"),
            "to_anchor": move.get("to"),
            "reason": move.get("why"),
        }
        optional = {
            "pos": "to_position",
            "face": "facing_after",
            "pose": "pose_height_after",
            "vis": "visibility_after",
        }
        for short, canonical in optional.items():
            if move.get(short) not in (None, ""):
                item[canonical] = move[short]
        result.append(item)
    return result


def _ref_type_and_purpose(
    asset_id: str, catalog_sets: dict[str, set[str]], media: str
) -> tuple[str, str]:
    if asset_id in catalog_sets["scenes"]:
        asset_type = "scene"
    elif asset_id in catalog_sets["roles"]:
        asset_type = "role"
    elif asset_id in catalog_sets["props"]:
        asset_type = "prop"
    else:
        asset_type = "logical_asset"
    default_purpose = {
        ("image", "scene"): "scene_reference",
        ("image", "role"): "character_reference",
        ("image", "prop"): "prop_reference",
        ("video", "logical_asset"): "video_motion_reference",
        ("audio", "logical_asset"): "audio_voice_reference",
    }.get((media, asset_type))
    if default_purpose is None:
        default_purpose = {
            "image": "style_reference",
            "video": "video_motion_reference",
            "audio": "audio_voice_reference",
        }[media]
    return asset_type, default_purpose


def _expand_ref_item(
    raw: Any,
    media: str,
    catalog_sets: dict[str, set[str]],
    optional: bool,
) -> dict[str, Any]:
    if isinstance(raw, str):
        asset_id = raw
        extra: dict[str, Any] = {}
    elif isinstance(raw, dict):
        asset_id = str(raw.get("id") or "")
        extra = raw
    else:
        raise ValueError("A1c ref 项必须是 asset_id 字符串或短对象")
    asset_id = asset_id.strip()
    if not asset_id:
        raise ValueError("A1c ref 项缺少 asset_id")
    asset_type, purpose = _ref_type_and_purpose(asset_id, catalog_sets, media)
    item: dict[str, Any] = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "purpose": str(extra.get("p") or purpose),
    }
    if extra.get("d") is not None:
        item["duration_seconds"] = extra["d"]
    if optional:
        item["priority"] = int(extra.get("q", 50))
    return item


def _expand_references(
    raw: Any, scene_asset: str, catalog: dict[str, list[str]]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if not isinstance(raw, dict):
        raise ValueError("A1c shot.ref 必须是对象")
    catalog_sets = {key: set(values) for key, values in catalog.items()}
    media_map = {"i": "image", "v": "video", "a": "audio"}
    plural_map = {"i": "images", "v": "videos", "a": "audios"}
    required: dict[str, list[dict[str, Any]]] = {
        "images": [],
        "videos": [],
        "audios": [],
    }
    optional_bucket: dict[str, list[dict[str, Any]]] = {
        "images": [],
        "videos": [],
        "audios": [],
    }
    for prefix, target, is_optional in (
        ("r", required, False),
        ("o", optional_bucket, True),
    ):
        for short_media, media in media_map.items():
            key = prefix + short_media
            for item in raw.get(key) or []:
                expanded = _expand_ref_item(item, media, catalog_sets, is_optional)
                if not any(x["asset_id"] == expanded["asset_id"] for x in target[plural_map[short_media]]):
                    target[plural_map[short_media]].append(expanded)

    if scene_asset and not any(x["asset_id"] == scene_asset for x in required["images"]):
        asset_type, purpose = _ref_type_and_purpose(scene_asset, catalog_sets, "image")
        required["images"].append(
            {"asset_id": scene_asset, "asset_type": asset_type, "purpose": purpose}
        )

    references: dict[str, Any] = {"required": required}
    if any(optional_bucket.values()):
        references["optional"] = optional_bucket

    all_items = [item for bucket in (required, optional_bucket) for items in bucket.values() for item in items]
    asset_refs = {
        "roles": [item["asset_id"] for item in all_items if item.get("asset_type") == "role"],
        "props": [item["asset_id"] for item in all_items if item.get("asset_type") == "prop"],
    }
    return references, asset_refs


def _expand_requirements(raw: Any) -> dict[str, str]:
    if not isinstance(raw, str) or len(raw) != len(ROUTING_REQUIREMENT_FIELDS):
        raise ValueError("A1c shot.rr 必须是 10 位需求编码")
    try:
        return {
            field: LEVEL_BY_CODE[code]
            for field, code in zip(ROUTING_REQUIREMENT_FIELDS, raw)
        }
    except KeyError as exc:
        raise ValueError("A1c shot.rr 只允许 0-4") from exc


def _complexity(requirements: dict[str, str]) -> dict[str, str]:
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

    def level(*fields: str) -> str:
        value = max(rank[requirements[field]] for field in fields)
        return "high" if value >= 3 else "medium" if value == 2 else "low"

    return {
        "m": level("motion_action", "physical_interaction"),
        "c": level(
            "acting_precision",
            "dialogue_lipsync",
            "identity_consistency",
            "multi_character_control",
        ),
        "e": level("prop_precision", "vfx_environment"),
        "cam": level("camera_control", "temporal_continuity"),
    }


def _expand_timeline(raw: Any, duration: int) -> tuple[list[dict[str, Any]], str]:
    rows = _expect_list(raw, "shot.tl")
    beats: list[dict[str, Any]] = []
    lines: list[str] = []
    for index, row in enumerate(rows):
        parts = _expect_list(row, f"shot.tl[{index}]", 3)
        start, end, action = int(parts[0]), int(parts[1]), str(parts[2]).strip()
        if start < 0 or end <= start or end > duration or not action:
            raise ValueError(f"A1c shot.tl[{index}] 时间段或动作非法")
        beats.append({"start": start, "end": end, "action": action})
        lines.append(f"{start}-{end}秒：{action}")
    return beats, "\n".join(lines)


def _composition(screen_positions: dict[str, Any]) -> str:
    parts = []
    for role_id, value in screen_positions.items():
        zone = str((value or {}).get("zone") or "")
        depth = str((value or {}).get("depth") or "")
        parts.append(f"[{role_id}]位于{zone}/{depth}")
    return "；".join(parts) or "主体位置按结构化空间计划锁定"


def _spatial_anchor(scene_asset: str, screen_positions: dict[str, Any]) -> str:
    return f"绑定[{scene_asset}]；" + _composition(screen_positions)


def _default_transition(cut_in: str) -> str | None:
    if cut_in == "scene_start":
        return None
    return {
        "match_cut_action": "match_cut_action",
        "match_cut_shape": "match_cut_shape",
        "concealed_cut": "concealed_cut",
        "fade": "fade",
    }.get(cut_in, "hard_cut")


def _expand_shot(
    raw: Any,
    catalog: dict[str, list[str]],
    index: int,
    shot_count: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A1c sh[] 必须是对象")
    scene_asset = str(raw.get("s") or "").strip()
    duration = int(raw.get("d") or 0)
    cut = _expect_list(raw.get("cut"), f"sh[{index}].cut", 2)
    camera = _expect_list(raw.get("cam"), f"sh[{index}].cam", 3)
    state = _expect_list(raw.get("state"), f"sh[{index}].state", 3)
    screen_positions = _expand_screen_positions(raw.get("pos"))
    scale_plan = _expand_scale(raw.get("scale"), str(camera[0]))
    references, asset_refs = _expand_references(raw.get("ref"), scene_asset, catalog)
    for role_id in screen_positions:
        if role_id in catalog["roles"] and role_id not in asset_refs["roles"]:
            asset_refs["roles"].append(role_id)
    requirements = _expand_requirements(raw.get("rr"))
    beats, timeline = _expand_timeline(raw.get("tl"), duration)
    narrative = NARRATIVE_BY_CODE.get(str(raw.get("n")))
    priority = PRIORITY_BY_CODE.get(str(raw.get("p")))
    if not narrative or not priority:
        raise ValueError(f"A1c sh[{index}] p/n 代码非法")

    guard_parts = ["画面无字幕、字卡和其他文字"]
    if str(raw.get("gd") or "").strip():
        guard_parts.append(str(raw["gd"]).strip())
    prompt_core: dict[str, Any] = {
        "mode": PROMPT_MODE_BY_NARRATIVE[narrative],
        "spatial_anchor": _spatial_anchor(scene_asset, screen_positions),
        "timeline_local": timeline,
        "guardrail": "；".join(guard_parts),
    }
    if str(raw.get("li") or "").strip():
        prompt_core["lighting"] = str(raw["li"]).strip()
    if str(raw.get("snd") or "").strip():
        prompt_core["sound"] = str(raw["snd"]).strip()

    spatial_plan: dict[str, Any] = {"screen_positions": screen_positions}
    axis = _expand_axis(raw.get("axis"))
    if axis:
        spatial_plan["camera_axis"] = axis
    moves = _expand_moves(raw.get("moves"))
    if moves:
        spatial_plan["position_changes"] = moves

    shot: dict[str, Any] = {
        "atomic_id": str(raw.get("id") or "").strip(),
        "group_id": str(raw.get("g") or "").strip(),
        "scene_asset": scene_asset,
        "story_priority": priority,
        "narrative_class": narrative,
        "narrative_function": str(raw.get("f") or "").strip(),
        "atomic_duration": duration,
        "asset_refs": asset_refs,
        "reference_assets": references,
        "camera_plan": {
            "shot_size": str(camera[0]),
            "angle": str(camera[1]),
            "composition": _composition(screen_positions),
            "movement": str(camera[2]),
        },
        "spatial_plan": spatial_plan,
        "scale_plan": scale_plan,
        "complexity": _complexity(requirements),
        "routing_requirements": requirements,
        "prompt_core": prompt_core,
        "continuity": {
            "entry": str(state[0]).strip(),
            "exit": str(state[1]).strip(),
            "los": str(state[2]).strip(),
        },
        "single_take": True,
        "indivisible": True,
        "independent_generation": True,
        "cut_in": str(cut[0]),
        "cut_out": str(cut[1]),
        "beats": beats,
    }
    if index < shot_count - 1:
        shot["merge_relation"] = "forbidden"
    transition = str(raw.get("tr") or "").strip() or _default_transition(shot["cut_in"])
    if transition:
        shot["transition_hint"] = transition
    if "tts" in raw:
        shot["tts"] = str(raw.get("tts") or "")
    if raw.get("pad") is not None:
        padding = _expect_list(raw.get("pad"), f"sh[{index}].pad", 2)
        shot["safe_padding"] = {"before": int(padding[0]), "after": int(padding[1])}
    return shot


def expand_compact_director_plan(
    raw_plan: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Expand the model wire format into the canonical V7.3 A-stage contract.

    Canonical input remains accepted so existing saved plans and custom providers do not break.
    """
    if "atomic_shots" in raw_plan:
        return deepcopy(raw_plan), "canonical"
    if raw_plan.get("v") != COMPACT_VERSION:
        raise ValueError(
            f"导演内部 JSON 缺少 v={COMPACT_VERSION}，且不是标准 A JSON"
        )
    scenes = _expect_list(raw_plan.get("sc"), "sc")
    shots = _expect_list(raw_plan.get("sh"), "sh")
    if not scenes or not shots:
        raise ValueError("A1c sc/sh 不得为空")
    catalog = asset_catalog_from_payload(payload)
    user_params = payload.get("user_params") or {}
    tier_raw = str(user_params.get("routing_tier") or "medium").strip().lower()
    tier = TIER_BY_CODE.get(tier_raw, tier_raw)
    if tier not in {"low", "medium", "high"}:
        tier = "medium"
    aspect_ratio = str(user_params.get("aspect_ratio") or "9:16").strip()
    global_style = str(payload.get("global_visual_lock") or "").strip()
    expanded = {
        "routing_tier": tier,
        "aspect_ratio": aspect_ratio,
        "asset_catalog": catalog,
        "scene_contexts": [_expand_scene(item, global_style) for item in scenes],
        "atomic_shots": [
            _expand_shot(item, catalog, index, len(shots))
            for index, item in enumerate(shots)
        ],
    }
    return expanded, COMPACT_VERSION
