from __future__ import annotations

import json
import re
from typing import Any

from .config import settings


ASSET_DATA_PATHS = (
    settings.work_root / "autoflow_assets" / "latest_prompts.json",
    settings.work_root / "autoflow_assets" / "latest.json",
    settings.work_root / "autoflow_assets" / "latest_identify.json",
)


def _asset_ids(item: dict[str, Any]) -> list[str]:
    values = [item.get("id"), item.get("gid"), item.get("asset_id")]
    return [str(value) for value in values if value]


URL_FIELDS = ("url", "public_url", "image_url")


def _collect_asset_metadata(
    container: Any,
    names: dict[str, str],
    records: dict[str, dict[str, Any]],
) -> None:
    if isinstance(container, dict):
        assets = container.get("assets")
        if isinstance(assets, dict):
            for key in ("characters", "scenes", "items"):
                _collect_asset_metadata(assets.get(key), names, records)
        elif isinstance(assets, list):
            _collect_asset_metadata(assets, names, records)
        raw_prompt_result = container.get("asset_prompt_result")
        if isinstance(raw_prompt_result, dict):
            _collect_asset_metadata(raw_prompt_result, names, records)
        name = str(container.get("name") or "").strip()
        asset_ids = _asset_ids(container)
        if name:
            for asset_id in asset_ids:
                names.setdefault(asset_id, name)
        if asset_ids:
            record = {
                key: value
                for key, value in container.items()
                if key not in {"assets", "asset_prompt_result"} and value is not None
            }
            for asset_id in asset_ids:
                existing = records.setdefault(asset_id, {})
                for key, value in record.items():
                    existing.setdefault(key, value)
    elif isinstance(container, list):
        for item in container:
            _collect_asset_metadata(item, names, records)


def _load_asset_index() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    names: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    for path in ASSET_DATA_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        _collect_asset_metadata(data, names, records)
    return names, records


def _has_url(record: dict[str, Any]) -> bool:
    return any(str(record.get(key) or "").strip() for key in URL_FIELDS)


def _url_binding(record: dict[str, Any]) -> dict[str, Any] | None:
    if not _has_url(record):
        return None
    source = str(
        record.get("public_url")
        or record.get("url")
        or record.get("image_url")
        or ""
    ).strip()
    if not source:
        return None
    return {
        **record,
        "url": source,
        "public_url": source,
        "image_url": source,
    }


def _remote_score(value: Any) -> int:
    text = str(value or "")
    if text.startswith(("http://", "https://")):
        return 2
    if text:
        return 1
    return 0


def _is_remote_binding(binding: dict[str, Any] | None) -> bool:
    if not binding:
        return False
    return any(_remote_score(binding.get(key)) == 2 for key in URL_FIELDS)


def _merge_bindings(*bindings: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for binding in bindings:
        if not binding:
            continue
        for key, value in binding.items():
            if value is None:
                continue
            if key in URL_FIELDS and _remote_score(value) >= _remote_score(merged.get(key)):
                merged[key] = value
            else:
                merged.setdefault(key, value)
    return merged or None


def _lookup_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("·基础状态", "").replace("基础状态", "")
    return re.sub(r"[\s·_\-:：/\\（）()]+", "", text)


def _registry_lookup_by_name(
    asset_id: str,
    asset_registry: dict[str, dict[str, Any]],
    asset_names: dict[str, str],
    asset_records: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    terms = [asset_id, asset_names.get(asset_id), asset_records.get(asset_id, {}).get("name")]
    normalized_terms = [_lookup_text(term) for term in terms if term]
    for term in terms:
        if term and asset_registry.get(str(term)):
            return asset_registry[str(term)]
    for key, record in asset_registry.items():
        record_text = " ".join(
            str(record.get(field) or "")
            for field in ("asset_id", "original_filename", "name")
        )
        key_text = _lookup_text(f"{key} {record_text}")
        if any(term and (term in key_text or key_text in term) for term in normalized_terms):
            return record
    return None


def _derived_role(ref: dict[str, Any]) -> str:
    if _is_entry_reference(ref):
        return "entry"
    if _is_exit_reference(ref):
        return "exit"
    return ""


def _registry_lookup_derived(
    shot: dict[str, Any],
    ref: dict[str, Any],
    asset_registry: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    role = _derived_role(ref)
    if not role:
        return None
    candidates = [
        f"shotref::{shot.get('shot_id')}::{role}",
        f"shotref::{shot.get('group_id')}::{role}",
    ]
    for candidate in candidates:
        if asset_registry.get(candidate):
            return asset_registry[candidate]
    shot_id = str(shot.get("shot_id") or "")
    for record in asset_registry.values():
        if str(record.get("shot_id") or "") == shot_id and str(record.get("generated_role") or "") == role:
            return record
    return None


def _find_binding(
    shot: dict[str, Any],
    ref: dict[str, Any],
    asset_registry: dict[str, dict[str, Any]],
    asset_names: dict[str, str],
    asset_records: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    asset_id = str(ref.get("asset_id") or "")
    registry_binding = (
        asset_registry.get(asset_id)
        or _registry_lookup_derived(shot, ref, asset_registry)
        or _registry_lookup_by_name(asset_id, asset_registry, asset_names, asset_records)
    )
    return _merge_bindings(
        registry_binding,
        _url_binding(asset_records.get(asset_id, {})),
        _url_binding(ref),
    )


def _is_entry_reference(ref: dict[str, Any]) -> bool:
    text = " ".join(
        str(ref.get(key) or "")
        for key in ("asset_id", "derived_role", "purpose", "generated_role")
    ).lower()
    return "entry" in text or "开始" in text or "开场" in text


def _is_exit_reference(ref: dict[str, Any]) -> bool:
    text = " ".join(
        str(ref.get(key) or "")
        for key in ("asset_id", "derived_role", "purpose", "generated_role")
    ).lower()
    return "exit" in text or "结束" in text or "尾帧" in text


def _ordered_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entry = [ref for ref in references if _is_entry_reference(ref)]
    exit_refs = [ref for ref in references if _is_exit_reference(ref)]
    first_refs = entry[:1] + exit_refs[:1]
    first_ids = {id(ref) for ref in first_refs}
    return first_refs + [ref for ref in references if id(ref) not in first_ids]


def _display_name(ref: dict[str, Any], asset_names: dict[str, str]) -> str:
    asset_id = str(ref.get("logical_asset_id") or ref.get("asset_id") or "")
    return (
        asset_names.get(asset_id)
        or str(ref.get("name") or ref.get("display_name") or ref.get("original_filename") or asset_id)
    )


def _image_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        ref
        for ref in references
        if str(ref.get("media_type") or "image").startswith("image")
    ]


def _replace_asset_tokens(prompt: str, image_refs: list[dict[str, Any]]) -> str:
    result = prompt
    replacements: list[tuple[str, str]] = []
    for ref in image_refs:
        asset_id = str(ref.get("logical_asset_id") or ref.get("asset_id") or "").strip()
        if not asset_id or asset_id.startswith("shotref::"):
            continue
        label = ref.get("picture_label") or f"图片{ref.get('picture_index')}"
        replacements.append((asset_id, f"{ref.get('display_name') or asset_id}(@{label})"))
    for asset_id, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"\[{re.escape(asset_id)}\]", replacement, result)
        result = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(asset_id)}(?![A-Za-z0-9_])",
            replacement,
            result,
        )
    return result


