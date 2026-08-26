import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCENE = "叶家主殿外山门区域"
ROLES = [
    "叶澜·基础状态",
    "叶灵·基础状态",
    "秦放·基础状态",
    "秦族弟子群·基础状态",
    "叶家弟子群·基础状态",
    "叶家长老二人·基础状态",
]
PROPS = ["并夕夕系统面板", "叶家护山大阵"]

BASE_RATIO = {
    "极远景": 0.06,
    "远景": 0.13,
    "全景": 0.22,
    "中远景": 0.30,
    "中景": 0.48,
    "中近景": 0.62,
    "近景": 0.75,
    "特写": 0.90,
    "大特写": 1.05,
}
DEPTH_FACTOR = {"foreground": 1.0, "midground": 0.62, "background": 0.30}
DEPTH_RANK = {"foreground": 0, "midground": 1, "background": 2}

shots = []


def reqs(kind, **overrides):
    presets = {
        "environment_vfx": dict(acting_precision="low", dialogue_lipsync="none", identity_consistency="medium", multi_character_control="low", motion_action="medium", physical_interaction="low", camera_control="medium", prop_precision="high", vfx_environment="critical", temporal_continuity="high"),
        "dialogue": dict(acting_precision="high", dialogue_lipsync="high", identity_consistency="high", multi_character_control="low", motion_action="low", physical_interaction="none", camera_control="low", prop_precision="none", vfx_environment="low", temporal_continuity="high"),
        "reaction": dict(acting_precision="high", dialogue_lipsync="none", identity_consistency="high", multi_character_control="low", motion_action="low", physical_interaction="none", camera_control="medium", prop_precision="none", vfx_environment="low", temporal_continuity="high"),
        "action": dict(acting_precision="medium", dialogue_lipsync="none", identity_consistency="high", multi_character_control="medium", motion_action="high", physical_interaction="medium", camera_control="medium", prop_precision="medium", vfx_environment="medium", temporal_continuity="high"),
        "prop_info": dict(acting_precision="medium", dialogue_lipsync="none", identity_consistency="high", multi_character_control="none", motion_action="low", physical_interaction="low", camera_control="medium", prop_precision="critical", vfx_environment="high", temporal_continuity="high"),
        "complex_narrative": dict(acting_precision="high", dialogue_lipsync="medium", identity_consistency="high", multi_character_control="high", motion_action="medium", physical_interaction="low", camera_control="medium", prop_precision="low", vfx_environment="medium", temporal_continuity="high"),
        "cinematic": dict(acting_precision="medium", dialogue_lipsync="none", identity_consistency="high", multi_character_control="medium", motion_action="medium", physical_interaction="low", camera_control="high", prop_precision="low", vfx_environment="high", temporal_continuity="high"),
    }
    out = presets[kind].copy()
    out.update(overrides)
    return out


def make_scale(shot_size, positions):
    if not positions:
        ratio = BASE_RATIO[shot_size]
        lens = "wide_angle" if shot_size in {"极远景", "远景", "全景", "中远景"} else ("portrait" if shot_size in {"近景", "特写", "大特写"} else "standard")
        return {
            "perspective_mode": "standard_depth",
            "lens_style": lens,
            "subjects": {SCENE: {"depth": "midground", "frame_height_ratio": ratio, "relative_scale": 1.0}},
            "environment_relation": "本镜以场景、能量或道具为尺度主体，不生成额外人物",
        }
    nearest = min(DEPTH_RANK[p[1]] for p in positions.values())
    subjects = {}
    ratios = {}
    for role, (_, depth, _) in positions.items():
        distance = DEPTH_RANK[depth] - nearest
        factor = (1.0, 0.62, 0.30)[max(0, min(2, distance))]
        ratio = round(BASE_RATIO[shot_size] * factor, 2)
        ratios[role] = ratio
    largest = max(ratios.values())
    for role, (_, depth, _) in positions.items():
        subjects[role] = {
            "depth": depth,
            "frame_height_ratio": ratios[role],
            "relative_scale": round(ratios[role] / largest, 2),
        }
    distinct = {v[1] for v in positions.values()}
    if len(distinct) > 1:
        relation = "前中后景严格近大远小，后景单个人物明显小于前景主体，不得等大并排"
        perspective = "strong_depth"
    elif shot_size in {"极远景", "远景", "全景", "中远景"}:
        relation = "环境尺度占主导，人物保持远中景尺寸，不得放大成近景"
        perspective = "standard_depth"
    else:
        relation = "人物大小严格服从当前景别，不复制角色参考图的原始取景比例"
        perspective = "standard_depth"
    lens = "wide_angle" if shot_size in {"极远景", "远景", "全景", "中远景"} else ("portrait" if shot_size in {"近景", "特写", "大特写"} else "standard")
    return {"perspective_mode": perspective, "lens_style": lens, "subjects": subjects, "environment_relation": relation}


def add(
    group,
    duration,
    narrative_class,
    narrative_function,
    shot_size,
    angle,
    composition,
    movement,
    positions,
    timeline,
    *,
    priority="normal",
    tts=None,
    focal=None,
    props_req=None,
    props_opt=None,
    axis=None,
    changes=None,
    merge="allowed",
    transition="hard_cut",
    entry="",
    exit="",
    los="",
    requirements=None,
    complexity=None,
    independent=False,
    safe_padding=None,
    sound=None,
    mode=None,
):
    idx = len(shots) + 1
    atomic_id = f"a{idx:03d}"
    focal = list(focal or [])
    props_req = list(props_req or [])
    props_opt = list(props_opt or [])
    roles = list(positions.keys())
    required_images = [
        {"asset_id": role, "asset_type": "role", "purpose": "character_reference"}
        for role in focal
    ]
    required_images.append({"asset_id": SCENE, "asset_type": "scene", "purpose": "scene_reference"})
    required_images.extend(
        {"asset_id": prop, "asset_type": "prop", "purpose": "prop_reference"}
        for prop in props_req
    )
    optional_roles = [r for r in roles if r not in focal]
    optional_images = [
        {"asset_id": role, "asset_type": "role", "purpose": "character_reference", "priority": 55}
        for role in optional_roles
    ]
    optional_images.extend(
        {"asset_id": prop, "asset_type": "prop", "purpose": "prop_reference", "priority": 60}
        for prop in props_opt
    )
    references = {"required": {"images": required_images}}
    if optional_images:
        references["optional"] = {"images": optional_images}
    spatial = {
        "screen_positions": {
            role: {"zone": zone, "depth": depth, "facing_screen": facing}
            for role, (zone, depth, facing) in positions.items()
        }
    }
    if axis:
        spatial["camera_axis"] = {"axis_id": axis, "side": "south", "crossed": False}
    if changes:
        spatial["position_changes"] = changes
    asset_refs = {}
    if roles:
        asset_refs["roles"] = roles
    if props_req or props_opt:
        asset_refs["props"] = props_req + props_opt
    guardrail = (
        "锁定东方玄幻古式宗门、冷青灰主色与右上方冷日光；除显式走位外人物世界位置不变；"
        "严禁现代建筑、西式建筑、城市道路、科技设施、山门坍塌、火焰废墟和无关背景；"
        "角色身份、发型、服装稳定，问号、感叹号、身份字卡和倒计时数字均留给后期。【不出现任何文字字幕】"
    )
    core = {
        "mode": mode or ("environment" if narrative_class == "environment_vfx" else "info" if narrative_class == "prop_info" else "action" if narrative_class == "action" else "performance"),
        "spatial_anchor": f"绑定[{SCENE}]的山门牌楼、宽阔石阶、青石广场圆形雕纹与两侧雕纹石柱，保持高处秦放与低处叶家众人的垂直权力关系。",
        "camera_visual": f"{angle}{shot_size}，{composition}，{movement}",
        "lighting": "右上方冷白日光穿过云雾形成柔硬适中的侧逆光，金色法术作为局部暖色高光，冷暖方向跨镜一致。",
        "timeline_local": f"0-{duration}秒：{timeline}",
        "guardrail": guardrail,
    }
    if sound:
        core["sound"] = sound
    shot = {
        "atomic_id": atomic_id,
        "group_id": group,
        "scene_asset": SCENE,
        "story_priority": priority,
        "narrative_class": narrative_class,
        "narrative_function": narrative_function,
        "atomic_duration": duration,
        "asset_refs": asset_refs,
        "reference_assets": references,
        "camera_plan": {"shot_size": shot_size, "angle": angle, "composition": composition, "movement": movement},
        "spatial_plan": spatial,
        "scale_plan": make_scale(shot_size, positions),
        "complexity": complexity or {
            "m": "high" if narrative_class == "action" else "medium" if narrative_class in {"environment_vfx", "cinematic", "complex_narrative"} else "low",
            "c": "high" if narrative_class == "complex_narrative" else "medium" if len(positions) > 1 else "low",
            "e": "high" if narrative_class == "environment_vfx" else "medium" if narrative_class in {"action", "cinematic"} else "low",
            "cam": "medium" if movement != "fixed" else "low",
        },
        "routing_requirements": requirements or reqs(narrative_class),
        "prompt_core": core,
        "continuity": {"entry": entry, "exit": exit, "los": los},
    }
    if tts is not None:
        shot["tts"] = tts
    if safe_padding:
        shot["safe_padding"] = safe_padding
    if independent:
        shot["independent_generation"] = True
    shot["merge_relation"] = merge
    if idx > 1:
        shot["transition_hint"] = transition
    shots.append(shot)


