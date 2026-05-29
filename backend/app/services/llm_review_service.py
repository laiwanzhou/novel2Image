from dataclasses import dataclass
import json
import uuid

from app.core.enums import ReviewStatus
from app.models.state import CharacterStateChange
from app.providers.llm import LlmProvider
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.states import StateRepository
from app.services.state_service import STATE_FIELDS, StateService


REVIEW_DECISIONS = {"confirm", "reject", "needs_human"}


@dataclass(frozen=True)
class ReviewDecision:
    target_type: str
    target_id: uuid.UUID
    decision: str
    confidence: float
    reason: str
    risk_flags: list[str]
    applied: bool


class LlmReviewService:
    def __init__(
        self,
        *,
        state_repository: StateRepository,
        chunk_repository: ChunkRepository,
        character_repository: CharacterRepository,
        state_service: StateService,
        llm_provider: LlmProvider,
    ) -> None:
        self.state_repository = state_repository
        self.chunk_repository = chunk_repository
        self.character_repository = character_repository
        self.state_service = state_service
        self.llm_provider = llm_provider

    def review_state_change_candidate(
        self,
        state_change_id: uuid.UUID,
        *,
        auto_apply: bool = False,
        confidence_threshold: float = 0.85,
    ) -> ReviewDecision:
        state_change = self._require_candidate_state_change(state_change_id)
        response = self.llm_provider.generate_review_json(
            self._system_prompt(),
            self._user_prompt(state_change),
        )
        decision = self._parse_review_decision(state_change.id, response)
        applied = False
        if auto_apply and decision.confidence >= confidence_threshold:
            note = self._review_note(decision)
            if decision.decision == "confirm":
                self.state_service.confirm_state_change(state_change.id, "llm-reviewer", note)
                applied = True
            elif decision.decision == "reject":
                self.state_service.reject_state_change(state_change.id, "llm-reviewer", note)
                applied = True

        return ReviewDecision(
            target_type=decision.target_type,
            target_id=decision.target_id,
            decision=decision.decision,
            confidence=decision.confidence,
            reason=decision.reason,
            risk_flags=decision.risk_flags,
            applied=applied,
        )

    def batch_review_state_changes(
        self,
        *,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        character_id: uuid.UUID | None = None,
        auto_apply: bool = False,
        limit: int | None = None,
        confidence_threshold: float = 0.85,
    ) -> list[ReviewDecision]:
        state_changes = self.state_repository.list_state_changes(
            novel_id=novel_id,
            chapter_id=chapter_id,
            character_id=character_id,
            status=ReviewStatus.CANDIDATE.value,
        )
        if limit is not None:
            state_changes = state_changes[:limit]
        return [
            self.review_state_change_candidate(
                state_change.id,
                auto_apply=auto_apply,
                confidence_threshold=confidence_threshold,
            )
            for state_change in state_changes
        ]

    def _require_candidate_state_change(self, state_change_id: uuid.UUID) -> CharacterStateChange:
        state_change = self.state_repository.get_state_change(state_change_id)
        if state_change is None:
            raise ValueError(f"CharacterStateChange not found: {state_change_id}")
        if state_change.status != ReviewStatus.CANDIDATE.value:
            raise ValueError("Only candidate CharacterStateChange records can be reviewed by LLM")
        return state_change

    def _parse_review_decision(self, target_id: uuid.UUID, response: dict) -> ReviewDecision:
        decision = response.get("decision")
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"Invalid review decision from LLM: {decision}")
        confidence = response.get("confidence")
        if not isinstance(confidence, int | float):
            raise ValueError("LLM review response requires numeric confidence")
        reason = response.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("LLM review response requires reason")
        risk_flags = response.get("risk_flags", [])
        if not isinstance(risk_flags, list) or not all(isinstance(flag, str) for flag in risk_flags):
            raise ValueError("LLM review response risk_flags must be a list of strings")
        return ReviewDecision(
            target_type="state_change",
            target_id=target_id,
            decision=decision,
            confidence=float(confidence),
            reason=reason,
            risk_flags=risk_flags,
            applied=False,
        )

    def _review_note(self, decision: ReviewDecision) -> str:
        flags = ",".join(decision.risk_flags) if decision.risk_flags else "-"
        return (
            f"llm-reviewer decision={decision.decision}; "
            f"confidence={decision.confidence:g}; "
            f"reason={decision.reason}; "
            f"risk_flags={flags}"
        )

    def _system_prompt(self) -> str:
        fields = "|".join(sorted(STATE_FIELDS))
        return f"""
You review candidate CharacterStateChange records. Return valid JSON only.

Output schema:
{{
  "decision": "confirm|reject|needs_human",
  "confidence": 0.0,
  "reason": "brief explanation",
  "risk_flags": ["temporary_state", "unsupported_by_evidence", "duplicate", "conflicts_with_current_state"]
}}

Rules:
- confirm only when the change is durable, supported by evidence chunks, connected to a long-term event, and not duplicate.
- reject temporary emotion, action, pose, location, one-off dialogue, unsupported changes, duplicate changes, or mismatched event/change pairs.
- use needs_human for ambiguity, weak evidence, or important identity/relationship/motivation uncertainty.
- changed_fields must be from this whitelist: {fields}.
- Do not synthesize CharacterState and do not invent evidence.
""".strip()

    def _user_prompt(self, state_change: CharacterStateChange) -> str:
        character = self.character_repository.get_character(state_change.character_id) if state_change.character_id else None
        event = self.state_repository.get_event(state_change.event_id) if state_change.event_id else None
        chunk_ids = self._collect_chunk_ids(state_change)
        chunks = self.chunk_repository.list_chunks_by_ids([uuid.UUID(chunk_id) for chunk_id in chunk_ids])
        latest_state = (
            self.state_repository.latest_confirmed_state_before_or_at(
                state_change.character_id,
                state_change.chapter_index,
            )
            if state_change.character_id is not None
            else None
        )
        confirmed_peer_changes = [
            {
                "id": str(peer.id),
                "changed_fields": peer.changed_fields,
                "explanation": peer.explanation,
            }
            for peer in self.state_repository.list_state_changes(
                novel_id=state_change.novel_id,
                chapter_id=state_change.chapter_id,
                character_id=state_change.character_id,
                status=ReviewStatus.CONFIRMED.value,
            )
        ]
        payload = {
            "state_change": {
                "id": str(state_change.id),
                "character_id": str(state_change.character_id) if state_change.character_id else None,
                "character_name": character.canonical_name if character else None,
                "chapter_index": state_change.chapter_index,
                "changed_fields": state_change.changed_fields,
                "source_chunk_ids": state_change.source_chunk_ids,
                "confidence": state_change.confidence,
                "explanation": state_change.explanation,
            },
            "event": None
            if event is None
            else {
                "id": str(event.id),
                "event_summary": event.event_summary,
                "event_type": event.event_type,
                "is_long_term_change": event.is_long_term_change,
                "affected_fields": event.affected_fields,
                "source_chunk_ids": event.source_chunk_ids,
                "explanation": event.explanation,
                "status": event.status,
            },
            "evidence_chunks": [
                {
                    "id": str(chunk.id),
                    "chapter_index": chunk.chapter_index,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                }
                for chunk in chunks
            ],
            "latest_confirmed_state": None
            if latest_state is None
            else {
                "id": str(latest_state.id),
                "chapter_start": latest_state.chapter_start,
                "chapter_end": latest_state.chapter_end,
                "appearance": latest_state.appearance,
                "personality": latest_state.personality,
                "identity": latest_state.identity,
                "motivation": latest_state.motivation,
                "relationship_summary": latest_state.relationship_summary,
                "visual_keywords": latest_state.visual_keywords,
                "negative_prompt": latest_state.negative_prompt,
            },
            "confirmed_peer_state_changes": confirmed_peer_changes,
        }
        return f"Review this candidate and return only JSON:\n{json.dumps(payload, ensure_ascii=False)}"

    def _collect_chunk_ids(self, state_change: CharacterStateChange) -> list[str]:
        chunk_ids: list[str] = []
        for chunk_id in state_change.source_chunk_ids or []:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        for changed_field in state_change.changed_fields or []:
            for chunk_id in changed_field.get("source_chunk_ids") or []:
                if chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
        return chunk_ids
