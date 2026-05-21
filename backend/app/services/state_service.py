from datetime import UTC, datetime
import uuid

from app.core.enums import ReviewStatus
from app.models.state import CharacterState
from app.repositories.states import StateRepository
from app.schemas.review_schema import CharacterStateFields


STATE_FIELDS = {
    "appearance",
    "personality",
    "identity",
    "motivation",
    "relationship_summary",
    "visual_keywords",
    "negative_prompt",
}


class StateService:
    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    def create_initial_state_candidate(
        self,
        *,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        chapter_start: int,
        source_chunk_ids: list[str],
        fields: CharacterStateFields,
        confidence: float | None = None,
    ) -> CharacterState:
        if not source_chunk_ids:
            raise ValueError("Initial CharacterState requires source chunks")
        state = CharacterState(
            novel_id=novel_id,
            character_id=character_id,
            chapter_start=chapter_start,
            chapter_end=None,
            appearance=fields.appearance,
            personality=fields.personality,
            identity=fields.identity,
            motivation=fields.motivation,
            relationship_summary=fields.relationship_summary,
            visual_keywords=fields.visual_keywords,
            negative_prompt=fields.negative_prompt,
            source_chapters=[chapter_start],
            source_chunk_ids=source_chunk_ids,
            event_id=None,
            state_change_id=None,
            confidence=confidence,
            status=ReviewStatus.CANDIDATE.value,
        )
        return self.repository.add_state(state)

    def synthesize_candidate_from_change(self, state_change_id: uuid.UUID) -> CharacterState:
        state_change = self.repository.get_state_change(state_change_id)
        if state_change is None:
            raise ValueError(f"CharacterStateChange not found: {state_change_id}")
        if state_change.character_id is None:
            raise ValueError("CharacterStateChange requires a confirmed character before state synthesis")
        previous = self.repository.latest_confirmed_state_before_or_at(
            state_change.character_id,
            state_change.chapter_index,
        )
        if previous is None:
            raise ValueError("No previous confirmed CharacterState exists; create an initial state first")

        values = CharacterStateFields(
            appearance=previous.appearance,
            personality=previous.personality,
            identity=previous.identity,
            motivation=previous.motivation,
            relationship_summary=previous.relationship_summary,
            visual_keywords=list(previous.visual_keywords),
            negative_prompt=previous.negative_prompt,
        )
        for change in state_change.changed_fields:
            field = change["field"]
            self._validate_change_after(field, change.get("after"))
            setattr(values, field, change.get("after"))

        state = CharacterState(
            novel_id=state_change.novel_id,
            character_id=state_change.character_id,
            chapter_start=state_change.chapter_index,
            chapter_end=None,
            appearance=values.appearance,
            personality=values.personality,
            identity=values.identity,
            motivation=values.motivation,
            relationship_summary=values.relationship_summary,
            visual_keywords=values.visual_keywords,
            negative_prompt=values.negative_prompt,
            source_chapters=[state_change.chapter_index],
            source_chunk_ids=state_change.source_chunk_ids,
            event_id=state_change.event_id,
            state_change_id=state_change.id,
            confidence=state_change.confidence,
            status=ReviewStatus.CANDIDATE.value,
        )
        return self.repository.add_state(state)

    def confirm_state(self, candidate_state_id: uuid.UUID, reviewer: str, note: str | None = None) -> CharacterState:
        with self.repository.session.begin_nested():
            candidate = self.repository.get_state(candidate_state_id)
            if candidate is None:
                raise ValueError(f"CharacterState not found: {candidate_state_id}")
            if candidate.status != ReviewStatus.CANDIDATE.value:
                raise ValueError("Only candidate CharacterState records can be confirmed")

            confirmed_states = self.repository.confirmed_states_for_character(candidate.character_id, for_update=True)
            previous = None
            next_state = None
            for state in confirmed_states:
                if state.chapter_start <= candidate.chapter_start:
                    previous = state
                elif next_state is None:
                    next_state = state

            if previous is not None and candidate.chapter_start <= previous.chapter_start:
                raise ValueError("New CharacterState chapter_start must be after previous confirmed state")
            if next_state is not None:
                raise ValueError("Cannot confirm a CharacterState before an existing future confirmed state")

            if previous is not None:
                previous.chapter_end = candidate.chapter_start - 1

            candidate.status = ReviewStatus.CONFIRMED.value
            candidate.reviewed_at = datetime.now(UTC)
            candidate.reviewed_by = reviewer
            candidate.review_note = note
            self.repository.session.flush()

            self._assert_no_confirmed_overlap(candidate.character_id)
            return candidate

    def _validate_change_after(self, field: str, after) -> None:
        if field not in STATE_FIELDS:
            raise ValueError(f"Unsupported CharacterState field change: {field}")
        if field == "visual_keywords":
            if not isinstance(after, list) or not all(isinstance(item, str) for item in after):
                raise ValueError("visual_keywords change must be a list of strings")
            return
        if after is not None and not isinstance(after, str):
            raise ValueError(f"{field} change must be a string or null")

    def _assert_no_confirmed_overlap(self, character_id: uuid.UUID) -> None:
        states = self.repository.confirmed_states_for_character(character_id)
        for previous, current in zip(states, states[1:], strict=False):
            previous_end = previous.chapter_end if previous.chapter_end is not None else float("inf")
            if previous_end >= current.chapter_start:
                raise ValueError("Confirmed CharacterState ranges overlap")
