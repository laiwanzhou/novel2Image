from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_LLM_DIAGNOSTICS_DIR = BACKEND_ROOT / ".pipeline-runs" / "diagnostics" / "raw-llm-responses"


@dataclass(frozen=True)
class RawLlmDiagnosticsContext:
    chapter_id: uuid.UUID
    chapter_index: int
    system_prompt: str
    user_prompt: str
    allowed_current_chapter_chunk_ids: list[str]
    confirmed_character_ids: list[str]
    provider: str | None = None
    model: str | None = None


class RawLlmResponseDiagnosticsWriter:
    def __init__(self, diagnostics_dir: Path | None = None) -> None:
        self.diagnostics_dir = diagnostics_dir or DEFAULT_RAW_LLM_DIAGNOSTICS_DIR

    def write_failure(
        self,
        *,
        context: RawLlmDiagnosticsContext,
        error: Exception,
        raw_response_text: str | None = None,
        raw_parsed_response: dict[str, Any] | None = None,
        attempt: int | None = None,
    ) -> Path:
        failure_type = classify_llm_failure(error)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"{timestamp}-chapter-{context.chapter_index:04d}-{context.chapter_id}-{failure_type}.json"
        path = self.diagnostics_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(UTC).isoformat(),
            "chapter_id": str(context.chapter_id),
            "chapter_index": context.chapter_index,
            "prompt_hash": _prompt_hash(context.system_prompt, context.user_prompt),
            "provider": context.provider or getattr(error, "provider_name", None),
            "model": context.model or getattr(error, "model", None),
            "failure_type": failure_type,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "allowed_current_chapter_chunk_ids": context.allowed_current_chapter_chunk_ids,
            "confirmed_character_ids": context.confirmed_character_ids,
            "returned_source_chunk_ids": _collect_values(raw_parsed_response, "source_chunk_ids"),
            "returned_character_ids": _collect_values(raw_parsed_response, "character_id"),
        }
        if attempt is not None:
            payload["attempt"] = attempt
        repair_notes = getattr(error, "repair_notes", None)
        if repair_notes:
            payload["repair_notes"] = repair_notes
        if raw_response_text is not None:
            payload["raw_response_text"] = raw_response_text
        if raw_parsed_response is not None:
            payload["raw_parsed_response"] = raw_parsed_response
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def classify_llm_failure(error: Exception) -> str:
    message = str(error).lower()
    if "valid json" in message or "jsondecodeerror" in message:
        return "invalid_json"
    if "source_chunk_ids" in message and "current chapter" in message:
        return "source_chunk_not_current_chapter"
    if "confirmed character" in message or "valid confirmed character" in message:
        return "invalid_character_reference"
    slug = re.sub(r"[^a-z0-9]+", "_", message).strip("_")
    return slug[:80] or "llm_validation_error"


def safe_write_raw_llm_failure(
    writer: RawLlmResponseDiagnosticsWriter | None,
    *,
    context: RawLlmDiagnosticsContext,
    error: Exception,
    raw_response_text: str | None = None,
    raw_parsed_response: dict[str, Any] | None = None,
    attempt: int | None = None,
) -> None:
    if writer is None:
        return
    try:
        writer.write_failure(
            context=context,
            error=error,
            raw_response_text=raw_response_text,
            raw_parsed_response=raw_parsed_response,
            attempt=attempt,
        )
    except Exception:
        return


def _prompt_hash(system_prompt: str, user_prompt: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(system_prompt.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(user_prompt.encode("utf-8"))
    return hasher.hexdigest()


def _collect_values(value: Any, key: str) -> list[Any]:
    collected: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                if isinstance(current_value, list):
                    collected.extend(current_value)
                else:
                    collected.append(current_value)
            else:
                collected.extend(_collect_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            collected.extend(_collect_values(item, key))
    seen: set[str] = set()
    unique: list[Any] = []
    for item in collected:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique
