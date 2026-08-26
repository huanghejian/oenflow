from __future__ import annotations

import copy
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "EP001" / "EP001_A导演输出.json"
OUTPUT = ROOT / "EP001_V73_A导演输出.json"


# 这些分组是逐镜审计后的“同一摄影机连续完成”段落。其余旧分镜边界均保留为真实剪辑点。
GROUPS = [
    ["a001"],
    ["a002"],
    ["a003"],
    ["a004"],
    ["a005"],
    ["a006", "a007"],
    ["a008"],
    ["a009"],
    ["a010"],
    ["a011"],
    ["a012", "a013"],
    ["a014", "a015"],
    ["a016"],
    ["a017", "a018", "a019", "a020"],
    ["a021", "a022"],
    ["a023"],
    ["a024"],
    ["a025"],
    ["a026"],
    ["a027"],
    ["a028"],
    ["a029"],
    ["a030"],
    ["a031"],
    ["a032"],
    ["a033"],
    ["a034", "a035"],
    ["a036"],
    ["a037", "a038"],
    ["a039"],
    ["a040", "a041"],
    ["a042"],
    ["a043"],
    ["a044"],
    ["a045", "a046", "a047"],
    ["a048"],
    ["a049"],
    ["a050"],
    ["a051"],
    ["a052"],
    ["a053"],
    ["a054", "a055"],
    ["a056"],
    ["a057"],
    ["a058"],
    ["a059", "a060"],
    ["a061"],
    ["a062"],
    ["a063"],
]


LEVELS = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
COMPLEXITY_LEVELS = {"low": 0, "medium": 1, "high": 2}


CUSTOM_CAMERA = {
    "a006": {
        "shot_size": "近景",
        "angle": "微低机位仰拍",
        "composition": "秦放保持在右三分之一，视线向左下留负空间，指向动作在同一构图内完成",
        "movement": "fixed",
    },
    "a012": {
        "shot_size": "近景→特写",
        "angle": "微低机位仰拍",
        "composition": "秦放位于右三分之一，镜头沿视线缓慢收紧到眼神与嘴角",
        "movement": "slow_push",
    },
    "a014": {
        "shot_size": "中景→近景",
        "angle": "平拍转轻仰拍",
        "composition": "先读叶灵原地起身祭剑，再沿剑锋缓慢收紧到左三分之一脸部",
        "movement": "slow_push",
    },
    "a017": {
        "shot_size": "中景→特写",
        "angle": "平拍",
        "composition": "雕纹石柱保持左前景遮挡，Q版叶澜由半身逐步收紧到偏右脸部",
        "movement": "slow_push",
    },
    "a021": {
        "shot_size": "中景→近景",
        "angle": "平拍侧前方",
        "composition": "叶澜沿左侧石柱后退，镜头跟到外缘后稳定在侧脸与退路负空间",
        "movement": "simple_follow",
    },
    "a034": {
        "shot_size": "近景",
        "angle": "侧前方平拍",
        "composition": "无字系统面板占左前景，叶澜位于右侧中景，二者关系全程不变",
        "movement": "fixed",
    },
    "a037": {
        "shot_size": "近景→特写",
        "angle": "主观平拍",
        "composition": "系统圆环居中，外围无字光格从完整范围逐步收紧到核心",
        "movement": "slow_push",
    },
    "a040": {
        "shot_size": "中景→近景",
        "angle": "平拍转轻仰拍",
        "composition": "跟随叶澜由左侧外缘走到圆形雕纹外缘，停步后收稳在左三分之一",
        "movement": "simple_follow",
    },
    "a045": {
        "shot_size": "近景→特写",
        "angle": "微低机位仰拍",
        "composition": "秦放保持右三分之一，视线转向叶家众人后镜头缓慢收紧到眼神与嘴角",
        "movement": "slow_push",
    },
    "a054": {
        "shot_size": "特写→近景",
        "angle": "微低机位仰拍",
        "composition": "从秦放双眼缓慢后拉，逐步露出右三分之一脸部与指向左下的手",
        "movement": "slow_pullback",
    },
    "a059": {
        "shot_size": "特写",
        "angle": "平拍",
        "composition": "叶澜脸部偏右，胸前金光从左下照亮眼睛与嘴角，命中后构图稳定",
        "movement": "fixed",
    },
}


