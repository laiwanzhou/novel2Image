from typing import Any, Protocol


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


def get_llm_provider(name: str) -> LlmProvider:
    if name == "fake":
        return FakeLlmProvider()
    raise ValueError(f"Unsupported LLM provider: {name}")
