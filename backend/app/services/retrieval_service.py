from dataclasses import dataclass
import uuid

from app.providers.embeddings import EmbeddingProvider
from app.repositories.chunks import ChunkRepository


@dataclass(frozen=True)
class RetrievedChunk:
    id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_index: int
    chunk_index: int
    text: str
    distance: float


class RetrievalService:
    def __init__(self, chunk_repository: ChunkRepository, embedding_provider: EmbeddingProvider) -> None:
        self.chunk_repository = chunk_repository
        self.embedding_provider = embedding_provider

    def search_chunks(
        self,
        novel_id: uuid.UUID,
        query: str,
        chapter_index: int | None = None,
        window: int = 1,
        limit: int = 8,
    ) -> list[RetrievedChunk]:
        [query_embedding] = self.embedding_provider.embed_texts([query])
        rows = self.chunk_repository.search_by_embedding(
            novel_id=novel_id,
            query_embedding=query_embedding,
            chapter_index=chapter_index,
            window=window,
            limit=limit,
        )
        return [
            RetrievedChunk(
                id=row.id,
                chapter_id=row.chapter_id,
                chapter_index=row.chapter_index,
                chunk_index=row.chunk_index,
                text=row.text,
                distance=row.distance,
            )
            for row in rows
        ]
