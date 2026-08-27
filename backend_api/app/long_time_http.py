from __future__ import annotations

import json
import threading
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


def _build_client(
    proxy_url: str | None = None, *, trust_env: bool = False
) -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=1, proxy=proxy_url),
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
        # Proxy behavior is request-controlled. Direct mode must not inherit
        # HTTP_PROXY/HTTPS_PROXY from the process environment.
        trust_env=trust_env,
    )


_client = _build_client(trust_env=True)
_direct_client = _build_client()
_proxy_clients: dict[str, httpx.Client] = {}
_proxy_clients_lock = threading.Lock()


def _proxy_client(proxy_url: str) -> httpx.Client:
    with _proxy_clients_lock:
        client = _proxy_clients.get(proxy_url)
        if client is None:
            client = _build_client(proxy_url)
            _proxy_clients[proxy_url] = client
        return client


def _request_with_connection_retry(
    method: str,
    url: str,
    content: bytes | None,
    headers: dict[str, str],
    client: Any | None = None,
) -> httpx.Response:
    request_client = client or _client
    for attempt in range(2):
        try:
            if hasattr(request_client, "request"):
                return request_client.request(
                    method, url, content=content, headers=headers
                )
            if method.upper() == "POST":
                return request_client.post(url, content=content, headers=headers)
            return request_client.get(url, headers=headers)
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


def _post_with_connection_retry(
    url: str,
    content: bytes,
    headers: dict[str, str],
    client: Any | None = None,
) -> httpx.Response:
    """兼容既有调用；新代码统一使用通用 request 重试函数。"""
    return _request_with_connection_retry("POST", url, content, headers, client)


def post_json(
    url: str,
    payload: dict[str, Any],
    token: str,
    headers: dict[str, str] | None = None,
    proxy_url: str | None = None,
    force_direct: bool = False,
) -> tuple[dict[str, Any], str | None]:
    if not str(url or "").strip() or str(url).strip().upper().startswith("XXX"):
        raise RuntimeError("视频模型提交 endpoint 尚未配置")
    request_headers = dict(headers or {})
    request_headers.setdefault("Authorization", token)
    request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    started_at = time.perf_counter()
    network_mode = "proxy" if proxy_url else "direct" if force_direct else "default"
    log_payload(
        logger,
        "http.post_json.request",
        {
            "url": url,
            "network_mode": network_mode,
            "headers": request_headers,
            "payload": payload,
        },
    )

    try:
        response = _request_with_connection_retry(
            "POST",
            url,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            request_headers,
            _proxy_client(proxy_url)
            if proxy_url
            else _direct_client
            if force_direct
            else _client,
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
            "network_mode": network_mode,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "response_id": response.headers.get("x-request-id"),
            "body": data,
        },
    )
    return data, response.headers.get("x-request-id")


def get_json(
    url: str,
    token: str,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    request_headers = dict(headers or {})
    request_headers.setdefault("Authorization", token)
    request_headers.setdefault("Accept", "application/json")
    started_at = time.perf_counter()
    log_payload(
        logger,
        "http.get_json.request",
        {"url": url, "headers": request_headers},
    )
    try:
        response = _request_with_connection_retry(
            "GET", url, None, request_headers
        )
    except httpx.TimeoutException as exc:
        logger.exception("http.get_json.timeout url=%s", url)
        raise RuntimeError(
            f"LongTimeHttp 等待超时（connect={CONNECT_TIMEOUT_SECONDS}s, "
            f"read={READ_TIMEOUT_SECONDS}s, write={WRITE_TIMEOUT_SECONDS}s）"
        ) from exc
    except httpx.TransportError as exc:
        logger.exception("http.get_json.transport_error url=%s", url)
        raise RuntimeError(f"LongTimeHttp 连接失败: {exc}") from exc

    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if not response.is_success:
        raise LongTimeHttpError(response.status_code, response.text[:2000])
    body_text = (response.text or "").strip()
    if not body_text:
        raise LongTimeHttpError(response.status_code, "empty response")
    try:
        data = response.json()
    except ValueError as exc:
        raise LongTimeHttpError(response.status_code, body_text[:2000]) from exc
    if not isinstance(data, dict):
        raise RuntimeError("LongTimeHttp 响应顶层必须是 JSON 对象")
    log_payload(
        logger,
        "http.get_json.response",
        {
            "url": url,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "response_id": response.headers.get("x-request-id"),
            "body": data,
        },
    )
    return data, response.headers.get("x-request-id")


def bearer(api_key: str | None) -> str:
    key = str(api_key or "").strip()
    if not key or key.upper() == "XXX":
        raise RuntimeError("视频模型 API Key 尚未配置")
    return f"Bearer {key}"


def join_task_url(base_url: str, task_id: str) -> str:
    base = str(base_url or "").strip()
    if not base or base.upper().startswith("XXX"):
        raise RuntimeError("视频模型查询 endpoint 尚未配置")
    if "{taskId}" in base:
        return base.replace("{taskId}", task_id)
    return f"{base.rstrip('/')}/{task_id}"