def _prompt_uses_asset(prompt: str, asset_id: str) -> bool:
    if not asset_id:
        return False
    return bool(
        re.search(rf"\[{re.escape(asset_id)}\]", prompt)
        or re.search(rf"(?<![A-Za-z0-9_]){re.escape(asset_id)}(?![A-Za-z0-9_])", prompt)
    )


def _video_prompt(prompt: str, image_refs: list[dict[str, Any]]) -> str:
    result = _replace_asset_tokens(prompt, image_refs).strip()
    if not result.startswith("开场画面："):
        result = f"开场画面：复刻开场画面(@图片1)。\n{result}"
    exit_line = "结束画面：复刻结束画面(@图片2)。"
    if exit_line not in result:
        match = re.search(r"\n限制[:：]", result)
        if match:
            result = f"{result[:match.start()]}\n{exit_line}{result[match.start():]}"
        else:
            result = f"{result}\n{exit_line}"
    return result


def _prepare_provider_prompt_and_references(
    shot: dict[str, Any],
    bound_references: list[dict[str, Any]],
    asset_names: dict[str, str],
) -> tuple[str, list[dict[str, Any]]]:
    ordered = _ordered_references(bound_references)
    image_index = 0
    prepared: list[dict[str, Any]] = []
    for ref in ordered:
        item = dict(ref)
        item["display_name"] = _display_name(item, asset_names)
        if str(item.get("media_type") or "image").startswith("image"):
            image_index += 1
            item["picture_index"] = image_index
            item["picture_label"] = f"图片{image_index}"
        prepared.append(item)
    prompt = _video_prompt(str(shot.get("prompt_zh") or ""), _image_references(prepared))
    return prompt, prepared


def bind_logical_assets(
    final_video_plan: dict[str, Any], asset_registry: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    asset_names, asset_records = _load_asset_index()

    for shot in final_video_plan.get("shots", []):
        bound_references = []
        missing_required = []
        missing_derived = []
        prompt_zh = str(shot.get("prompt_zh") or "")
        for ref in shot.get("references", []):
            asset_id = str(ref.get("asset_id") or "")
            if not ref.get("derived") and not _prompt_uses_asset(prompt_zh, asset_id):
                continue
            binding = _find_binding(shot, ref, asset_registry, asset_names, asset_records)
            if not binding:
                if ref.get("derived"):
                    missing_derived.append(asset_id)
                    continue
                if ref.get("required"):
                    missing_required.append(asset_id)
                continue
            if ref.get("derived") and not _is_remote_binding(binding):
                missing_derived.append(asset_id)
                continue
            bound_ref = dict(ref)
            bound_ref["logical_asset_id"] = asset_id
            for key, value in binding.items():
                if value is None:
                    continue
                if key == "asset_id":
                    bound_ref["binding_asset_id"] = value
                else:
                    bound_ref[key] = value
            bound_ref["asset_id"] = asset_id
            bound_ref["binding_status"] = "bound"
            bound_references.append(bound_ref)

        if missing_required or missing_derived:
            status = "asset_binding_missing" if missing_required else "reference_image_generation_pending"
            blocked.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "status": status,
                    "missing_required_asset_ids": missing_required,
                    "missing_derived_reference_ids": missing_derived,
                    **({"reference_image_plan": shot.get("reference_image_plan")} if missing_derived else {}),
                }
            )
            continue

        prompt, ordered_references = _prepare_provider_prompt_and_references(
            shot, bound_references, asset_names
        )
        provider_payload = {
            "shot_id": shot.get("shot_id"),
            "model": shot.get("model"),
            "model_params": shot.get("model_params"),
            "duration": shot.get("duration"),
            "prompt": prompt,
            "references": ordered_references,
        }
        ready.append(
            {
                "shot_id": shot.get("shot_id"),
                "status": "ready_for_provider_adapter",
                "provider_payload": provider_payload,
            }
        )

    return {
        "ready_count": len(ready),
        "blocked_count": len(blocked),
        "ready": ready,
        "blocked": blocked,
        "reference_image_jobs": final_video_plan.get("reference_image_jobs", []),
    }
