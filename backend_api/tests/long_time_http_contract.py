from __future__ import annotations

import httpx

import app.long_time_http as long_http


class StaleThenSuccessClient:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, url: str, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            )
        return httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", url),
        )


def main() -> None:
    original = long_http._client
    fake = StaleThenSuccessClient()
    long_http._client = fake  # type: ignore[assignment]
    try:
        response = long_http._post_with_connection_retry(
            "http://example.test/converse", b"{}", {}
        )
    finally:
        long_http._client = original
    assert response.status_code == 200
    assert fake.calls == 2
    print("long_time_http: stale keep-alive retry PASS")


if __name__ == "__main__":
    main()
