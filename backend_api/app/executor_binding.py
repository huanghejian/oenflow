from __future__ import annotations

from typing import Any


def bind_logical_assets(
    final_video_plan: dict[str, Any], asset_registry: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for shot in final_video_plan.get("shots", []):
        bound_references = []
        missing_required = []
        missing_derived = []
        for ref in shot.get("references", []):
            asset_id = ref.get("asset_id")
            binding = asset_registry.get(str(asset_id))
            if not binding:
                if ref.get("derived"):
                    missing_derived.append(asset_id)
                    continue
                if ref.get("required"):
                    missing_required.append(asset_id)
                continue
            bound_ref = dict(ref)
            bound_ref.update({k: v for k, v in binding.items() if v is not None})
            bound_ref["binding_status"] = "bound"
            bound_references.append(bound_ref)

        if missing_required or missing_derived:
            status = "asset_binding_missing" if missing_required else "reference_image_generation_pending"
            blocked.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "status": status,
                    "missing_required_asset_ids": missing_required,
                    "missing_derived_reference_ids": missing_derived,
                    **({"reference_image_plan": shot.get("reference_image_plan")} if missing_derived else {}),
                }
            )
            continue

        provider_payload = {
            "shot_id": shot.get("shot_id"),
            "model": shot.get("model"),
            "model_params": shot.get("model_params"),
            "duration": shot.get("duration"),
            "prompt": shot.get("prompt_zh"),
            "references": bound_references,
        }
        ready.append(
            {
                "shot_id": shot.get("shot_id"),
                "status": "ready_for_provider_adapter",
                "provider_payload": provider_payload,
            }
        )

    return {
        "ready_count": len(ready),
        "blocked_count": len(blocked),
        "ready": ready,
        "blocked": blocked,
        "reference_image_jobs": final_video_plan.get("reference_image_jobs", []),
    }
