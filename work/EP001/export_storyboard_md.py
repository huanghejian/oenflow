import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
A_PATH = ROOT / "EP001_A导演输出.json"
FINAL_PATH = ROOT / "pipeline" / "EP001_final_video_shots.json"
ROUTED_PATH = ROOT / "pipeline" / "EP001_routed_units.json"
OUT_PATH = ROOT / "EP001_分镜表.md"


def tc(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def esc(value) -> str:
    return str(value or "").replace("|", "｜").replace("\n", " ")


a_doc = json.loads(A_PATH.read_text(encoding="utf-8"))
final_doc = json.loads(FINAL_PATH.read_text(encoding="utf-8"))
routed_doc = json.loads(ROUTED_PATH.read_text(encoding="utf-8"))
routed_by_id = {u["unit_id"]: u for u in routed_doc["routed_units"]}

post_notes = {
    "a006": "后期叠加身份字卡：秦放／秦家神子；不要在生视频阶段生成文字。",
    "a017": "后期叠加人物名：叶澜；本镜短暂Q版，下一动作镜恢复真人正常比例。",
    "a038": "后期叠加十秒倒计时数字；底片只保留十段光格和警报流光。",
    "a042": "后期叠加头顶问号；底片用停步、歪头、错愕对视表达。",
    "a049": "系统报三，画面数字由后期叠加。",
    "a050": "辱骂末段后期叠加密集电报哔声。",
    "a052": "后期叠加头顶感叹号；底片用集体僵住与微张嘴表达。",
    "a056": "系统报二，画面数字由后期叠加。",
    "a058": "系统报一，画面数字由后期叠加，并与剑锋逼近同步。",
}

lines = [
    "# 第1集 1-1 叶家主殿外｜生产分镜表",
    "",
    "## 制作参数",
    "",
    f"- 项目：短剧；画幅：{a_doc['aspect_ratio']}；目标分辨率：{final_doc['target_resolution']}；路由档位：{final_doc['routing_tier']}。",
    f"- 导演原子镜头：{len(a_doc['atomic_shots'])} 个，内容时长 {sum(s['atomic_duration'] for s in a_doc['atomic_shots'])} 秒。",
    f"- 最终生视频单元：{len(final_doc['shots'])} 个，请求时长 {sum(s['duration'] for s in final_doc['shots'])} 秒。",
    f"- 请求时长包含 {sum(s['duration'] for s in final_doc['shots']) - sum(s['atomic_duration'] for s in a_doc['atomic_shots'])} 秒模型最短时长／安全停留，剪辑按 240 秒内容时码裁切。",
    f"- Medium 路由积分：{routed_doc['routing_meta']['total_call_points']}；预计可用积分：{routed_doc['routing_meta']['total_expected_usable_points']}。",
    "- 视频底片统一不生成文字、数字、问号、感叹号或身份字卡；这些元素按下表后期备注叠加。",
    "- 护山大阵破裂采用局部撞击、阵纹裂光、烟光遮罩、受击结果的蒙太奇链，不连续演算山门坍塌。",
    "",
    "## 场面调度锁",
    "",
    "- 秦放始终处于山门牌楼高处；叶灵、叶家弟子与长老位于青石广场低处，前半段保持高低位压迫。",
    "- 叶澜起初藏在广场左侧雕纹石柱后，沿外缘退路后撤；系统激活后走到圆形雕纹外缘主动挑衅。",
    "- 叶灵与叶家弟子冲到山门石阶下端后停步回看叶澜；秦放最后被气浪沿牌楼顶部向后震退数米。",
    "- 全场摄影轴线保持同侧，不越轴；右上冷白日光不变，金色法术和冰蓝阵法／系统仅作为局部辅光。",
    "",
    "## 原子分镜",
    "",
    "| 镜号 | 时码 | 时长 | 景别／运镜 | 画面与表演 | 台词／声音 | 核心资产 | 后期备注 |",
    "|---|---:|---:|---|---|---|---|---|",
]

cursor = 0
for shot in a_doc["atomic_shots"]:
    start = cursor
    cursor += int(shot["atomic_duration"])
    cp = shot["camera_plan"]
    timeline = shot["prompt_core"]["timeline_local"]
    asset_refs = shot.get("asset_refs", {})
    assets = list(asset_refs.get("roles", [])) + list(asset_refs.get("props", []))
    dialogue = shot.get("tts", "—")
    sound = shot.get("prompt_core", {}).get("sound")
    if sound:
        dialogue = f"{dialogue}；{sound}" if dialogue != "—" else sound
    lines.append(
        "| {id} | {start}–{end} | {dur}s | {shot_size}／{movement} | {timeline} | {dialogue} | {assets} | {note} |".format(
            id=shot["atomic_id"],
            start=tc(start),
            end=tc(cursor),
            dur=shot["atomic_duration"],
            shot_size=esc(cp["shot_size"]),
            movement=esc(cp["movement"]),
            timeline=esc(timeline),
            dialogue=esc(dialogue),
            assets=esc("、".join(assets) if assets else "场景／能量特效"),
            note=esc(post_notes.get(shot["atomic_id"], "—")),
        )
    )

lines.extend([
    "",
    "## 最终生视频单元",
    "",
    "| 单元 | 时长 | 模型／预设 | 原子镜头 | 逻辑引用状态 |",
    "|---|---:|---|---|---|",
])

for unit in final_doc["shots"]:
    params = unit.get("model_params", {})
    preset = params.get("resolution_preset", "")
    atomic_ids = routed_by_id.get(unit["shot_id"], {}).get("atomic_ids", [])
    lines.append(
        f"| {esc(unit['shot_id'])} | {unit['duration']}s | {esc(unit['model'])}／{esc(preset)} | {esc('、'.join(atomic_ids))} | {esc(unit.get('reference_binding_status', 'logical_only'))} |"
    )

lines.extend([
    "",
    "## 后期统一事项",
    "",
    "- 身份字卡、人物名字、系统数值、倒计时数字、问号和感叹号均在剪辑包装阶段叠加。",
    "- 叶澜和系统VO的内心／画外音段，演员嘴唇保持不动；秦放、叶灵、叶澜外放对白段要求清晰口型。",
    "- a050 的辱骂末段使用电报哔声覆盖；原始台词轨可保留供审片，发布版使用消音轨。",
    "- 最终视频提示词与逻辑 references 见 `pipeline/EP001_final_video_shots.json`；绑定真实素材 file_id 后即可提交视频API。",
    "",
])

OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT_PATH}")
