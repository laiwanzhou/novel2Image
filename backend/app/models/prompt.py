import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class PromptGeneration(Base, TimestampMixin):
    __tablename__ = "prompt_generations"
    __table_args__ = (
        CheckConstraint("prompt_type IN ('character', 'scene')", name="ck_prompt_generations_prompt_type"),
        Index("ix_prompt_generations_novel_chapter_character", "novel_id", "chapter_index", "character_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    novel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chapters.id"), nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"))
    character_state_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("character_states.id"))
    prompt_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_request: Mapped[str | None] = mapped_column(Text)
    final_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(100))
    model_params: Mapped[dict] = mapped_column("model_params_json", JSONB, default=dict, nullable=False)
    used_event_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    used_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    warnings: Mapped[list[dict]] = mapped_column("warnings_json", JSONB, default=list, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column("evidence_snapshot_json", JSONB, default=dict, nullable=False)


class GeneratedImage(Base, TimestampMixin):
    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = uuid_pk()
    prompt_generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prompt_generations.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100))
    image_uri: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[str | None] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column("params_json", JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class ReviewAction(Base, TimestampMixin):
    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column("before_json", JSONB)
    after: Mapped[dict | None] = mapped_column("after_json", JSONB)
    actor: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
