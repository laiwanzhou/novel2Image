import pytest

from app.providers.llm import FastGptLlmProvider, get_llm_provider, repair_json_content


def test_repair_json_content_accepts_plain_json_object() -> None:
    repaired, notes = repair_json_content('{"events": [], "state_changes": []}')

    assert repaired == '{"events": [], "state_changes": []}'
    assert notes == []


def test_repair_json_content_extracts_markdown_fenced_json() -> None:
    repaired, notes = repair_json_content('```json\n{"events": [], "state_changes": []}\n```')

    assert repaired == '{"events": [], "state_changes": []}'
    assert notes == ["stripped_code_fence"]


def test_repair_json_content_extracts_object_from_surrounding_text() -> None:
    repaired, notes = repair_json_content('Here is json:\n{"events": [{"text": "a { brace }"}], "state_changes": []}\nDone.')

    assert repaired == '{"events": [{"text": "a { brace }"}], "state_changes": []}'
    assert notes == ["extracted_json_object", "removed_surrounding_text"]


def test_repair_json_content_handles_nested_objects_and_arrays() -> None:
    repaired, _ = repair_json_content('prefix {"events": [{"nested": {"ok": true}}], "state_changes": []} suffix')

    assert repaired == '{"events": [{"nested": {"ok": true}}], "state_changes": []}'


def test_repair_json_content_rejects_truncated_json() -> None:
    with pytest.raises(ValueError, match="complete JSON object"):
        repair_json_content('{"events": [{"event_summary": "unfinished')


def test_repair_json_content_rejects_multiple_top_level_objects() -> None:
    with pytest.raises(ValueError, match="multiple JSON objects"):
        repair_json_content('{"events": [], "state_changes": []} {"events": [], "state_changes": []}')


def test_repair_json_content_rejects_non_object_json() -> None:
    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=lambda url, *, headers, payload, timeout: {"choices": [{"message": {"content": "[]"}}]},
    )

    with pytest.raises(ValueError, match="JSON must be an object"):
        provider.generate_json("system", "user")


def test_fastgpt_provider_posts_openai_compatible_chat_completion_request() -> None:
    calls = []

    def post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {
            "choices": [
                {
                    "message": {
                        "content": """
                        {
                          "events": [
                            {
                              "character_id": "00000000-0000-0000-0000-000000000001",
                              "chapter_index": 1,
                              "event_summary": "Talia enters the ruins.",
                              "event_type": "motivation",
                              "is_long_term_change": true,
                              "affected_fields": ["motivation"],
                              "source_chunk_ids": ["00000000-0000-0000-0000-000000000101"],
                              "confidence": 0.8,
                              "explanation": "The chunk states her goal."
                            }
                          ],
                          "state_changes": []
                        }
                        """
                    }
                }
            ]
        }

    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=post_json,
    )

    result = provider.generate_json("system text", "user text")

    assert result["events"][0]["event_summary"] == "Talia enters the ruins."
    assert calls == [
        {
            "url": "https://fastgpt.example.com/api/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer test-key",
                "Content-Type": "application/json",
            },
            "payload": {
                "model": "workflow-model",
                "messages": [
                    {"role": "system", "content": "system text"},
                    {"role": "user", "content": "user text"},
                ],
                "temperature": 0,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            },
            "timeout": 180.0,
        }
    ]


def test_fastgpt_provider_adds_json_mode_and_max_tokens_when_enabled() -> None:
    calls = []

    def post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
        calls.append({"payload": payload, "timeout": timeout})
        return {"choices": [{"message": {"content": '{"events": [], "state_changes": []}'}}]}

    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        json_mode=True,
        max_tokens=4096,
        timeout=180,
        post_json=post_json,
    )

    provider.generate_json("system json", "user json")

    assert calls == [
        {
            "payload": {
                "model": "workflow-model",
                "messages": [
                    {"role": "system", "content": "system json"},
                    {"role": "user", "content": "user json"},
                ],
                "temperature": 0,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            },
            "timeout": 180,
        }
    ]


