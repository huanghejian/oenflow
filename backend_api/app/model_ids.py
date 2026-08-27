from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "pipeline_runtime" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from model_ids import (  # noqa: E402
    CANONICAL_MODELS,
    MODEL_ALIASES,
    PROMPT_COMPILER_BY_MODEL,
    canonicalize_model_id,
    resolve_model_config,
)

__all__ = [
    "CANONICAL_MODELS",
    "MODEL_ALIASES",
    "PROMPT_COMPILER_BY_MODEL",
    "canonicalize_model_id",
    "resolve_model_config",
]
