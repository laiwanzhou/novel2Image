from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.novel import Chapter, ChapterChunk, Novel
from app.providers.embeddings import EMBEDDING_DIMENSIONS, FakeEmbeddingProvider
from app.repositories.chunks import ChunkRepository
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService


def test_fake_embedding_provider_returns_deterministic_1536_dimensional_vectors() -> None:
    provider = FakeEmbeddingProvider()

    first = provider.embed_texts(["青衣少年"])[0]
    second = provider.embed_texts(["青衣少年"])[0]

    assert len(first) == EMBEDDING_DIMENSIONS
    assert first == second


def test_embedding_service_persists_missing_chunk_embeddings(pg_session: Session) -> None:
    novel = _create_novel_with_chunks(pg_session)
    repository = ChunkRepository(pg_session)

    count = EmbeddingService(repository, FakeEmbeddingProvider()).embed_missing_chunks(novel.id)
    pg_session.commit()

    assert count == 3
    assert repository.list_chunks_missing_embeddings(novel.id, limit=10) == []


def test_retrieval_service_searches_by_pgvector_distance(pg_session: Session) -> None:
    novel = _create_novel_with_chunks(pg_session)
    repository = ChunkRepository(pg_session)
    provider = FakeEmbeddingProvider()
    EmbeddingService(repository, provider).embed_missing_chunks(novel.id)
    pg_session.commit()

    results = RetrievalService(repository, provider).search_chunks(
        novel_id=novel.id,
        query="青衣少年",
        limit=2,
    )

    assert results[0].text == "青衣少年"
    assert results[0].distance == 0.0


def test_retrieval_service_filters_by_chapter_window(pg_session: Session) -> None:
    novel = _create_novel_with_chunks(pg_session)
    repository = ChunkRepository(pg_session)
    provider = FakeEmbeddingProvider()
    EmbeddingService(repository, provider).embed_missing_chunks(novel.id)
    pg_session.commit()

    results = RetrievalService(repository, provider).search_chunks(
        novel_id=novel.id,
        query="青衣少年",
        chapter_index=2,
        window=0,
        limit=10,
    )

    assert {result.chapter_index for result in results} == {2}
    assert [result.text for result in results] == ["黑衣刺客"]


def _create_novel_with_chunks(session: Session) -> Novel:
    novel = Novel(
        title="测试小说",
        author=None,
        source_type="markdown",
        language="zh",
        source_path=None,
        meta={},
        imported_at=datetime.now(UTC),
    )
    session.add(novel)
    session.flush()

    chapter_one = Chapter(
        novel_id=novel.id,
        chapter_index=1,
        title="第1章 初见",
        content="青衣少年",
        word_count=4,
        checksum="chapter-one",
    )
    chapter_two = Chapter(
        novel_id=novel.id,
        chapter_index=2,
        title="第2章 转折",
        content="黑衣刺客",
        word_count=4,
        checksum="chapter-two",
    )
    session.add_all([chapter_one, chapter_two])
    session.flush()

    session.add_all(
        [
            ChapterChunk(
                novel_id=novel.id,
                chapter_id=chapter_one.id,
                chapter_index=1,
                chunk_index=1,
                text="青衣少年",
                start_char=0,
                end_char=4,
                char_count=4,
                token_count=4,
                checksum="chunk-one",
                meta={},
            ),
            ChapterChunk(
                novel_id=novel.id,
                chapter_id=chapter_one.id,
                chapter_index=1,
                chunk_index=2,
                text="白衣少女",
                start_char=5,
                end_char=9,
                char_count=4,
                token_count=4,
                checksum="chunk-two",
                meta={},
            ),
            ChapterChunk(
                novel_id=novel.id,
                chapter_id=chapter_two.id,
                chapter_index=2,
                chunk_index=1,
                text="黑衣刺客",
                start_char=0,
                end_char=4,
                char_count=4,
                token_count=4,
                checksum="chunk-three",
                meta={},
            ),
        ]
    )
    session.commit()
    return novel