# G01 护山大阵被破：以局部冲击与烟光遮罩替代完整建筑连续破坏。
add("g01", 2, "cinematic", "开场压迫钩子", "全景", "低机位仰拍", "秦放占画面上三分之一，叶家众人在广场下缘", "fixed",
    {"秦放·基础状态": ("upper_right", "midground", "left"), "叶灵·基础状态": ("lower_left", "background", "right"), "叶家弟子群·基础状态": ("lower_edge", "background", "right")},
    "【山门下方低机位全景，固定机位】巨大的金色剑尖从云层垂直压入竖屏上缘，[秦放·基础状态]立于山门牌楼高处，冷光双眼俯视广场；[叶灵·基础状态]与数名[叶家弟子群·基础状态]在下缘被威压压低肩膀。",
    priority="climax", focal=["秦放·基础状态"], props_opt=["叶家护山大阵"], axis="AX01", entry="护山大阵完整激活，秦放立于高处，叶家众人站在广场", exit="金色巨剑逼近阵法顶部，众人仅出现预反应", los="秦放向下俯视叶灵与叶家众人", requirements=reqs("cinematic", vfx_environment="critical"), merge="preferred")
add("g01", 2, "action", "秦放抬手降剑", "特写", "微低机位仰拍", "秦放面部偏右，抬起的手掌切入左前景", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位特写，固定机位】[秦放·基础状态]双眼泛冷金光，抬起右手向下一压，袖口暗金纹样被灵压掀动，背景山峰与云雾适度虚焦。",
    priority="key", focal=["秦放·基础状态"], axis="AX01", entry="秦放右手尚未完全压下", exit="秦放完成向下压手，金剑开始坠落", los="秦放→叶家广场", requirements=reqs("action", physical_interaction="none", vfx_environment="high"), merge="preferred")
add("g01", 2, "environment_vfx", "金剑撞击护山大阵", "近景", "平拍", "护山大阵局部阵纹占满画面，金色剑锋从右上刺入", "fixed", {},
    "【护山大阵顶部局部近景，固定机位】巨大金色剑形能量撞上[叶家护山大阵]冰蓝穹顶，金蓝阵纹骤然炽亮并向撞击点收缩，冲击只发生在局部，不展示整座建筑连续碎裂。",
    priority="climax", props_req=["叶家护山大阵"], entry="冰蓝穹顶与金色阵纹完整", exit="撞击点出现密集裂光，尚未呈现全景坍塌", los="无人物视线", requirements=reqs("environment_vfx", physical_interaction="high"), merge="preferred")
add("g01", 2, "environment_vfx", "阵法破碎烟光遮罩", "特写", "平拍", "阵纹裂光由中心向竖屏四周扩散", "fixed", {},
    "【阵纹特写，固定机位】金蓝阵纹沿撞击点爆成发光碎片，冰蓝灵力脉络骤灭，白金强光与浓烟光尘迅速吞没整个画面，形成完整遮罩，不演算山门实体坍塌。",
    priority="climax", props_req=["叶家护山大阵"], entry="阵法局部布满裂光", exit="护山大阵破碎，强光烟尘充满画面", los="无人物视线", requirements=reqs("environment_vfx"), merge="forbidden", transition="match_cut_shape", independent=True)
add("g02", 3, "action", "叶家众人受击结果", "中景", "轻俯拍", "叶灵在前景下缘半跪，叶家弟子错落跪在后景", "fixed",
    {"叶灵·基础状态": ("lower_left", "foreground", "right"), "叶家弟子群·基础状态": ("lower_edge", "background", "right"), "叶家长老二人·基础状态": ("upper_left", "background", "right")},
    "【广场轻俯拍中景，固定机位】金蓝光尘与贴地薄烟未散，[叶灵·基础状态]和数名[叶家弟子群·基础状态]被余波压得跪地并同时咳出一口血，[叶家长老二人·基础状态]在后景抬袖抵挡气浪，画面震动一次后立刻稳定。",
    priority="key", focal=["叶灵·基础状态", "叶家弟子群·基础状态"], axis="AX01", changes=[
        {"role_id": "叶灵·基础状态", "from_anchor": "A02", "to_anchor": "A02", "path": "在广场圆形雕纹前被冲击压低至单膝跪地", "reason": "护山大阵破碎后的冲击明确使叶灵跪地", "pose_height_after": "kneeling"},
        {"role_id": "叶家弟子群·基础状态", "from_anchor": "A02", "to_anchor": "A02", "path": "在叶灵后方被冲击压得成片跪下", "reason": "护山大阵破碎后的冲击明确使叶家弟子跪地", "pose_height_after": "kneeling"}],
    entry="强光散去，叶灵与叶家弟子承受冲击", exit="叶灵与叶家弟子跪地吐血，烟尘未散", los="叶灵与叶家众人向上看秦放", requirements=reqs("action", multi_character_control="high", physical_interaction="high", vfx_environment="high"), merge="allowed")

# G02 秦放与叶灵正反打。
add("g02", 3, "dialogue", "秦放轻蔑宣判", "近景", "微低机位仰拍", "秦放右三分之一，视线向左下留负空间", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left"), "秦族弟子群·基础状态": ("upper_left", "background", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]先扫过下方跪地众人，嘴角慢慢扬起，以清晰口型讥笑说出{一群蝼蚁！}，背景适度虚焦；数名[秦族弟子群·基础状态]冷肃站在后景。",
    tts="一群蝼蚁！", priority="key", focal=["秦放·基础状态"], axis="AX01", entry="秦放俯视受伤众人", exit="秦放轻蔑笑意停在嘴角", los="秦放→叶家众人", merge="preferred")
add("g02", 4, "dialogue", "秦放点名索命", "近景", "微低机位仰拍", "秦放右三分之一，脸部与指向广场的手清晰", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]笑意收窄，手指缓慢指向广场后方，以清晰口型狂傲喝出{让叶澜出来受死！}，暗金冠饰和黑金衣领稳定，背景适度虚焦。",
    tts="让叶澜出来受死！", priority="key", focal=["秦放·基础状态"], axis="AX01", entry="秦放嘴角仍有轻蔑笑意", exit="秦放手指锁定叶家广场后方", los="秦放→叶澜藏身方向", merge="allowed")
