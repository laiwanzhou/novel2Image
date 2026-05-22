from pathlib import Path
from uuid import UUID

import typer

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.novel import Chapter
from app.providers.embeddings import get_embedding_provider
from app.providers.llm import get_llm_provider
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.novels import NovelRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.services.character_service import CharacterService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.evidence_service import EvidenceService
from app.services.extraction_service import ExtractionService
from app.services.import_service import ImportService
from app.services.prompt_generation_service import PromptGenerationService


app = typer.Typer(help="Novel character visualization MVP CLI.")


@app.callback()
def main() -> None:
    """Run offline MVP tasks."""


@app.command("health")
def health() -> None:
    typer.echo("ok")


@app.command("import-book")
def import_book(
    path: Path = typer.Option(..., exists=True, file_okay=True, dir_okay=False),
    title: str | None = typer.Option(None),
    author: str | None = typer.Option(None),
) -> None:
    manifest = ImportService().parse_path(path, title=title, author=author)
    with SessionLocal() as session:
        novel = NovelRepository(session).create_from_manifest(manifest, source_path=str(path))
        session.commit()
        typer.echo(str(novel.id))


@app.command("chunk-book")
def chunk_book(novel_id: UUID = typer.Option(...)) -> None:
    chunker = ChunkingService()
    with SessionLocal() as session:
        chapters = (
            session.query(Chapter)
            .filter(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_index)
            .all()
        )
        repository = ChunkRepository(session)
        total_chunks = 0
        for chapter in chapters:
            chunks = chunker.chunk_chapter(chapter.content)
            repository.replace_chunks_for_chapter(
                novel_id=chapter.novel_id,
                chapter_id=chapter.id,
                chapter_index=chapter.chapter_index,
                chunks=chunks,
            )
            total_chunks += len(chunks)
        session.commit()
        typer.echo(f"chunked {len(chapters)} chapters into {total_chunks} chunks")


@app.command("embed-book")
def embed_book(novel_id: UUID = typer.Option(...)) -> None:
    settings = get_settings()
    provider = get_embedding_provider(settings.embedding_provider)
    with SessionLocal() as session:
        repository = ChunkRepository(session)
        count = EmbeddingService(repository, provider).embed_missing_chunks(novel_id)
        session.commit()
        typer.echo(f"embedded {count} chunks")


@app.command("extract-chapter")
def extract_chapter(chapter_id: UUID = typer.Option(...)) -> None:
    settings = get_settings()
    llm_provider = get_llm_provider(
        settings.llm_provider,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        json_mode=settings.llm_json_mode,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    with SessionLocal() as session:
        result = ExtractionService(
            state_repository=StateRepository(session),
            chunk_repository=ChunkRepository(session),
            character_repository=CharacterRepository(session),
            llm_provider=llm_provider,
        ).extract_chapter_candidates(chapter_id)
        session.commit()
        typer.echo(f"created {len(result.events)} event candidates and {len(result.state_changes)} state change candidates")


@app.command("generate-prompt")
def generate_prompt(
    novel_id: UUID = typer.Option(...),
    chapter_index: int = typer.Option(...),
    character_id: UUID = typer.Option(...),
    user_request: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        state_repository = StateRepository(session)
        chunk_repository = ChunkRepository(session)
        prompt = PromptGenerationService(
            state_repository=state_repository,
            chunk_repository=chunk_repository,
            prompt_repository=PromptRepository(session),
            evidence_service=EvidenceService(
                state_repository=state_repository,
                chunk_repository=chunk_repository,
            ),
        ).generate_character_prompt(
            novel_id=novel_id,
            chapter_index=chapter_index,
            character_id=character_id,
            user_request=user_request,
        )
        session.commit()
        typer.echo(str(prompt.id))


@app.command("list-character-candidates")
def list_character_candidates(novel_id: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        candidates = CharacterRepository(session).list_candidates(novel_id)
        for candidate in candidates:
            label = getattr(candidate, "canonical_name", None) or getattr(candidate, "alias_text", "")
            typer.echo(f"{candidate.__tablename__}\t{candidate.id}\t{label}\t{candidate.status}")


@app.command("confirm-character")
def confirm_character(
    character_id: UUID = typer.Option(...),
    reviewer: str = typer.Option("cli"),
    note: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        character = CharacterService(CharacterRepository(session)).confirm_character(character_id, reviewer, note)
        session.commit()
        typer.echo(f"confirmed character {character.id}")


@app.command("confirm-alias")
def confirm_alias(
    alias_id: UUID = typer.Option(...),
    character_id: UUID = typer.Option(...),
    reviewer: str = typer.Option("cli"),
    note: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        alias = CharacterService(CharacterRepository(session)).confirm_alias(alias_id, character_id, reviewer, note)
        session.commit()
        typer.echo(f"confirmed alias {alias.id}")


@app.command("reject-candidate")
def reject_candidate(
    target_type: str = typer.Option(...),
    target_id: UUID = typer.Option(...),
    reviewer: str = typer.Option("cli"),
    note: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        target = CharacterService(CharacterRepository(session)).reject_candidate(target_type, target_id, reviewer, note)
        session.commit()
        typer.echo(f"rejected {target_type} {target.id}")


if __name__ == "__main__":
    app()
