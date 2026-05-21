from datetime import UTC, datetime
import uuid

from app.core.enums import AliasType, ReviewStatus
from app.models.character import Character, CharacterAlias
from app.repositories.characters import CharacterRepository


class CharacterService:
    def __init__(self, repository: CharacterRepository) -> None:
        self.repository = repository

    def create_character_candidate(
        self,
        *,
        novel_id: uuid.UUID,
        canonical_name: str,
        source_chunk_ids: list[str],
        confidence: float | None = None,
        description: str | None = None,
    ) -> Character:
        return self.repository.add_character(
            Character(
                novel_id=novel_id,
                canonical_name=canonical_name,
                description=description,
                status=ReviewStatus.CANDIDATE.value,
                source_chunk_ids=source_chunk_ids,
                confidence=confidence,
            )
        )

    def create_alias_candidate(
        self,
        *,
        novel_id: uuid.UUID,
        alias_text: str,
        source_chunk_ids: list[str],
        alias_type: AliasType = AliasType.UNKNOWN,
        character_id: uuid.UUID | None = None,
        confidence: float | None = None,
        context_excerpt: str | None = None,
    ) -> CharacterAlias:
        return self.repository.add_alias(
            CharacterAlias(
                novel_id=novel_id,
                character_id=character_id,
                alias_text=alias_text,
                alias_type=alias_type.value,
                status=ReviewStatus.CANDIDATE.value,
                source_chunk_ids=source_chunk_ids,
                context_excerpt=context_excerpt,
                confidence=confidence,
                merge_suggestion={},
            )
        )

    def confirm_character(self, character_id: uuid.UUID, reviewer: str, note: str | None = None) -> Character:
        character = self._require_character(character_id)
        self._require_candidate(character)
        character.status = ReviewStatus.CONFIRMED.value
        self._mark_reviewed(character, reviewer, note)
        self.repository.session.flush()
        return character

    def confirm_alias(
        self,
        alias_id: uuid.UUID,
        character_id: uuid.UUID,
        reviewer: str,
        note: str | None = None,
    ) -> CharacterAlias:
        alias = self._require_alias(alias_id)
        self._require_candidate(alias)
        character = self._require_character(character_id)
        if character.status != ReviewStatus.CONFIRMED.value:
            raise ValueError("Alias can only be confirmed against a confirmed character")
        alias.character_id = character_id
        alias.status = ReviewStatus.CONFIRMED.value
        self._mark_reviewed(alias, reviewer, note)
        self.repository.session.flush()
        return alias

    def reject_candidate(self, target_type: str, target_id: uuid.UUID, reviewer: str, note: str | None = None):
        if target_type == "character":
            target = self._require_character(target_id)
        elif target_type == "alias":
            target = self._require_alias(target_id)
        else:
            raise ValueError(f"Unsupported rejection target type: {target_type}")
        self._require_candidate(target)
        target.status = ReviewStatus.REJECTED.value
        self._mark_reviewed(target, reviewer, note)
        self.repository.session.flush()
        return target

    def _require_character(self, character_id: uuid.UUID) -> Character:
        character = self.repository.get_character(character_id)
        if character is None:
            raise ValueError(f"Character not found: {character_id}")
        return character

    def _require_alias(self, alias_id: uuid.UUID) -> CharacterAlias:
        alias = self.repository.get_alias(alias_id)
        if alias is None:
            raise ValueError(f"Alias not found: {alias_id}")
        return alias

    def _mark_reviewed(self, target, reviewer: str, note: str | None) -> None:
        target.reviewed_at = datetime.now(UTC)
        target.reviewed_by = reviewer
        target.review_note = note

    def _require_candidate(self, target) -> None:
        if target.status != ReviewStatus.CANDIDATE.value:
            raise ValueError("Only candidate records can be reviewed")
