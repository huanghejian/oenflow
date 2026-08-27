from __future__ import annotations

import tempfile
from pathlib import Path

from app import autoflow_service


def main() -> None:
    original_path = autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH
    with tempfile.TemporaryDirectory() as temporary_directory:
        test_path = Path(temporary_directory) / "autoflow_routing" / "latest.json"
        autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH = test_path
        try:
            result = {
                "difficulty_analysis": {"shots": []},
                "routing_analysis": {"shots": [{"shot_id": "u001"}]},
                "final_video_plan": {"shots": [{"shot_id": "u001"}]},
                "reference_generation": {
                    "completed_count": 1,
                    "blocked_count": 0,
                    "completed": [
                        {
                            "shot_id": "u001",
                            "entry": {"image_url": "/v1/assets/entry"},
                            "exit": {"image_url": "/v1/assets/exit"},
                        }
                    ],
                    "blocked": [],
                    "generation_mode": "xingtu",
                },
                "source_context": {
                    "project_params": {"episode_id": "EP001"},
                    "assets": {"characters": [], "scenes": [], "items": []},
                    "story_context": {},
                    "shot_groups": [{"group_id": "g001"}],
                },
            }
            autoflow_service._save_step_result(test_path, result, "test.route.saved")
            loaded = autoflow_service.load_latest_route_result()
        finally:
            autoflow_service.AUTOFLOW_ROUTE_RESULT_PATH = original_path

    assert loaded == result
    assert loaded["reference_generation"]["completed"][0]["entry"]["image_url"] == "/v1/assets/entry"
    assert loaded["source_context"]["shot_groups"][0]["group_id"] == "g001"
    print("route result persistence contract: ok")


if __name__ == "__main__":
    main()
