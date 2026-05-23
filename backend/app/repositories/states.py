import uuid

from sqlalchemy import func, select

from app.models.state import CharacterEvent, CharacterState, CharacterStateChange
from app.repositories.base import BaseRepository


class StateRepository(BaseRepository[CharacterState]):
    def add_event(self, event: CharacterEvent) -> CharacterEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def add_state_change(self, state_change: CharacterStateChange) -> CharacterStateChange:
        self.session.add(state_change)
        self.session.flush()
        return state_change

    def add_state(self, state: CharacterState) -> CharacterState:
        self.session.add(state)
        self.session.flush()
        return state

    def get_state(self, state_id: uuid.UUID) -> CharacterState | None:
        return self.session.get(CharacterState, state_id)

    def get_state_change(self, state_change_id: uuid.UUID) -> CharacterStateChange | None:
        return self.session.get(CharacterStateChange, state_change_id)

    def get_event(self, event_id: uuid.UUID) -> CharacterEvent | None:
        return self.session.get(CharacterEvent, event_id)

    def list_events_by_ids(self, event_ids: list[uuid.UUID]) -> list[CharacterEvent]:
        if not event_ids:
            return []
        statement = select(CharacterEvent).where(CharacterEvent.id.in_(event_ids))
        events = {event.id: event for event in self.session.scalars(statement)}
        return [events[event_id] for event_id in event_ids if event_id in events]

    def list_events(
        self,
        *,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        character_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[CharacterEvent]:
        statement = select(CharacterEvent).where(CharacterEvent.novel_id == novel_id)
        if chapter_id is not None:
            statement = statement.where(CharacterEvent.chapter_id == chapter_id)
        if character_id is not None:
            statement = statement.where(CharacterEvent.character_id == character_id)
        if status is not None:
            statement = statement.where(CharacterEvent.status == status)
        statement = statement.order_by(CharacterEvent.chapter_index, CharacterEvent.created_at, CharacterEvent.id)
        return list(self.session.scalars(statement))

    def list_state_changes(
        self,
        *,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        character_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[CharacterStateChange]:
        statement = select(CharacterStateChange).where(CharacterStateChange.novel_id == novel_id)
        if chapter_id is not None:
            statement = statement.where(CharacterStateChange.chapter_id == chapter_id)
        if character_id is not None:
            statement = statement.where(CharacterStateChange.character_id == character_id)
        if status is not None:
            statement = statement.where(CharacterStateChange.status == status)
        statement = statement.order_by(
            CharacterStateChange.chapter_index,
            CharacterStateChange.created_at,
            CharacterStateChange.id,
        )
        return list(self.session.scalars(statement))

    def latest_confirmed_state_before_or_at(self, character_id: uuid.UUID, chapter_index: int) -> CharacterState | None:
        statement = (
            select(CharacterState)
            .where(
                CharacterState.character_id == character_id,
                CharacterState.status == "confirmed",
                CharacterState.chapter_start <= chapter_index,
            )
            .order_by(CharacterState.chapter_start.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def confirmed_states_covering(
        self,
        *,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        chapter_index: int,
    ) -> list[CharacterState]:
        statement = (
            select(CharacterState)
            .where(
                CharacterState.novel_id == novel_id,
                CharacterState.character_id == character_id,
                CharacterState.status == "confirmed",
                CharacterState.chapter_start <= chapter_index,
                (CharacterState.chapter_end >= chapter_index) | (CharacterState.chapter_end.is_(None)),
            )
            .order_by(CharacterState.chapter_start)
        )
        return list(self.session.scalars(statement))

    def recent_confirmed_events(
        self,
        *,
        character_id: uuid.UUID,
        chapter_index: int,
        limit: int,
    ) -> list[CharacterEvent]:
        statement = (
            select(CharacterEvent)
            .where(
                CharacterEvent.character_id == character_id,
                CharacterEvent.status == "confirmed",
                CharacterEvent.chapter_index <= chapter_index,
            )
            .order_by(CharacterEvent.chapter_index.desc(), CharacterEvent.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(statement))))

    def confirmed_states_for_character(self, character_id: uuid.UUID, *, for_update: bool = False) -> list[CharacterState]:
        statement = (
            select(CharacterState)
            .where(CharacterState.character_id == character_id, CharacterState.status == "confirmed")
            .order_by(CharacterState.chapter_start)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement))

    def list_states_for_character(self, character_id: uuid.UUID) -> list[CharacterState]:
        statement = (
            select(CharacterState)
            .where(CharacterState.character_id == character_id)
            .order_by(CharacterState.chapter_start, CharacterState.created_at)
        )
        return list(self.session.scalars(statement))

    def count_events(self, novel_id: uuid.UUID, status: str | None = None) -> int:
        statement = select(func.count()).select_from(CharacterEvent).where(CharacterEvent.novel_id == novel_id)
        if status is not None:
            statement = statement.where(CharacterEvent.status == status)
        return int(self.session.scalar(statement) or 0)

    def count_state_changes(self, novel_id: uuid.UUID, status: str | None = None) -> int:
        statement = select(func.count()).select_from(CharacterStateChange).where(CharacterStateChange.novel_id == novel_id)
        if status is not None:
            statement = statement.where(CharacterStateChange.status == status)
        return int(self.session.scalar(statement) or 0)

    def count_states(self, novel_id: uuid.UUID, status: str | None = None) -> int:
        statement = select(func.count()).select_from(CharacterState).where(CharacterState.novel_id == novel_id)
        if status is not None:
            statement = statement.where(CharacterState.status == status)
        return int(self.session.scalar(statement) or 0)

    def has_events_or_states_for_novel(self, novel_id: uuid.UUID) -> bool:
        event_statement = select(CharacterEvent.id).where(CharacterEvent.novel_id == novel_id).limit(1)
        if self.session.scalar(event_statement) is not None:
            return True

        state_change_statement = (
            select(CharacterStateChange.id).where(CharacterStateChange.novel_id == novel_id).limit(1)
        )
        if self.session.scalar(state_change_statement) is not None:
            return True

        state_statement = select(CharacterState.id).where(CharacterState.novel_id == novel_id).limit(1)
        return self.session.scalar(state_statement) is not None