CUSTOM_TIMELINES = {
    "a006": (
        "0-3秒：【山门高处微低机位近景，连续固定镜头】[秦放·基础状态]位于右三分之一，先扫过下方跪地众人，嘴角慢慢扬起，以清晰口型讥笑说出{一群蝼蚁！}，背景适度虚焦；数名[秦族弟子群·基础状态]冷肃站在后景。"
        "3-7秒：【同机位同景别，连续固定镜头】[秦放·基础状态]笑意收窄，手指缓慢指向广场后方，以清晰口型狂傲喝出{让叶澜出来受死！}，暗金冠饰和黑金衣领稳定，背景适度虚焦。"
    ),
    "a012": (
        "0-5秒：【山门高处微低机位近景，连续缓慢推进】[秦放·基础状态]位于右三分之一，听完控诉后眼神不动，嘴角才重新挑起，以清晰口型戏弄说出{叶澜可是我的好兄弟，}，背景适度虚焦。"
        "5-10秒：【同一镜头缓慢收紧至特写后稳定】[秦放·基础状态]微微偏头，轻蔑笑意加深，以清晰口型说出{不就是用来利用的吗？}，最后一个字落下后眼神冰冷。"
    ),
    "a014": (
        "0-3秒：【广场平拍中景，连续缓慢推进】[叶灵·基础状态]在左侧一手撑膝从跪姿站起，另一手并指祭出腰侧银灰长剑，剑身悬停在肩侧；后景[叶家弟子群·基础状态]开始抬手结印。"
        "3-7秒：【同一镜头沿剑锋收紧至轻仰拍近景】飞剑锋从右前景斜入，[叶灵·基础状态]站稳后咬紧牙关，以清晰口型喊出{我们跟你拼了！}，衣摆被灵力风掀动，背景适度虚焦。"
    ),
    "a017": (
        "0-3秒：【广场雕纹石柱后平拍中景，连续缓慢推进】以[叶澜·基础状态]身份、发型与浅青白长袍为锁做可辨识Q版比例；他从左前景石柱后只探出脑袋和半边肩膀，额角冒冷汗。"
        "3-10秒：【同一镜头推进至近景】Q版[叶澜·基础状态]背贴石柱，眉头垮下并擦去额角冷汗，嘴唇不发声，以内心旁白说{真倒霉！我本科刚毕业的大学生，}，远处叶家众人虚化。"
        "10-17秒：【同一近景继续缓慢推进】Q版[叶澜·基础状态]无奈地指向自己又摊开手掌，嘴唇不发声，以内心旁白说{就因为网吧通宵打个游戏，竟然穿越了！}，石柱遮挡关系不变。"
        "17-21秒：【同一镜头收紧至特写后稳定】Q版[叶澜·基础状态]低头看一眼空空的掌心，肩膀一下塌下，嘴唇不发声，以内心旁白说{还穿成了个废人！}，背景适度虚焦。"
    ),
    "a021": (
        "0-3秒：【广场石柱侧平拍中景，连续简单跟随】恢复正常人体比例的[叶澜·基础状态]踮脚贴着雕纹石柱，从遮蔽处向广场左侧外缘退去，视线仍警惕地看向高处秦放。"
        "3-7秒：【同一镜头跟到外缘并稳定为侧脸近景】[叶澜·基础状态]侧身朝退路，眼角仍偷看高处，嘴唇不发声，以内心旁白说{还是溜之大吉吧……}，说完轻轻抬起后脚准备再退，背景适度虚焦。"
    ),
    "a034": (
        "0-8秒：【烟尘内侧前方近景，连续固定镜头】无字[并夕夕系统面板]在左前景发出柔和流光，[叶澜·基础状态]在右侧逐项扫视无字光框，嘴唇不动；系统声音说出{恭喜宿主挨一刀激活并夕夕系统，获得筑基大圆满修为，}，背景适度虚焦。"
        "8-16秒：【同机位同景别，连续固定镜头】无字[并夕夕系统面板]的圆环核心旋转并停在几乎闭合的位置，[叶澜·基础状态]的视线随之移动；系统声音说出{当前领取进度99.99%，只需让秦放砍一刀，即可到账。}，画面不显示数字或文字。"
    ),
    "a037": (
        "0-7秒：【叶澜主观视角近景，连续缓慢推进】无字[并夕夕系统面板]边框由柔蓝转为急促闪烁，圆环外出现十段纯光格但没有数字；系统声音警告{奖励领取时限还剩10秒，超时宿主立即死亡！}。"
        "7-9秒：【同一主观镜头收紧至系统核心特写】外围十段无字光格开始逐段熄灭，圆环核心加速旋转，蓝色警报流光沿边框急促奔走；画面完全无文字无数字。"
    ),
    "a040": (
        "0-3秒：【广场平拍中景，连续简单跟随】[叶澜·基础状态]从外缘烟尘中快步走到圆形雕纹外缘，停下后单手叉腰，另一手指向山门高处[秦放·基础状态]；[叶灵·基础状态]在石阶下端侧身停步。"
        "3-10秒：【同一镜头跟随停稳并收成轻仰拍近景】[叶澜·基础状态]位于左三分之一，手指直指高处，眉峰挑起并露出故意嚣张的笑，以清晰口型喊出{喂，那边的儿砸，有本事来砍你爹啊！}，远处秦放只作缩小背景。"
    ),
    "a045": (
        "0-2秒：【山门高处微低机位近景，连续缓慢推进】[秦放·基础状态]位于右三分之一，从叶澜身上移开视线，转而瞥向石阶下端的[叶灵·基础状态]等人，嘴角带着戏谑。"
        "2-10秒：【同一近景继续缓慢推进】[秦放·基础状态]看着叶家众人，以清晰口型缓慢说出{让你亲眼看着他们一个个死去而无能为力，}，末尾轻轻抬起右手，后景人物明显缩小并虚化。"
        "10-14秒：【同一镜头收紧至特写后稳定】[秦放·基础状态]手指停在左前景，眼神仍落在叶家众人身上，以清晰口型补完{也挺有趣……}，话尾笑意更深。"
    ),
    "a054": (
        "0-2秒：【山门高处微低机位特写，连续缓慢后拉】[秦放·基础状态]双眼红色杀意骤然暴涨，眉骨压低，鼻息变重，眼神死死锁定叶澜，背景强烈虚焦。"
        "2-8秒：【同一镜头后拉至近景并稳定】[秦放·基础状态]位于右三分之一，猛然抬手指向左下叶澜，袖袍被杀意掀起，以清晰口型怒喝{本神子要把你大卸八块！}，尾音落下时指尖金光凝成剑形。"
    ),
    "a059": (
        "0-2秒：【广场平拍特写，连续固定镜头】金色剑形能量命中[叶澜·基础状态]胸前并爆开强烈金光，画面只轻震一次后立即稳定；叶澜身体后仰半寸，却在光中勾起阴谋得逞的笑。"
        "2-6秒：【同机位同景别，连续固定镜头】[叶澜·基础状态]保持阴笑，眼神越过金光锁住高处秦放，嘴唇不动，以内心旁白说{终于上当了！}，背景适度虚焦。"
    ),
}