add("g02", 4, "dialogue", "叶灵伤后质问", "近景", "轻俯拍", "叶灵左下三分之一，抬眼朝画面右上", "fixed",
    {"叶灵·基础状态": ("lower_left", "foreground", "right"), "叶家弟子群·基础状态": ("lower_right", "background", "right")},
    "【广场轻俯拍近景，固定机位】[叶灵·基础状态]用手背抹开嘴角血痕，吸气稳住跪姿后咬牙抬眼，以清晰口型怒斥{秦放！你欺人太甚！}，后景弟子衣襟沾灰，背景适度虚焦。",
    tts="秦放！你欺人太甚！", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵跪地吐血，嘴角带血", exit="叶灵稳住呼吸并怒视秦放", los="叶灵→秦放", merge="preferred")
add("g02", 6, "dialogue", "叶灵揭露秘境偷袭", "近景", "平拍侧前方", "叶灵左三分之一，脸部清晰，身后弟子虚化", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right"), "叶家弟子群·基础状态": ("lower_right", "background", "right")},
    "【广场侧前方近景，固定机位】[叶灵·基础状态]指尖抓紧染血衣袖，视线不离高处，以清晰口型控诉{入苍龙秘境时，你偷袭暗算我哥，}，尾音处下颌绷紧，背景适度虚焦。",
    tts="入苍龙秘境时，你偷袭暗算我哥，", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵稳住呼吸怒视秦放", exit="叶灵说到兄长被暗算，手指攥紧衣袖", los="叶灵→秦放", merge="preferred")
add("g02", 6, "dialogue", "叶灵揭露抽取灵根", "近景", "平拍侧前方", "叶灵左三分之一，眼睛落在上三分之一", "slow_push",
    {"叶灵·基础状态": ("left_third", "foreground", "right")},
    "【广场侧前方近景，缓慢推进】[叶灵·基础状态]眼眶发红但泪未落，肩背因愤怒慢慢挺直，以清晰口型继续说{不仅抽他灵根害他修为尽失，}，背景适度虚焦。",
    tts="不仅抽他灵根害他修为尽失，", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵手指攥紧衣袖", exit="叶灵眼眶发红，跪姿中挺直肩背", los="叶灵→秦放", merge="preferred")
add("g02", 5, "dialogue", "叶灵指控赶尽杀绝", "特写", "轻仰拍", "叶灵脸部偏左，视线向右上", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right")},
    "【广场轻仰拍特写，固定机位】[叶灵·基础状态]猛地抬高下颌，泪光停在眼眶，以清晰口型喊出{现在还要赶尽杀绝！}，尾音落下时嘴角血痕清楚，背景适度虚焦。",
    tts="现在还要赶尽杀绝！", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵眼眶发红并挺直肩背", exit="叶灵喊完，泪光未落，仍跪在原地", los="叶灵→秦放", merge="allowed")
add("g02", 5, "dialogue", "秦放戏弄兄弟关系", "近景", "微低机位仰拍", "秦放右三分之一，眼神向左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]先听完控诉，眼神没有移动，嘴角才重新挑起，以清晰口型戏弄说{叶澜可是我的好兄弟，}，背景适度虚焦。",
    tts="叶澜可是我的好兄弟，", focal=["秦放·基础状态"], axis="AX01", entry="秦放冷眼听完叶灵控诉", exit="秦放嘴角挑起，故意停顿", los="秦放→叶灵", merge="preferred")
add("g02", 5, "dialogue", "秦放承认利用", "特写", "微低机位仰拍", "秦放眼睛位于上三分之一，嘴角清晰", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位特写，固定机位】[秦放·基础状态]微微偏头，轻蔑笑意加深，以清晰口型说出{不就是用来利用的吗？}，最后一个字落下后眼神冰冷，背景适度虚焦。",
    tts="不就是用来利用的吗？", priority="key", focal=["秦放·基础状态"], axis="AX01", entry="秦放故意停顿", exit="秦放承认利用叶澜，笑意冰冷", los="秦放→叶灵", merge="allowed")

# G03 叶灵拔剑、叶家弟子响应。
add("g03", 3, "action", "叶灵祭出飞剑", "中景", "平拍", "叶灵由下缘撑身而起，银灰长剑在右侧出鞘", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right"), "叶家弟子群·基础状态": ("right_third", "background", "right")},
    "【广场平拍中景，固定机位】[叶灵·基础状态]一手撑膝从跪姿站起，另一手并指祭出腰侧银灰长剑，剑身悬停在肩侧；后景[叶家弟子群·基础状态]开始抬手结印。",
    priority="key", focal=["叶灵·基础状态"], axis="AX01", changes=[{"role_id": "叶灵·基础状态", "from_anchor": "A02", "to_anchor": "A02", "path": "在原地从单膝跪姿撑身站起", "reason": "剧本明确叶灵祭出飞剑准备拼命", "pose_height_after": "standing"}], entry="叶灵跪在广场，长剑佩在腰侧", exit="叶灵站起，飞剑悬停在肩侧", los="叶灵→秦放", requirements=reqs("action", prop_precision="high"), merge="preferred")
add("g03", 4, "dialogue", "叶灵决死宣言", "近景", "轻仰拍", "叶灵左三分之一，飞剑锋从右前景斜入", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right")},
    "【广场轻仰拍近景，固定机位】飞剑锋从右前景斜入，[叶灵·基础状态]站稳后咬紧牙关，以清晰口型喊出{我们跟你拼了！}，衣摆被灵力风掀动，背景适度虚焦。",
    tts="我们跟你拼了！", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵站起并祭出飞剑", exit="叶灵飞剑指向秦放，战意决绝", los="叶灵→秦放", merge="preferred")
add("g03", 2, "complex_narrative", "叶家弟子集体祭剑", "中景", "平拍", "叶灵在左前景，叶家弟子沿纵深错落排列", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right"), "叶家弟子群·基础状态": ("right_third", "background", "right")},
    "【广场平拍中景，固定机位】[叶灵·基础状态]保持飞剑指向高处，后景数名[叶家弟子群·基础状态]依次祭出飞剑，剑光错落悬停，不要求所有成员同步做复杂表情。",
    priority="key", focal=["叶家弟子群·基础状态", "叶灵·基础状态"], axis="AX01", entry="叶灵飞剑已出，弟子开始结印", exit="叶家弟子群飞剑全部悬停待发", los="叶灵与叶家弟子群→秦放", requirements=reqs("complex_narrative", dialogue_lipsync="none", motion_action="high", vfx_environment="high"), merge="allowed", safe_padding={"after": 1})

# G04 Q版叶澜旁观、退走。
add("g04", 3, "cinematic", "Q版叶澜探头观战", "中景", "平拍", "石柱占左前景，Q版叶澜从柱后探出右半边身体", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "right"), "叶灵·基础状态": ("lower_right", "background", "right"), "叶家弟子群·基础状态": ("right_edge", "background", "right")},
    "【广场石柱后平拍中景，固定机位】以[叶澜·基础状态]身份、发型与浅青白长袍为锁，做夸张但可辨识的Q版比例处理；他从高大雕纹石柱后只探出脑袋和半边肩膀，额角冒冷汗，远处叶家众人虚化。",
    focal=["叶澜·基础状态"], entry="叶澜躲在广场左侧雕纹石柱后", exit="叶澜探头看见双方即将冲突并冒冷汗", los="叶澜→秦放与叶灵", requirements=reqs("cinematic", acting_precision="high", identity_consistency="critical"), merge="preferred")
add("g04", 7, "dialogue", "叶澜自述穿越身份", "近景", "平拍", "Q版叶澜脸部偏左，石柱边缘形成遮挡", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "right")},
    "【石柱后平拍近景，固定机位】Q版[叶澜·基础状态]背贴雕纹石柱，眉头垮下并抬手擦去额角冷汗，嘴唇不发声，以内心旁白说{真倒霉！我本科刚毕业的大学生，}，背景适度虚焦。",
    tts="真倒霉！我本科刚毕业的大学生，", focal=["叶澜·基础状态"], entry="叶澜探头冒冷汗", exit="叶澜缩回石柱后并擦汗", los="叶澜偷看广场冲突", merge="preferred", sound="叶澜内心旁白，角色嘴唇不动；远处剑鸣与风声压低。")
add("g04", 7, "dialogue", "叶澜自述通宵穿越", "近景", "平拍", "Q版叶澜右三分之一，手指无奈指向自己", "fixed",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【石柱后平拍近景，固定机位】Q版[叶澜·基础状态]无奈地指了指自己，又摊开手掌，嘴唇不发声，以内心旁白说{就因为网吧通宵打个游戏，竟然穿越了！}，背景适度虚焦。",
    tts="就因为网吧通宵打个游戏，竟然穿越了！", focal=["叶澜·基础状态"], entry="叶澜缩在石柱后擦汗", exit="叶澜摊掌露出荒唐无奈的神情", los="叶澜视线在广场与退路间游移", merge="preferred", sound="叶澜内心旁白，角色嘴唇不动。")
add("g04", 4, "dialogue", "叶澜自嘲废人", "特写", "平拍", "Q版叶澜脸部偏右，双肩塌下", "fixed",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【石柱后平拍特写，固定机位】Q版[叶澜·基础状态]低头看一眼空空的掌心，肩膀一下塌下，嘴唇不发声，以内心旁白说{还穿成了个废人！}，背景适度虚焦。",
    tts="还穿成了个废人！", focal=["叶澜·基础状态"], entry="叶澜无奈摊掌", exit="叶澜低头泄气，确认自己毫无修为", los="叶澜→自己掌心", merge="allowed", sound="叶澜内心旁白，角色嘴唇不动。")
add("g04", 3, "action", "叶澜小心后退", "中景", "平拍", "叶澜贴着石柱向左后方退，广场冲突在右后景", "simple_follow",
    {"叶澜·基础状态": ("left_third", "foreground", "left"), "叶灵·基础状态": ("right_third", "background", "right"), "叶家弟子群·基础状态": ("right_edge", "background", "right")},
    "【广场石柱侧平拍中景，简单跟随】恢复正常人体比例的[叶澜·基础状态]踮脚贴着雕纹石柱向广场外缘退去，每一步都轻落脚，视线仍警惕地看向高处秦放。",
    focal=["叶澜·基础状态"], changes=[{"role_id": "叶澜·基础状态", "from_anchor": "A03", "to_anchor": "A07", "path": "贴着广场左侧雕纹石柱向后方外缘退去", "reason": "剧本明确叶澜小心翼翼退后", "facing_after": "侧身看向秦放并朝退路后撤"}], entry="叶澜躲在A03石柱后", exit="叶澜退至广场外缘退路", los="叶澜→秦放", requirements=reqs("action", physical_interaction="none", vfx_environment="low"), merge="preferred")
add("g04", 4, "dialogue", "叶澜准备逃离", "近景", "平拍侧脸", "叶澜左三分之一，身后留出退路负空间", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "left")},
    "【广场外缘平拍侧脸近景，固定机位】[叶澜·基础状态]侧身朝退路，眼角仍偷看高处，嘴唇不发声，以内心旁白说{还是溜之大吉吧……}，说完轻轻抬起后脚准备再退，背景适度虚焦。",
    tts="还是溜之大吉吧……", focal=["叶澜·基础状态"], entry="叶澜退到广场外缘", exit="叶澜抬起后脚准备继续逃", los="叶澜余光→秦放", merge="allowed", sound="叶澜内心旁白，角色嘴唇不动。")

