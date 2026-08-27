from __future__ import annotations

import threading

from app import autoflow_service
from app import reference_image_service as service


class _FakeResponse:
    def __init__(self, *, body: dict | None = None, content: bytes = b"", media_type: str = "application/json", status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self._body = body or {}
        self.content = content
        self.headers = {"content-type": media_type}
        self.text = text

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    posted_json: dict | None = None
    posted_payloads: list[dict] = []
    reject_sequential = False

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, *, headers: dict, json: dict):
        assert url.endswith("/api/v3/images/generations")
        assert headers["Authorization"].startswith("Bearer ")
        _FakeClient.posted_json = json
        _FakeClient.posted_payloads.append(json)
        if _FakeClient.reject_sequential and "sequential_image_generation" in json:
            return _FakeResponse(
                status_code=400,
                text='{"error":{"code":"InvalidParameter","message":"sequential_image_generation is not supported"}}',
            )
        return _FakeResponse(body={"data": [{"url": "https://images.example/result.jpeg"}], "usage": {"images": 1}})

    def get(self, url: str, *, timeout: float):
        assert url == "https://images.example/result.jpeg"
        return _FakeResponse(content=b"\xff\xd8\xffmock-jpeg", media_type="image/jpeg")


def main() -> None:
    payload = service._xingtu_request_payload(
        "国漫少年剑客",
        "doubao-seedream-5-0-pro-260628",
        "9:16",
        "2K",
    )
    assert payload == {
        "model": "doubao-seedream-5-0-pro-260628",
        "prompt": "【图片比例9:16】国漫少年剑客",
        "sequential_image_generation": "disabled",
        "watermark": False,
        "response_format": "url",
        "size": "2K",
        "output_format": "jpeg",
    }

    original_client = service.httpx.Client
    original_key = service.settings.xingtu_image_api_key
    try:
        service.httpx.Client = _FakeClient
        object.__setattr__(service.settings, "xingtu_image_api_key", "test-key")
        data, media_type, usage = service._call_xingtu_image(
            "国漫少年剑客",
            "doubao-seedream-5-0-pro-260628",
            "9:16",
            "2K",
        )
    finally:
        service.httpx.Client = original_client
        object.__setattr__(service.settings, "xingtu_image_api_key", original_key)

    assert data.startswith(b"\xff\xd8\xff")
    assert media_type == "image/jpeg"
    assert usage == {"images": 1}
    assert _FakeClient.posted_json == payload

    _FakeClient.posted_payloads = []
    _FakeClient.reject_sequential = True
    try:
        service.httpx.Client = _FakeClient
        object.__setattr__(service.settings, "xingtu_image_api_key", "test-key")
        service._call_xingtu_image(
            "国漫少年剑客",
            "doubao-seedream-5-0-pro-260628",
            "9:16",
            "2K",
        )
    finally:
        service.httpx.Client = original_client
        object.__setattr__(service.settings, "xingtu_image_api_key", original_key)
        _FakeClient.reject_sequential = False
    assert len(_FakeClient.posted_payloads) == 2
    assert "sequential_image_generation" in _FakeClient.posted_payloads[0]
    assert "sequential_image_generation" not in _FakeClient.posted_payloads[1]

    lineart = service._station_lineart_prompt("秦放站在山门中央", "开始")
    assert "黑白干净线描" in lineart
    assert "秦放站在山门中央" in lineart

    original_call = service._call_xingtu_image
    original_save = service._save_generated_image
    barrier = threading.Barrier(2)
    prompts: list[str] = []

    def parallel_call(prompt: str, model: str, aspect_ratio: str, size: str):
        prompts.append(prompt)
        barrier.wait(timeout=2)
        return b"\xff\xd8\xffmock-jpeg", "image/jpeg", {"images": 1}

    try:
        service._call_xingtu_image = parallel_call
        service._save_generated_image = lambda job_id, role, data, media_type: (
            f"/workflow-generated/{job_id}_{role}.jpg",
            "image/jpeg",
        )
        manifest = service.create_reference_image_pair_xingtu_job(
            {
                "episode_id": "TEST",
                "shot_id": "u001",
                "entry_prompt_zh": "开始站位",
                "exit_prompt_zh": "结束站位",
                "aspect_ratio": "9:16",
            }
        )
    finally:
        service._call_xingtu_image = original_call
        service._save_generated_image = original_save

    assert len(prompts) == 2
    assert any("开始站位" in prompt for prompt in prompts)
    assert any("结束站位" in prompt for prompt in prompts)
    assert manifest["generation_strategy"] == "parallel_synchronous_text_to_lineart_pair"
    assert manifest["entry"]["status"] == "completed"
    assert manifest["exit"]["status"] == "completed"

    original_missing = autoflow_service.missing_asset_ids
    original_create_pair = autoflow_service.create_reference_image_pair_xingtu_job
    original_register = autoflow_service.register_reference_pair
    try:
        autoflow_service.missing_asset_ids = lambda ids: ["C01"]
        autoflow_service.create_reference_image_pair_xingtu_job = lambda payload: {
            "shot_id": payload["shot_id"],
            "status": "completed",
            "entry": {"status": "completed", "image_url": "/entry.jpg"},
            "exit": {"status": "completed", "image_url": "/exit.jpg"},
        }
        autoflow_service.register_reference_pair = lambda manifest: {}
        generated = autoflow_service._generate_reference_for_shot(
            "TEST",
            {
                "shot_id": "u001",
                "reference_image_plan": {
                    "input_asset_ids": ["C01"],
                    "output_asset_ids": {"entry": "entry-id", "exit": "exit-id"},
                    "entry_state_reference_prompt_zh": "开始状态",
                    "exit_state_reference_edit_prompt_zh": "结束状态",
                },
            },
            "xingtu",
            "doubao-seedream-5-0-pro-260628",
            "9:16",
        )
    finally:
        autoflow_service.missing_asset_ids = original_missing
        autoflow_service.create_reference_image_pair_xingtu_job = original_create_pair
        autoflow_service.register_reference_pair = original_register
    assert generated["status"] == "completed"
    assert generated["unused_missing_asset_ids"] == ["C01"]
    print("xingtu image contract: PASS")


if __name__ == "__main__":
    main()
