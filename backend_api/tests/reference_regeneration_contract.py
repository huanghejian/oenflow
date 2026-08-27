from __future__ import annotations

import tempfile
from pathlib import Path

from app import autoflow_service


def main() -> None:
    original_path = autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH
    original_generate = autoflow_service._generate_reference_for_shot
    with tempfile.TemporaryDirectory() as temporary_directory:
        test_path = Path(temporary_directory) / "autoflow_routing" / "latest.json"
        source = {
            "routing_analysis": {"shots": [{"shot_id": "u001"}, {"shot_id": "u002"}]},
            "final_video_plan": {
                "shots": [
                    {"shot_id": "u001", "reference_image_plan": {"input_asset_ids": []}},
                    {"shot_id": "u002", "reference_image_plan": {"input_asset_ids": []}},
                ]
            },
            "reference_generation": {
                "completed_count": 0,
                "blocked_count": 2,
                "completed": [],
                "blocked": [
                    {"shot_id": "u001", "status": "blocked"},
                    {"shot_id": "u002", "status": "blocked"},
                ],
                "generation_mode": "xingtu",
            },
            "source_context": {
                "project_params": {"episode_id": "EP001", "aspect_ratio": "9:16"},
            },
        }
        calls: list[str] = []

        def fake_generate(episode_id, shot, generation_mode, image_model, aspect_ratio):
            shot_id = shot["shot_id"]
            calls.append(shot_id)
            return {
                "shot_id": shot_id,
                "status": "completed",
                "entry": {"image_url": f"/{shot_id}-entry.jpeg"},
                "exit": {"image_url": f"/{shot_id}-exit.jpeg"},
            }

        autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH = test_path
        autoflow_service._generate_reference_for_shot = fake_generate
        try:
            autoflow_service._save_step_result(test_path, source, "test.route.saved")
            result = autoflow_service.regenerate_latest_reference_images(
                "xingtu", "doubao-seedream-4-5-251128"
            )
        finally:
            autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH = original_path
            autoflow_service._generate_reference_for_shot = original_generate

    assert sorted(calls) == ["u001", "u002"]
    assert result["routing_analysis"] == source["routing_analysis"]
    assert result["reference_generation"]["completed_count"] == 2
    assert result["reference_generation"]["blocked_count"] == 0
    assert result["reference_generation"]["regenerated_only"] is True
    print("reference regeneration contract: ok")


if __name__ == "__main__":
    main()
