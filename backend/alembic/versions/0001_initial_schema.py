"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "novels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_type IN ('txt', 'epub', 'markdown', 'manifest')", name="ck_novels_source_type"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chapters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chapters_novel_chapter_index", "chapters", ["novel_id", "chapter_index"])
    op.create_table(
        "characters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_characters_status"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_characters_novel_status", "characters", ["novel_id", "status"])
    op.create_table(
        "chapter_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1536), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chapter_chunks_novel_chapter_chunk", "chapter_chunks", ["novel_id", "chapter_id", "chunk_index"])
    op.create_table(
        "character_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=True),
        sa.Column("alias_text", sa.String(length=255), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_excerpt", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("merge_suggestion_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("alias_type IN ('name', 'title', 'nickname', 'disguise', 'unknown')", name="ck_character_aliases_alias_type"),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_aliases_status"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_character_aliases_novel_alias_status", "character_aliases", ["novel_id", "alias_text", "status"])
    op.create_table(
        "character_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=True),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("event_summary", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("is_long_term_change", sa.Boolean(), nullable=False),
        sa.Column("affected_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('appearance', 'identity', 'relationship', 'motivation', 'other')", name="ck_character_events_event_type"),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_events_status"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"]),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["merged_into_id"], ["character_events.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["character_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_character_events_novel_character_chapter_status", "character_events", ["novel_id", "character_id", "chapter_index", "status"])
    op.create_table(
        "character_state_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("changed_fields_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_state_changes_status"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"]),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["character_events.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "character_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=False),
        sa.Column("chapter_start", sa.Integer(), nullable=False),
        sa.Column("chapter_end", sa.Integer(), nullable=True),
        sa.Column("appearance", sa.Text(), nullable=True),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column("identity", sa.Text(), nullable=True),
        sa.Column("motivation", sa.Text(), nullable=True),
        sa.Column("relationship_summary", sa.Text(), nullable=True),
        sa.Column("visual_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("source_chapters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("state_change_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("chapter_end IS NULL OR chapter_end >= chapter_start", name="ck_character_states_valid_range"),
        sa.CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="ck_character_states_status"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["character_events.id"]),
        sa.ForeignKeyConstraint(["merged_into_id"], ["character_states.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.ForeignKeyConstraint(["state_change_id"], ["character_state_changes.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["character_states.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_character_states_novel_character_range_status", "character_states", ["novel_id", "character_id", "chapter_start", "chapter_end", "status"])
    op.create_table(
        "prompt_generations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=True),
        sa.Column("character_state_id", sa.UUID(), nullable=True),
        sa.Column("prompt_type", sa.String(length=32), nullable=False),
        sa.Column("user_request", sa.Text(), nullable=True),
        sa.Column("final_prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("model_provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("model_params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("used_event_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("used_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("prompt_type IN ('character', 'scene')", name="ck_prompt_generations_prompt_type"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"]),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["character_state_id"], ["character_states.id"]),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_generations_novel_chapter_character", "prompt_generations", ["novel_id", "chapter_index", "character_id"])
    op.create_table(
        "generated_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("prompt_generation_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("image_uri", sa.Text(), nullable=True),
        sa.Column("seed", sa.String(length=100), nullable=True),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_generation_id"], ["prompt_generations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "review_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("review_actions")
    op.drop_table("generated_images")
    op.drop_index("ix_prompt_generations_novel_chapter_character", table_name="prompt_generations")
    op.drop_table("prompt_generations")
    op.drop_index("ix_character_states_novel_character_range_status", table_name="character_states")
    op.drop_table("character_states")
    op.drop_table("character_state_changes")
    op.drop_index("ix_character_events_novel_character_chapter_status", table_name="character_events")
    op.drop_table("character_events")
    op.drop_index("ix_character_aliases_novel_alias_status", table_name="character_aliases")
    op.drop_table("character_aliases")
    op.drop_index("ix_chapter_chunks_novel_chapter_chunk", table_name="chapter_chunks")
    op.drop_table("chapter_chunks")
    op.drop_index("ix_characters_novel_status", table_name="characters")
    op.drop_table("characters")
    op.drop_index("ix_chapters_novel_chapter_index", table_name="chapters")
    op.drop_table("chapters")
    op.drop_table("novels")
