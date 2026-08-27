from .base import (
    ProviderQueryResult,
    ProviderSubmitPayload,
    ProviderSubmitResult,
    VideoModelService,
)
from .dashscope_video import DashScopeWan3Adapter, Wan3VideoService
from .h3_video import H3VideoAdapter, H3VideoService
from .registry import VIDEO_MODEL_SERVICES, service_for
from .topenrouter_video import (
    TopenRouterXingguangAdapter,
    Xingguang30VideoService,
    Xingguang35VideoService,
    XingguangVideoService,
)

__all__ = [
    "DashScopeWan3Adapter",
    "H3VideoAdapter",
    "H3VideoService",
    "ProviderQueryResult",
    "ProviderSubmitPayload",
    "ProviderSubmitResult",
    "TopenRouterXingguangAdapter",
    "VIDEO_MODEL_SERVICES",
    "VideoModelService",
    "Wan3VideoService",
    "Xingguang30VideoService",
    "Xingguang35VideoService",
    "XingguangVideoService",
    "service_for",
]