def test_fastgpt_provider_omits_json_mode_when_disabled_but_keeps_max_tokens() -> None:
    calls = []

    def post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"events": [], "state_changes": []}'}}]}

    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        json_mode=False,
        max_tokens=2048,
        post_json=post_json,
    )

    provider.generate_json("system", "user")

    assert calls[0]["max_tokens"] == 2048
    assert "response_format" not in calls[0]


def test_fastgpt_provider_rejects_empty_content() -> None:
    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=lambda url, *, headers, payload, timeout: {"choices": [{"message": {"content": ""}}]},
    )

    with pytest.raises(ValueError, match="content is empty"):
        provider.generate_json("system", "user")


def test_fastgpt_provider_accepts_fenced_json_response() -> None:
    def post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": """```json
                        {
                          "events": [],
                          "state_changes": [
                            {
                              "character_id": "00000000-0000-0000-0000-000000000001",
                              "event_index": null,
                              "changed_fields": [
                                {
                                  "field": "identity",
                                  "after": "ruin heir",
                                  "source_chunk_ids": ["00000000-0000-0000-0000-000000000101"]
                                }
                              ],
                              "source_chunk_ids": ["00000000-0000-0000-0000-000000000101"],
                              "confidence": 0.7,
                              "explanation": "The chunk identifies her."
                            }
                          ]
                        }
                        ```"""
                    }
                }
            ]
        }

    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api/",
        api_key="test-key",
        model="workflow-model",
        post_json=post_json,
    )

    result = provider.generate_json("system", "user")

    assert result["state_changes"][0]["changed_fields"][0]["after"] == "ruin heir"


def test_fastgpt_provider_rejects_non_json_response() -> None:
    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=lambda url, *, headers, payload, timeout: {"choices": [{"message": {"content": "not json"}}]},
    )

    with pytest.raises(ValueError, match="valid JSON"):
        provider.generate_json("system", "user")


def test_fastgpt_provider_wraps_http_errors() -> None:
    def post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
        raise RuntimeError("503 unavailable")

    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=post_json,
    )

    with pytest.raises(ValueError, match="request failed"):
        provider.generate_json("system", "user")


@pytest.mark.parametrize(
    ("api_base", "api_key", "model"),
    [
        ("", "test-key", "workflow-model"),
        ("https://fastgpt.example.com/api", "", "workflow-model"),
        ("https://fastgpt.example.com/api", "test-key", ""),
    ],
)
def test_fastgpt_provider_rejects_missing_configuration(api_base: str, api_key: str, model: str) -> None:
    with pytest.raises(ValueError, match="requires"):
        FastGptLlmProvider(api_base=api_base, api_key=api_key, model=model)


def test_fastgpt_provider_rejects_missing_required_schema_keys() -> None:
    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=lambda url, *, headers, payload, timeout: {"choices": [{"message": {"content": '{"events":[]}'}}]},
    )

    with pytest.raises(ValueError, match="events and state_changes"):
        provider.generate_json("system", "user")


def test_fastgpt_provider_rejects_outputs_without_source_chunks() -> None:
    provider = FastGptLlmProvider(
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        post_json=lambda url, *, headers, payload, timeout: {
            "choices": [
                {
                    "message": {
                        "content": """
                        {
                          "events": [
                            {
                              "character_id": "00000000-0000-0000-0000-000000000001",
                              "event_summary": "Missing source chunks"
                            }
                          ],
                          "state_changes": []
                        }
                        """
                    }
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="source_chunk_ids"):
        provider.generate_json("system", "user")


def test_get_llm_provider_builds_fastgpt_provider() -> None:
    provider = get_llm_provider(
        "fastgpt",
        api_base="https://fastgpt.example.com/api",
        api_key="test-key",
        model="workflow-model",
        json_mode=True,
        max_tokens=4096,
        timeout_seconds=180,
    )

    assert isinstance(provider, FastGptLlmProvider)
    assert provider.json_mode is True
    assert provider.max_tokens == 4096
    assert provider.timeout == 180
