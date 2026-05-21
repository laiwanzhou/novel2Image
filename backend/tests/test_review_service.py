from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.enums import AliasType, ReviewStatus
from app.models.novel import Novel
from app.repositories.characters import CharacterRepository
from app.services.character_service import CharacterService


def test_character_candidate_can_be_confirmed(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.create_character_candidate(
        novel_id=novel.id,
        canonical_name="林青",
        source_chunk_ids=["chunk-1"],
        confidence=0.9,
    )

    confirmed = service.confirm_character(character.id, reviewer="tester", note="main character")
    pg_session.commit()

    assert confirmed.status == ReviewStatus.CONFIRMED.value
    assert confirmed.reviewed_by == "tester"
    assert confirmed.review_note == "main character"


def test_alias_confirmation_requires_confirmed_character(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.create_character_candidate(
        novel_id=novel.id,
        canonical_name="林青",
        source_chunk_ids=["chunk-1"],
    )
    alias = service.create_alias_candidate(
        novel_id=novel.id,
        alias_text="青衣少年",
        alias_type=AliasType.NICKNAME,
        source_chunk_ids=["chunk-1"],
    )

    with pytest.raises(ValueError, match="confirmed character"):
        service.confirm_alias(alias.id, character.id, reviewer="tester")


def test_alias_can_be_confirmed_against_confirmed_character(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.confirm_character(
        service.create_character_candidate(
            novel_id=novel.id,
            canonical_name="林青",
            source_chunk_ids=["chunk-1"],
        ).id,
        reviewer="tester",
    )
    alias = service.create_alias_candidate(
        novel_id=novel.id,
        alias_text="青衣少年",
        source_chunk_ids=["chunk-1"],
    )

    confirmed_alias = service.confirm_alias(alias.id, character.id, reviewer="tester")

    assert confirmed_alias.status == ReviewStatus.CONFIRMED.value
    assert confirmed_alias.character_id == character.id


def test_reject_alias_candidate(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    alias = service.create_alias_candidate(
        novel_id=novel.id,
        alias_text="陌生人",
        source_chunk_ids=["chunk-1"],
    )

    rejected = service.reject_candidate("alias", alias.id, reviewer="tester", note="not a character")

    assert rejected.status == ReviewStatus.REJECTED.value
    assert rejected.review_note == "not a character"


def test_confirm_character_requires_candidate(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.confirm_character(
        service.create_character_candidate(
            novel_id=novel.id,
            canonical_name="Lin Qing",
            source_chunk_ids=["chunk-1"],
        ).id,
        reviewer="tester",
    )

    with pytest.raises(ValueError, match="candidate"):
        service.confirm_character(character.id, reviewer="tester")


def test_reject_character_requires_candidate(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.confirm_character(
        service.create_character_candidate(
            novel_id=novel.id,
            canonical_name="Lin Qing",
            source_chunk_ids=["chunk-1"],
        ).id,
        reviewer="tester",
    )

    with pytest.raises(ValueError, match="candidate"):
        service.reject_candidate("character", character.id, reviewer="tester")


def test_confirm_alias_requires_candidate_alias(pg_session: Session) -> None:
    novel = _create_novel(pg_session)
    service = CharacterService(CharacterRepository(pg_session))
    character = service.confirm_character(
        service.create_character_candidate(
            novel_id=novel.id,
            canonical_name="Lin Qing",
            source_chunk_ids=["chunk-1"],
        ).id,
        reviewer="tester",
    )
    alias = service.create_alias_candidate(
        novel_id=novel.id,
        alias_text="Young man in green",
        source_chunk_ids=["chunk-1"],
    )
    service.confirm_alias(alias.id, character.id, reviewer="tester")

    with pytest.raises(ValueError, match="candidate"):
        service.confirm_alias(alias.id, character.id, reviewer="tester")


def _create_novel(session: Session) -> Novel:
    novel = Novel(
        title="测试小说",
        source_type="markdown",
        language="zh",
        meta={},
        imported_at=datetime.now(UTC),
    )
    session.add(novel)
    session.flush()
    return novel
