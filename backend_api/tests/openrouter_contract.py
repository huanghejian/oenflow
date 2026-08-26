from __future__ import annotations

import json

from app.director_service import (
    ATOMIC_REQUIRED_FIELDS,
    CANONICAL_DIRECTOR_OUTPUT_SCHEMA,
    DIRECTOR_OUTPUT_SCHEMA,
    _check_minimum_contract,
    _extract_openrouter_text,
    _openrouter_credit_retry_max_tokens,
    _openrouter_reasoning,
    _parse_json_text,
)
from director_contract_fixture import PLAN
from app.long_time_http import LongTimeHttpError


def main() -> None:
    raw_plan = json.dumps(PLAN, ensure_ascii=False)
    response_shapes = [
        {"choices": [{"message": {"content": raw_plan}}]},
        {
            "choices": [
                {
                    "message": {
                        "content": [{"type": "text", "text": raw_plan}],
                        "reasoning_details": [{"type": "reasoning.text", "text": "hidden"}],
                    }
                }
            ]
        },
    ]
    for response in response_shapes:
        parsed = _parse_json_text(
            _extract_openrouter_text(response), "OpenRouter"
        )
        _check_minimum_contract(parsed)
    assert DIRECTOR_OUTPUT_SCHEMA["required"] == ["v", "sc", "sh"]
    schema_required = CANONICAL_DIRECTOR_OUTPUT_SCHEMA["properties"]["atomic_shots"]["items"]["required"]
    assert schema_required == ATOMIC_REQUIRED_FIELDS
    broken = json.loads(raw_plan)
    del broken["atomic_shots"][0]["scene_asset"]
    try:
        _check_minimum_contract(broken)
    except ValueError as exc:
        assert "scene_asset" in str(exc)
    else:
        raise AssertionError("missing scene_asset should fail before pipeline")
    assert _openrouter_reasoning("medium") == {"effort": "medium"}
    credit_error = LongTimeHttpError(
        402,
        "You requested up to 128000 tokens, but can only afford 120613.",
    )
    assert _openrouter_credit_retry_max_tokens(credit_error, 128000) == 108551
    assert _openrouter_credit_retry_max_tokens(
        LongTimeHttpError(500, "server error"), 128000
    ) is None
    print(f"openrouter: {len(response_shapes)} response shapes PASS")


if __name__ == "__main__":
    main()
