from __future__ import annotations

from unittest.mock import patch

from app.demo_service import load_demo_tier
from app.main import _reference_payload_from_shot
from app.reference_image_service import (
    DEMO_IMAGE_ROOT,
    create_reference_image_pair_job,
    create_reference_image_pair_provider_job,
)
from app.workflow_service import (
    auto_bind_video_plan,
    missing_asset_ids,
    register_reference_pair,
    seed_demo_assets,
    submit_video_jobs,
)


def main() -> None:
    seeded = seed_demo_assets()
    assert seeded["seeded_count"] >= 1

    final_plan = load_demo_tier("medium")["final_video_plan"]
    for shot in final_plan["shots"]:
        payload, input_ids = _reference_payload_from_shot("EP001", shot, True)
        assert missing_asset_ids(input_ids) == []
        manifest = create_reference_image_pair_job(payload)
        assert manifest["status"] == "completed"
        assert register_reference_pair(manifest)["registered_count"] == 2

    binding = auto_bind_video_plan(final_plan)
    assert binding["ready_count"] == len(final_plan["shots"])
    assert binding["blocked_count"] == 0
    first_references = binding["ready"][0]["provider_payload"]["references"]
    assert any(str(item.get("asset_id", "")).endswith("::entry") for item in first_references)
    assert any(str(item.get("asset_id", "")).endswith("::exit") for item in first_references)
    assert any(not item.get("derived") for item in first_references)

    submission = submit_video_jobs(final_plan)
    assert submission["submitted_count"] == len(final_plan["shots"])
    assert submission["blocked_count"] == 0
    assert len(submission["jobs"][0]["derived_reference_ids"]) == 2

    provider_payload, _ = _reference_payload_from_shot(
        "EP001", final_plan["shots"][0], False
    )
    provider_payload["image_model"] = "mock/image-model"
    provider_payload["aspect_ratio"] = "9:16"
    png_bytes = (DEMO_IMAGE_ROOT / "u001_entry-v4.png").read_bytes()
    with patch(
        "app.reference_image_service._call_openrouter_image",
        side_effect=[
            (png_bytes, "image/png", {"cost": 0.01}),
            (png_bytes, "image/png", {"cost": 0.01}),
        ],
    ) as mocked_image_call:
        real_manifest = create_reference_image_pair_provider_job(
            provider_payload, ["data:image/png;base64,ZmFrZQ=="]
        )
    assert real_manifest["generation_mode"] == "openrouter_images_api"
    assert real_manifest["image_model"] == "mock/image-model"
    assert real_manifest["entry"]["image_url"].startswith("/workflow-generated/")
    assert real_manifest["exit"]["source_image_url"] == real_manifest["entry"]["image_url"]
    assert mocked_image_call.call_args_list[0].args[0] == provider_payload["entry_prompt_zh"]
    assert mocked_image_call.call_args_list[1].args[0] == provider_payload["exit_prompt_zh"]
    assert mocked_image_call.call_args_list[1].args[1][0].startswith("data:image/png;base64,")
    print("workflow: assets + reference pairs + binding + video queue PASS")


if __name__ == "__main__":
    main()
