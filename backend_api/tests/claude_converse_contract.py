from __future__ import annotations

import json

from app.director_service import (
    _bedrock_additional_model_fields,
    _bedrock_converse_url,
    _bedrock_inference_config,
    _check_minimum_contract,
    _extract_claude_text,
    _parse_json_text,
)
from director_contract_fixture import PLAN


def main() -> None:
    raw_plan = json.dumps(PLAN, ensure_ascii=False)
    response_shapes = [
        {
            "output": {
                "message": {
                    "content": [
                        {"reasoningContent": {"reasoningText": {"text": "internal"}}},
                        {"text": raw_plan},
                    ]
                }
            }
        },
        {"content": [{"type": "text", "text": f"```json\n{raw_plan}\n```"}]},
        {"choices": [{"message": {"content": raw_plan}}]},
        {"body": json.dumps({"output_text": raw_plan})},
    ]
    for response in response_shapes:
        parsed = _parse_json_text(_extract_claude_text(response))
        _check_minimum_contract(parsed)
    url = _bedrock_converse_url(
        "http://example.test/v1/claude/converse",
        "global.anthropic.claude-opus-5",
        "us-west-2",
    )
    assert "region=us-west-2" in url
    assert "model=global.anthropic.claude-opus-5" in url
    assert "temperature" not in _bedrock_inference_config(
        128000, "global.anthropic.claude-opus-5"
    )
    assert _bedrock_inference_config(128000, "claude-opus-4")["temperature"] == 0.01
    fields = _bedrock_additional_model_fields(
        "global.anthropic.claude-opus-5", "medium"
    )
    assert fields == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }
    print(f"claude_converse: {len(response_shapes)} response shapes PASS")


if __name__ == "__main__":
    main()
