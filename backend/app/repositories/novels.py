from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from sqlalchemy import func, select

from app.models.novel import Chapter, ChapterChunk, Novel
from app.repositories.base import BaseRepository
from app.schemas.import_schema import BookManifest


@dataclass(frozen=True)
class ChapterSummaryRow:
    id: uuid.UUID
    title: str
    chapter_index: int
    word_count: int
    chunk_count: int
    embedded_count: int


class NovelRepository(BaseRepository[Novel]):
    def create_from_manifest(self, manifest: BookManifest, source_path: str | None = None) -> Novel:
        novel = Novel(
            title=manifest.title,
            author=manifest.author,
            source_type=manifest.source_type,
            language=manifest.language,
            source_path=source_path,
            meta={},
            imported_at=datetime.now(UTC),
        )
        self.session.add(novel)
        self.session.flush()

        for chapter_input in manifest.chapters:
            self.session.add(
                Chapter(
                    novel_id=novel.id,
                    chapter_index=chapter_input.chapter_index,
                    title=chapter_input.title,
                    content=chapter_input.content,
                    summary=None,
                    source_path=chapter_input.source_path,
                    word_count=chapter_input.word_count,
                    checksum=chapter_input.checksum,
                )
            )
        self.session.flush()
        return novel

    def get_novel(self, novel_id: uuid.UUID) -> Novel | None:
        return self.session.get(Novel, novel_id)

    def list_chapters(self, novel_id) -> list[Chapter]:
        statement = select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_index)
        return list(self.session.scalars(statement))

    def count_chapters(self, novel_id: uuid.UUID) -> int:
        statement = select(func.count()).select_from(Chapter).where(Chapter.novel_id == novel_id)
        return int(self.session.scalar(statement) or 0)

    def list_chapter_summaries(self, novel_id: uuid.UUID) -> list[ChapterSummaryRow]:
        chunk_counts = (
            select(
                ChapterChunk.chapter_id.label("chapter_id"),
                func.count(ChapterChunk.id).label("chunk_count"),
                func.count(ChapterChunk.embedding).label("embedded_count"),
            )
            .where(ChapterChunk.novel_id == novel_id)
            .group_by(ChapterChunk.chapter_id)
            .subquery()
        )
        statement = (
            select(
                Chapter.id,
                Chapter.title,
                Chapter.chapter_index,
                Chapter.word_count,
                func.coalesce(chunk_counts.c.chunk_count, 0),
                func.coalesce(chunk_counts.c.embedded_count, 0),
            )
            .outerjoin(chunk_counts, chunk_counts.c.chapter_id == Chapter.id)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_index)
        )
        return [
            ChapterSummaryRow(
                id=row.id,
                title=row.title,
                chapter_index=row.chapter_index,
                word_count=row.word_count,
                chunk_count=int(row[4]),
                embedded_count=int(row[5]),
            )
            for row in self.session.execute(statement)
        ]
