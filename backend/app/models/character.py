import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UpdatedTimestampMixin, uuid_pk


class Character(Base, UpdatedTimestampMixin):
    __tablename__ = "characters"
    __table_args__ = (
        CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_characters_status"),
        Index("ix_characters_novel_status", "novel_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[float | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)


class CharacterAlias(Base, UpdatedTimestampMixin):
    __tablename__ = "character_aliases"
    __table_args__ = (
        CheckConstraint("alias_type IN ('name', 'title', 'nickname', 'disguise', 'unknown')", name="ck_character_aliases_alias_type"),
        CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_aliases_status"),
        Index("ix_character_aliases_novel_alias_status", "novel_id", "alias_text", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"))
    alias_text: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    context_excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None]
    merge_suggestion: Mapped[dict] = mapped_column("merge_suggestion_json", JSONB, default=dict, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