BOUNDARY_OVERRIDES = {
    ("a003", "a004"): "match_cut_shape",
    ("a004", "a005"): "concealed_cut",
    ("a028", "a029"): "concealed_cut",
    ("a032", "a033"): "match_cut_shape",
    ("a058", "a059"): "match_cut_action",
    ("a061", "a062"): "match_cut_action",
}


def unique(items):
    seen = set()
    result = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else item
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(item))
    return result


def merge_text(shots, field):
    values = [shot.get("prompt_core", {}).get(field) for shot in shots]
    return "；".join(unique([value for value in values if value]))


def strip_timeline_prefix(text):
    text = re.sub(r"^\s*\d+-\d+秒：", "", text.strip())
    text = re.sub(r"^【[^】]+】", "", text)
    return text.strip()


def max_requirement(shots, field):
    values = [shot["routing_requirements"][field] for shot in shots]
    return max(values, key=lambda value: LEVELS[value])


def max_complexity(shots, field):
    values = [shot["complexity"][field] for shot in shots]
    return max(values, key=lambda value: COMPLEXITY_LEVELS[value])


def merge_asset_refs(shots):
    result = {}
    for key in ("roles", "props"):
        values = []
        for shot in shots:
            values.extend(shot.get("asset_refs", {}).get(key, []))
        if values:
            result[key] = unique(values)
    return result


