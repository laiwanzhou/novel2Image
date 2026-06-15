from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any, Protocol

import httpx


class LlmProviderResponseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        parsed_response: dict[str, Any] | None = None,
        provider_name: str | None = None,
        model: str | None = None,
        repair_notes: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.parsed_response = parsed_response
        self.provider_name = provider_name
        self.model = model
        self.repair_notes = repair_notes or []


class LlmProvider(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...

    def generate_review_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


class FakeLlmProvider:
    """Deterministic structured-output provider for tests and local development."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"events": [], "state_changes": []}
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))
        return self.response

    def generate_review_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))
        return self.response


PostJson = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def repair_json_content(content: str) -> tuple[str, list[str]]:
    cleaned = content.strip()
    notes: list[str] = []
    fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()
        notes.append("stripped_code_fence")

    try:
        json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    else:
        return cleaned, notes

    spans = _json_object_spans(cleaned)
    if len(spans) > 1:
        raise ValueError("FastGPT LLM response contains multiple JSON objects")
    if not spans:
        raise ValueError("FastGPT LLM response must be valid JSON and contain a complete JSON object")

    start, end = spans[0]
    candidate = cleaned[start:end]
    if start != 0 or cleaned[end:].strip():
        notes.extend(["extracted_json_object", "removed_surrounding_text"])
    return candidate, notes


def _json_object_spans(value: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    in_string = False
    escape = False
    depth = 0
    start: int | None = None
    for index, char in enumerate(value):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    return spans


class FastGptLlmProvider:
    """OpenAI-compatible chat completions provider for FastGPT workflows."""

    def __init__(
        self,
        *,
        api_base: str | None,
        api_key: str | None,
        model: str | None,
        timeout: float = 180.0,
        json_mode: bool = True,
        max_tokens: int | None = 4096,
        post_json: PostJson | None = None,
    ) -> None:
        if not api_base:
            raise ValueError("FastGPT LLM provider requires NOVEL_VIS_LLM_API_BASE")
        if not api_key:
            raise ValueError("FastGPT LLM provider requires NOVEL_VIS_LLM_API_KEY")
        if not model:
            raise ValueError("FastGPT LLM provider requires NOVEL_VIS_LLM_MODEL")
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider_name = "fastgpt"
        self.timeout = timeout
        self.json_mode = json_mode
        self.max_tokens = max_tokens
        self._post_json = post_json or self._httpx_post_json

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        parsed = self._generate_parsed_json(system_prompt, user_prompt)
        try:
            self._validate_extraction_schema(parsed)
        except ValueError as exc:
            raise LlmProviderResponseError(
                str(exc),
                parsed_response=parsed,
                provider_name="fastgpt",
                model=self.model,
            ) from exc
        return parsed

    def generate_review_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return self._generate_parsed_json(system_prompt, user_prompt)

    def _generate_parsed_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._post_json(
                f"{self.api_base}/v1/chat/completions",
                headers=headers,
                payload=payload,
                timeout=self.timeout,
            )
        except Exception as exc:
            raise ValueError(f"FastGPT LLM request failed: {exc}") from exc

        content = self._extract_message_content(response)
        return self._parse_json_content(content)

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("FastGPT LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("FastGPT LLM response content is empty")
        return content

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        try:
            cleaned, repair_notes = repair_json_content(content)
        except ValueError as exc:
            raise LlmProviderResponseError(
                str(exc),
                raw_response=content,
                provider_name="fastgpt",
                model=self.model,
            ) from exc
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LlmProviderResponseError(
                "FastGPT LLM response must be valid JSON",
                raw_response=content,
                provider_name="fastgpt",
                model=self.model,
                repair_notes=repair_notes,
            ) from exc
        if not isinstance(parsed, dict):
            raise LlmProviderResponseError(
                "FastGPT LLM response JSON must be an object",
                raw_response=content,
                provider_name="fastgpt",
                model=self.model,
                repair_notes=repair_notes,
            )
        return parsed

    def _validate_extraction_schema(self, parsed: dict[str, Any]) -> None:
        events = parsed.get("events")
        state_changes = parsed.get("state_changes")
        if not isinstance(events, list) or not isinstance(state_changes, list):
            raise ValueError("FastGPT LLM response must contain events and state_changes lists")

        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Each event must be a JSON object")
            self._require_source_chunk_ids(event, "event")

        for state_change in state_changes:
            if not isinstance(state_change, dict):
                raise ValueError("Each state_change must be a JSON object")
            self._require_source_chunk_ids(state_change, "state_change")
            changed_fields = state_change.get("changed_fields")
            if not isinstance(changed_fields, list) or not changed_fields:
                raise ValueError("Each state_change requires non-empty changed_fields")
            for changed_field in changed_fields:
                if not isinstance(changed_field, dict):
                    raise ValueError("Each changed_field must be a JSON object")
                self._require_source_chunk_ids(changed_field, "changed_field")

    def _require_source_chunk_ids(self, value: dict[str, Any], label: str) -> None:
        source_chunk_ids = value.get("source_chunk_ids")
        if not isinstance(source_chunk_ids, list) or not source_chunk_ids:
            raise ValueError(f"{label} requires non-empty source_chunk_ids")

    def _httpx_post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("FastGPT LLM HTTP response JSON must be an object")
        return data


def get_llm_provider(
    name: str,
    *,
    api_base: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    json_mode: bool = True,
    max_tokens: int | None = 4096,
    timeout_seconds: float = 180.0,
) -> LlmProvider:
    if name == "fake":
        return FakeLlmProvider()
    if name == "fastgpt":
        return FastGptLlmProvider(
            api_base=api_base,
            api_key=api_key,
            model=model,
            json_mode=json_mode,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )
    raise ValueError(f"Unsupported LLM provider: {name}")
