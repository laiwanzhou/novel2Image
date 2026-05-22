from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from app.providers.llm import FakeLlmProvider
from app.repositories.chunks import ChunkRepository
from app.repositories.characters import CharacterRepository
from app.repositories.states import StateRepository
from app.services.extraction_service import ExtractionService


def test_fake_llm_extraction_persists_candidate_event_and_state_change(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                    "confidence": 0.92,
                    "explanation": "The chapter explicitly says the sect accepted him.",
                }
            ],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "event_index": 0,
                    "changed_fields": [
                        {
                            "field": "identity",
                            "before": "outer disciple",
                            "after": "inner disciple",
                            "source_chunk_ids": [str(fixture.chunk.id)],
                            "confidence": 0.9,
                        }
                    ],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                    "confidence": 0.9,
                    "explanation": "Identity changes from outer disciple to inner disciple.",
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    result = service.extract_chapter_candidates(fixture.chapter.id)

    assert len(result.events) == 1
    assert len(result.state_changes) == 1
    event = result.events[0]
    state_change = result.state_changes[0]
    assert event.status == ReviewStatus.CANDIDATE.value
    assert event.character_id == fixture.character.id
    assert event.source_chunk_ids == [str(fixture.chunk.id)]
    assert state_change.status == ReviewStatus.CANDIDATE.value
    assert state_change.event_id == event.id
    assert state_change.changed_fields[0]["after"] == "inner disciple"


