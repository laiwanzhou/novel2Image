from app.core.enums import PromptType, ReviewStatus
import pytest
from app.models import Base
from app.models.character import Character
from app.models.novel import Chapter, Novel
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from app.repositories.states import StateRepository
from app.schemas.review_schema import CharacterStateFields
from app.services.state_service import StateService


EXPECTED_TABLES = {
    "novels",
    "chapters",
    "chapter_chunks",
    "characters",
    "character_aliases",
    "character_events",
    "character_state_changes",
    "character_states",
    "prompt_generations",
    "generated_images",
    "review_actions",
}


def test_model_metadata_contains_mvp_tables() -> None:
    assert EXPECTED_TABLES.issubset(Base.metadata.tables.keys())


def test_prompt_type_scope_excludes_group() -> None:
    assert {item.value for item in PromptType} == {"character", "scene"}


def test_review_status_values_match_candidate_lifecycle() -> None:
    assert {item.value for item in ReviewStatus} == {"candidate", "confirmed", "rejected"}


def test_character_state_range_index_exists() -> None:
    table = Base.metadata.tables["character_states"]
    index_columns = {index.name: [column.name for column in index.columns] for index in table.indexes}

    assert index_columns["ix_character_states_novel_character_range_status"] == [
        "novel_id",
        "character_id",
        "chapter_start",
        "chapter_end",
        "status",
    ]


def test_core_check_constraints_exist() -> None:
    constraints_by_table = {
        table_name: {constraint.name for constraint in table.constraints}
        for table_name, table in Base.metadata.tables.items()
    }

    assert "ck_characters_status" in constraints_by_table["characters"]
    assert "ck_character_aliases_status" in constraints_by_table["character_aliases"]
    assert "ck_character_events_status" in constraints_by_table["character_events"]
    assert "ck_character_state_changes_status" in constraints_by_table["character_state_changes"]
    assert "ck_character_states_status" in constraints_by_table["character_states"]
    assert "ck_character_states_valid_range" in constraints_by_table["character_states"]
    assert "ck_prompt_generations_prompt_type" in constraints_by_table["prompt_generations"]


def test_initial_character_state_candidate_requires_sources(pg_session) -> None:
    novel, character, _chapter = _create_state_fixture(pg_session)
    service = StateService(StateRepository(pg_session))

    state = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(
            appearance="青衣少年",
            identity="外门弟子",
            visual_keywords=["青衣", "少年"],
        ),
        confidence=0.8,
    )

    assert state.status == ReviewStatus.CANDIDATE.value
    assert state.event_id is None
    assert state.state_change_id is None
    assert state.chapter_start == 1
    assert state.source_chunk_ids == ["chunk-1"]


def test_confirm_initial_state_marks_confirmed(pg_session) -> None:
    novel, character, _chapter = _create_state_fixture(pg_session)
    service = StateService(StateRepository(pg_session))
    state = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(identity="外门弟子"),
    )

    confirmed = service.confirm_state(state.id, reviewer="tester", note="initial")

    assert confirmed.status == ReviewStatus.CONFIRMED.value
    assert confirmed.chapter_end is None
    assert confirmed.reviewed_by == "tester"