# G05 秦放发现叶澜并发出五道光刃。
add("g05", 2, "reaction", "秦放锁定叶澜", "大特写", "微低机位仰拍", "秦放双眼占画面上半部，视线斜向左下", "quick_push",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位大特写，短促压近后稳定】[秦放·基础状态]眼球瞬间偏转，红金冷光在瞳孔中收紧，视线精准锁住广场外缘的叶澜，背景强烈虚焦。",
    priority="key", focal=["秦放·基础状态"], axis="AX02", entry="秦放注意力仍在叶灵身上", exit="秦放已锁定叶澜退路", los="秦放→叶澜", merge="preferred", safe_padding={"after": 1})
add("g05", 3, "dialogue", "秦放喝止叶澜", "特写", "微低机位仰拍", "秦放偏右，视线朝画面左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位特写，固定机位】[秦放·基础状态]眼神锁死叶澜，嘴角向下一压，以清晰口型冷笑说出{想逃？}，背景适度虚焦。",
    tts="想逃？", priority="key", focal=["秦放·基础状态"], axis="AX02", entry="秦放已锁定叶澜", exit="秦放冷笑并准备挥袖", los="秦放→叶澜", merge="preferred")
add("g05", 2, "action", "秦放挥袖释放光刃", "中景", "微低机位仰拍", "秦放右侧高处，挥袖轨迹朝左下方", "fixed",
    {"秦放·基础状态": ("upper_right", "midground", "left"), "叶澜·基础状态": ("lower_left", "background", "right")},
    "【山门至广场斜向中景，固定机位】[秦放·基础状态]在高处拂袖一甩，五道锐利金色光刃从袖前成扇形射向左下方；远处[叶澜·基础状态]刚抬脚便僵住，只出现预反应。",
    priority="key", focal=["秦放·基础状态", "叶澜·基础状态"], axis="AX02", entry="秦放准备挥袖，叶澜抬脚欲退", exit="五道光刃离开秦放飞向叶澜", los="秦放→叶澜；叶澜→飞来光刃", requirements=reqs("action", motion_action="critical", physical_interaction="low", vfx_environment="high"), merge="preferred")
add("g05", 3, "reaction", "叶澜面对死亡", "特写", "平拍", "叶澜脸部偏左，金色刃光映入右侧瞳孔", "slight_handheld",
    {"叶澜·基础状态": ("left_third", "foreground", "right")},
    "【广场外缘平拍特写，极轻手持】[叶澜·基础状态]看见金色刃光逼近后猛然后仰，呼吸停住一瞬，嘴唇不发声，以内心旁白说{完了！刚穿越就要死了！}，背景适度虚焦。",
    tts="完了！刚穿越就要死了！", priority="key", focal=["叶澜·基础状态"], axis="AX02", entry="五道光刃高速逼近叶澜", exit="叶澜惊恐后仰，光刃即将到达", los="叶澜→光刃", merge="preferred", sound="叶澜内心旁白，角色嘴唇不动；五道光刃破空声快速增强。")
add("g05", 3, "dialogue", "叶灵惊呼提醒", "近景", "平拍", "叶灵左前景猛然回头，叶澜方向在右侧负空间", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right"), "叶家弟子群·基础状态": ("lower_left", "background", "right")},
    "【广场平拍近景，固定机位】[叶灵·基础状态]听见破空声猛然回头，瞳孔骤缩，以清晰口型惊叫{哥！小心！}，肩侧飞剑失去稳定轻颤，背景适度虚焦。",
    tts="哥！小心！", priority="key", focal=["叶灵·基础状态"], axis="AX02", entry="叶灵与弟子正准备迎战秦放", exit="叶灵回头惊叫，飞剑轻颤", los="叶灵→叶澜", merge="preferred")
add("g05", 2, "environment_vfx", "光刃淹没叶澜", "近景", "平拍", "五道金色光刃从右侧贯入，叶澜轮廓在左侧", "fixed",
    {"叶澜·基础状态": ("left_third", "midground", "right")},
    "【广场外缘平拍近景，固定机位】五道金色光刃同时吞没[叶澜·基础状态]的身影，落点爆出强光与浓烟，冲击光尘迅速遮满竖屏，不展示清晰伤口或断肢。",
    priority="climax", focal=["叶澜·基础状态"], axis="AX02", entry="叶澜惊恐后仰，光刃到达", exit="叶澜身影被浓烟与强光完全遮蔽", los="叶澜→光刃", requirements=reqs("environment_vfx", identity_consistency="high", motion_action="high", physical_interaction="high"), merge="forbidden", independent=True)

# G06 叶灵悲愤冲锋，随后被叶澜存活打断。
add("g06", 3, "reaction", "叶灵含泪转怒", "特写", "平拍", "叶灵脸部偏左，烟尘倒映在眼睛中", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right")},
    "【广场平拍特写，固定机位】[叶灵·基础状态]望着远处浓烟，泪水终于滑过脸颊，下一拍眉峰压低、下颌绷紧，悲痛转成决绝愤怒，背景适度虚焦。",
    priority="key", focal=["叶灵·基础状态"], entry="叶灵目睹叶澜被光刃吞没", exit="叶灵落泪并转为决绝愤怒", los="叶灵→叶澜烟尘", merge="preferred")
add("g06", 6, "dialogue", "叶灵怒吼报仇", "近景", "轻仰拍", "叶灵左三分之一，飞剑斜指右上", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "right")},
    "【广场轻仰拍近景，固定机位】[叶灵·基础状态]抬剑锁住山门高处，泪痕未干，以清晰口型怒吼{我要为我哥报仇！}，尾音处向前踏出第一步，背景适度虚焦。",
    tts="我要为我哥报仇！", priority="key", focal=["叶灵·基础状态"], axis="AX01", entry="叶灵含泪转怒", exit="叶灵抬剑并迈出冲锋第一步", los="叶灵→秦放", merge="preferred")
