import pytest

from app.providers.llm import FastGptLlmProvider, get_llm_provider


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
            },
            "timeout": 60.0,
        }
    ]


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
    )

    assert isinstance(provider, FastGptLlmProvider)
