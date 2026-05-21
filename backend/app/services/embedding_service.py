import uuid

from app.providers.embeddings import EmbeddingProvider
from app.repositories.chunks import ChunkRepository


class EmbeddingService:
    def __init__(self, chunk_repository: ChunkRepository, provider: EmbeddingProvider) -> None:
        self.chunk_repository = chunk_repository
        self.provider = provider

    def embed_missing_chunks(self, novel_id: uuid.UUID, batch_size: int = 64) -> int:
        total = 0
        while True:
            chunks = self.chunk_repository.list_chunks_missing_embeddings(novel_id, limit=batch_size)
            if not chunks:
                return total
            embeddings = self.provider.embed_texts([chunk.text for chunk in chunks])
            self.chunk_repository.update_embeddings(
                [(chunk.id, embedding) for chunk, embedding in zip(chunks, embeddings, strict=True)]
            )
            total += len(chunks)