add("g06", 3, "action", "叶家众人冲向秦放", "中景", "平拍", "叶灵在左前景领冲，叶家弟子从后景跟上，秦放在右上远处", "simple_follow",
    {"叶灵·基础状态": ("left_third", "foreground", "right"), "叶家弟子群·基础状态": ("lower_left", "midground", "right"), "秦放·基础状态": ("upper_right", "background", "left")},
    "【广场平拍中景，简单跟随】[叶灵·基础状态]持剑沿青石广场冲向山门石阶下端，数名[叶家弟子群·基础状态]持飞剑错落跟随；高处[秦放·基础状态]不动，只轻蔑地扬起嘴角。",
    priority="key", focal=["叶灵·基础状态", "叶家弟子群·基础状态", "秦放·基础状态"], axis="AX01", changes=[
        {"role_id": "叶灵·基础状态", "from_anchor": "A02", "to_anchor": "A05", "path": "沿广场中轴线冲向山门石阶下端", "reason": "剧本明确叶灵冲向秦放", "facing_after": "仰面朝向秦放"},
        {"role_id": "叶家弟子群·基础状态", "from_anchor": "A02", "to_anchor": "A05", "path": "从叶灵后方沿广场中轴线持剑跟随冲锋", "reason": "剧本明确叶家弟子随叶灵冲向秦放", "facing_after": "仰面朝向秦放", "pose_height_after": "standing"}],
    entry="叶灵迈出冲锋第一步，弟子群跪地准备起身", exit="叶灵与叶家弟子群冲到石阶下端，秦放轻蔑一笑", los="叶灵与叶家弟子群→秦放；秦放→冲锋众人", requirements=reqs("action", multi_character_control="critical", motion_action="critical", camera_control="high"), merge="forbidden")
add("g07", 3, "reaction", "叶澜烟中存活并看见面板", "特写", "平拍", "烟尘中的叶澜脸部偏右，青蓝光从左侧照亮眼睛", "focus_shift",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【烟尘内平拍特写，焦点从漂浮光尘回到眼睛】[叶澜·基础状态]衣襟沾灰、发丝凌乱却未见致命伤，他先睁眼愣住，随后看向面前升起的青蓝光源，错愕停住呼吸，背景适度虚焦。",
    priority="climax", focal=["叶澜·基础状态"], props_opt=["并夕夕系统面板"], entry="叶澜被浓烟遮蔽，生死不明", exit="叶澜在烟尘中存活并看向青蓝光源", los="叶澜→系统面板", requirements=reqs("reaction", acting_precision="critical", vfx_environment="medium"), merge="forbidden")
add("g07", 3, "prop_info", "并夕夕系统面板激活", "特写", "主观平拍", "青蓝悬浮面板占画面中央，叶澜肩部虚化在下缘", "fixed",
    {"叶澜·基础状态": ("lower_edge", "background", "forward")},
    "【叶澜主观视角特写，固定机位】[并夕夕系统面板]在烟尘中展开，晶体感蓝色边框、左侧五组无字图标框、右侧多层圆环核心与胶囊形组件依次点亮；界面完全无文字无数字，叶澜肩部只作虚化尺度参照。",
    priority="climax", focal=[], props_req=["并夕夕系统面板"], entry="青蓝光源在叶澜面前凝聚", exit="无字系统面板完整激活并稳定悬浮", los="叶澜→系统面板", requirements=reqs("prop_info"), merge="forbidden", independent=True)
add("g07", 8, "prop_info", "系统说明激活与修为奖励", "近景", "侧前方平拍", "系统面板在左前景，叶澜在右侧中景读取", "fixed",
    {"叶澜·基础状态": ("right_third", "midground", "left")},
    "【烟尘内侧前方近景，固定机位】无字[并夕夕系统面板]在左前景发出柔和流光，[叶澜·基础状态]在右侧逐项扫视无字光框，嘴唇不动；系统声音说出{恭喜宿主挨一刀激活并夕夕系统，获得筑基大圆满修为，}，背景适度虚焦。",
    tts="恭喜宿主挨一刀激活并夕夕系统，获得筑基大圆满修为，", priority="climax", focal=["叶澜·基础状态"], props_req=["并夕夕系统面板"], entry="系统面板完整激活，叶澜错愕注视", exit="叶澜听见可领取筑基大圆满修为", los="叶澜→系统面板", requirements=reqs("prop_info", acting_precision="high", dialogue_lipsync="none"), merge="preferred", sound="冷静清晰的系统画外音；叶澜嘴唇不动。")
add("g07", 8, "prop_info", "系统说明领取条件", "近景", "侧前方平拍", "系统圆环核心在左前景，叶澜眼睛在右上三分之一", "fixed",
    {"叶澜·基础状态": ("right_third", "midground", "left")},
    "【烟尘内侧前方近景，固定机位】无字[并夕夕系统面板]的圆环核心旋转并停在几乎闭合的位置，[叶澜·基础状态]的视线随之移动，系统声音说出{当前领取进度99.99%，只需让秦放砍一刀，即可到账。}，画面不显示数字或文字，背景适度虚焦。",
    tts="当前领取进度99.99%，只需让秦放砍一刀，即可到账。", priority="climax", focal=["叶澜·基础状态"], props_req=["并夕夕系统面板"], entry="叶澜听见可领取修为", exit="叶澜理解必须再让秦放砍一刀", los="叶澜→系统面板圆环核心", requirements=reqs("prop_info", acting_precision="high", dialogue_lipsync="none"), merge="allowed", sound="冷静清晰的系统画外音；叶澜嘴唇不动。")
add("g07", 5, "dialogue", "叶澜燃起希望", "特写", "平拍", "叶澜脸部偏右，青蓝面板光映亮双眼", "quick_push",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【烟尘内平拍特写，短促压近后稳定】[叶澜·基础状态]先怔住，下一拍双眼被青蓝光映得发亮，嘴角扬起，嘴唇不动，以内心旁白说{是统子哥，我有救了！}，背景适度虚焦。",
    tts="是统子哥，我有救了！", priority="climax", focal=["叶澜·基础状态"], props_opt=["并夕夕系统面板"], entry="叶澜理解领取条件", exit="叶澜双眼发亮并露出获救希望", los="叶澜→系统面板", merge="allowed", sound="叶澜兴奋的内心旁白，角色嘴唇不动。")
add("g08", 7, "prop_info", "系统发布死亡时限", "近景", "主观平拍", "面板圆环与十段无字光格占中央，叶澜虚化在下缘", "fixed",
    {"叶澜·基础状态": ("lower_edge", "background", "forward")},
    "【叶澜主观视角近景，固定机位】无字[并夕夕系统面板]边框由柔蓝转为急促闪烁，圆环外出现十段纯光格但没有数字，系统声音警告{奖励领取时限还剩10秒，超时宿主立即死亡！}，画面完全无文字。",
    tts="奖励领取时限还剩10秒，超时宿主立即死亡！", priority="climax", props_req=["并夕夕系统面板"], entry="叶澜刚燃起希望", exit="系统面板进入急促倒计时状态", los="叶澜→系统面板", requirements=reqs("prop_info", temporal_continuity="critical"), merge="forbidden", independent=True, sound="急促系统警报音与系统画外音；不用屏幕数字表达时限。")
add("g08", 2, "prop_info", "无字十秒倒计时启动", "特写", "主观平拍", "系统圆环核心居中，外围光格逐段熄灭", "fixed", {},
    "【系统界面特写，固定机位】[并夕夕系统面板]外围十段无字光格开始逐段熄灭，圆环核心加速旋转，蓝色警报流光沿边框急促奔走；不出现倒计时数字。",
    priority="climax", props_req=["并夕夕系统面板"], entry="系统面板刚进入倒计时", exit="第一段光格熄灭，倒计时持续", los="无人物视线", requirements=reqs("prop_info", temporal_continuity="critical"), merge="forbidden", independent=True, safe_padding={"after": 2})
add("g08", 3, "action", "叶澜急忙站起", "中景", "平拍", "叶澜从烟尘下缘撑地起身，面板悬在左侧", "fixed",
    {"叶澜·基础状态": ("right_third", "midground", "left")},
    "【广场外缘平拍中景，固定机位】[叶澜·基础状态]一掌撑地急忙站起，掸落衣摆烟尘，转头锁定山门高处秦放；无字[并夕夕系统面板]缩到左侧悬浮跟随。",
    priority="key", focal=["叶澜·基础状态"], props_opt=["并夕夕系统面板"], changes=[{"role_id": "叶澜·基础状态", "from_anchor": "A07", "to_anchor": "A07", "path": "在广场外缘原地从受击后的低姿态急忙站起", "reason": "剧本明确叶澜急忙站起", "pose_height_after": "standing", "facing_after": "朝向秦放"}], entry="叶澜在烟尘中低姿态读取倒计时", exit="叶澜站起并锁定秦放", los="叶澜→秦放", requirements=reqs("action", physical_interaction="low", vfx_environment="low"), merge="preferred")
