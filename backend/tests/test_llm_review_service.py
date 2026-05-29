from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.states import StateRepository
from app.services.llm_review_service import LlmReviewService
from app.services.state_service import StateService


class FakeReviewProvider:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response or {
            "decision": "needs_human",
            "confidence": 0.5,
            "reason": "uncertain",
            "risk_flags": ["ambiguous"],
        }
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate_review_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.response


def test_llm_reviewer_confirms_high_confidence_state_change_when_apply_enabled(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(pg_session, {"decision": "confirm", "confidence": 0.91, "reason": "durable", "risk_flags": []})

    decision = service.review_state_change_candidate(fixture.state_change.id, auto_apply=True, confidence_threshold=0.85)

    assert decision.decision == "confirm"
    assert decision.applied is True
    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.CONFIRMED.value
    assert fixture.state_change.reviewed_by == "llm-reviewer"
    assert fixture.state_change.reviewed_at is not None
    assert "decision=confirm" in fixture.state_change.review_note
    assert "confidence=0.91" in fixture.state_change.review_note
    assert "reason=durable" in fixture.state_change.review_note
    assert _count_rows(pg_session, CharacterState) == 1
    pg_session.refresh(fixture.event)
    assert fixture.event.status == ReviewStatus.CONFIRMED.value


def test_llm_reviewer_rejects_high_confidence_state_change_when_apply_enabled(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(
        pg_session,
        {
            "decision": "reject",
            "confidence": 0.95,
            "reason": "temporary emotion only",
            "risk_flags": ["temporary_state"],
        },
    )

    decision = service.review_state_change_candidate(fixture.state_change.id, auto_apply=True, confidence_threshold=0.85)

    assert decision.decision == "reject"
    assert decision.applied is True
    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.REJECTED.value
    assert fixture.state_change.reviewed_by == "llm-reviewer"
    assert "decision=reject" in fixture.state_change.review_note
    assert "risk_flags=temporary_state" in fixture.state_change.review_note
    assert _count_rows(pg_session, CharacterState) == 1


def test_llm_reviewer_keeps_low_confidence_state_change_candidate(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(pg_session, {"decision": "confirm", "confidence": 0.4, "reason": "weak", "risk_flags": []})

    decision = service.review_state_change_candidate(fixture.state_change.id, auto_apply=True, confidence_threshold=0.85)

    assert decision.applied is False
    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.CANDIDATE.value
    assert fixture.state_change.reviewed_by is None


def test_llm_reviewer_keeps_needs_human_candidate_even_with_apply(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(
        pg_session,
        {"decision": "needs_human", "confidence": 0.99, "reason": "important ambiguity", "risk_flags": ["ambiguous"]},
    )

    decision = service.review_state_change_candidate(fixture.state_change.id, auto_apply=True, confidence_threshold=0.85)

    assert decision.applied is False
    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.CANDIDATE.value
    assert fixture.state_change.reviewed_by is None


def test_llm_reviewer_dry_run_does_not_modify_database(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(pg_session, {"decision": "confirm", "confidence": 0.99, "reason": "supported", "risk_flags": []})

    decision = service.review_state_change_candidate(fixture.state_change.id, auto_apply=False, confidence_threshold=0.85)

    assert decision.applied is False
    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.CANDIDATE.value
    assert fixture.state_change.reviewed_by is None


def test_llm_reviewer_rejects_invalid_llm_response_without_modifying_database(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    service = _review_service(pg_session, {"decision": "approve", "confidence": 0.99, "reason": "bad", "risk_flags": []})

    with pytest.raises(ValueError, match="Invalid review decision"):
        service.review_state_change_candidate(fixture.state_change.id, auto_apply=True, confidence_threshold=0.85)

    pg_session.refresh(fixture.state_change)
    assert fixture.state_change.status == ReviewStatus.CANDIDATE.value
    assert fixture.state_change.reviewed_by is None


def test_llm_reviewer_batch_reviews_candidate_state_changes(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    provider = FakeReviewProvider({"decision": "needs_human", "confidence": 0.7, "reason": "uncertain", "risk_flags": []})
    service = _review_service(pg_session, provider=provider)

    decisions = service.batch_review_state_changes(
        novel_id=fixture.novel.id,
        chapter_id=fixture.chapter.id,
        auto_apply=True,
        limit=1,
        confidence_threshold=0.85,
    )

    assert [decision.target_id for decision in decisions] == [fixture.state_change.id]
    assert decisions[0].decision == "needs_human"
    assert decisions[0].applied is False
    assert len(provider.calls) == 1


def test_llm_reviewer_prompt_contains_evidence_event_and_current_state(pg_session: Session) -> None:
    fixture = _create_review_fixture(pg_session)
    provider = FakeReviewProvider({"decision": "confirm", "confidence": 0.9, "reason": "supported", "risk_flags": []})
    service = _review_service(pg_session, provider=provider)

    service.review_state_change_candidate(fixture.state_change.id)

    system_prompt, user_prompt = provider.calls[0]
    assert "valid JSON" in system_prompt
    assert "confirm|reject|needs_human" in system_prompt
    assert str(fixture.state_change.id) in user_prompt
    assert str(fixture.event.id) in user_prompt
    assert str(fixture.chunk.id) in user_prompt
    assert "outer disciple" in user_prompt
    assert "inner disciple" in user_prompt


class ReviewFixture:
    def __init__(
        self,
        *,
        novel: Novel,
        chapter: Chapter,
        chunk: ChapterChunk,
        character: Character,
        event: CharacterEvent,
        state_change: CharacterStateChange,
    ) -> None:
        self.novel = novel
        self.chapter = chapter
        self.chunk = chunk
        self.character = character
        self.event = event
        self.state_change = state_change


def _review_service(pg_session: Session, response: dict | None = None, provider: FakeReviewProvider | None = None) -> LlmReviewService:
    return LlmReviewService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
        character_repository=CharacterRepository(pg_session),
        state_service=StateService(StateRepository(pg_session)),
        llm_provider=provider or FakeReviewProvider(response),
    )


def _create_review_fixture(pg_session: Session) -> ReviewFixture:
    novel = Novel(
        title="Review Novel",
        source_type="markdown",
        language="zh",
        meta={},
        imported_at=datetime.now(UTC),
    )
    pg_session.add(novel)
    pg_session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        chapter_index=2,
        title="Chapter 2",
        content="Lin Qing is accepted into the inner sect.",
        summary="Lin Qing's identity changes.",
        word_count=9,
        checksum="review-chapter-2",
    )
    character = Character(
        novel_id=novel.id,
        canonical_name="Lin Qing",
        status=ReviewStatus.CONFIRMED.value,
        source_chunk_ids=[],
    )
    pg_session.add_all([chapter, character])
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel.id,
        chapter_id=chapter.id,
        chapter_index=2,
        chunk_index=1,
        text="Lin Qing is accepted into the inner sect and receives a new robe.",
        start_char=0,
        end_char=66,
        char_count=66,
        token_count=66,
        checksum="review-chunk-2-1",
        meta={},
    )
    pg_session.add(chunk)
    pg_session.flush()
    event = CharacterEvent(
        novel_id=novel.id,
        character_id=character.id,
        chapter_id=chapter.id,
        chapter_index=2,
        event_summary="Lin Qing joins the inner sect.",
        event_type="identity",
        is_long_term_change=True,
        affected_fields=["identity"],
        source_chunk_ids=[str(chunk.id)],
        status=ReviewStatus.CONFIRMED.value,
    )
    state = CharacterState(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        chapter_end=None,
        appearance="green robe",
        personality="quiet",
        identity="outer disciple",
        motivation="train hard",
        relationship_summary="alone",
        visual_keywords=["green robe"],
        negative_prompt="modern clothing",
        source_chapters=[1],
        source_chunk_ids=[str(chunk.id)],
        status=ReviewStatus.CONFIRMED.value,
    )
    pg_session.add_all([event, state])
    pg_session.flush()
    state_change = CharacterStateChange(
        novel_id=novel.id,
        character_id=character.id,
        event_id=event.id,
        chapter_id=chapter.id,
        chapter_index=2,
        changed_fields=[
            {
                "field": "identity",
                "before": "outer disciple",
                "after": "inner disciple",
                "source_chunk_ids": [str(chunk.id)],
            }
        ],
        source_chunk_ids=[str(chunk.id)],
        confidence=0.88,
        explanation="The chapter explicitly changes his sect status.",
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(state_change)
    pg_session.commit()
    return ReviewFixture(
        novel=novel,
        chapter=chapter,
        chunk=chunk,
        character=character,
        event=event,
        state_change=state_change,
    )


def _count_rows(pg_session: Session, model: type) -> int:
    return pg_session.scalar(select(func.count()).select_from(model)) or 0
