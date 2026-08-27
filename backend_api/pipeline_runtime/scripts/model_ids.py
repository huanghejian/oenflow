#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical video model IDs and backward-compatible aliases."""
from __future__ import annotations

from typing import Any, Dict

CANONICAL_MODELS = ("h3", "xingguang-3.0", "xingguang-3.5", "wan3")

MODEL_ALIASES = {
    "h3": "h3",
    "higgsfield-h3": "h3",
    "minimax-h3": "h3",
    "xingdou-3.0": "h3",
    "xingguang-3.0": "xingguang-3.0",
    "seedance-2.0": "xingguang-3.0",
    "doubao-seedance-2.0": "xingguang-3.0",
    "xingguang-3.5": "xingguang-3.5",
    "seedance-2.5": "xingguang-3.5",
    "doubao-seedance-2-5-260628": "xingguang-3.5",
    "wan3": "wan3",
    "wan-3.0": "wan3",
    "wan3.0": "wan3",
    "wan3.0-video": "wan3",
}

PROMPT_COMPILER_BY_MODEL = {
    "h3": "h3",
    "xingguang-3.0": "s20",
    "xingguang-3.5": "s25",
    "wan3": "wan",
}


def canonicalize_model_id(model: Any) -> str:
    text = str(model or "").strip()
    if not text:
        return ""
    return MODEL_ALIASES.get(text, MODEL_ALIASES.get(text.lower(), text))


def resolve_model_config(
    registry: Dict[str, Any], model: Any
) -> tuple[str, Dict[str, Any]]:
    canonical = canonicalize_model_id(model)
    config = registry.get(canonical)
    if not isinstance(config, dict):
        config = registry.get(str(model or "").strip())
        if isinstance(config, dict):
            return canonicalize_model_id(model) or str(model), config
        raise KeyError(canonical or str(model))
    return canonical, config
