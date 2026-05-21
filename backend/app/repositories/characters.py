import uuid

from sqlalchemy import func, select

from app.models.character import Character, CharacterAlias
from app.repositories.base import BaseRepository


class CharacterRepository(BaseRepository[Character]):
    def add_character(self, character: Character) -> Character:
        self.session.add(character)
        self.session.flush()
        return character

    def add_alias(self, alias: CharacterAlias) -> CharacterAlias:
        self.session.add(alias)
        self.session.flush()
        return alias

    def get_character(self, character_id: uuid.UUID) -> Character | None:
        return self.session.get(Character, character_id)

    def get_alias(self, alias_id: uuid.UUID) -> CharacterAlias | None:
        return self.session.get(CharacterAlias, alias_id)

    def list_candidates(self, novel_id: uuid.UUID) -> list[Character | CharacterAlias]:
        characters = list(
            self.session.scalars(
                select(Character).where(Character.novel_id == novel_id, Character.status == "candidate")
            )
        )
        aliases = list(
            self.session.scalars(
                select(CharacterAlias).where(CharacterAlias.novel_id == novel_id, CharacterAlias.status == "candidate")
            )
        )
        return [*characters, *aliases]

    def list_characters(self, novel_id: uuid.UUID, status: str | None) -> list[Character]:
        statement = select(Character).where(Character.novel_id == novel_id).order_by(Character.canonical_name, Character.id)
        if status is not None:
            statement = statement.where(Character.status == status)
        return list(self.session.scalars(statement))

    def count_characters(self, novel_id: uuid.UUID, status: str) -> int:
        statement = select(func.count()).select_from(Character).where(
            Character.novel_id == novel_id,
            Character.status == status,
        )
        return int(self.session.scalar(statement) or 0)

    def count_aliases(self, novel_id: uuid.UUID, status: str) -> int:
        statement = select(func.count()).select_from(CharacterAlias).where(
            CharacterAlias.novel_id == novel_id,
            CharacterAlias.status == status,
        )
        return int(self.session.scalar(statement) or 0)

    def has_chunk_evidence_candidates(self, novel_id: uuid.UUID) -> bool:
        character_statement = (
            select(Character.id)
            .where(
                Character.novel_id == novel_id,
                Character.status == "candidate",
                func.jsonb_array_length(Character.source_chunk_ids) > 0,
            )
            .limit(1)
        )
        if self.session.scalar(character_statement) is not None:
            return True

        alias_statement = (
            select(CharacterAlias.id)
            .where(
                CharacterAlias.novel_id == novel_id,
                CharacterAlias.status == "candidate",
                func.jsonb_array_length(CharacterAlias.source_chunk_ids) > 0,
            )
            .limit(1)
        )
        return self.session.scalar(alias_statement) is not None
