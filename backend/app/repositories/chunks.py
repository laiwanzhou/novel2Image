import uuid

from sqlalchemy import func, select

from app.models.novel import Chapter, ChapterChunk
from app.repositories.base import BaseRepository
from app.services.chunking_service import ChunkDraft


class ChunkSearchRow:
    def __init__(
        self,
        *,
        id: uuid.UUID,
        chapter_id: uuid.UUID,
        chapter_index: int,
        chunk_index: int,
        text: str,
        distance: float,
    ) -> None:
        self.id = id
        self.chapter_id = chapter_id
        self.chapter_index = chapter_index
        self.chunk_index = chunk_index
        self.text = text
        self.distance = distance


class ChunkRepository(BaseRepository[ChapterChunk]):
    def get_chapter(self, chapter_id: uuid.UUID) -> Chapter | None:
        return self.session.get(Chapter, chapter_id)

    def get_chapter_by_index(self, novel_id: uuid.UUID, chapter_index: int) -> Chapter | None:
        statement = select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.chapter_index == chapter_index,
        )
        return self.session.scalar(statement)

    def list_chunks_for_chapter(self, chapter_id: uuid.UUID) -> list[ChapterChunk]:
        statement = (
            select(ChapterChunk)
            .where(ChapterChunk.chapter_id == chapter_id)
            .order_by(ChapterChunk.chunk_index)
        )
        return list(self.session.scalars(statement))

    def list_chunk_previews_for_chapter(self, chapter_id: uuid.UUID) -> list[ChapterChunk]:
        return self.list_chunks_for_chapter(chapter_id)

    def count_chunks_for_novel(self, novel_id: uuid.UUID) -> int:
        statement = select(func.count()).select_from(ChapterChunk).where(ChapterChunk.novel_id == novel_id)
        return int(self.session.scalar(statement) or 0)

    def count_embedded_chunks_for_novel(self, novel_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(ChapterChunk)
            .where(ChapterChunk.novel_id == novel_id, ChapterChunk.embedding.is_not(None))
        )
        return int(self.session.scalar(statement) or 0)

    def list_chunks_by_ids(self, chunk_ids: list[uuid.UUID]) -> list[ChapterChunk]:
        if not chunk_ids:
            return []
        statement = select(ChapterChunk).where(ChapterChunk.id.in_(chunk_ids))
        chunks = {chunk.id: chunk for chunk in self.session.scalars(statement)}
        return [chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks]

    def list_chunks_for_chapter_window(
        self,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        window: int,
    ) -> list[ChapterChunk]:
        statement = (
            select(ChapterChunk)
            .where(
                ChapterChunk.novel_id == novel_id,
                ChapterChunk.chapter_index >= chapter_index - window,
                ChapterChunk.chapter_index <= chapter_index + window,
            )
            .order_by(ChapterChunk.chapter_index, ChapterChunk.chunk_index)
        )
        return list(self.session.scalars(statement))

    def replace_chunks_for_chapter(
        self,
        *,
        novel_id,
        chapter_id,
        chapter_index: int,
        chunks: list[ChunkDraft],
    ) -> list[ChapterChunk]:
        self.session.query(ChapterChunk).filter(ChapterChunk.chapter_id == chapter_id).delete()
        records = [
            ChapterChunk(
                novel_id=novel_id,
                chapter_id=chapter_id,
                chapter_index=chapter_index,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                char_count=chunk.char_count,
                token_count=chunk.token_count,
                checksum=chunk.checksum,
                meta={},
            )
            for chunk in chunks
        ]
        self.session.add_all(records)
        self.session.flush()
        return records

    def list_chunks_missing_embeddings(self, novel_id: uuid.UUID, limit: int) -> list[ChapterChunk]:
        statement = (
            select(ChapterChunk)
            .where(ChapterChunk.novel_id == novel_id, ChapterChunk.embedding.is_(None))
            .order_by(ChapterChunk.chapter_index, ChapterChunk.chunk_index)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def update_embeddings(self, chunk_embeddings: list[tuple[uuid.UUID, list[float]]]) -> None:
        for chunk_id, embedding in chunk_embeddings:
            chunk = self.session.get(ChapterChunk, chunk_id)
            if chunk is not None:
                chunk.embedding = embedding
        self.session.flush()

    def search_by_embedding(
        self,
        *,
        novel_id: uuid.UUID,
        query_embedding: list[float],
        chapter_index: int | None,
        window: int,
        limit: int,
    ) -> list[ChunkSearchRow]:
        distance = ChapterChunk.embedding.l2_distance(query_embedding).label("distance")
        statement = (
            select(
                ChapterChunk.id,
                ChapterChunk.chapter_id,
                ChapterChunk.chapter_index,
                ChapterChunk.chunk_index,
                ChapterChunk.text,
                distance,
            )
            .where(ChapterChunk.novel_id == novel_id, ChapterChunk.embedding.is_not(None))
            .order_by(distance, ChapterChunk.chapter_index, ChapterChunk.chunk_index)
            .limit(limit)
        )
        if chapter_index is not None:
            statement = statement.where(
                ChapterChunk.chapter_index >= chapter_index - window,
                ChapterChunk.chapter_index <= chapter_index + window,
            )
        rows = self.session.execute(statement).all()
        return [
            ChunkSearchRow(
                id=row.id,
                chapter_id=row.chapter_id,
                chapter_index=row.chapter_index,
                chunk_index=row.chunk_index,
                text=row.text,
                distance=float(row.distance),
            )
            for row in rows
        ]