def merge_reference_assets(shots):
    result = {"required": {}}
    required_ids = {media: set() for media in ("images", "videos", "audios")}
    for media in ("images", "videos", "audios"):
        required = []
        optional = []
        for shot in shots:
            refs = shot.get("reference_assets", {})
            required.extend(refs.get("required", {}).get(media, []))
            optional.extend(refs.get("optional", {}).get(media, []))
        required = unique(required)
        required_ids[media] = {item["asset_id"] for item in required}
        optional = [item for item in unique(optional) if item["asset_id"] not in required_ids[media]]
        if required:
            result["required"][media] = required
        if optional:
            result.setdefault("optional", {})[media] = optional
    return result


def merge_spatial_plan(shots):
    plan = copy.deepcopy(shots[0]["spatial_plan"])
    screen_positions = {}
    position_changes = []
    camera_axis = None
    for shot in shots:
        shot_plan = shot["spatial_plan"]
        screen_positions.update(copy.deepcopy(shot_plan.get("screen_positions", {})))
        position_changes.extend(copy.deepcopy(shot_plan.get("position_changes", [])))
        if shot_plan.get("camera_axis"):
            camera_axis = copy.deepcopy(shot_plan["camera_axis"])
    plan["screen_positions"] = screen_positions
    if camera_axis:
        plan["camera_axis"] = camera_axis
    else:
        plan.pop("camera_axis", None)
    if position_changes:
        plan["position_changes"] = position_changes
    else:
        plan.pop("position_changes", None)
    return plan


def merge_scale_plan(shots):
    plan = copy.deepcopy(shots[-1]["scale_plan"])
    subjects = {}
    for shot in shots:
        subjects.update(copy.deepcopy(shot["scale_plan"].get("subjects", {})))
    if subjects:
        largest_ratio = max(float(subject["frame_height_ratio"]) for subject in subjects.values())
        for subject in subjects.values():
            subject["relative_scale"] = round(float(subject["frame_height_ratio"]) / largest_ratio, 3)
    plan["subjects"] = subjects
    if len(shots) > 1:
        plan["environment_relation"] = (
            "同一连续镜头内按导演时间轴逐步收紧或跟随；人物世界站位不因景别变化而改变，"
            "前中后景始终保持近大远小。"
        )
    return plan


def merge_prompt_core(shots, first_id, camera_plan):
    prompt = copy.deepcopy(shots[0]["prompt_core"])
    prompt["mode"] = "general" if len({shot.get("narrative_class") for shot in shots}) > 1 else prompt.get("mode", "general")
    for field in (
        "spatial_anchor",
        "reference_binding",
        "core_conflict",
        "emotion",
        "power_relation",
        "performance",
        "subject_description",
        "scene_description",
        "motion_description",
        "lighting",
        "environment_motion",
        "sound",
    ):
        merged = merge_text(shots, field)
        if merged:
            prompt[field] = merged
    prompt["camera_visual"] = (
        f"9:16竖屏单一连续镜头，{camera_plan['angle']}，{camera_plan['shot_size']}，"
        f"{camera_plan['composition']}，主要镜头状态为{camera_plan['movement']}；内部不得硬切。"
    )
    if first_id in CUSTOM_TIMELINES:
        prompt["timeline_local"] = CUSTOM_TIMELINES[first_id]
    prompt["guardrail"] = merge_text(shots, "guardrail") or "【不出现任何文字字幕】"
    return prompt


