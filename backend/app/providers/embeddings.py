import hashlib
from typing import Protocol


EMBEDDING_DIMENSIONS = 1536


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbeddingProvider:
    """Deterministic 1536-dimensional embedding provider for tests and local development."""

    dimensions = EMBEDDING_DIMENSIONS

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < self.dimensions:
            for byte in digest:
                values.append((byte / 255.0) - 0.5)
                if len(values) == self.dimensions:
                    break
            digest = hashlib.sha256(digest).digest()
        return values


def get_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "fake":
        return FakeEmbeddingProvider()
    raise ValueError(f"Unsupported embedding provider: {name}")