def test_synthesize_candidate_from_state_change_copies_unchanged_fields(pg_session) -> None:
    novel, character, chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(
            appearance="青衣少年",
            personality="谨慎",
            identity="外门弟子",
            motivation="求道",
            visual_keywords=["青衣"],
        ),
    )
    service.confirm_state(initial.id, reviewer="tester")
    event = repository.add_event(
        CharacterEvent(
            novel_id=novel.id,
            character_id=character.id,
            chapter_id=chapter.id,
            chapter_index=5,
            event_summary="林青拜入内门",
            event_type="identity",
            is_long_term_change=True,
            affected_fields=["identity"],
            source_chunk_ids=["chunk-5"],
            status=ReviewStatus.CONFIRMED.value,
        )
    )
    state_change = repository.add_state_change(
        CharacterStateChange(
            novel_id=novel.id,
            character_id=character.id,
            event_id=event.id,
            chapter_id=chapter.id,
            chapter_index=5,
            changed_fields=[{"field": "identity", "before": "外门弟子", "after": "内门弟子"}],
            source_chunk_ids=["chunk-5"],
            confidence=0.9,
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    candidate = service.synthesize_candidate_from_change(state_change.id)

    assert candidate.status == ReviewStatus.CANDIDATE.value
    assert candidate.chapter_start == 5
    assert candidate.identity == "内门弟子"
    assert candidate.appearance == "青衣少年"
    assert candidate.personality == "谨慎"
    assert candidate.visual_keywords == ["青衣"]
    assert candidate.event_id == event.id
    assert candidate.state_change_id == state_change.id


def test_confirm_new_state_closes_previous_range(pg_session) -> None:
    novel, character, chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(identity="外门弟子"),
    )
    service.confirm_state(initial.id, reviewer="tester")
    candidate = repository.add_state(
        CharacterState(
            novel_id=novel.id,
            character_id=character.id,
            chapter_start=5,
            chapter_end=None,
            identity="内门弟子",
            visual_keywords=[],
            source_chapters=[5],
            source_chunk_ids=["chunk-5"],
            confidence=0.9,
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    confirmed = service.confirm_state(candidate.id, reviewer="tester")
    pg_session.refresh(initial)

    assert initial.chapter_end == 4
    assert confirmed.status == ReviewStatus.CONFIRMED.value
    assert confirmed.chapter_start == 5
    assert confirmed.chapter_end is None


def test_confirm_state_rejects_non_forward_chapter_start(pg_session) -> None:
    novel, character, _chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=5,
        source_chunk_ids=["chunk-5"],
        fields=CharacterStateFields(identity="内门弟子"),
    )
    service.confirm_state(initial.id, reviewer="tester")
    candidate = repository.add_state(
        CharacterState(
            novel_id=novel.id,
            character_id=character.id,
            chapter_start=5,
            chapter_end=None,
            identity="重复状态",
            visual_keywords=[],
            source_chapters=[5],
            source_chunk_ids=["chunk-5b"],
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    try:
        service.confirm_state(candidate.id, reviewer="tester")
    except ValueError as exc:
        assert "after previous confirmed state" in str(exc)
    else:
        raise AssertionError("Expected non-forward state confirmation to fail")


def test_failed_state_confirmation_leaves_session_state_unchanged(pg_session) -> None:
    novel, character, _chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=5,
        source_chunk_ids=["chunk-5"],
        fields=CharacterStateFields(identity="inner disciple"),
    )
    service.confirm_state(initial.id, reviewer="tester")
    candidate = repository.add_state(
        CharacterState(
            novel_id=novel.id,
            character_id=character.id,
            chapter_start=5,
            chapter_end=None,
            identity="duplicate state",
            visual_keywords=[],
            source_chapters=[5],
            source_chunk_ids=["chunk-5b"],
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    try:
        service.confirm_state(candidate.id, reviewer="tester")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected state confirmation to fail")

    assert initial.chapter_end is None
    assert candidate.status == ReviewStatus.CANDIDATE.value
    pg_session.flush()
    pg_session.refresh(initial)
    pg_session.refresh(candidate)
    assert initial.chapter_end is None
    assert candidate.status == ReviewStatus.CANDIDATE.value


def test_synthesize_candidate_normalizes_visual_keywords_string(pg_session) -> None:
    novel, character, chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(identity="outer disciple", visual_keywords=["green robe"]),
    )
    service.confirm_state(initial.id, reviewer="tester")
    state_change = repository.add_state_change(
        CharacterStateChange(
            novel_id=novel.id,
            character_id=character.id,
            event_id=None,
            chapter_id=chapter.id,
            chapter_index=3,
                changed_fields=[
                    {
                        "field": "visual_keywords",
                        "before": ["green robe"],
                        "after": "red robe, iron sword、moonlight",
                    }
                ],
            source_chunk_ids=["chunk-3"],
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    state = service.synthesize_candidate_from_change(state_change.id)

    assert state.visual_keywords == ["red robe", "iron sword", "moonlight"]


def test_synthesize_candidate_validates_text_field_type(pg_session) -> None:
    novel, character, chapter = _create_state_fixture(pg_session)
    repository = StateRepository(pg_session)
    service = StateService(repository)
    initial = service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=["chunk-1"],
        fields=CharacterStateFields(identity="outer disciple"),
    )
    service.confirm_state(initial.id, reviewer="tester")
    state_change = repository.add_state_change(
        CharacterStateChange(
            novel_id=novel.id,
            character_id=character.id,
            event_id=None,
            chapter_id=chapter.id,
            chapter_index=3,
            changed_fields=[{"field": "identity", "before": "outer disciple", "after": {"bad": "shape"}}],
            source_chunk_ids=["chunk-3"],
            status=ReviewStatus.CANDIDATE.value,
        )
    )

    with pytest.raises(ValueError, match="identity"):
        service.synthesize_candidate_from_change(state_change.id)


def _create_state_fixture(session):
    novel = Novel(
        title="测试小说",
        source_type="markdown",
        language="zh",
        meta={},
    )
    session.add(novel)
    session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        chapter_index=1,
        title="第1章 初见",
        content="林青初见。",
        word_count=5,
        checksum="chapter-1",
    )
    character = Character(
        novel_id=novel.id,
        canonical_name="林青",
        status=ReviewStatus.CONFIRMED.value,
        source_chunk_ids=["chunk-1"],
    )
    session.add_all([chapter, character])
    session.flush()
    return novel, character, chapter
