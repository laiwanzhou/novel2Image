from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.core.enums import PromptType, ReviewStatus
from app.models.character import Character, CharacterAlias
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.prompt import PromptGeneration
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange


def test_operator_crawled_novel_preview_returns_fixed_file_summary(pg_session: Session) -> None:
    client = _client(pg_session)

    response = client.get("/operator/crawled-novel-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["novel_md_path"].endswith("backend\\data\\samples\\crawled-novel\\novel.md")
    assert payload["manifest_path"].endswith("backend\\data\\samples\\crawled-novel\\manifest.json")
    assert payload["title"] == "幽魂骑士王的地下城工程（示例）"
    assert payload["chapter_count"] == 2
    assert payload["chapters"][0]["title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert payload["chapters"][0]["word_count"] == 118
    assert len(payload["chapters"][0]["page_urls"]) == 2
    assert payload["selected_chapter_index"] == 1
    assert payload["selected_chapter_title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert "轰隆" in payload["preview_text"]
    assert "那就来最后一次吧" in payload["chapter_text"]
    assert "蓝光从她掌心闪烁" in payload["chapter_text"]
    assert "本章未完，点击下一页继续阅读" not in payload["preview_text"]
    assert "本章未完，点击下一页继续阅读" not in payload["chapter_text"]


def test_operator_crawled_novel_preview_selects_chapter_by_index(pg_session: Session) -> None:
    client = _client(pg_session)

    response = client.get("/operator/crawled-novel-preview?chapter_index=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_chapter_index"] == 1
    assert payload["selected_chapter_title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert "那就来最后一次吧" in payload["chapter_text"]
    assert "蓝光从她掌心闪烁" in payload["chapter_text"]


def test_operator_crawled_novel_preview_rejects_missing_chapter_index(pg_session: Session) -> None:
    client = _client(pg_session)

    response = client.get("/operator/crawled-novel-preview?chapter_index=999")

    assert response.status_code == 400
    assert "Chapter index not found" in response.json()["detail"]


def test_review_routes_list_accept_reject_and_confirm_alias(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    alias = CharacterAlias(
        novel_id=fixture.novel.id,
        alias_text="青衣少年",
        alias_type="nickname",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[str(fixture.chunk.id)],
        merge_suggestion={},
    )
    rejected = Character(
        novel_id=fixture.novel.id,
        canonical_name="Reject Me",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[str(fixture.chunk.id)],
    )
    pg_session.add_all([alias, rejected])
    pg_session.commit()
    client = _client(pg_session)

    candidates = client.get(f"/review/candidates?novel_id={fixture.novel.id}")
    assert candidates.status_code == 200
    assert {item["id"] for item in candidates.json()} >= {str(fixture.character.id), str(alias.id)}

    accepted = client.post(
        f"/review/character/{fixture.character.id}/accept",
        json={"reviewer": "api", "note": "confirmed by API"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == ReviewStatus.CONFIRMED.value

    confirmed_alias = client.post(
        f"/review/aliases/{alias.id}/confirm",
        json={"character_id": str(fixture.character.id), "reviewer": "api"},
    )
    assert confirmed_alias.status_code == 200
    assert confirmed_alias.json()["character_id"] == str(fixture.character.id)
    assert confirmed_alias.json()["status"] == ReviewStatus.CONFIRMED.value

    rejected_response = client.post(
        f"/review/character/{rejected.id}/reject",
        json={"reviewer": "api", "note": "not a real character"},
    )
    assert rejected_response.status_code == 200
    assert rejected_response.json()["status"] == ReviewStatus.REJECTED.value


def test_review_routes_list_accept_and_reject_event_candidates(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=True)
    event = CharacterEvent(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        event_summary="Lin Qing decides to enter the courtyard.",
        event_type="motivation",
        is_long_term_change=True,
        affected_fields=["motivation"],
        source_chunk_ids=[str(fixture.chunk.id)],
        confidence=0.82,
        explanation="The chapter states the decision directly.",
        status=ReviewStatus.CANDIDATE.value,
    )
    rejected_event = CharacterEvent(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        event_summary="Temporary mood.",
        event_type="other",
        is_long_term_change=False,
        affected_fields=[],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add_all([event, rejected_event])
    pg_session.commit()
    client = _client(pg_session)

    listed = client.get(f"/review/events?novel_id={fixture.novel.id}&chapter_id={fixture.chapter.id}&status=candidate")

    assert listed.status_code == 200
    payload = listed.json()
    assert {item["id"] for item in payload} == {str(event.id), str(rejected_event.id)}
    first = next(item for item in payload if item["id"] == str(event.id))
    assert first["character_name"] == "Lin Qing"
    assert first["chapter_index"] == 1
    assert first["event_summary"] == "Lin Qing decides to enter the courtyard."
    assert first["event_type"] == "motivation"
    assert first["is_long_term_change"] is True
    assert first["affected_fields"] == ["motivation"]
    assert first["source_chunk_ids"] == [str(fixture.chunk.id)]
    assert first["confidence"] == 0.82
    assert first["explanation"] == "The chapter states the decision directly."
    assert first["status"] == ReviewStatus.CANDIDATE.value

    accepted = client.post(f"/review/events/{event.id}/accept", json={"reviewer": "api", "note": "looks durable"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == ReviewStatus.CONFIRMED.value
    assert accepted.json()["reviewed_by"] == "api"
    assert accepted.json()["review_note"] == "looks durable"

    rejected = client.post(f"/review/events/{rejected_event.id}/reject", json={"reviewer": "api", "note": "too small"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == ReviewStatus.REJECTED.value
    assert rejected.json()["review_note"] == "too small"


def test_review_routes_list_accept_and_reject_state_change_candidates(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=True)
    event = CharacterEvent(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        event_summary="Lin Qing is promoted.",
        event_type="identity",
        is_long_term_change=True,
        affected_fields=["identity"],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(event)
    pg_session.flush()
    change = CharacterStateChange(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        event_id=event.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        changed_fields=[
            {
                "field": "identity",
                "before": "outer disciple",
                "after": "inner disciple",
                "source_chunk_ids": [str(fixture.chunk.id)],
            }
        ],
        source_chunk_ids=[str(fixture.chunk.id)],
        confidence=0.77,
        explanation="Promotion is explicitly described.",
        status=ReviewStatus.CANDIDATE.value,
    )
    rejected_change = CharacterStateChange(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        event_id=event.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        changed_fields=[
            {
                "field": "personality",
                "before": "quiet",
                "after": "temporarily angry",
                "source_chunk_ids": [str(fixture.chunk.id)],
            }
        ],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add_all([change, rejected_change])
    pg_session.commit()
    client = _client(pg_session)

    listed = client.get(
        f"/review/state-changes?novel_id={fixture.novel.id}&character_id={fixture.character.id}&status=candidate"
    )

    assert listed.status_code == 200
    payload = listed.json()
    assert {item["id"] for item in payload} == {str(change.id), str(rejected_change.id)}
    first = next(item for item in payload if item["id"] == str(change.id))
    assert first["character_name"] == "Lin Qing"
    assert first["event_id"] == str(event.id)
    assert first["chapter_index"] == 1
    assert first["changed_fields"][0]["field"] == "identity"
    assert first["source_chunk_ids"] == [str(fixture.chunk.id)]
    assert first["confidence"] == 0.77
    assert first["explanation"] == "Promotion is explicitly described."
    assert first["status"] == ReviewStatus.CANDIDATE.value

    accepted = client.post(f"/review/state-changes/{change.id}/accept", json={"reviewer": "api", "note": "supported"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == ReviewStatus.CONFIRMED.value
    assert accepted.json()["reviewed_by"] == "api"

    rejected = client.post(
        f"/review/state-changes/{rejected_change.id}/reject",
        json={"reviewer": "api", "note": "temporary"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == ReviewStatus.REJECTED.value
    assert rejected.json()["review_note"] == "temporary"


def test_state_routes_create_initial_state_and_list_history(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    fixture.character.status = ReviewStatus.CONFIRMED.value
    pg_session.commit()
    client = _client(pg_session)

    created = client.post(
        f"/characters/{fixture.character.id}/initial-state",
        json={
            "novel_id": str(fixture.novel.id),
            "chapter_start": 1,
            "source_chunk_ids": [str(fixture.chunk.id)],
            "fields": {
                "appearance": "wearing a blue robe",
                "identity": "outer disciple",
                "visual_keywords": ["blue robe"],
                "negative_prompt": "modern clothing",
            },
            "confidence": 0.8,
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == ReviewStatus.CANDIDATE.value
    assert created.json()["identity"] == "outer disciple"

    history = client.get(f"/characters/{fixture.character.id}/states")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [created.json()["id"]]


def test_prompt_routes_generate_and_read_history(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=True)
    client = _client(pg_session)

    generated = client.post(
        "/prompts/generate",
        json={
            "novel_id": str(fixture.novel.id),
            "chapter_index": 1,
            "character_id": str(fixture.character.id),
            "user_request": "portrait",
        },
    )
    assert generated.status_code == 200
    prompt_id = generated.json()["id"]
    assert generated.json()["character_state_id"] == str(fixture.state.id)
    assert "outer disciple" in generated.json()["final_prompt"]

    history = client.get(f"/prompts/history?novel_id={fixture.novel.id}")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [prompt_id]

    detail = client.get(f"/prompts/{prompt_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == prompt_id
    assert detail.json()["evidence_snapshot"]["state"]["id"] == str(fixture.state.id)


def test_api_maps_value_error_to_400_response(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(
        f"/review/character/{fixture.character.id}/accept",
        json={"reviewer": "api"},
    )
    assert response.status_code == 200

    repeated = client.post(
        f"/review/character/{fixture.character.id}/accept",
        json={"reviewer": "api"},
    )
    assert repeated.status_code == 400
    assert repeated.json() == {"detail": "Only candidate records can be reviewed"}


def test_get_novel_metadata_excludes_chapter_content(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.get(f"/novels/{fixture.novel.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(fixture.novel.id)
    assert payload["title"] == "API Novel"
    assert payload["source_type"] == "markdown"
    assert payload["language"] == "zh"
    assert "content" not in payload


def test_list_chapters_returns_lightweight_counts(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    fixture.chunk.embedding = [0.0] * 1536
    pg_session.commit()
    client = _client(pg_session)

    response = client.get(f"/novels/{fixture.novel.id}/chapters")

    assert response.status_code == 200
    payload = response.json()
    assert payload == [
        {
            "id": str(fixture.chapter.id),
            "title": "Chapter 1",
            "chapter_index": 1,
            "word_count": 6,
            "chunk_count": 1,
            "embedded_count": 1,
        }
    ]
    assert "content" not in payload[0]


def test_list_chapter_chunks_returns_previews_without_full_text(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    fixture.chunk.embedding = [0.0] * 1536
    long_text = "Lin Qing " * 80
    fixture.chunk.text = long_text
    fixture.chunk.char_count = len(long_text)
    fixture.chunk.end_char = len(long_text)
    pg_session.commit()
    client = _client(pg_session)

    response = client.get(f"/chapters/{fixture.chapter.id}/chunks")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(fixture.chunk.id)
    assert payload[0]["novel_id"] == str(fixture.novel.id)
    assert payload[0]["chapter_id"] == str(fixture.chapter.id)
    assert payload[0]["chapter_index"] == 1
    assert payload[0]["chunk_index"] == 1
    assert payload[0]["has_embedding"] is True
    assert payload[0]["text_preview"] == long_text[:240]
    assert "text" not in payload[0]


def test_processing_status_returns_counts(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=True)
    fixture.chunk.embedding = [0.0] * 1536
    change = CharacterStateChange(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        event_id=None,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        changed_fields=[{"field": "identity", "after": "inner disciple", "source_chunk_ids": [str(fixture.chunk.id)]}],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    prompt = PromptGeneration(
        novel_id=fixture.novel.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        character_id=fixture.character.id,
        character_state_id=fixture.state.id,
        prompt_type=PromptType.CHARACTER.value,
        final_prompt="portrait",
        model_params={},
        used_event_ids=[],
        used_chunk_ids=[str(fixture.chunk.id)],
        warnings=[],
        evidence_snapshot={},
    )
    alias = CharacterAlias(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        alias_text="Young cultivator",
        alias_type="nickname",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[str(fixture.chunk.id)],
        merge_suggestion={},
    )
    pg_session.add_all([change, prompt, alias])
    pg_session.commit()
    client = _client(pg_session)

    response = client.get(f"/novels/{fixture.novel.id}/processing-status")

    assert response.status_code == 200
    assert response.json() == {
        "novel_id": str(fixture.novel.id),
        "chapter_count": 1,
        "chunk_count": 1,
        "embedded_count": 1,
        "missing_embedding_count": 0,
        "candidate_character_count": 0,
        "confirmed_character_count": 1,
        "candidate_alias_count": 1,
        "candidate_event_count": 0,
        "candidate_state_change_count": 1,
        "candidate_state_count": 0,
        "confirmed_state_count": 1,
        "prompt_generation_count": 1,
    }


def test_list_characters_filters_by_status(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=True)
    candidate = Character(
        novel_id=fixture.novel.id,
        canonical_name="Candidate",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[],
    )
    rejected = Character(
        novel_id=fixture.novel.id,
        canonical_name="Rejected",
        status=ReviewStatus.REJECTED.value,
        source_chunk_ids=[],
    )
    pg_session.add_all([candidate, rejected])
    pg_session.commit()
    client = _client(pg_session)

    confirmed = client.get(f"/novels/{fixture.novel.id}/characters?status=confirmed")
    assert confirmed.status_code == 200
    assert [item["id"] for item in confirmed.json()] == [str(fixture.character.id)]

    all_characters = client.get(f"/novels/{fixture.novel.id}/characters?status=all")
    assert all_characters.status_code == 200
    assert {item["id"] for item in all_characters.json()} == {
        str(fixture.character.id),
        str(candidate.id),
        str(rejected.id),
    }

    invalid = client.get(f"/novels/{fixture.novel.id}/characters?status=archived")
    assert invalid.status_code == 400
    assert "Unsupported character status filter" in invalid.json()["detail"]


def test_create_character_route_can_create_confirmed_character(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(
        f"/novels/{fixture.novel.id}/characters",
        json={
            "canonical_name": "塔莉亚·罗诺威",
            "description": "第 1 章登场的混血魔族，隆多兰地下城继承者。",
            "source_chunk_ids": [str(fixture.chunk.id)],
            "confidence": 0.95,
            "status": ReviewStatus.CONFIRMED.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["novel_id"] == str(fixture.novel.id)
    assert payload["canonical_name"] == "塔莉亚·罗诺威"
    assert payload["description"] == "第 1 章登场的混血魔族，隆多兰地下城继承者。"
    assert payload["source_chunk_ids"] == [str(fixture.chunk.id)]
    assert payload["confidence"] == 0.95
    assert payload["status"] == ReviewStatus.CONFIRMED.value
    assert payload["reviewed_by"] == "workspace"

    confirmed = client.get(f"/novels/{fixture.novel.id}/characters?status=confirmed")
    assert {item["id"] for item in confirmed.json()} == {payload["id"]}


def test_create_character_route_rejects_unsupported_status(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(
        f"/novels/{fixture.novel.id}/characters",
        json={"canonical_name": "塔莉亚·罗诺威", "status": ReviewStatus.REJECTED.value},
    )

    assert response.status_code == 400
    assert "status must be candidate or confirmed" in response.json()["detail"]


def test_chunk_novel_succeeds_without_downstream_knowledge(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(
        f"/novels/{fixture.novel.id}/chunk",
        json={"target_chars": 1200, "max_chars": 1500},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["novel_id"] == str(fixture.novel.id)
    assert payload["chapter_count"] == 1
    assert payload["chunk_count"] == 1
    assert payload["replaced_existing_chunks"] is True


def test_chunk_novel_rejects_character_candidate_with_chunk_evidence(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    fixture.character.source_chunk_ids = [str(fixture.chunk.id)]
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_chunk_novel_rejects_alias_candidate_with_chunk_evidence(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    alias = CharacterAlias(
        novel_id=fixture.novel.id,
        alias_text="Young cultivator",
        alias_type="nickname",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[str(fixture.chunk.id)],
        merge_suggestion={},
    )
    pg_session.add(alias)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_chunk_novel_rejects_existing_character_event(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    event = CharacterEvent(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        event_summary="Lin Qing appears.",
        event_type="other",
        is_long_term_change=False,
        affected_fields=[],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(event)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_chunk_novel_rejects_existing_state_change(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    state_change = CharacterStateChange(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        event_id=None,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        changed_fields=[{"field": "identity", "after": "disciple", "source_chunk_ids": [str(fixture.chunk.id)]}],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(state_change)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_chunk_novel_rejects_existing_character_state(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    state = CharacterState(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_start=1,
        chapter_end=None,
        appearance="plain robe",
        visual_keywords=[],
        source_chapters=[1],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(state)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_chunk_novel_rejects_existing_prompt_generation(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    prompt = PromptGeneration(
        novel_id=fixture.novel.id,
        chapter_id=fixture.chapter.id,
        chapter_index=1,
        character_id=fixture.character.id,
        character_state_id=None,
        prompt_type=PromptType.CHARACTER.value,
        final_prompt="portrait",
        model_params={},
        used_event_ids=[],
        used_chunk_ids=[str(fixture.chunk.id)],
        warnings=[],
        evidence_snapshot={},
    )
    pg_session.add(prompt)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/chunk", json={})

    assert _is_blocked_chunk_rebuild(response)


def test_embed_novel_embeds_missing_chunks(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(f"/novels/{fixture.novel.id}/embed", json={"batch_size": 16})

    assert response.status_code == 200
    assert response.json() == {
        "novel_id": str(fixture.novel.id),
        "embedded_count": 1,
        "remaining_missing_embedding_count": 0,
        "provider": "fake",
    }


def test_extract_chapter_runs_single_chapter_extraction(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    client = _client(pg_session)

    response = client.post(f"/chapters/{fixture.chapter.id}/extract", json={})

    assert response.status_code == 200
    assert response.json() == {
        "chapter_id": str(fixture.chapter.id),
        "chapter_index": 1,
        "event_candidate_count": 0,
        "state_change_candidate_count": 0,
    }


def test_confirm_state_route_confirms_candidate_state(pg_session: Session) -> None:
    fixture = _create_api_fixture(pg_session, include_confirmed_state=False)
    state = CharacterState(
        novel_id=fixture.novel.id,
        character_id=fixture.character.id,
        chapter_start=1,
        chapter_end=None,
        appearance="plain robe",
        visual_keywords=["plain robe"],
        source_chapters=[1],
        source_chunk_ids=[str(fixture.chunk.id)],
        status=ReviewStatus.CANDIDATE.value,
    )
    pg_session.add(state)
    pg_session.commit()
    client = _client(pg_session)

    response = client.post(
        f"/states/{state.id}/confirm",
        json={"reviewer": "api", "note": "initial state accepted"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(state.id)
    assert payload["status"] == ReviewStatus.CONFIRMED.value
    assert payload["reviewed_by"] == "api"
    assert payload["review_note"] == "initial state accepted"


def _is_blocked_chunk_rebuild(response) -> bool:
    if response.status_code != 400:
        return False
    detail = response.json()["detail"]
    return "chunk-based knowledge or prompt records" in detail and "Workspace chunk rebuild is blocked" in detail


class ApiFixture:
    def __init__(
        self,
        *,
        novel: Novel,
        chapter: Chapter,
        chunk: ChapterChunk,
        character: Character,
        state: CharacterState | None,
    ) -> None:
        self.novel = novel
        self.chapter = chapter
        self.chunk = chunk
        self.character = character
        self.state = state


def _client(pg_session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app)


def _create_api_fixture(pg_session: Session, *, include_confirmed_state: bool) -> ApiFixture:
    novel = Novel(
        title="API Novel",
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
        title="Chapter 1",
        content="Lin Qing stands in the courtyard.",
        summary="Opening scene.",
        word_count=6,
        checksum="api-chapter-1",
    )
    character = Character(
        novel_id=novel.id,
        canonical_name="Lin Qing",
        status=ReviewStatus.CANDIDATE.value,
        source_chunk_ids=[],
    )
    pg_session.add_all([chapter, character])
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel.id,
        chapter_id=chapter.id,
        chapter_index=1,
        chunk_index=1,
        text="Lin Qing stands in the courtyard.",
        start_char=0,
        end_char=34,
        char_count=34,
        token_count=34,
        checksum="api-chunk-1",
        meta={},
    )
    pg_session.add(chunk)
    pg_session.flush()
    state = None
    if include_confirmed_state:
        character.status = ReviewStatus.CONFIRMED.value
        event = CharacterEvent(
            novel_id=novel.id,
            character_id=character.id,
            chapter_id=chapter.id,
            chapter_index=1,
            event_summary="Lin Qing appears as an outer disciple.",
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
            appearance="wearing a blue robe",
            personality="quiet",
            identity="outer disciple",
            motivation="train hard",
            relationship_summary="alone",
            visual_keywords=["blue robe"],
            negative_prompt="modern clothing",
            source_chapters=[1],
            source_chunk_ids=[str(chunk.id)],
            status=ReviewStatus.CONFIRMED.value,
        )
        pg_session.add_all([event, state])
    pg_session.commit()
    return ApiFixture(novel=novel, chapter=chapter, chunk=chunk, character=character, state=state)
