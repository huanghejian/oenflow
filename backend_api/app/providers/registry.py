from __future__ import annotations

from ..model_ids import canonicalize_model_id
from .base import VideoModelService
from .dashscope_video import Wan3VideoService
from .h3_video import H3VideoService
from .topenrouter_video import Xingguang30VideoService, Xingguang35VideoService

VIDEO_MODEL_SERVICES: dict[str, type[VideoModelService]] = {
    "h3": H3VideoService,
    "xingguang-3.0": Xingguang30VideoService,
    "xingguang-3.5": Xingguang35VideoService,
    "wan3": Wan3VideoService,
}


def service_for(model: str) -> VideoModelService:
    canonical = canonicalize_model_id(model)
    service_cls = VIDEO_MODEL_SERVICES.get(canonical)
    if service_cls is None:
        raise ValueError(f"不支持的视频模型: {model}")
    return service_cls()