add("g08", 3, "action", "叶澜上前挑衅站位", "中景", "平拍", "叶澜从左侧外缘走到广场中央，秦放位于右上远处", "simple_follow",
    {"叶澜·基础状态": ("left_third", "foreground", "right"), "秦放·基础状态": ("upper_right", "background", "left"), "叶灵·基础状态": ("lower_right", "background", "left")},
    "【广场平拍中景，简单跟随】[叶澜·基础状态]从外缘烟尘中快步走到圆形雕纹外缘，停下后单手叉腰，另一手指向山门高处[秦放·基础状态]；[叶灵·基础状态]在石阶下端侧身停步。",
    priority="key", focal=["叶澜·基础状态"], axis="AX02", changes=[{"role_id": "叶澜·基础状态", "from_anchor": "A07", "to_anchor": "A04", "path": "从广场外缘快步走到中央圆形雕纹外缘", "reason": "剧本明确叶澜上前挑衅秦放", "facing_after": "抬头朝向秦放"}], entry="叶澜站在广场外缘锁定秦放", exit="叶澜站到圆形雕纹外缘，叉腰指向秦放", los="叶澜→秦放；叶灵→叶澜", requirements=reqs("action", multi_character_control="medium", physical_interaction="none", camera_control="high"), merge="preferred")
add("g08", 7, "dialogue", "叶澜第一次激将", "近景", "轻仰拍", "叶澜左三分之一，指向高处的手臂形成对角线", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "right"), "秦放·基础状态": ("upper_right", "background", "left")},
    "【广场轻仰拍近景，固定机位】[叶澜·基础状态]单手叉腰、手指直指高处，眉峰挑起并露出故意嚣张的笑，以清晰口型喊出{喂，那边的儿砸，有本事来砍你爹啊！}；远处秦放只作缩小背景，叶澜背景适度虚焦。",
    tts="喂，那边的儿砸，有本事来砍你爹啊！", priority="climax", focal=["叶澜·基础状态", "秦放·基础状态"], axis="AX02", entry="叶澜叉腰指向秦放", exit="叶澜完成第一次挑衅并保持指向", los="叶澜→秦放；秦放→叶澜", requirements=reqs("dialogue", acting_precision="critical", multi_character_control="medium"), merge="allowed")
add("g08", 3, "complex_narrative", "叶家众人困惑停步", "中景", "平拍", "叶灵在前景回头，弟子群在纵深依次停步，叶澜在远处", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "left"), "叶家弟子群·基础状态": ("lower_right", "midground", "left"), "叶澜·基础状态": ("upper_left", "background", "right")},
    "【石阶下端平拍中景，固定机位】[叶灵·基础状态]和数名[叶家弟子群·基础状态]同时刹住脚步并回头，叶灵眉头抬起、弟子们互相错愕对视；不用问号符号，只用停顿、歪头和僵住的剑势表达困惑。",
    priority="key", focal=["叶灵·基础状态", "叶家弟子群·基础状态"], axis="AX02", entry="叶灵与弟子正冲向秦放", exit="叶灵与弟子群停在石阶下端并回头看叶澜", los="叶灵与叶家弟子群→叶澜", requirements=reqs("complex_narrative", dialogue_lipsync="none", motion_action="medium"), merge="allowed")

# G09 秦放转移目标，叶澜升级辱骂。
add("g09", 2, "reaction", "秦放惊讶后蔑笑", "特写", "微低机位仰拍", "秦放脸部偏右，眼神向左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位特写，固定机位】[秦放·基础状态]先因挑衅停顿半拍，眉梢微抬，随后嘴角缓慢扬成蔑笑，背景适度虚焦。",
    priority="key", focal=["秦放·基础状态"], axis="AX02", entry="秦放听见叶澜挑衅", exit="秦放由惊讶转为蔑笑", los="秦放→叶澜", merge="preferred", safe_padding={"after": 1})
add("g09", 5, "dialogue", "秦放蔑视叶澜", "近景", "微低机位仰拍", "秦放右三分之一，朝左下留视线负空间", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]保持蔑笑，垂眼看向广场，以清晰口型说出{一只蝼蚁，还敢挑衅本神子！}，黑金衣领与冠饰清晰，背景适度虚焦。",
    tts="一只蝼蚁，还敢挑衅本神子！", priority="key", focal=["秦放·基础状态"], axis="AX02", entry="秦放由惊讶转为蔑笑", exit="秦放完成对叶澜的蔑视", los="秦放→叶澜", merge="allowed")
add("g09", 2, "reaction", "秦放瞥向叶家众人", "近景", "微低机位仰拍", "秦放占右侧，眼神从左下移向更左侧", "focus_shift",
    {"秦放·基础状态": ("right_third", "foreground", "left"), "叶灵·基础状态": ("lower_left", "background", "right")},
    "【山门高处微低机位近景，焦点稳定锁脸】[秦放·基础状态]从叶澜身上移开视线，转而瞥向石阶下端的[叶灵·基础状态]等人，嘴角带着戏谑，后景人物明显缩小并虚化。",
    focal=["秦放·基础状态"], axis="AX01", entry="秦放蔑视叶澜", exit="秦放把注意力转向叶灵与叶家弟子", los="秦放→叶灵与叶家弟子群", merge="preferred")
add("g09", 8, "dialogue", "秦放宣告折磨叶澜", "近景", "微低机位仰拍", "秦放右三分之一，侧脸朝左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]看着叶家众人，眼底戏谑不减，以清晰口型缓慢说出{让你亲眼看着他们一个个死去而无能为力，}，说到末尾轻轻抬起右手，背景适度虚焦。",
    tts="让你亲眼看着他们一个个死去而无能为力，", priority="key", focal=["秦放·基础状态"], axis="AX01", entry="秦放注意力转向叶家众人", exit="秦放抬起右手准备施诀", los="秦放→叶灵与叶家弟子群", merge="preferred")
add("g09", 4, "dialogue", "秦放享受戏弄", "特写", "微低机位仰拍", "秦放嘴角与眼神偏右，抬起手指虚化在左前景", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位特写，固定机位】[秦放·基础状态]手指停在左前景，眼神仍落在叶家众人身上，以清晰口型补完{也挺有趣……}，话尾笑意更深，背景适度虚焦。",
    tts="也挺有趣……", focal=["秦放·基础状态"], axis="AX01", entry="秦放抬手准备施诀", exit="秦放手指蓄起微弱金光，尚未释放", los="秦放→叶灵与叶家弟子群", merge="allowed")
add("g09", 2, "action", "秦放转身准备施诀", "中景", "微低机位仰拍", "秦放在右侧转肩朝叶家众人，叶澜在左下远处", "fixed",
    {"秦放·基础状态": ("upper_right", "midground", "left"), "叶澜·基础状态": ("lower_left", "background", "right")},
    "【山门至广场斜向中景，固定机位】[秦放·基础状态]转肩面向石阶下端，抬手汇聚金色法诀；远处[叶澜·基础状态]仍叉腰指着他，发现秦放不理自己后神色骤急。",
    focal=["秦放·基础状态", "叶澜·基础状态"], axis="AX02", entry="秦放手指蓄起微弱金光", exit="秦放即将朝叶家众人释放法诀，叶澜焦急", los="秦放→叶家众人；叶澜→秦放", requirements=reqs("action", physical_interaction="none", vfx_environment="high"), merge="preferred")
add("g09", 2, "prop_info", "系统倒数三", "特写", "主观平拍", "无字面板圆环偏左，剩余光格快速收缩", "fixed", {},
    "【系统面板特写，固定机位】无字[并夕夕系统面板]的一段警报光格骤然熄灭，圆环核心急促收缩一次；系统声音短促报出{三…}，画面不出现数字。",
    tts="三…", priority="climax", props_req=["并夕夕系统面板"], entry="倒计时持续，秦放准备攻击叶家众人", exit="系统报到三，叶澜可用时间更少", los="无人物视线", requirements=reqs("prop_info", temporal_continuity="critical"), merge="forbidden", independent=True, sound="急促系统画外音报数，配合一段警报光格熄灭。")
