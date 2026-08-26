from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .config import settings


REQUEST_ID_HEADER = "x-request-id"
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_configured = False


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> contextvars.Token[str]:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    previous_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        record.request_id = get_request_id()
        return record

    logging.setLogRecordFactory(record_factory)
    log_format = (
        "%(asctime)s %(levelname)s "
        "[%(name)s] [request_id=%(request_id)s] %(message)s"
    )
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_directory = settings.work_root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_handlers.append(
        logging.FileHandler(log_directory / "backend.log", encoding="utf-8")
    )
    logging.basicConfig(
        level=os.environ.get("BACKEND_LOG_LEVEL", "INFO").upper(),
        format=log_format,
        handlers=log_handlers,
        force=True,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(authorization|token|api[_-]?key|secret|password)", key_text, re.I):
                redacted[key_text] = "***REDACTED***"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def compact_summary(value: Any, *, max_text: int = 1200) -> str:
    text = json.dumps(_redact(_jsonable(value)), ensure_ascii=False, default=str)
    if len(text) <= max_text:
        return text
    return f"{text[:max_text]}... <truncated {len(text) - max_text} chars>"


def log_payload(
    logger: logging.Logger,
    event: str,
    payload: Any,
    *,
    level: int = logging.INFO,
) -> Path | None:
    """Log a compact payload summary and persist the full JSON debug artifact."""
    safe_payload = _redact(_jsonable(payload))
    path = _write_debug_artifact(event, safe_payload)
    logger.log(
        level,
        "%s summary=%s%s",
        event,
        compact_summary(safe_payload),
        f" dump={path}" if path else "",
    )
    return path


def log_event(
    logger: logging.Logger,
    event: str,
    **fields: Any,
) -> None:
    logger.info("%s %s", event, compact_summary(fields))


def _write_debug_artifact(event: str, payload: Any) -> Path | None:
    if os.environ.get("BACKEND_DEBUG_DUMP", "1").strip().lower() in {"0", "false", "no"}:
        return None
    safe_event = re.sub(r"[^A-Za-z0-9_.-]+", "_", event).strip("_") or "event"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    directory = settings.work_root / "debug_logs" / get_request_id()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp}_{time.perf_counter_ns()}_{safe_event}.json"
    path.write_text(
        json.dumps(
            {
                "event": event,
                "request_id": get_request_id(),
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path
