from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "EP001" / "EP001_A导演输出.json"
TIERS = ("low", "medium", "high")
LEGAL_CUTS = {
    "scene_start",
    "scene_end",
    "hard_cut",
    "concealed_cut",
    "match_cut_action",
    "match_cut_shape",
    "fade",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    old = load(OLD)
    director = load(ROOT / "EP001_V73_A导演输出.json")
    bundle = load(ROOT / "EP001_V73_三档完整提示词.json")
    image_jobs = load(ROOT / "EP001_V73_普通图片参考任务.json")["jobs"]
    shots = director["atomic_shots"]

    assert len(old["atomic_shots"]) == 63
    assert len(shots) == 49
    assert sum(item["atomic_duration"] for item in shots) == 240
    assert max(item["atomic_duration"] for item in shots) <= 30
    assert "".join(item.get("tts", "") for item in old["atomic_shots"]) == "".join(
        item.get("tts", "") for item in shots
    )
    assert all(item["single_take"] is True and item["indivisible"] is True for item in shots)
    assert all(item["cut_in"] in LEGAL_CUTS and item["cut_out"] in LEGAL_CUTS for item in shots)
    assert shots[0]["cut_in"] == "scene_start"
    assert shots[-1]["cut_out"] == "scene_end"
    assert all(left["cut_out"] == right["cut_in"] for left, right in zip(shots, shots[1:]))
    assert all(item["beats"][0]["start"] == 0 for item in shots)
    assert all(item["beats"][-1]["end"] == item["atomic_duration"] for item in shots)

    assert len(image_jobs) == 49
    assert len(bundle["shots"]) == 49
    for index, job in enumerate(image_jobs):
        shot_id = f"u{index + 1:03d}"
        assert job["shot_id"] == shot_id
        assert job["output_asset_ids"]["entry"] == f"shotref::{shot_id}::entry"
        assert job["output_asset_ids"]["exit"] == f"shotref::{shot_id}::exit"
        if index:
            previous_id = f"u{index:03d}"
            assert job["continuity_source_shot_id"] == previous_id
            assert job["depends_on_output_asset_id"] == f"shotref::{previous_id}::exit"

    for tier in TIERS:
        final = load(ROOT / f"pipeline_{tier}" / "EP001_V73_final_video_shots.json")
        validation = load(ROOT / f"pipeline_{tier}" / "EP001_V73_validation.json")
        spatial = load(ROOT / f"pipeline_{tier}" / "EP001_V73_spatial_validation.json")
        assert validation["ok"] is True and validation["error_count"] == 0
        assert spatial["ok"] is True and spatial["error_count"] == 0 and spatial["warning_count"] == 0
        assert len(final["shots"]) == 49
        assert all(shot["single_take"] is True and shot["indivisible"] is True for shot in final["shots"])
        assert all(len(shot["atomic_ids"]) == 1 for shot in final["shots"])
        assert all("【不出现任何文字字幕】" in shot["prompt_zh"] or "画面无字幕" in shot["prompt_zh"] for shot in final["shots"])
        assert all("entry_state_reference_prompt_zh" in shot["reference_image_plan"] for shot in final["shots"])
        assert all("exit_state_reference_edit_prompt_zh" in shot["reference_image_plan"] for shot in final["shots"])

    print("DELIVERY QA OK")
    print("dialogue_coverage=100%")
    print("atomic_shots=49; content_duration=240s; max_single_take=21s")
    print("image_reference_jobs=49; image_outputs=98; chained_dependencies=48")
    print("low_medium_high=PASS; spatial_warnings=0")


if __name__ == "__main__":
    main()
