from __future__ import annotations

from app.contracts import DirectorRequest
from app import main


def run() -> None:
    captured: dict = {}

    def fake_create(payload: dict, director_prompt: str | None = None):
        captured["payload"] = payload
        captured["prompt"] = director_prompt
        return {"routing_tier": "medium", "atomic_shots": []}, {"provider": "test"}

    original = main.create_director_plan
    main.create_director_plan = fake_create
    try:
        request = DirectorRequest(
            director_prompt="本次自定义导演规则",
            user_params={"routing_tier": "medium"},
            registered_assets={"scenes": [], "roles": [], "props": []},
            script={"episode_id": "EP-test", "content": "测试剧本"},
        )
        response = main.director_plan(request)
    finally:
        main.create_director_plan = original

    assert captured["prompt"] == "本次自定义导演规则"
    assert "director_prompt" not in captured["payload"]
    assert response["llm"]["provider"] == "test"
    print("director prompt override: PASS")


if __name__ == "__main__":
    run()