add("g09", 7, "dialogue", "叶澜爆粗激怒秦放", "近景", "轻仰拍", "叶澜左三分之一，手指直指右上高处", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "right"), "秦放·基础状态": ("upper_right", "background", "left")},
    "【广场轻仰拍近景，固定机位】[叶澜·基础状态]急得上身前倾，手指直指高处，以清晰口型破口大骂{秦放，你个狗娘养的……}；辱骂末段用连续电报哔声覆盖，远处秦放动作顿住，叶澜背景适度虚焦。",
    tts="秦放，你个狗娘养的……", priority="climax", focal=["叶澜·基础状态", "秦放·基础状态"], axis="AX02", entry="系统报到三，秦放正要攻击叶家众人", exit="叶澜完成辱骂，秦放施诀动作停住", los="叶澜→秦放；秦放开始转回叶澜", requirements=reqs("dialogue", acting_precision="critical", multi_character_control="medium"), merge="allowed", sound="叶澜高声辱骂，末段由密集电报哔声覆盖敏感词；风声短暂压低。")
add("g09", 2, "reaction", "秦放黑脸破防", "大特写", "微低机位仰拍", "秦放脸部居右，眼神压向左下", "quick_push",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位大特写，短促压近后稳定】[秦放·基础状态]嘴角笑意瞬间消失，面色沉下，下颌绷紧，眼底红色杀意开始燃起，背景强烈虚焦。",
    priority="climax", focal=["秦放·基础状态"], axis="AX02", entry="秦放听见叶澜辱骂并停住施诀", exit="秦放黑脸，杀意开始上升", los="秦放→叶澜", merge="allowed", safe_padding={"after": 1})
add("g09", 2, "complex_narrative", "叶家众人震惊呆滞", "中景", "平拍", "叶灵在前景僵住，弟子群在后景错愕张口", "fixed",
    {"叶灵·基础状态": ("left_third", "foreground", "left"), "叶家弟子群·基础状态": ("right_third", "background", "left"), "叶家长老二人·基础状态": ("upper_left", "background", "left")},
    "【石阶下端平拍中景，固定机位】[叶灵·基础状态]、数名[叶家弟子群·基础状态]与[叶家长老二人·基础状态]同时僵住，飞剑停在半空，众人睁大眼、微张嘴；不用感叹号符号，只用集体静止和错愕表情表达震惊。",
    focal=["叶灵·基础状态", "叶家弟子群·基础状态"], axis="AX02", entry="叶家众人停步回看叶澜", exit="叶家众人因辱骂内容集体呆滞", los="叶家众人→叶澜", requirements=reqs("complex_narrative", dialogue_lipsync="none", acting_precision="medium"), merge="allowed")
add("g10", 7, "dialogue", "叶澜老太太式追骂", "近景", "轻仰拍", "叶澜左三分之一，叉腰与指人姿态清楚", "fixed",
    {"叶澜·基础状态": ("left_third", "foreground", "right"), "秦放·基础状态": ("upper_right", "background", "left")},
    "【广场轻仰拍近景，固定机位】[叶澜·基础状态]一手叉腰，另一手连续点向高处，身体前倾，采用老太太骂街般泼辣节奏，以清晰口型喊出{你有种就杀我啊！儿砸，你聋了吗？}；远处秦放明显缩小，叶澜背景适度虚焦。",
    tts="你有种就杀我啊！儿砸，你聋了吗？", priority="climax", focal=["叶澜·基础状态", "秦放·基础状态"], axis="AX02", entry="秦放黑脸，叶家众人呆滞", exit="叶澜再次激将并保持叉腰指人", los="叶澜→秦放；秦放→叶澜", requirements=reqs("dialogue", acting_precision="critical", multi_character_control="medium"), merge="allowed")
add("g10", 2, "reaction", "秦放红眼杀意爆发", "大特写", "微低机位仰拍", "秦放双眼与眉骨占据画面，视线斜向左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位大特写，固定机位】[秦放·基础状态]双眼红色杀意骤然暴涨，眉骨压低，鼻息变重，眼神死死锁定叶澜，背景强烈虚焦。",
    priority="climax", focal=["秦放·基础状态"], axis="AX02", entry="秦放黑脸并听见第二轮挑衅", exit="秦放红眼杀意完全锁住叶澜", los="秦放→叶澜", merge="preferred", safe_padding={"after": 1})
add("g10", 6, "dialogue", "秦放宣判大卸八块", "近景", "微低机位仰拍", "秦放右三分之一，抬手指向左下", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门高处微低机位近景，固定机位】[秦放·基础状态]猛然抬手指向叶澜，袖袍被杀意掀起，以清晰口型怒喝{本神子要把你大卸八块！}，尾音落下时指尖金光凝成剑形，背景适度虚焦。",
    tts="本神子要把你大卸八块！", priority="climax", focal=["秦放·基础状态"], axis="AX02", entry="秦放红眼锁定叶澜", exit="秦放指尖凝成金色剑形能量", los="秦放→叶澜", merge="preferred")
add("g10", 2, "prop_info", "系统倒数二", "特写", "主观平拍", "无字面板圆环居中，警报光格再熄灭一段", "fixed", {},
    "【系统面板特写，固定机位】无字[并夕夕系统面板]又一段警报光格熄灭，圆环核心向内压缩；系统声音报出{二。}，画面不出现数字。",
    tts="二。", priority="climax", props_req=["并夕夕系统面板"], entry="秦放指尖剑形能量成形", exit="系统报到二，倒计时逼近终点", los="无人物视线", requirements=reqs("prop_info", temporal_continuity="critical"), merge="forbidden", independent=True, sound="系统画外音短促报数。")
add("g10", 3, "action", "秦放指剑射向叶澜", "中景", "微低机位仰拍", "秦放在右上高处，金色剑形能量沿对角线射向左下叶澜", "fixed",
    {"秦放·基础状态": ("upper_right", "midground", "left"), "叶澜·基础状态": ("lower_left", "background", "right")},
    "【山门至广场斜向中景，固定机位】[秦放·基础状态]并指朝下猛点，凝成的金色剑形能量呼啸射向[叶澜·基础状态]；叶澜站在圆形雕纹外缘不躲，反而收紧嘴角。",
    priority="climax", focal=["秦放·基础状态", "叶澜·基础状态"], axis="AX02", entry="秦放指尖剑形能量成形，叶澜原地挑衅", exit="金色剑形能量飞至叶澜面前", los="秦放→叶澜；叶澜→飞剑", requirements=reqs("action", motion_action="critical", vfx_environment="high", physical_interaction="high"), merge="preferred")
add("g10", 3, "prop_info", "系统倒数一与飞剑同步", "特写", "侧前方平拍", "叶澜眼睛在右侧，飞剑锋与面板末段光格在左前景", "fixed",
    {"叶澜·基础状态": ("right_third", "midground", "left")},
    "【叶澜侧前方特写，固定机位】金色剑锋从左前景逼近[叶澜·基础状态]胸前，无字[并夕夕系统面板]最后一段警报光格同时熄灭；系统声音报出{一。}，叶澜没有躲避，背景适度虚焦。",
    tts="一。", priority="climax", focal=["叶澜·基础状态"], props_req=["并夕夕系统面板"], axis="AX02", entry="金色剑形能量飞至叶澜面前", exit="剑锋即将命中，最后光格熄灭", los="叶澜→飞剑", requirements=reqs("prop_info", motion_action="high", physical_interaction="high", temporal_continuity="critical"), merge="forbidden", independent=True, sound="系统画外音报一，与剑锋破空声同步。")
add("g10", 2, "action", "叶澜中剑阴笑", "特写", "平拍", "叶澜脸部偏右，胸前金光从左下照亮嘴角", "fixed",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【广场平拍特写，固定机位】金色剑形能量命中[叶澜·基础状态]胸前并爆开强烈金光，画面只轻震一次；叶澜身体后仰半寸却在光中勾起阴谋得逞的笑，背景适度虚焦。",
    priority="climax", focal=["叶澜·基础状态"], axis="AX02", entry="剑锋即将命中叶澜", exit="叶澜中剑却露出阴笑，金光包围身体", los="叶澜→秦放", requirements=reqs("action", acting_precision="critical", physical_interaction="high", vfx_environment="high"), merge="preferred")
