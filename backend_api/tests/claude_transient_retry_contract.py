from __future__ import annotations

from app.autoflow_service import (
    _is_transient_claude_failure,
    _post_claude_autoflow_with_retry,
)
from app.long_time_http import LongTimeHttpError


class TransientThenSuccess:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise LongTimeHttpError(
                500,
                '{"message":"Claude 服务错误: Bedrock API 调用失败: '
                'Bedrock API 返回 503: {\\"message\\":\\"Bedrock is unable to process your request.\\"}"}',
            )
        return {"ok": True}, "response-test"


def main() -> None:
    nested_503 = LongTimeHttpError(
        500,
        'Bedrock API 返回 503: {"message":"Bedrock is unable to process your request."}',
    )
    assert _is_transient_claude_failure(nested_503)
    assert _is_transient_claude_failure(LongTimeHttpError(503, "busy"))
    assert not _is_transient_claude_failure(LongTimeHttpError(400, "bad request"))

    fake = TransientThenSuccess()
    sleeps: list[float] = []
    data, response_id, retries = _post_claude_autoflow_with_retry(
        "https://example.test/converse",
        {"messages": []},
        "Bearer test",
        proxy_url=None,
        force_direct=True,
        post_func=fake,
        sleep_func=sleeps.append,
    )
    assert data == {"ok": True}
    assert response_id == "response-test"
    assert retries == 2
    assert fake.calls == 3
    assert sleeps == [2.0, 6.0]

    print("claude transient retry contract: PASS")


if __name__ == "__main__":
    main()