def build_group(shots, new_index):
    first = shots[0]
    last = shots[-1]
    first_id = first["atomic_id"]
    duration = sum(shot["atomic_duration"] for shot in shots)
    result = copy.deepcopy(first)
    result["atomic_id"] = f"s{new_index:03d}"
    result["atomic_duration"] = duration
    result["single_take"] = True
    result["indivisible"] = True
    result["independent_generation"] = True
    result["story_priority"] = max(
        (shot["story_priority"] for shot in shots),
        key=lambda value: {"normal": 0, "key": 1, "climax": 2}[value],
    )
    classes = {shot["narrative_class"] for shot in shots}
    result["narrative_class"] = first["narrative_class"] if len(classes) == 1 else "complex_narrative"
    result["narrative_function"] = "连续单镜头：" + " → ".join(unique([shot["narrative_function"] for shot in shots]))
    result["asset_refs"] = merge_asset_refs(shots)
    result["reference_assets"] = merge_reference_assets(shots)
    result["camera_plan"] = copy.deepcopy(CUSTOM_CAMERA.get(first_id, first["camera_plan"]))
    result["spatial_plan"] = merge_spatial_plan(shots)
    result["scale_plan"] = merge_scale_plan(shots)
    result["complexity"] = {
        field: max_complexity(shots, field) for field in ("m", "c", "e", "cam")
    }
    result["routing_requirements"] = {
        field: max_requirement(shots, field)
        for field in (
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
        )
    }
    if len(shots) > 1:
        result["routing_requirements"]["temporal_continuity"] = max(
            result["routing_requirements"]["temporal_continuity"], "high", key=lambda value: LEVELS[value]
        )
    if first_id in CUSTOM_CAMERA and CUSTOM_CAMERA[first_id]["movement"] != "fixed":
        result["routing_requirements"]["camera_control"] = max(
            result["routing_requirements"]["camera_control"], "high", key=lambda value: LEVELS[value]
        )
    result["prompt_core"] = merge_prompt_core(shots, first_id, result["camera_plan"])
    result["continuity"] = {
        "entry": first["continuity"]["entry"],
        "exit": last["continuity"]["exit"],
        "los": last["continuity"]["los"],
    }
    offset = 0
    beats = []
    for shot in shots:
        end = offset + shot["atomic_duration"]
        beats.append(
            {
                "start": offset,
                "end": end,
                "action": strip_timeline_prefix(shot["prompt_core"]["timeline_local"]),
            }
        )
        offset = end
    result["beats"] = beats
    tts = "".join(shot.get("tts", "") for shot in shots)
    if tts:
        result["tts"] = tts
    else:
        result.pop("tts", None)
    if duration > 3:
        result.pop("safe_padding", None)
    result.pop("cut_in", None)
    result.pop("cut_out", None)
    result.pop("transition_hint", None)
    result.pop("merge_relation", None)
    return result, first["atomic_id"], last["atomic_id"]


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_by_id = {shot["atomic_id"]: shot for shot in source["atomic_shots"]}
    expected = [f"a{index:03d}" for index in range(1, 64)]
    flattened = [atomic_id for group in GROUPS for atomic_id in group]
    if flattened != expected:
        raise ValueError("GROUPS must cover a001-a063 exactly once and in order")

    built = []
    old_boundaries = []
    for index, group in enumerate(GROUPS, start=1):
        shot, first_old_id, last_old_id = build_group([source_by_id[item] for item in group], index)
        built.append(shot)
        old_boundaries.append((first_old_id, last_old_id))

    for index, shot in enumerate(built):
        if index == 0:
            shot["cut_in"] = "scene_start"
        else:
            previous_last = old_boundaries[index - 1][1]
            current_first = old_boundaries[index][0]
            shot["cut_in"] = BOUNDARY_OVERRIDES.get((previous_last, current_first), "hard_cut")
            shot["transition_hint"] = shot["cut_in"]

        if index == len(built) - 1:
            shot["cut_out"] = "scene_end"
            shot.pop("merge_relation", None)
        else:
            current_last = old_boundaries[index][1]
            next_first = old_boundaries[index + 1][0]
            shot["cut_out"] = BOUNDARY_OVERRIDES.get((current_last, next_first), "hard_cut")
            shot["merge_relation"] = "forbidden"

    source["routing_tier"] = "medium"
    source["atomic_shots"] = built
    OUTPUT.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"source_shots=63")
    print(f"v73_shots={len(built)}")
    print(f"total_duration={sum(shot['atomic_duration'] for shot in built)}")
    print(f"output={OUTPUT}")


if __name__ == "__main__":
    main()
