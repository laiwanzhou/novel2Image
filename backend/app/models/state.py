import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedTimestampMixin, uuid_pk


class CharacterEvent(Base, TimestampMixin):
    __tablename__ = "character_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('appearance', 'identity', 'relationship', 'motivation', 'other')", name="ck_character_events_event_type"),
        CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_events_status"),
        Index("ix_character_events_novel_character_chapter_status", "novel_id", "character_id", "chapter_index", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chapters.id"), nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_long_term_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    affected_fields: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[float | None]
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_events.id"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_events.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)


class CharacterStateChange(Base, TimestampMixin):
    __tablename__ = "character_state_changes"
    __table_args__ = (CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_state_changes_status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_events.id"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chapters.id"), nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_fields: Mapped[list[dict]] = mapped_column("changed_fields_json", JSONB, default=list, nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[float | None]
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)


class CharacterState(Base, UpdatedTimestampMixin):
    __tablename__ = "character_states"
    __table_args__ = (
        CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_states_status"),
        CheckConstraint("chapter_end IS NULL OR chapter_end >= chapter_start", name="ck_character_states_valid_range"),
        Index("ix_character_states_novel_character_range_status", "novel_id", "character_id", "chapter_start", "chapter_end", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"), nullable=False)
    chapter_start: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_end: Mapped[int | None] = mapped_column(Integer)
    appearance: Mapped[str | None] = mapped_column(Text)
    personality: Mapped[str | None] = mapped_column(Text)
    identity: Mapped[str | None] = mapped_column(Text)
    motivation: Mapped[str | None] = mapped_column(Text)
    relationship_summary: Mapped[str | None] = mapped_column(Text)
    visual_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    source_chapters: Mapped[list[int]] = mapped_column(JSONB, default=list, nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_events.id"))
    state_change_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_state_changes.id"))
    confidence: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_states.id"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_states.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
