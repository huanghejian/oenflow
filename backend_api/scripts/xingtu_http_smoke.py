from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


def load_local_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="星图 5.0 Pro 直接 HTTP 文生图测试")
    parser.add_argument("prompt")
    parser.add_argument("--output", required=True)
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--size", default=None)
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    load_local_env(backend_root / ".env")
    api_key = os.environ.get("XINGTU_IMAGE_API_KEY", "").strip()
    endpoint = os.environ.get(
        "XINGTU_IMAGE_ENDPOINT",
        "https://ark.cn-beijing.volces.com/api/v3/images/generations",
    ).strip()
    model = os.environ.get("XINGTU_IMAGE_MODEL", "doubao-seedream-5-0-pro-260628").strip()
    size = (args.size or os.environ.get("XINGTU_IMAGE_SIZE", "2K")).strip().upper()
    verify_ssl = os.environ.get("XINGTU_IMAGE_VERIFY_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not api_key:
        raise RuntimeError("未配置 XINGTU_IMAGE_API_KEY")

    payload = {
        "model": model,
        "prompt": f"【图片比例{args.ratio}】{args.prompt}",
        "watermark": False,
        "response_format": "url",
        "size": size,
        "output_format": "jpeg",
    }
    print("POST", endpoint)
    print("请求参数:", json.dumps(payload, ensure_ascii=False))
    started = time.perf_counter()
    with httpx.Client(timeout=300.0, follow_redirects=True, verify=verify_ssl, trust_env=False) as client:
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        print("HTTP状态:", response.status_code)
        if response.status_code >= 400:
            raise RuntimeError(response.text[:1000])
        body = response.json()
        data = body.get("data") or []
        if not data:
            raise RuntimeError("响应中没有 data")
        item = data[0]
        if item.get("url"):
            image_url = str(item["url"])
            parsed_url = urlparse(image_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise RuntimeError("响应图片 URL 无效")
            image_response = client.get(image_url, timeout=120.0)
            image_response.raise_for_status()
            image_bytes = image_response.content
        elif item.get("b64_json"):
            image_bytes = base64.b64decode(item["b64_json"], validate=True)
        else:
            raise RuntimeError("data[0] 中没有 url 或 b64_json")

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image_bytes)
    elapsed = time.perf_counter() - started
    print("模型:", model)
    print("耗时秒:", round(elapsed, 1))
    print("图片字节:", len(image_bytes))
    print("已保存:", output)
    print("usage:", json.dumps(body.get("usage") or {}, ensure_ascii=False))


if __name__ == "__main__":
    main()
