from __future__ import annotations

import threading

from .config import settings
from .logging_utils import get_logger, log_event

logger = get_logger(__name__)

_stop = threading.Event()
_tick_lock = threading.Lock()
_thread: threading.Thread | None = None


def poll_once() -> dict:
    from .video_generation_service import poll_pending_jobs

    if not _tick_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "previous_tick_running"}
    try:
        result = poll_pending_jobs()
        log_event(logger, "video.poll.tick", **result)
        return result
    finally:
        _tick_lock.release()


def _run() -> None:
    interval = max(1, int(settings.video_poll_interval_seconds or 10))
    log_event(logger, "video.poll.started", interval_seconds=interval)
    if _stop.wait(interval):
        log_event(logger, "video.poll.stopped")
        return
    while not _stop.is_set():
        try:
            poll_once()
        except Exception:
            logger.exception("video.poll.tick_failed")
        if _stop.wait(interval):
            break
    log_event(logger, "video.poll.stopped")


def start_video_poll_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="video-poll-scheduler", daemon=True)
    _thread.start()


def stop_video_poll_scheduler() -> None:
    _stop.set()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