def test_extraction_rejects_event_without_source_chunks(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "No evidence event.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [],
                    "confidence": 0.2,
                    "explanation": "Missing evidence.",
                }
            ],
            "state_changes": [],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="source_chunk_ids"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_rejects_event_with_chunk_outside_current_chapter(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    outside_chunk = _create_outside_chapter_chunk(pg_session, fixture.novel.id)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(outside_chunk.id)],
                }
            ],
            "state_changes": [],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="current chapter"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_rejects_state_change_without_source_chunks(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "event_index": 0,
                    "changed_fields": [
                        {
                            "field": "identity",
                            "before": "outer disciple",
                            "after": "inner disciple",
                        }
                    ],
                    "source_chunk_ids": [],
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="source_chunk_ids"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_rejects_state_change_with_chunk_outside_current_chapter(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    outside_chunk = _create_outside_chapter_chunk(pg_session, fixture.novel.id)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "event_index": 0,
                    "changed_fields": [
                        {
                            "field": "identity",
                            "before": "outer disciple",
                            "after": "inner disciple",
                            "source_chunk_ids": [str(fixture.chunk.id)],
                        }
                    ],
                    "source_chunk_ids": [str(outside_chunk.id)],
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="current chapter"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_rejects_changed_field_with_chunk_outside_current_chapter(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    outside_chunk = _create_other_novel_chunk(pg_session)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "event_index": 0,
                    "changed_fields": [
                        {
                            "field": "identity",
                            "before": "outer disciple",
                            "after": "inner disciple",
                            "source_chunk_ids": [str(outside_chunk.id)],
                        }
                    ],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="current chapter"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_failure_does_not_persist_partial_event_or_state_change(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    event_count_before = _count_rows(pg_session, CharacterEvent)
    state_change_count_before = _count_rows(pg_session, CharacterStateChange)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing joins the inner sect.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "event_index": 0,
                    "changed_fields": [
                        {
                            "field": "identity",
                            "before": "outer disciple",
                            "after": "inner disciple",
                        }
                    ],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="source_chunk_ids"):
        service.extract_chapter_candidates(fixture.chapter.id)

    pg_session.flush()
    assert _count_rows(pg_session, CharacterEvent) == event_count_before
    assert _count_rows(pg_session, CharacterStateChange) == state_change_count_before


def test_extraction_blocks_unconfirmed_character_from_candidate_outputs(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CANDIDATE.value)
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Candidate character event.",
                    "event_type": "identity",
                    "is_long_term_change": True,
                    "affected_fields": ["identity"],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="confirmed character"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_rejects_invalid_event_type_before_persisting(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    service = _service_for_event_type(pg_session, fixture, "decision")

    with pytest.raises(
        ValueError,
        match=(
            "Invalid event_type from LLM: decision. Allowed values: "
            "appearance, identity, relationship, motivation, other"
        ),
    ):
        service.extract_chapter_candidates(fixture.chapter.id)

    pg_session.flush()
    assert _count_rows(pg_session, CharacterEvent) == 0


@pytest.mark.parametrize("event_type", ["motivation", "other"])
def test_extraction_accepts_supported_event_type(pg_session: Session, event_type: str) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    service = _service_for_event_type(pg_session, fixture, event_type)

    result = service.extract_chapter_candidates(fixture.chapter.id)

    assert len(result.events) == 1
    assert result.events[0].event_type == event_type


def test_extraction_rejects_invalid_changed_field_name(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    provider = FakeLlmProvider(
        response={
            "events": [],
            "state_changes": [
                {
                    "character_id": str(fixture.character.id),
                    "changed_fields": [
                        {
                            "field": "location",
                            "after": "inner hall",
                            "source_chunk_ids": [str(fixture.chunk.id)],
                        }
                    ],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
        }
    )
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    with pytest.raises(ValueError, match="Invalid changed field from LLM: location"):
        service.extract_chapter_candidates(fixture.chapter.id)


def test_extraction_prompt_includes_confirmed_character_ids(pg_session: Session) -> None:
    fixture = _create_extraction_fixture(pg_session, character_status=ReviewStatus.CONFIRMED.value)
    provider = FakeLlmProvider()
    service = ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )

    service.extract_chapter_candidates(fixture.chapter.id)

    assert provider.calls
    user_prompt = provider.calls[0][1]
    assert str(fixture.character.id) in user_prompt
    assert "Lin Qing" in user_prompt
    assert "confirmed_characters" in user_prompt
    system_prompt = provider.calls[0][0]
    assert "json" in system_prompt.lower()
    assert '"events"' in system_prompt
    assert '"state_changes"' in system_prompt
    assert '"source_chunk_ids"' in system_prompt
    assert "confirmed character_id" in system_prompt
    assert '"event_type": "appearance|identity|relationship|motivation|other"' in system_prompt
    assert '"event_type": "identity|motivation|relationship|appearance|personality|encounter|decision|other"' not in system_prompt
    assert "decision" not in system_prompt
    assert "encounter" not in system_prompt
    assert "Use event_type other for discoveries, actions, battles, and dialogue." in system_prompt


class ExtractionFixture:
    def __init__(self, novel: Novel, chapter: Chapter, chunk: ChapterChunk, character: Character) -> None:
        self.novel = novel
        self.chapter = chapter
        self.chunk = chunk
        self.character = character


def _service_for_event_type(pg_session: Session, fixture: ExtractionFixture, event_type: str) -> ExtractionService:
    provider = FakeLlmProvider(
        response={
            "events": [
                {
                    "character_id": str(fixture.character.id),
                    "event_summary": "Lin Qing chooses the next step.",
                    "event_type": event_type,
                    "is_long_term_change": event_type == "motivation",
                    "affected_fields": ["motivation"] if event_type == "motivation" else [],
                    "source_chunk_ids": [str(fixture.chunk.id)],
                }
            ],
            "state_changes": [],
        }
    )
    return ExtractionService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        llm_provider=provider,
    )


def _create_extraction_fixture(pg_session: Session, character_status: str) -> ExtractionFixture:
    novel = Novel(
        title="Test Novel",
        source_type="markdown",
        language="zh",
        meta={},
        imported_at=datetime.now(UTC),
    )
    pg_session.add(novel)
    pg_session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        chapter_index=3,
        title="Chapter 3",
        content="Lin Qing is accepted into the inner sect.",
        summary="Lin Qing's identity changes.",
        word_count=9,
        checksum="chapter-3",
    )
    character = Character(
        novel_id=novel.id,
        canonical_name="Lin Qing",
        status=character_status,
        source_chunk_ids=["chunk-1"],
    )
    pg_session.add_all([chapter, character])
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel.id,
        chapter_id=chapter.id,
        chapter_index=3,
        chunk_index=1,
        text="Lin Qing is accepted into the inner sect.",
        start_char=0,
        end_char=42,
        char_count=42,
        token_count=42,
        checksum="chunk-3-1",
        meta={},
    )
    pg_session.add(chunk)
    pg_session.flush()
    if character_status == ReviewStatus.CONFIRMED.value:
        pg_session.add(
            CharacterState(
                novel_id=novel.id,
                character_id=character.id,
                chapter_start=1,
                chapter_end=None,
                identity="outer disciple",
                visual_keywords=["green robe"],
                source_chapters=[1],
                source_chunk_ids=["chunk-1"],
                status=ReviewStatus.CONFIRMED.value,
            )
        )
    pg_session.commit()
    return ExtractionFixture(novel=novel, chapter=chapter, chunk=chunk, character=character)


def _create_outside_chapter_chunk(pg_session: Session, novel_id) -> ChapterChunk:
    chapter = Chapter(
        novel_id=novel_id,
        chapter_index=4,
        title="Chapter 4",
        content="A different chapter.",
        summary="Different chapter.",
        word_count=3,
        checksum="chapter-4",
    )
    pg_session.add(chapter)
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel_id,
        chapter_id=chapter.id,
        chapter_index=4,
        chunk_index=1,
        text="A different chapter.",
        start_char=0,
        end_char=20,
        char_count=20,
        token_count=20,
        checksum="chunk-4-1",
        meta={},
    )
    pg_session.add(chunk)
    pg_session.commit()
    return chunk


def _create_other_novel_chunk(pg_session: Session) -> ChapterChunk:
    novel = Novel(
        title="Other Novel",
        source_type="markdown",
        language="zh",
        meta={},
        imported_at=datetime.now(UTC),
    )
    pg_session.add(novel)
    pg_session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        chapter_index=1,
        title="Other Chapter",
        content="A different novel.",
        summary="Other novel.",
        word_count=3,
        checksum="other-chapter-1",
    )
    pg_session.add(chapter)
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel.id,
        chapter_id=chapter.id,
        chapter_index=1,
        chunk_index=1,
        text="A different novel.",
        start_char=0,
        end_char=18,
        char_count=18,
        token_count=18,
        checksum="other-chunk-1",
        meta={},
    )
    pg_session.add(chunk)
    pg_session.commit()
    return chunk


def _count_rows(pg_session: Session, model: type) -> int:
    return pg_session.scalar(select(func.count()).select_from(model)) or 0
