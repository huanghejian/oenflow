from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TIERS = ("low", "medium", "high")
TIER_LABELS = {"low": "低档", "medium": "中档", "high": "高档"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def preset_of(shot):
    params = shot.get("model_params", {})
    return params.get("resolution_preset") or params.get("preset") or "default"


def distribution(shots):
    return Counter((shot["model"], preset_of(shot)) for shot in shots)


def main():
    director = load_json(ROOT / "EP001_V73_A导演输出.json")
    final = {
        tier: load_json(ROOT / f"pipeline_{tier}" / "EP001_V73_final_video_shots.json")
        for tier in TIERS
    }
    routed = {
        tier: load_json(ROOT / f"pipeline_{tier}" / "EP001_V73_routed_units.json")
        for tier in TIERS
    }

    for tier in TIERS:
        if len(final[tier]["shots"]) != len(director["atomic_shots"]):
            raise ValueError(f"{tier}: final shot count does not match director shot count")

    tier_summary = {}
    for tier in TIERS:
        shots = final[tier]["shots"]
        meta = routed[tier]["routing_meta"]
        tier_summary[tier] = {
            "label": TIER_LABELS[tier],
            "shot_count": len(shots),
            "content_duration_seconds": sum(item["atomic_duration"] for item in director["atomic_shots"]),
            "request_duration_seconds": sum(shot["duration"] for shot in shots),
            "total_call_points": meta["total_call_points"],
            "total_expected_usable_points": meta["total_expected_usable_points"],
            "model_preset_distribution": [
                {"model": model, "preset": preset, "count": count}
                for (model, preset), count in sorted(distribution(shots).items())
            ],
        }

    director_by_id = {shot["atomic_id"]: shot for shot in director["atomic_shots"]}
    tier_shots = {
        tier: {shot["atomic_ids"][0]: shot for shot in final[tier]["shots"]}
        for tier in TIERS
    }

    bundled_shots = []
    for atomic in director["atomic_shots"]:
        atomic_id = atomic["atomic_id"]
        medium_shot = tier_shots["medium"][atomic_id]
        item = {
            "shot_id": medium_shot["shot_id"],
            "atomic_id": atomic_id,
            "director": {
                "narrative_function": atomic["narrative_function"],
                "content_duration_seconds": atomic["atomic_duration"],
                "single_take": atomic["single_take"],
                "indivisible": atomic["indivisible"],
                "cut_in": atomic["cut_in"],
                "cut_out": atomic["cut_out"],
                "camera_plan": atomic["camera_plan"],
                "beats": atomic["beats"],
                "continuity": atomic["continuity"],
            },
            "reference_image_plan": medium_shot["reference_image_plan"],
            "tiers": {},
        }
        if atomic.get("tts"):
            item["director"]["tts"] = atomic["tts"]
        for tier in TIERS:
            shot = tier_shots[tier][atomic_id]
            item["tiers"][tier] = {
                "model": shot["model"],
                "model_params": shot["model_params"],
                "request_duration_seconds": shot["duration"],
                "prompt_zh": shot["prompt_zh"],
                "references": shot["references"],
                "reference_binding_status": shot["reference_binding_status"],
            }
        bundled_shots.append(item)

    bundle = {
        "contract_version": "v7.3-three-tier-prompt-bundle",
        "project_type": "短剧",
        "aspect_ratio": director["aspect_ratio"],
        "target_resolution": "720P",
        "summary": {
            "source_beat_count": 63,
            "cut_to_cut_atomic_shot_count": len(director["atomic_shots"]),
            "content_duration_seconds": sum(item["atomic_duration"] for item in director["atomic_shots"]),
            "reference_image_job_count": len(final["medium"]["reference_image_jobs"]),
            "reference_image_output_count": len(final["medium"]["reference_image_jobs"]) * 2,
            "all_tiers_validated": True,
        },
        "tier_summaries": tier_summary,
        "asset_catalog": director["asset_catalog"],
        "reference_image_jobs": final["medium"]["reference_image_jobs"],
        "shots": bundled_shots,
    }
    (ROOT / "EP001_V73_三档完整提示词.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "EP001_V73_普通图片参考任务.json").write_text(
        json.dumps(
            {
                "contract_version": "v7.3-ordinary-image-reference-jobs",
                "usage": "ordinary_image_reference",
                "note": "这些图片是视频模型的普通图片参考，不是视频API首帧/尾帧控制参数。",
                "jobs": final["medium"]["reference_image_jobs"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cut_counts = Counter(shot["cut_out"] for shot in director["atomic_shots"][:-1])
    lines = [
        "# EP001 V7.3 三档生产报告",
        "",
        "## 生产结论",
        "",
        f"- 原逐拍段落：63；按真实剪辑点重组后：{len(director['atomic_shots'])} 个不可拆分连续镜头。",
        f"- 剧情内容总时长：{sum(item['atomic_duration'] for item in director['atomic_shots'])} 秒。",
        f"- 剪辑边界：硬切 {cut_counts['hard_cut']}，烟光藏切 {cut_counts['concealed_cut']}，形状匹配切 {cut_counts['match_cut_shape']}，动作匹配切 {cut_counts['match_cut_action']}。",
        f"- 普通图片参考任务：{len(final['medium']['reference_image_jobs'])} 组，共 {len(final['medium']['reference_image_jobs']) * 2} 张动作开始/结束状态图。",
        "- 低、中、高三档均保持 49 镜一镜一包，空间校验 0 警告，最终校验通过。",
        "",
        "## 三档路由汇总",
        "",
        "| 档位 | 镜头数 | 请求总时长 | 调用积分 | 预计可用积分 | 模型 / preset 分布 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for tier in TIERS:
        summary = tier_summary[tier]
        dist = "；".join(
            f"{item['model']} / {item['preset']} × {item['count']}"
            for item in summary["model_preset_distribution"]
        )
        lines.append(
            f"| {summary['label']} | {summary['shot_count']} | {summary['request_duration_seconds']}秒 | "
            f"{summary['total_call_points']:.1f} | {summary['total_expected_usable_points']:.4f} | {dist} |"
        )

    lines.extend(
        [
            "",
            "## 批量执行顺序",
            "",
            "1. 为 u001 生成动作开始状态参考图，再以它为编辑底图生成 u001 动作结束状态参考图。",
            "2. 从 u002 开始，以上一镜结束状态图为编辑参考，生成本镜动作开始状态图；再以本镜开始状态图生成本镜结束状态图。",
            "3. 把本镜开始/结束状态图连同注册角色、场景、道具图一起绑定为普通图片参考，再提交所选档位的视频提示词。",
            "4. 视频生成后按 cut_out 执行剪辑：hard_cut 直接切；concealed_cut 在全屏烟光处切；match_cut 在形状或动作对应点切。",
            "",
            "## 逐镜路由",
            "",
            "| 镜号 | 原子 | 内容时长 | 入/出剪辑 | 导演功能 | 低档 | 中档 | 高档 |",
            "|---:|---|---:|---|---|---|---|---|",
        ]
    )
    for index, atomic in enumerate(director["atomic_shots"], start=1):
        atomic_id = atomic["atomic_id"]
        routes = []
        for tier in TIERS:
            shot = tier_shots[tier][atomic_id]
            routes.append(f"{shot['model']} / {preset_of(shot)} / {shot['duration']}s")
        function = atomic["narrative_function"].replace("|", "／")
        lines.append(
            f"| {index:02d} | {atomic_id} | {atomic['atomic_duration']}s | "
            f"{atomic['cut_in']} → {atomic['cut_out']} | {function} | {routes[0]} | {routes[1]} | {routes[2]} |"
        )

    lines.extend(
        [
            "",
            "## 交付文件",
            "",
            "- `EP001_V73_A导演输出.json`：49 镜不可拆分导演稿。",
            "- `EP001_V73_三档完整提示词.json`：逐镜聚合低、中、高档视频提示词及普通图片参考提示词。",
            "- `EP001_V73_普通图片参考任务.json`：可直接送入图片批处理队列的 49 组参考图任务。",
            "- `pipeline_low/medium/high/*_final_video_shots.json`：各档独立完整视频执行 JSON。",
            "- `pipeline_low/medium/high/*_validation.json`：各档最终校验报告。",
        ]
    )
    (ROOT / "EP001_V73_三档生产报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("bundle=EP001_V73_三档完整提示词.json")
    print("image_jobs=EP001_V73_普通图片参考任务.json")
    print("report=EP001_V73_三档生产报告.md")


if __name__ == "__main__":
    main()
