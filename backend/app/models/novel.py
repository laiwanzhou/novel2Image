import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Novel(Base, TimestampMixin):
    __tablename__ = "novels"
    __table_args__ = (CheckConstraint("source_type IN ('txt', 'epub', 'markdown', 'manifest')", name="ck_novels_source_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="zh", nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata_json", JSONB, default=dict, nullable=False)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chapter(Base, TimestampMixin):
    __tablename__ = "chapters"
    __table_args__ = (Index("ix_chapters_novel_chapter_index", "novel_id", "chapter_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)


class ChapterChunk(Base, TimestampMixin):
    __tablename__ = "chapter_chunks"
    __table_args__ = (Index("ix_chapter_chunks_novel_chapter_chunk", "novel_id", "chapter_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chapters.id"), nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    meta: Mapped[dict] = mapped_column("metadata_json", JSONB, default=dict, nullable=False)
