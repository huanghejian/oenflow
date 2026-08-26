from __future__ import annotations

from app.pipeline_service import _build_routing_analysis


def main() -> None:
    routed = {
        "routing_tier": "medium",
        "target_resolution": "720P",
        "routed_units": [
            {
                "unit_id": "u001",
                "atomic_ids": ["s001"],
                "duration": 5,
                "routing_decision": {
                    "selected_model": "seedance-2.0",
                    "selected_preset": "720p-fast",
                    "fit_quality": 91.2,
                    "candidates": [
                        {
                            "model": "seedance-2.0",
                            "preset": "720p-fast",
                            "qualified": True,
                            "fit_quality": 91.2,
                            "selected_references": [{"asset_id": "private-large-field"}],
                        },
                        {
                            "model": "higgsfield-h3",
                            "preset": "2K",
                            "qualified": False,
                            "hard_reasons": ["preset_output_resolution_mismatch"],
                        },
                    ],
                },
            }
        ],
    }
    analysis = _build_routing_analysis(routed)
    candidates = analysis["shots"][0]["routing_decision"]["candidates"]
    assert candidates[0]["selected"] is True
    assert candidates[1]["selected"] is False
    assert "selected_references" not in candidates[0]
    assert candidates[1]["hard_reasons"] == ["preset_output_resolution_mismatch"]
    print("routing analysis: PASS")


if __name__ == "__main__":
    main()
