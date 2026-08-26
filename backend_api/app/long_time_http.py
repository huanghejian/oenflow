from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .logging_utils import get_logger, log_payload


# 与 Java LongTimeHttp 保持一致。
CONNECT_TIMEOUT_SECONDS = 60.0
READ_TIMEOUT_SECONDS = 30.0 * 60.0
WRITE_TIMEOUT_SECONDS = 100.0
POOL_TIMEOUT_SECONDS = 60.0
MAX_CONNECTIONS = 64
KEEPALIVE_MINUTES = 16
logger = get_logger(__name__)


class LongTimeHttpError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}; {body or 'empty response'}")


_transport = httpx.HTTPTransport(retries=1)
_client = httpx.Client(
    transport=_transport,
    timeout=httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=READ_TIMEOUT_SECONDS,
        write=WRITE_TIMEOUT_SECONDS,
        pool=POOL_TIMEOUT_SECONDS,
    ),
    limits=httpx.Limits(
        max_connections=MAX_CONNECTIONS,
        max_keepalive_connections=MAX_CONNECTIONS,
        keepalive_expiry=KEEPALIVE_MINUTES * 60.0,
    ),
)


def _post_with_connection_retry(
    url: str, content: bytes, headers: dict[str, str]
) -> httpx.Response:
    for attempt in range(2):
        try:
            return _client.post(url, content=content, headers=headers)
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            message = str(exc).lower()
            disconnected_before_response = (
                "disconnected without sending a response" in message
                or "server disconnected" in message
            )
            if attempt == 0 and disconnected_before_response:
                # 与 OkHttp retryOnConnectionFailure(true) 对齐：连接池中的旧连接
                # 被远端静默关闭时，httpcore 会淘汰它，第二次调用建立新连接。
                continue
            raise
    raise RuntimeError("LongTimeHttp connection retry exhausted")


def post_json(
    url: str,
    payload: dict[str, Any],
    token: str,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    request_headers = dict(headers or {})
    request_headers.setdefault("Authorization", token)
    request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    started_at = time.perf_counter()
    log_payload(
        logger,
        "http.post_json.request",
        {"url": url, "headers": request_headers, "payload": payload},
    )

    try:
        response = _post_with_connection_retry(
            url,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            request_headers,
        )
    except httpx.TimeoutException as exc:
        logger.exception("http.post_json.timeout url=%s", url)
        raise RuntimeError(
            f"LongTimeHttp 等待超时（connect={CONNECT_TIMEOUT_SECONDS}s, "
            f"read={READ_TIMEOUT_SECONDS}s, write={WRITE_TIMEOUT_SECONDS}s）"
        ) from exc
    except httpx.TransportError as exc:
        logger.exception("http.post_json.transport_error url=%s", url)
        raise RuntimeError(f"LongTimeHttp 连接失败: {exc}") from exc

    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if not response.is_success:
        log_payload(
            logger,
            "http.post_json.error_response",
            {
                "url": url,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "body": response.text,
            },
        )
        raise LongTimeHttpError(response.status_code, response.text[:2000])
    try:
        data = response.json()
    except ValueError as exc:
        logger.exception("http.post_json.non_json_response url=%s", url)
        raise RuntimeError("LongTimeHttp 收到非 JSON 响应") from exc
    if not isinstance(data, dict):
        raise RuntimeError("LongTimeHttp 响应顶层必须是 JSON 对象")
    log_payload(
        logger,
        "http.post_json.response",
        {
            "url": url,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "response_id": response.headers.get("x-request-id"),
            "body": data,
        },
    )
    return data, response.headers.get("x-request-id")
