from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any, Protocol

import httpx


class LlmProvider(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


class FakeLlmProvider:
    """Deterministic structured-output provider for tests and local development."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"events": [], "state_changes": []}
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))
        return self.response


PostJson = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class FastGptLlmProvider:
    """OpenAI-compatible chat completions provider for FastGPT workflows."""

    def __init__(
        self,
        *,
        api_base: str | None,
        api_key: str | None,
        model: str | None,
        timeout: float = 60.0,
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
        self.timeout = timeout
        self._post_json = post_json or self._httpx_post_json

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
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
        parsed = self._parse_json_content(content)
        self._validate_extraction_schema(parsed)
        return parsed

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("FastGPT LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("FastGPT LLM response content is empty")
        return content

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fenced_match:
            cleaned = fenced_match.group(1).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("FastGPT LLM response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("FastGPT LLM response JSON must be an object")
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
) -> LlmProvider:
    if name == "fake":
        return FakeLlmProvider()
    if name == "fastgpt":
        return FastGptLlmProvider(api_base=api_base, api_key=api_key, model=model)
    raise ValueError(f"Unsupported LLM provider: {name}")
