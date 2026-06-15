from datetime import UTC, datetime
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from scripts.run_chapter_block_pipeline import BlockPipelineOptions, run_chapter_block_pipeline


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


def test_block_pipeline_processes_chapters_in_range_order_and_keeps_state_changes_candidate(
    pg_session: Session,
    tmp_path,
) -> None:
    fixture = _create_block_fixture(pg_session)
    provider = SequencedLlmProvider(
        extraction_responses=[
            _extraction_response(fixture, 1),
            _extraction_response(fixture, 2),
        ],
        review_responses=[
            {"decision": "confirm", "confidence": 0.99, "reason": "supported", "risk_flags": []},
            {"decision": "needs_human", "confidence": 0.7, "reason": "ambiguous", "risk_flags": ["ambiguous"]},
        ],
    )

    result = run_chapter_block_pipeline(
        pg_session,
        BlockPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=2,
            auto_confirm_events=True,
            review_state_changes=True,
            review_dry_run=True,
            apply_high_confidence_rejects=False,
            auto_reject_threshold=0.9,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["processed_chapters"] == [1, 2]
    assert result["failed_chapters"] == []
    assert result["event_created_count"] == 2
    assert result["event_confirmed_count"] == 2
    assert result["state_change_created_count"] == 2
    assert result["reviewer_decision_distribution"] == {"confirm": 1, "reject": 0, "needs_human": 1}
    assert '"chapter_index": 1' in provider.extraction_calls[0][1]
    assert '"chapter_index": 2' in provider.extraction_calls[1][1]

    events = pg_session.scalars(select(CharacterEvent).order_by(CharacterEvent.chapter_index)).all()
    assert [event.chapter_index for event in events] == [1, 2]
    assert all(event.status == ReviewStatus.CONFIRMED.value for event in events)
    assert all(event.reviewed_by == "auto-extraction" for event in events)

    changes = pg_session.scalars(select(CharacterStateChange).order_by(CharacterStateChange.chapter_index)).all()
    assert [change.chapter_index for change in changes] == [1, 2]
    assert all(change.status == ReviewStatus.CANDIDATE.value for change in changes)
    assert all(change.reviewed_by is None for change in changes)
    assert (
        pg_session.scalar(
            select(func.count())
            .select_from(CharacterState)
            .where(CharacterState.status == ReviewStatus.CONFIRMED.value)
        )
        == 1
    )


def test_block_pipeline_applies_only_high_confidence_rejects_when_explicitly_enabled(pg_session: Session, tmp_path) -> None:
    fixture = _create_block_fixture(pg_session)
    provider = SequencedLlmProvider(
        extraction_responses=[_extraction_response(fixture, 1), _extraction_response(fixture, 2), _extraction_response(fixture, 3)],
        review_responses=[
            {"decision": "reject", "confidence": 0.96, "reason": "duplicate", "risk_flags": ["duplicate"]},
            {"decision": "confirm", "confidence": 0.99, "reason": "valid", "risk_flags": []},
            {"decision": "reject", "confidence": 0.4, "reason": "weak", "risk_flags": ["duplicate"]},
        ],
    )

    result = run_chapter_block_pipeline(
        pg_session,
        BlockPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=3,
            auto_confirm_events=True,
            review_state_changes=True,
            review_dry_run=False,
            apply_high_confidence_rejects=True,
            auto_reject_threshold=0.9,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["high_confidence_reject_count"] == 1
    assert result["high_confidence_reject_applied_count"] == 1
    changes = pg_session.scalars(select(CharacterStateChange).order_by(CharacterStateChange.chapter_index)).all()
    assert [change.status for change in changes] == [
        ReviewStatus.REJECTED.value,
        ReviewStatus.CANDIDATE.value,
        ReviewStatus.CANDIDATE.value,
    ]
    assert changes[0].reviewed_by == "llm-reviewer"
    assert changes[1].reviewed_by is None
    assert changes[2].reviewed_by is None


def test_block_pipeline_boundary_report_tracks_pending_changes_and_latest_states(pg_session: Session, tmp_path) -> None:
    fixture = _create_block_fixture(pg_session)
    provider = SequencedLlmProvider(
        extraction_responses=[_extraction_response(fixture, 1)],
        review_responses=[{"decision": "needs_human", "confidence": 0.88, "reason": "important", "risk_flags": []}],
    )

    run_chapter_block_pipeline(
        pg_session,
        BlockPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=1,
            auto_confirm_events=True,
            review_state_changes=True,
            review_dry_run=True,
            apply_high_confidence_rejects=False,
            auto_reject_threshold=0.9,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    report = json.loads((tmp_path / "block_boundary_report.json").read_text(encoding="utf-8"))
    assert report["block_start"] == 1
    assert report["block_end"] == 1
    assert report["per_character_latest_confirmed_state_at_block_end"][str(fixture.character.id)]["chapter_start"] == 1
    assert report["per_character_pending_state_changes_in_block"][str(fixture.character.id)] == 1
    assert report["candidate_state_changes_that_may_affect_next_block"]
    assert report["warnings"]


def test_block_pipeline_records_failed_chapter_and_continues(pg_session: Session, tmp_path) -> None:
    fixture = _create_block_fixture(pg_session)
    provider = SequencedLlmProvider(
        extraction_responses=[{"events": [{"bad": "shape"}], "state_changes": []}, _extraction_response(fixture, 2)],
        review_responses=[],
    )

    result = run_chapter_block_pipeline(
        pg_session,
        BlockPipelineOptions(
            novel_id=fixture.novel.id,
            chapter_start=1,
            chapter_end=2,
            auto_confirm_events=True,
            review_state_changes=False,
            review_dry_run=True,
            apply_high_confidence_rejects=False,
            auto_reject_threshold=0.9,
            continue_on_error=True,
            log_dir=tmp_path,
        ),
        extraction_provider=provider,
        review_provider=provider,
    )

    assert result["processed_chapters"] == [2]
    assert result["failed_chapters"][0]["chapter_index"] == 1
    assert (tmp_path / "chapter-0001.jsonl").exists()
    assert (tmp_path / "chapter-0002.jsonl").exists()


class BlockFixture:
    def __init__(self, *, novel: Novel, chapters: list[Chapter], chunks: dict[int, ChapterChunk], character: Character) -> None:
        self.novel = novel
        self.chapters = chapters
        self.chunks = chunks
        self.character = character


def _create_block_fixture(pg_session: Session) -> BlockFixture:
    novel = Novel(title="Block Novel", source_type="markdown", language="zh", meta={}, imported_at=datetime.now(UTC))
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
    for index in range(1, 5):
        chapter = Chapter(
            novel_id=novel.id,
            chapter_index=index,
            title=f"Chapter {index}",
            content=f"Chapter {index} content changes Lin Qing.",
            summary=f"Summary {index}",
            word_count=8,
            checksum=f"chapter-{index}",
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
            checksum=f"chunk-{index}",
            meta={},
        )
        pg_session.add(chunk)
        chapters.append(chapter)
        chunks[index] = chunk
    state = CharacterState(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        chapter_end=None,
        identity="outer disciple",
        motivation="survive",
        relationship_summary="alone",
        visual_keywords=["robe"],
        source_chapters=[1],
        source_chunk_ids=[str(chunks[1].id)],
        status=ReviewStatus.CONFIRMED.value,
    )
    pg_session.add(state)
    pg_session.commit()
    return BlockFixture(novel=novel, chapters=chapters, chunks=chunks, character=character)


def _extraction_response(fixture: BlockFixture, chapter_index: int) -> dict:
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
