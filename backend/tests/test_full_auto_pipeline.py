from datetime import UTC, datetime
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from scripts.run_full_auto_pipeline import FullAutoPipelineOptions, run_full_auto_pipeline


class SequencedLlmProvider:
    def __init__(self, *, extraction_responses: list[dict], review_responses: list[dict]) -> None:
        self.extraction_responses = extraction_responses
        self.review_responses = review_responses
        self.extraction_calls: list[tuple[str, str]] = []
        self.review_calls: list[tuple[str, str]] = []

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.extraction_calls.append((system_prompt, user_prompt))
        if not self.extraction_responses:
            raise AssertionError("unexpected extraction call")
        return self.extraction_responses.pop(0)

    def generate_review_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.review_calls.append((system_prompt, user_prompt))
        if not self.review_responses:
            raise AssertionError("unexpected review call")
        return self.review_responses.pop(0)


def test_full_auto_skips_existing_extraction_and_auto_confirms_states(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    existing_event = _add_confirmed_event(pg_session, fixture, 1)
    existing_change = _add_candidate_change(pg_session, fixture, 1, existing_event)
    provider = SequencedLlmProvider(
        extraction_responses=[_extraction_response(fixture, 2)],
        review_responses=[
            {"decision": "confirm", "confidence": 0.95, "reason": "durable", "risk_flags": []},
            {"decision": "confirm", "confidence": 0.92, "reason": "durable", "risk_flags": []},
        ],
    )

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=2,
            block_size=1,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            confirm_threshold=0.85,
            reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["processed_chapters"] == [1, 2]
    assert result["skipped_extraction_chapters"] == [1]
    assert len(provider.extraction_calls) == 1
    assert result["state_change_confirmed_count"] == 2
    assert result["synthesized_state_count"] == 2
    assert result["auto_confirmed_state_count"] == 2

    changes = pg_session.scalars(select(CharacterStateChange).order_by(CharacterStateChange.chapter_index)).all()
    assert [change.id for change in changes] == [existing_change.id, changes[1].id]
    assert all(change.status == ReviewStatus.CONFIRMED.value for change in changes)
    assert all(change.reviewed_by == "llm-reviewer" for change in changes)

    first_block_summary = json.loads((tmp_path / "block-001-001" / "block_summary.json").read_text(encoding="utf-8"))
    second_block_summary = json.loads((tmp_path / "block-002-002" / "block_summary.json").read_text(encoding="utf-8"))
    assert first_block_summary["state_change_confirmed_count"] == 1
    assert second_block_summary["state_change_confirmed_count"] == 1

    states = pg_session.scalars(select(CharacterState).order_by(CharacterState.chapter_start, CharacterState.created_at)).all()
    assert len(states) == 3
    assert states[-1].status == ReviewStatus.CONFIRMED.value
    assert states[-1].reviewed_by == "full-auto-pipeline"
    assert (tmp_path / "block-001-001" / "block_summary.json").exists()
    assert (tmp_path / "block-002-002" / "block_boundary_report.json").exists()
    assert (tmp_path / "full_auto_summary.json").exists()
    assert (tmp_path / "full_auto_report.md").exists()


def test_full_auto_logs_normalized_event_types(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    provider = SequencedLlmProvider(
        extraction_responses=[
            {
                "events": [
                    {
                        "character_id": str(fixture.character.id),
                        "event_summary": "Lin Qing discovers a hidden archive.",
                        "event_type": "discovery",
                        "is_long_term_change": False,
                        "affected_fields": [],
                        "source_chunk_ids": [str(fixture.chunks[1].id)],
                        "confidence": 0.8,
                        "explanation": "The chapter shows a discovery.",
                    }
                ],
                "state_changes": [],
            }
        ],
        review_responses=[],
    )

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["failed_chapters"] == []
    event = pg_session.scalar(select(CharacterEvent))
    assert event.event_type == "other"
    assert "original_event_type=discovery" in event.explanation
    chapter_log = (tmp_path / "chapter-0001.jsonl").read_text(encoding="utf-8")
    extraction_payload = json.loads(chapter_log.splitlines()[0])
    assert extraction_payload["normalized_event_types"] == [
        {
            "event_index": 0,
            "original_event_type": "discovery",
            "normalized_event_type": "other",
            "reason": "unknown LLM event_type normalized before persistence",
        }
    ]


def test_full_auto_applies_rejects_but_leaves_needs_human_and_low_confidence_candidate(
    pg_session: Session,
    tmp_path,
) -> None:
    fixture = _create_full_auto_fixture(pg_session, chapter_count=3)
    provider = SequencedLlmProvider(
        extraction_responses=[
            _extraction_response(fixture, 1),
            _extraction_response(fixture, 2),
            _extraction_response(fixture, 3),
        ],
        review_responses=[
            {"decision": "reject", "confidence": 0.95, "reason": "duplicate", "risk_flags": ["duplicate"]},
            {"decision": "needs_human", "confidence": 0.6, "reason": "ambiguous", "risk_flags": []},
            {"decision": "confirm", "confidence": 0.4, "reason": "weak", "risk_flags": []},
        ],
    )

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=3,
            block_size=2,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            confirm_threshold=0.85,
            reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["reviewer_decision_distribution"] == {"confirm": 1, "reject": 1, "needs_human": 1}
    assert result["auto_rejected_state_change_count"] == 1
    assert result["auto_confirmed_state_change_count"] == 0
    assert result["needs_human_count"] == 1
    assert result["low_confidence_remaining_count"] == 1
    assert result["synthesized_state_count"] == 0

    changes = pg_session.scalars(select(CharacterStateChange).order_by(CharacterStateChange.chapter_index)).all()
    assert [change.status for change in changes] == [
        ReviewStatus.REJECTED.value,
        ReviewStatus.CANDIDATE.value,
        ReviewStatus.CANDIDATE.value,
    ]
    assert changes[0].reviewed_by == "llm-reviewer"
    assert changes[1].reviewed_by is None
    assert changes[2].reviewed_by is None


def test_full_auto_does_not_synthesize_same_state_change_twice(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    event = _add_confirmed_event(pg_session, fixture, 1)
    change = _add_confirmed_change(pg_session, fixture, 1, event)
    existing_state = CharacterState(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_start=1,
        chapter_end=None,
        identity="already synthesized",
        motivation="existing",
        relationship_summary="existing",
        visual_keywords=["existing"],
        source_chapters=[1],
        source_chunk_ids=[str(fixture.chunks[1].id)],
        event_id=event.id,
        state_change_id=change.id,
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(existing_state)
    pg_session.commit()
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            confirm_threshold=0.85,
            reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["synthesized_state_count"] == 0
    assert pg_session.scalar(select(func.count()).select_from(CharacterState).where(CharacterState.state_change_id == change.id)) == 1


def test_full_auto_skips_second_confirmed_state_change_for_same_character_chapter(
    pg_session: Session,
    tmp_path,
) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    event = _add_confirmed_event(pg_session, fixture, 1)
    first_change = _add_confirmed_change(pg_session, fixture, 1, event)
    second_change = _add_confirmed_change(pg_session, fixture, 1, event)
    second_change.changed_fields = [
        {
            "field": "motivation",
            "before": "survive",
            "after": "protect allies",
            "source_chunk_ids": [str(fixture.chunks[1].id)],
        }
    ]
    pg_session.commit()
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["synthesis_failure_count"] == 0
    assert result["synthesized_state_count"] == 1
    assert result["synthesis_skipped_same_chapter_count"] == 1
    states = pg_session.scalars(
        select(CharacterState).where(CharacterState.state_change_id.in_([first_change.id, second_change.id]))
    ).all()
    assert len(states) == 1
    chapter_log = (tmp_path / "chapter-0001.jsonl").read_text(encoding="utf-8")
    assert "skipped_same_chapter" in chapter_log


def test_full_auto_synthesis_failure_does_not_rollback_confirmed_state_change(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    existing_initial = pg_session.scalar(
        select(CharacterState).where(
            CharacterState.novel_id == fixture.novel.id,
            CharacterState.character_id == fixture.character.id,
            CharacterState.status == ReviewStatus.CONFIRMED.value,
        )
    )
    assert existing_initial is not None
    existing_initial.chapter_start = 1
    event = _add_confirmed_event(pg_session, fixture, 1)
    change = _add_candidate_change(pg_session, fixture, 1, event)
    pg_session.commit()
    provider = SequencedLlmProvider(
        extraction_responses=[],
        review_responses=[{"decision": "confirm", "confidence": 0.95, "reason": "durable", "risk_flags": []}],
    )

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            confirm_threshold=0.85,
            reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    pg_session.refresh(change)
    assert change.status == ReviewStatus.CONFIRMED.value
    assert change.reviewed_by == "llm-reviewer"
    assert result["synthesis_failure_count"] == 1
    assert result["synthesized_state_count"] == 0


def test_full_auto_auto_seeds_missing_character_state_before_synthesis(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session, with_initial_state=False)
    event = _add_confirmed_event(pg_session, fixture, 1)
    change = _add_confirmed_change(pg_session, fixture, 1, event)
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            auto_seed_missing_character_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["seeded_state_count"] == 1
    assert result["synthesized_state_count"] == 1
    assert result["auto_confirmed_state_count"] == 1
    states = pg_session.scalars(select(CharacterState).order_by(CharacterState.chapter_start, CharacterState.created_at)).all()
    assert len(states) == 2
    seed_state = states[0]
    synthesized_state = states[1]
    assert seed_state.state_change_id is None
    assert seed_state.status == ReviewStatus.CONFIRMED.value
    assert seed_state.reviewed_by == "full-auto-pipeline"
    assert seed_state.review_note == "auto-seeded missing initial CharacterState before synthesis"
    assert seed_state.identity in {fixture.character.canonical_name, "outer disciple"}
    assert synthesized_state.state_change_id == change.id
    assert synthesized_state.status == ReviewStatus.CONFIRMED.value


def test_full_auto_seed_default_off_preserves_missing_latest_state_failure(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session, with_initial_state=False)
    event = _add_confirmed_event(pg_session, fixture, 1)
    _add_confirmed_change(pg_session, fixture, 1, event)
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["seeded_state_count"] == 0
    assert result["synthesis_failure_count"] == 1


def test_full_auto_does_not_duplicate_seed_when_confirmed_state_exists(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session)
    event = _add_confirmed_event(pg_session, fixture, 1)
    _add_confirmed_change(pg_session, fixture, 1, event)
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            auto_seed_missing_character_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["seeded_state_count"] == 0


def test_full_auto_does_not_duplicate_existing_seed(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session, with_initial_state=False)
    seed = CharacterState(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_start=0,
        chapter_end=None,
        identity=fixture.character.canonical_name,
        visual_keywords=[],
        source_chapters=[1],
        source_chunk_ids=[str(fixture.chunks[1].id)],
        status=ReviewStatus.CONFIRMED.value,
        reviewed_at=datetime.now(UTC),
        reviewed_by="full-auto-pipeline",
        review_note="auto-seeded missing initial CharacterState before synthesis",
    )
    pg_session.add(seed)
    event = _add_confirmed_event(pg_session, fixture, 1)
    _add_confirmed_change(pg_session, fixture, 1, event)
    pg_session.commit()
    provider = SequencedLlmProvider(extraction_responses=[], review_responses=[])

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            auto_seed_missing_character_states=True,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["seeded_state_count"] == 0
    assert pg_session.scalar(select(func.count()).select_from(CharacterState)) == 2


def test_full_auto_records_failed_chapter_and_continues(pg_session: Session, tmp_path) -> None:
    fixture = _create_full_auto_fixture(pg_session, chapter_count=2)
    provider = SequencedLlmProvider(
        extraction_responses=[
            {"events": [{"bad": "shape"}], "state_changes": []},
            _extraction_response(fixture, 2),
        ],
        review_responses=[{"decision": "needs_human", "confidence": 0.7, "reason": "check", "risk_flags": []}],
    )

    result = run_full_auto_pipeline(
        pg_session,
        FullAutoPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=2,
            block_size=20,
            auto_confirm_events=True,
            auto_review_state_changes=True,
            auto_apply_reviewer_decisions=True,
            auto_synthesize_states=True,
            auto_confirm_synthesized_states=True,
            confirm_threshold=0.85,
            reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["processed_chapters"] == [2]
    assert result["failed_chapters"][0]["chapter_index"] == 1
    assert result["extraction_failure_count"] == 1
    assert (tmp_path / "chapter-0001.jsonl").exists()
    assert (tmp_path / "chapter-0002.jsonl").exists()


class FullAutoFixture:
    def __init__(self, *, novel: Novel, chapters: list[Chapter], chunks: dict[int, ChapterChunk], character: Character) -> None:
        self.novel = novel
        self.chapters = chapters
        self.chunks = chunks
        self.character = character


def _create_full_auto_fixture(
    pg_session: Session,
    chapter_count: int = 2,
    *,
    with_initial_state: bool = True,
) -> FullAutoFixture:
    novel = Novel(title="Full Auto Novel", source_type="markdown", language="zh", meta={}, imported_at=datetime.now(UTC))
    pg_session.add(novel)
    pg_session.flush()
    character = Character(
        novel_id=novel.id,
        canonical_name="Lin Qing",
        description="main character",
        status=ReviewStatus.CONFIRMED.value,
        source_chunk_ids=[],
    )
    pg_session.add(character)
    pg_session.flush()
    chapters: list[Chapter] = []
    chunks: dict[int, ChapterChunk] = {}
    for index in range(1, chapter_count + 1):
        chapter = Chapter(
            novel_id=novel.id,
            chapter_index=index,
            title=f"Chapter {index}",
            content=f"Chapter {index} content changes Lin Qing.",
            summary=f"Summary {index}",
            word_count=8,
            checksum=f"full-auto-chapter-{index}",
        )
        pg_session.add(chapter)
        pg_session.flush()
        chunk = ChapterChunk(
            novel_id=novel.id,
            chapter_id=chapter.id,
            chapter_index=index,
            chunk_index=1,
            text=f"Lin Qing receives durable chapter {index} identity evidence.",
            start_char=0,
            end_char=60,
            char_count=60,
            token_count=60,
            checksum=f"full-auto-chunk-{index}",
            meta={},
        )
        pg_session.add(chunk)
        chapters.append(chapter)
        chunks[index] = chunk
    if with_initial_state:
        state = CharacterState(
            novel_id=novel.id,
            character_id=character.id,
            chapter_start=0,
            chapter_end=None,
            identity="outer disciple",
            motivation="survive",
            relationship_summary="alone",
            visual_keywords=["robe"],
            source_chapters=[0],
            source_chunk_ids=[str(chunks[1].id)],
            status=ReviewStatus.CONFIRMED.value,
        )
        pg_session.add(state)
    pg_session.commit()
    return FullAutoFixture(novel=novel, chapters=chapters, chunks=chunks, character=character)


def _add_confirmed_event(pg_session: Session, fixture: FullAutoFixture, chapter_index: int) -> CharacterEvent:
    event = CharacterEvent(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_id=fixture.chapters[chapter_index - 1].id,
        chapter_index=chapter_index,
        event_summary=f"Existing durable event {chapter_index}.",
        event_type="identity",
        is_long_term_change=True,
        affected_fields=["identity"],
        source_chunk_ids=[str(fixture.chunks[chapter_index].id)],
        confidence=0.9,
        explanation="Existing evidence.",
        status=ReviewStatus.CONFIRMED.value,
        reviewed_at=datetime.now(UTC),
        reviewed_by="auto-extraction",
        review_note="existing",
    )
    pg_session.add(event)
    pg_session.flush()
    return event


def _add_candidate_change(
    pg_session: Session,
    fixture: FullAutoFixture,
    chapter_index: int,
    event: CharacterEvent,
) -> CharacterStateChange:
    change = CharacterStateChange(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        event_id=event.id,
        chapter_id=fixture.chapters[chapter_index - 1].id,
        chapter_index=chapter_index,
        changed_fields=[
            {
                "field": "identity",
                "before": "outer disciple",
                "after": f"chapter {chapter_index} identity",
                "source_chunk_ids": [str(fixture.chunks[chapter_index].id)],
            }
        ],
        source_chunk_ids=[str(fixture.chunks[chapter_index].id)],
        confidence=0.9,
        explanation="Candidate durable change.",
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(change)
    pg_session.flush()
    return change


def _add_confirmed_change(
    pg_session: Session,
    fixture: FullAutoFixture,
    chapter_index: int,
    event: CharacterEvent,
) -> CharacterStateChange:
    change = _add_candidate_change(pg_session, fixture, chapter_index, event)
    change.status = ReviewStatus.CONFIRMED.value
    change.reviewed_at = datetime.now(UTC)
    change.reviewed_by = "llm-reviewer"
    change.review_note = "existing confirmed"
    pg_session.flush()
    return change


def _extraction_response(fixture: FullAutoFixture, chapter_index: int) -> dict:
    chunk = fixture.chunks[chapter_index]
    return {
        "events": [
            {
                "character_id": str(fixture.character.id),
                "event_summary": f"Lin Qing changes in chapter {chapter_index}.",
                "event_type": "identity",
                "is_long_term_change": True,
                "affected_fields": ["identity"],
                "source_chunk_ids": [str(chunk.id)],
                "confidence": 0.9,
                "explanation": "The chapter explicitly supports a durable change.",
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
                        "after": f"chapter {chapter_index} identity",
                        "source_chunk_ids": [str(chunk.id)],
                    }
                ],
                "source_chunk_ids": [str(chunk.id)],
                "confidence": 0.9,
                "explanation": "The identity change should affect future chapters.",
            }
        ],
    }
