from __future__ import annotations

from app.demo_service import (
    DEBUG_STAGES,
    demo_debug_artifact_path,
    load_demo_case,
    load_demo_debug_stage,
    load_demo_tier,
)


def main() -> None:
    demo = load_demo_case()
    plan = demo["director_plan"]
    assert demo["llm"]["provider"] == "local_demo"
    assert len(plan["atomic_shots"]) == 49
    assert plan["scene_contexts"]
    assert plan["atomic_shots"][0]["prompt_core"]["timeline_local"]

    for tier in ("low", "medium", "high"):
        compiled = load_demo_tier(tier)
        assert compiled["validation"]["ok"] is True
        assert len(compiled["final_video_plan"]["shots"]) == 49
        routes = compiled["routing_analysis"]["shots"]
        assert len(routes) == 49
        assert routes[0]["routing_decision"]["candidates"]
        assert any(
            candidate.get("selected")
            for candidate in routes[0]["routing_decision"]["candidates"]
        )
    for stage in DEBUG_STAGES:
        debug = load_demo_debug_stage(stage, "medium")
        assert debug["summary"]
        assert debug["preview"]
        assert debug["output_size_bytes"] > 0
        assert demo_debug_artifact_path(stage, "medium").is_file()
    print("local demo: A plan + 3 tiers + 6 independent debug stages PASS")


if __name__ == "__main__":
    main()