add("g10", 4, "dialogue", "叶澜确认秦放上当", "特写", "平拍", "叶澜嘴角与发亮眼睛占画面上半部", "fixed",
    {"叶澜·基础状态": ("right_third", "foreground", "left")},
    "【金光中的平拍特写，固定机位】[叶澜·基础状态]保持阴笑，眼神越过金光锁住高处秦放，嘴唇不动，以内心旁白说{终于上当了！}，背景适度虚焦。",
    tts="终于上当了！", priority="climax", focal=["叶澜·基础状态"], axis="AX02", entry="叶澜中剑露出阴笑", exit="叶澜确认秦放已触发奖励条件", los="叶澜→秦放", merge="allowed", sound="叶澜压低而兴奋的内心旁白，角色嘴唇不动。")
add("g11", 3, "prop_info", "系统奖励领取成功", "特写", "主观平拍", "系统圆环完全闭合，青蓝光流由面板涌向画外叶澜", "fixed", {},
    "【系统面板特写，固定机位】无字[并夕夕系统面板]的多层圆环完全闭合，全部警报光格转为稳定青蓝光，能量流从界面边缘涌向叶澜方向；系统声音宣布{奖励领取成功。}，画面不出现文字。",
    tts="奖励领取成功。", priority="climax", props_req=["并夕夕系统面板"], entry="叶澜中剑满足领取条件", exit="系统确认奖励成功，青蓝能量流入叶澜", los="无人物视线", requirements=reqs("prop_info", temporal_continuity="critical"), merge="forbidden", independent=True, sound="系统成功提示音与清晰系统画外音。")
add("g11", 4, "environment_vfx", "叶澜修为暴涨震退秦放", "全景", "平拍低机位", "叶澜在下方前景成为能量中心，秦放在右上高处被冲击推后", "fixed",
    {"叶澜·基础状态": ("lower_left", "foreground", "right"), "秦放·基础状态": ("upper_right", "background", "left"), "叶灵·基础状态": ("lower_right", "midground", "left"), "叶家弟子群·基础状态": ("right_edge", "background", "left")},
    "【广场至山门平拍低机位全景，固定机位】[叶澜·基础状态]周身青蓝与金色灵力骤然冲天，衣袍和长发被气浪掀起；环形冲击波沿广场向上席卷，[秦放·基础状态]在山门高处被震得向后滑退数米，[叶灵·基础状态]与叶家弟子在下方抬袖遮挡。山门建筑保持完整，不出现坍塌。",
    priority="climax", focal=["叶澜·基础状态", "秦放·基础状态"], axis="AX02", changes=[{"role_id": "秦放·基础状态", "from_anchor": "A01", "to_anchor": "A09", "path": "在山门牌楼顶部被叶澜爆发的环形气浪沿平台向后震退数米", "reason": "剧本明确叶澜气息暴涨并将秦放震退数米", "facing_after": "仍朝向叶澜"}], entry="系统奖励成功，能量流入叶澜，秦放仍在山门前侧高处", exit="叶澜气息暴涨，秦放被震退至山门顶部后侧，叶家众人遮挡气浪", los="叶澜↔秦放；叶灵与弟子→叶澜", requirements=reqs("environment_vfx", identity_consistency="critical", multi_character_control="high", motion_action="high", physical_interaction="high"), merge="allowed")
add("g11", 3, "reaction", "秦放不可思议", "大特写", "平拍", "秦放脸部偏右，眼睛落在上三分之一", "fixed",
    {"秦放·基础状态": ("right_third", "foreground", "left")},
    "【山门顶部后侧平拍大特写，固定机位】[秦放·基础状态]脚步刚稳，瞳孔骤然放大，嘴角僵住，呼吸停顿半拍，满脸不可思议地看向下方灵压暴涨的叶澜，背景适度虚焦。",
    priority="climax", focal=["秦放·基础状态"], axis="AX02", entry="秦放被气浪震退数米刚刚站稳", exit="秦放震惊失语，权力优势首次动摇", los="秦放→叶澜", requirements=reqs("reaction", acting_precision="critical", identity_consistency="critical", camera_control="low"), merge=None)


# The last atomic shot must not carry a merge_relation.
shots[-1].pop("merge_relation", None)

document = {
    "routing_tier": "medium",
    "aspect_ratio": "9:16",
    "asset_catalog": {"scenes": [SCENE], "roles": ROLES, "props": PROPS},
    "scene_contexts": [
        {
            "scene_asset": SCENE,
            "state": "山门建筑保持完整；护山大阵在开场冲击后破碎，后续以金蓝光尘、薄烟、灰尘与人物血迹覆盖完整场景母版",
            "lighting": "右上方冷白日光穿过云雾形成侧逆光，金色法术为局部暖高光，阵法与系统为冰蓝辅光",
            "style_lock": "9:16东方玄幻真人短剧，冷青灰古朴宗门基调，写实电影质感；Q版叶澜仅在指定喜剧镜头短暂使用，随后恢复真人正常比例",
            "spatial_bible": {
                "anchor_catalog": {
                    "A01": {"landmark": "依山而建的古朴大型宗门山门牌楼", "description": "山门牌楼顶部前侧可站立平台，俯瞰广场"},
                    "A02": {"landmark": "广场中央带有圆形雕纹石质地面图案", "description": "圆形雕纹中央与靠石阶一侧的叶家集结区"},
                    "A03": {"landmark": "广场两侧排列高大雕纹石柱、石灯与宗门附属建筑", "description": "广场左侧高大雕纹石柱背后的遮蔽位置"},
                    "A04": {"landmark": "广场中央带有圆形雕纹石质地面图案", "description": "圆形雕纹外缘、能被山门高处清楚看见的位置"},
                    "A05": {"landmark": "山门后方沿中轴线向上延伸的宽阔石阶", "description": "山门石阶下端与广场连接处"},
                    "A06": {"landmark": "前景为大面积灰色青石铺装宗门广场", "description": "广场右侧青石地面上的秦族弟子阵列区域"},
                    "A07": {"landmark": "广场两侧排列高大雕纹石柱、石灯与宗门附属建筑", "description": "广场左侧雕纹石柱后方通往外缘的退路"},
                    "A08": {"landmark": "山门后方沿中轴线向上延伸的宽阔石阶", "description": "宽阔石阶中上段、秦族弟子可列阵处"},
                    "A09": {"landmark": "依山而建的古朴大型宗门山门牌楼", "description": "山门牌楼顶部后侧、距前侧平台数米的位置"},
                },
                "axis_catalog": {
                    "AX01": {"between": ["秦放·基础状态", "叶灵·基础状态"], "default_side": "south", "cross_axis_allowed": False},
                    "AX02": {"between": ["秦放·基础状态", "叶澜·基础状态"], "default_side": "south", "cross_axis_allowed": False},
                },
                "initial_world_positions": {
                    "秦放·基础状态": {"anchor_id": "A01", "position": "山门牌楼顶部前侧平台", "facing": "俯视叶家广场", "pose_height": "elevated", "visibility": "visible"},
                    "秦族弟子群·基础状态": {"anchor_id": "A08", "position": "山门后方宽阔石阶中上段列阵", "facing": "朝向叶家广场", "pose_height": "standing", "visibility": "visible"},
                    "叶灵·基础状态": {"anchor_id": "A02", "position": "广场中央圆形雕纹前侧", "facing": "仰望秦放", "pose_height": "standing", "visibility": "visible"},
                    "叶家弟子群·基础状态": {"anchor_id": "A02", "position": "叶灵后方的圆形雕纹区域", "facing": "仰望秦放", "pose_height": "standing", "visibility": "visible"},
                    "叶家长老二人·基础状态": {"anchor_id": "A02", "position": "叶家弟子群后方两侧", "facing": "仰望秦放", "pose_height": "standing", "visibility": "visible"},
                    "叶澜·基础状态": {"anchor_id": "A03", "position": "广场左侧高大雕纹石柱后", "facing": "侧身偷看山门与广场", "pose_height": "standing", "visibility": "occluded"},
                },
            },
        }
    ],
    "atomic_shots": shots,
}

output_path = ROOT / "EP001_A导演输出.json"
output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {output_path}")
print(f"atomic_shots={len(shots)}, total_duration={sum(s['atomic_duration'] for s in shots)}s")
