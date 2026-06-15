from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.core.enums import ReviewStatus  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.models.novel import Chapter  # noqa: E402
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange  # noqa: E402
from app.providers.llm import LlmProvider, get_llm_provider  # noqa: E402
from app.repositories.characters import CharacterRepository  # noqa: E402
from app.repositories.chunks import ChunkRepository  # noqa: E402
from app.repositories.states import StateRepository  # noqa: E402
from app.services.extraction_service import ExtractionService  # noqa: E402
from app.services.llm_review_service import LlmReviewService, ReviewDecision  # noqa: E402
from app.services.state_service import StateService  # noqa: E402


AUTO_REJECT_FLAGS = {
    "duplicate",
    "unsupported_by_evidence",
    "conflicts_with_current_state",
    "temporary_state",
}


@dataclass(frozen=True)
class FullAutoPipelineOptions:
    novel_id: uuid.UUID
    chapter_start: int
    chapter_end: int
    block_size: int = 20
    auto_confirm_events: bool = False
    auto_review_state_changes: bool = False
    auto_apply_reviewer_decisions: bool = False
    auto_synthesize_states: bool = False
    auto_confirm_synthesized_states: bool = False
    auto_seed_missing_character_states: bool = False
    confirm_threshold: float = 0.85
    reject_threshold: float = 0.9
    extraction_max_retries: int | None = None
    continue_on_error: bool = True
    force_reextract: bool = False
    log_dir: Path = Path(".pipeline-runs/full-auto")


def run_full_auto_pipeline(
    session: Session,
    options: FullAutoPipelineOptions,
    *,
    extraction_provider: LlmProvider,
    review_provider: LlmProvider,
) -> dict[str, Any]:
    log_dir = Path(options.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    state_repository = StateRepository(session)
    chunk_repository = ChunkRepository(session)
    character_repository = CharacterRepository(session)
    state_service = StateService(state_repository)
    review_service = LlmReviewService(
        state_repository=state_repository,
        chunk_repository=chunk_repository,
        character_repository=character_repository,
        state_service=state_service,
        llm_provider=review_provider,
    )
    reusable_decisions = _load_reusable_review_decisions(log_dir.parent)

    chapters = _list_chapters(session, options)
    summary = _empty_summary(options, total_chapters=len(chapters))

    for block_start in range(options.chapter_start, options.chapter_end + 1, options.block_size):
        block_end = min(block_start + options.block_size - 1, options.chapter_end)
        block_dir = log_dir / f"block-{block_start:03d}-{block_end:03d}"
        block_dir.mkdir(parents=True, exist_ok=True)
        block_summary = _empty_block_summary(block_start, block_end)
        block_chapters = [chapter for chapter in chapters if block_start <= chapter.chapter_index <= block_end]

        for chapter in block_chapters:
            chapter_log = log_dir / f"chapter-{chapter.chapter_index:04d}.jsonl"
            try:
                before_event_ids = _event_ids(state_repository, options.novel_id)
                before_change_ids = _state_change_ids(state_repository, options.novel_id)
                if _chapter_has_extraction(state_repository, options.novel_id, chapter.id) and not options.force_reextract:
                    summary["skipped_extraction_chapters"].append(chapter.chapter_index)
                    block_summary["skipped_extraction_chapters"].append(chapter.chapter_index)
                    _append_log(chapter_log, {"type": "skipped_extraction", "chapter_index": chapter.chapter_index})
                else:
                    extraction_service = ExtractionService(
                        state_repository=state_repository,
                        chunk_repository=chunk_repository,
                        character_repository=character_repository,
                        llm_provider=extraction_provider,
                        auto_confirm_events=options.auto_confirm_events,
                        extraction_max_retries=options.extraction_max_retries,
                    )
                    extraction = extraction_service.extract_chapter_candidates(chapter.id)
                    new_events = [event for event in extraction.events if event.id not in before_event_ids]
                    new_changes = [change for change in extraction.state_changes if change.id not in before_change_ids]
                    _count_created(summary, block_summary, new_events, new_changes)
                    _append_log(
                        chapter_log,
                        {
                            "type": "extraction",
                            "chapter_index": chapter.chapter_index,
                            "event_ids": [str(event.id) for event in new_events],
                            "state_change_ids": [str(change.id) for change in new_changes],
                            "retry_count": extraction_service.last_retry_count,
                            "normalized_event_types": extraction_service.last_normalized_event_types,
                            "normalized_source_chunk_ids": extraction_service.last_normalized_source_chunk_ids,
                        },
                    )

                summary["processed_chapters"].append(chapter.chapter_index)
                block_summary["processed_chapters"].append(chapter.chapter_index)

                if options.auto_review_state_changes:
                    decisions = _review_and_apply_chapter_state_changes(
                        state_repository=state_repository,
                        state_service=state_service,
                        review_service=review_service,
                        chapter=chapter,
                        options=options,
                        reusable_decisions=reusable_decisions,
                    )
                    for decision in decisions:
                        _count_decision(summary, block_summary, decision, options)
                    _append_log(
                        chapter_log,
                        {"type": "review", "chapter_index": chapter.chapter_index, "decisions": decisions},
                    )

                if options.auto_synthesize_states:
                    syntheses = _synthesize_chapter_states(
                        session=session,
                        state_repository=state_repository,
                        state_service=state_service,
                        chapter=chapter,
                        options=options,
                    )
                    for synthesis in syntheses:
                        _count_synthesis(summary, block_summary, synthesis)
                    _append_log(
                        chapter_log,
                        {"type": "synthesis", "chapter_index": chapter.chapter_index, "results": syntheses},
                    )

                session.commit()
            except Exception as exc:
                session.rollback()
                failure = {
                    "chapter_index": chapter.chapter_index,
                    "chapter_id": str(chapter.id),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                summary["failed_chapters"].append(failure)
                block_summary["failed_chapters"].append(failure)
                summary["extraction_failure_count"] += 1
                _append_log(chapter_log, {"type": "failed", **failure})
                if not options.continue_on_error:
                    break

        _fill_counts(session, options, block_summary, range_start=block_start, range_end=block_end)
        block_report = _build_boundary_report(session, options, block_summary, block_start, block_end)
        _write_json(block_dir / "block_summary.json", block_summary)
        _write_json(block_dir / "block_boundary_report.json", block_report)

    _fill_counts(session, options, summary, range_start=options.chapter_start, range_end=options.chapter_end)
    _fill_final_observations(session, options, summary)
    _write_json(log_dir / "full_auto_summary.json", summary)
    _write_markdown_report(log_dir / "full_auto_report.md", summary)
    return summary


def _list_chapters(session: Session, options: FullAutoPipelineOptions) -> list[Chapter]:
    if options.chapter_end < options.chapter_start:
        raise ValueError("chapter_end must be greater than or equal to chapter_start")
    if options.block_size < 1:
        raise ValueError("block_size must be greater than zero")
    statement = (
        select(Chapter)
        .where(
            Chapter.novel_id == options.novel_id,
            Chapter.chapter_index >= options.chapter_start,
            Chapter.chapter_index <= options.chapter_end,
        )
        .order_by(Chapter.chapter_index)
    )
    return list(session.scalars(statement))


def _chapter_has_extraction(state_repository: StateRepository, novel_id: uuid.UUID, chapter_id: uuid.UUID) -> bool:
    return bool(state_repository.list_events(novel_id=novel_id, chapter_id=chapter_id)) or bool(
        state_repository.list_state_changes(novel_id=novel_id, chapter_id=chapter_id)
    )


def _event_ids(state_repository: StateRepository, novel_id: uuid.UUID) -> set[uuid.UUID]:
    return {event.id for event in state_repository.list_events(novel_id=novel_id)}


def _state_change_ids(state_repository: StateRepository, novel_id: uuid.UUID) -> set[uuid.UUID]:
    return {change.id for change in state_repository.list_state_changes(novel_id=novel_id)}


def _review_and_apply_chapter_state_changes(
    *,
    state_repository: StateRepository,
    state_service: StateService,
    review_service: LlmReviewService,
    chapter: Chapter,
    options: FullAutoPipelineOptions,
    reusable_decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = state_repository.list_state_changes(
        novel_id=options.novel_id,
        chapter_id=chapter.id,
        status=ReviewStatus.CANDIDATE.value,
    )
    payloads: list[dict[str, Any]] = []
    for state_change in candidates:
        reusable = reusable_decisions.get(str(state_change.id))
        if reusable is None:
            try:
                decision = review_service.review_state_change_candidate(
                    state_change.id,
                    auto_apply=False,
                    confidence_threshold=options.confirm_threshold,
                )
                payload = _decision_payload(decision, applied=False, reused=False)
            except Exception as exc:
                payload = {
                    "target_type": "state_change",
                    "target_id": str(state_change.id),
                    "decision": "review_failed",
                    "confidence": 0.0,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "risk_flags": [],
                    "applied": False,
                    "reused": False,
                }
        else:
            payload = {**reusable, "applied": False, "reused": True}

        if options.auto_apply_reviewer_decisions:
            payload["applied"] = _apply_decision_if_allowed(state_service, payload, options)
        payloads.append(payload)
    return payloads


def _apply_decision_if_allowed(
    state_service: StateService,
    payload: dict[str, Any],
    options: FullAutoPipelineOptions,
) -> bool:
    if payload["decision"] == "confirm" and payload["confidence"] >= options.confirm_threshold:
        state_service.confirm_state_change(uuid.UUID(payload["target_id"]), "llm-reviewer", _review_note(payload))
        return True
    if (
        payload["decision"] == "reject"
        and payload["confidence"] >= options.reject_threshold
        and AUTO_REJECT_FLAGS.intersection(payload["risk_flags"])
    ):
        state_service.reject_state_change(uuid.UUID(payload["target_id"]), "llm-reviewer", _review_note(payload))
        return True
    return False


def _synthesize_chapter_states(
    *,
    session: Session,
    state_repository: StateRepository,
    state_service: StateService,
    chapter: Chapter,
    options: FullAutoPipelineOptions,
) -> list[dict[str, Any]]:
    confirmed_changes = state_repository.list_state_changes(
        novel_id=options.novel_id,
        chapter_id=chapter.id,
        status=ReviewStatus.CONFIRMED.value,
    )
    results: list[dict[str, Any]] = []
    synthesized_keys: set[tuple[uuid.UUID, int]] = set()
    for state_change in confirmed_changes:
        existing = session.scalar(select(CharacterState).where(CharacterState.state_change_id == state_change.id).limit(1))
        if existing is not None:
            synthesized_keys.add((state_change.character_id, state_change.chapter_index))
            results.append(
                {
                    "state_change_id": str(state_change.id),
                    "state_id": str(existing.id),
                    "created": False,
                    "confirmed": existing.status == ReviewStatus.CONFIRMED.value,
                    "skipped_same_chapter": False,
                    "error": None,
                }
            )
            continue
        same_chapter_state = session.scalar(
            select(CharacterState)
            .where(
                CharacterState.novel_id == state_change.novel_id,
                CharacterState.character_id == state_change.character_id,
                CharacterState.chapter_start == state_change.chapter_index,
                CharacterState.state_change_id.is_not(None),
            )
            .order_by(CharacterState.created_at)
            .limit(1)
        )
        key = (state_change.character_id, state_change.chapter_index)
        if same_chapter_state is not None or key in synthesized_keys:
            results.append(
                {
                    "state_change_id": str(state_change.id),
                    "state_id": str(same_chapter_state.id) if same_chapter_state is not None else None,
                    "created": False,
                    "confirmed": same_chapter_state.status == ReviewStatus.CONFIRMED.value
                    if same_chapter_state is not None
                    else False,
                    "seeded_state_id": None,
                    "skipped_same_chapter": True,
                    "error": None,
                }
            )
            continue
        try:
            with session.begin_nested():
                seeded_state = None
                if options.auto_seed_missing_character_states:
                    seeded_state = _seed_missing_character_state_if_needed(
                        session=session,
                        state_repository=state_repository,
                        state_change=state_change,
                    )
                state = state_service.synthesize_candidate_from_change(state_change.id)
                confirmed = False
                if options.auto_confirm_synthesized_states:
                    state_service.confirm_state(
                        state.id,
                        "full-auto-pipeline",
                        "auto-confirmed synthesized state from confirmed state_change",
                    )
                    confirmed = True
            results.append(
                {
                    "state_change_id": str(state_change.id),
                    "state_id": str(state.id),
                    "created": True,
                    "confirmed": confirmed,
                    "seeded_state_id": str(seeded_state.id) if seeded_state is not None else None,
                    "skipped_same_chapter": False,
                    "error": None,
                }
            )
            synthesized_keys.add(key)
        except Exception as exc:
            results.append(
                {
                    "state_change_id": str(state_change.id),
                    "state_id": None,
                    "created": False,
                    "confirmed": False,
                    "seeded_state_id": None,
                    "skipped_same_chapter": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results


def _seed_missing_character_state_if_needed(
    *,
    session: Session,
    state_repository: StateRepository,
    state_change: CharacterStateChange,
) -> CharacterState | None:
    if state_change.character_id is None:
        return None
    previous = state_repository.latest_confirmed_state_before_or_at(
        state_change.character_id,
        state_change.chapter_index,
    )
    if previous is not None:
        return None
    character = session.get(Character, state_change.character_id)
    values = _seed_values(character, state_change)
    seed = CharacterState(
        novel_id=state_change.novel_id,
        character_id=state_change.character_id,
        chapter_start=max(0, state_change.chapter_index - 1),
        chapter_end=None,
        appearance=values["appearance"],
        personality=values["personality"],
        identity=values["identity"],
        motivation=values["motivation"],
        relationship_summary=values["relationship_summary"],
        visual_keywords=values["visual_keywords"],
        negative_prompt=values["negative_prompt"],
        source_chapters=[state_change.chapter_index],
        source_chunk_ids=state_change.source_chunk_ids,
        event_id=None,
        state_change_id=None,
        confidence=state_change.confidence,
        status=ReviewStatus.CONFIRMED.value,
        reviewed_at=datetime.now(UTC),
        reviewed_by="full-auto-pipeline",
        review_note="auto-seeded missing initial CharacterState before synthesis",
    )
    return state_repository.add_state(seed)


def _seed_values(character: Character | None, state_change: CharacterStateChange) -> dict[str, Any]:
    values: dict[str, Any] = {
        "appearance": None,
        "personality": None,
        "identity": character.canonical_name if character is not None else None,
        "motivation": None,
        "relationship_summary": None,
        "visual_keywords": [],
        "negative_prompt": None,
    }
    for change in state_change.changed_fields or []:
        field = change.get("field")
        before = change.get("before")
        if field == "visual_keywords" and isinstance(before, list) and all(isinstance(item, str) for item in before):
            values[field] = before
        elif field in values and field != "visual_keywords" and (before is None or isinstance(before, str)):
            values[field] = before
    if not values["identity"] and character is not None:
        values["identity"] = character.canonical_name
    return values


def _load_reusable_review_decisions(root: Path) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return decisions
    for path in sorted(root.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for decision in payload.get("decisions", []) if payload.get("type") == "review" else []:
                target_id = decision.get("target_id")
                if target_id:
                    decisions[target_id] = {
                        "target_type": decision.get("target_type", "state_change"),
                        "target_id": target_id,
                        "decision": decision.get("decision"),
                        "confidence": float(decision.get("confidence") or 0),
                        "reason": decision.get("reason") or "",
                        "risk_flags": list(decision.get("risk_flags") or []),
                    }
    return decisions


def _empty_summary(options: FullAutoPipelineOptions, *, total_chapters: int) -> dict[str, Any]:
    return {
        "total_chapters": total_chapters,
        "processed_chapters": [],
        "skipped_chapters": [],
        "skipped_extraction_chapters": [],
        "failed_chapters": [],
        "extraction_failure_count": 0,
        "reviewer_failure_count": 0,
        "synthesis_failure_count": 0,
        "event_created_count": 0,
        "event_confirmed_count": 0,
        "state_change_created_count": 0,
        "state_change_confirmed_count": 0,
        "state_change_rejected_count": 0,
        "state_change_candidate_remaining_count": 0,
        "reviewer_decision_distribution": {"confirm": 0, "reject": 0, "needs_human": 0},
        "auto_confirmed_state_change_count": 0,
        "auto_rejected_state_change_count": 0,
        "needs_human_count": 0,
        "low_confidence_remaining_count": 0,
        "synthesized_state_count": 0,
        "synthesis_skipped_same_chapter_count": 0,
        "auto_confirmed_state_count": 0,
        "seeded_state_count": 0,
        "per_character_state_count": {},
        "per_character_latest_state_at_end": {},
        "chapters_with_unusually_many_events": [],
        "chapters_with_unusually_many_state_changes": [],
        "duplicate_or_conflict_warnings": [],
        "continuity_warnings": [],
        "top_failure_reasons": {},
        "full_auto_quality_observations": [],
        "confirm_threshold": options.confirm_threshold,
        "reject_threshold": options.reject_threshold,
    }


def _empty_block_summary(block_start: int, block_end: int) -> dict[str, Any]:
    return {
        "block_start": block_start,
        "block_end": block_end,
        "processed_chapters": [],
        "skipped_extraction_chapters": [],
        "failed_chapters": [],
        "event_created_count": 0,
        "event_confirmed_count": 0,
        "state_change_created_count": 0,
        "state_change_confirmed_count": 0,
        "state_change_rejected_count": 0,
        "state_change_candidate_remaining_count": 0,
        "reviewer_decision_distribution": {"confirm": 0, "reject": 0, "needs_human": 0},
        "auto_confirmed_state_change_count": 0,
        "auto_rejected_state_change_count": 0,
        "needs_human_count": 0,
        "low_confidence_remaining_count": 0,
        "synthesized_state_count": 0,
        "synthesis_skipped_same_chapter_count": 0,
        "auto_confirmed_state_count": 0,
        "seeded_state_count": 0,
        "synthesis_failure_count": 0,
        "reviewer_failure_count": 0,
        "warnings": [],
    }


def _count_created(
    summary: dict[str, Any],
    block_summary: dict[str, Any],
    events: list[CharacterEvent],
    changes: list[CharacterStateChange],
) -> None:
    for target in (summary, block_summary):
        target["event_created_count"] += len(events)
        target["event_confirmed_count"] += sum(1 for event in events if event.status == ReviewStatus.CONFIRMED.value)
        target["state_change_created_count"] += len(changes)


def _count_decision(
    summary: dict[str, Any],
    block_summary: dict[str, Any],
    payload: dict[str, Any],
    options: FullAutoPipelineOptions,
) -> None:
    decision = payload["decision"]
    targets = (summary, block_summary)
    if decision == "review_failed":
        for target in targets:
            target["reviewer_failure_count"] += 1
        return
    for target in targets:
        if decision in target["reviewer_decision_distribution"]:
            target["reviewer_decision_distribution"][decision] += 1
        if decision == "needs_human":
            target["needs_human_count"] += 1
        if decision in {"confirm", "reject"} and not payload["applied"]:
            threshold = options.confirm_threshold if decision == "confirm" else options.reject_threshold
            if payload["confidence"] < threshold:
                target["low_confidence_remaining_count"] += 1
        if payload["applied"] and decision == "confirm":
            target["auto_confirmed_state_change_count"] += 1
        if payload["applied"] and decision == "reject":
            target["auto_rejected_state_change_count"] += 1


def _count_synthesis(summary: dict[str, Any], block_summary: dict[str, Any], payload: dict[str, Any]) -> None:
    for target in (summary, block_summary):
        if payload["error"]:
            target["synthesis_failure_count"] += 1
        if payload["created"]:
            target["synthesized_state_count"] += 1
        if payload.get("skipped_same_chapter"):
            target["synthesis_skipped_same_chapter_count"] += 1
        if payload["confirmed"]:
            target["auto_confirmed_state_count"] += 1
        if payload.get("seeded_state_id"):
            target["seeded_state_count"] += 1


def _fill_counts(
    session: Session,
    options: FullAutoPipelineOptions,
    summary: dict[str, Any],
    *,
    range_start: int,
    range_end: int,
) -> None:
    state_repository = StateRepository(session)
    events = [
        event
        for event in state_repository.list_events(novel_id=options.novel_id)
        if range_start <= event.chapter_index <= range_end
    ]
    changes = [
        change
        for change in state_repository.list_state_changes(novel_id=options.novel_id)
        if range_start <= change.chapter_index <= range_end
    ]
    summary["state_change_confirmed_count"] = sum(
        1 for change in changes if change.status == ReviewStatus.CONFIRMED.value
    )
    summary["state_change_rejected_count"] = sum(1 for change in changes if change.status == ReviewStatus.REJECTED.value)
    summary["state_change_candidate_remaining_count"] = sum(
        1 for change in changes if change.status == ReviewStatus.CANDIDATE.value
    )
    summary["event_confirmed_count"] = sum(1 for event in events if event.status == ReviewStatus.CONFIRMED.value)


def _fill_final_observations(session: Session, options: FullAutoPipelineOptions, summary: dict[str, Any]) -> None:
    state_repository = StateRepository(session)
    states = [
        state
        for state in session.scalars(select(CharacterState).where(CharacterState.novel_id == options.novel_id))
        if state.status == ReviewStatus.CONFIRMED.value
    ]
    by_character: dict[str, list[CharacterState]] = defaultdict(list)
    for state in states:
        by_character[str(state.character_id)].append(state)
    for character_id, character_states in by_character.items():
        ordered = sorted(character_states, key=lambda state: (state.chapter_start, state.created_at))
        summary["per_character_state_count"][character_id] = len(ordered)
        latest = ordered[-1]
        summary["per_character_latest_state_at_end"][character_id] = {
            "id": str(latest.id),
            "chapter_start": latest.chapter_start,
            "chapter_end": latest.chapter_end,
            "identity": latest.identity,
            "motivation": latest.motivation,
            "relationship_summary": latest.relationship_summary,
        }
        starts = [state.chapter_start for state in ordered]
        if len(starts) != len(set(starts)):
            summary["duplicate_or_conflict_warnings"].append(
                f"Character {character_id} has multiple confirmed states starting at the same chapter"
            )
        if ordered and ordered[-1].chapter_start < options.chapter_end - 20:
            summary["continuity_warnings"].append(
                f"Character {character_id} latest confirmed state may be stale at chapter {ordered[-1].chapter_start}"
            )

    chapter_event_counts = Counter(
        event.chapter_index for event in state_repository.list_events(novel_id=options.novel_id)
    )
    summary["chapters_with_unusually_many_events"] = [
        {"chapter_index": chapter_index, "count": count}
        for chapter_index, count in chapter_event_counts.items()
        if count >= 8
    ]
    chapter_change_counts = Counter(
        change.chapter_index for change in state_repository.list_state_changes(novel_id=options.novel_id)
    )
    summary["chapters_with_unusually_many_state_changes"] = [
        {"chapter_index": chapter_index, "count": count}
        for chapter_index, count in chapter_change_counts.items()
        if count >= 5
    ]
    failure_reasons = Counter(failure["error"] for failure in summary["failed_chapters"])
    summary["top_failure_reasons"] = dict(failure_reasons.most_common(10))
    if summary["state_change_candidate_remaining_count"]:
        summary["full_auto_quality_observations"].append("Some state_change candidates remain after full-auto run")
    if summary["synthesis_failure_count"]:
        summary["full_auto_quality_observations"].append("Some confirmed state_changes failed CharacterState synthesis")


def _build_boundary_report(
    session: Session,
    options: FullAutoPipelineOptions,
    block_summary: dict[str, Any],
    block_start: int,
    block_end: int,
) -> dict[str, Any]:
    state_repository = StateRepository(session)
    block_changes = [
        change
        for change in state_repository.list_state_changes(novel_id=options.novel_id)
        if block_start <= change.chapter_index <= block_end
    ]
    latest_states: dict[str, Any] = {}
    pending_important: list[dict[str, Any]] = []
    confirmed_not_synthesized: list[str] = []
    warnings: list[str] = list(block_summary.get("warnings", []))
    important_fields = {"identity", "relationship_summary", "motivation"}
    for character_id_text in sorted({str(change.character_id) for change in block_changes if change.character_id}):
        character_id = uuid.UUID(character_id_text)
        latest = state_repository.latest_confirmed_state_before_or_at(character_id, block_end)
        if latest:
            latest_states[character_id_text] = {
                "id": str(latest.id),
                "chapter_start": latest.chapter_start,
                "chapter_end": latest.chapter_end,
            }
        pending = [
            change
            for change in block_changes
            if str(change.character_id) == character_id_text and change.status == ReviewStatus.CANDIDATE.value
        ]
        for change in pending:
            fields = [field.get("field") for field in change.changed_fields or []]
            if important_fields.intersection(fields):
                pending_important.append(
                    {
                        "id": str(change.id),
                        "character_id": character_id_text,
                        "chapter_index": change.chapter_index,
                        "changed_fields": fields,
                    }
                )
                warnings.append(f"Pending important state_change {change.id} may affect next block")
        confirmed = [
            change
            for change in block_changes
            if str(change.character_id) == character_id_text and change.status == ReviewStatus.CONFIRMED.value
        ]
        for change in confirmed:
            synthesized = session.scalar(
                select(CharacterState).where(CharacterState.state_change_id == change.id).limit(1)
            )
            if synthesized is None:
                confirmed_not_synthesized.append(str(change.id))
                warnings.append(f"Confirmed state_change {change.id} has not been synthesized")
    return {
        **block_summary,
        "per_character_latest_confirmed_state_at_block_end": latest_states,
        "candidate_state_changes_that_may_affect_next_block": pending_important,
        "confirmed_state_changes_not_synthesized": confirmed_not_synthesized,
        "warnings": warnings,
    }


def _decision_payload(decision: ReviewDecision, *, applied: bool, reused: bool) -> dict[str, Any]:
    return {
        "target_type": decision.target_type,
        "target_id": str(decision.target_id),
        "decision": decision.decision,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "risk_flags": decision.risk_flags,
        "applied": applied,
        "reused": reused,
    }


def _review_note(payload: dict[str, Any]) -> str:
    flags = ",".join(payload["risk_flags"]) if payload["risk_flags"] else "-"
    return (
        f"llm-reviewer decision={payload['decision']}; "
        f"confidence={payload['confidence']:g}; "
        f"reason={payload['reason']}; "
        f"risk_flags={flags}"
    )


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    payload = {"created_at": datetime.now(UTC).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_jsonable(payload), ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Full Auto Pipeline Report",
        "",
        f"- total_chapters: {summary['total_chapters']}",
        f"- processed_chapters: {len(summary['processed_chapters'])}",
        f"- failed_chapters: {len(summary['failed_chapters'])}",
        f"- event_confirmed_count: {summary['event_confirmed_count']}",
        f"- state_change_confirmed_count: {summary['state_change_confirmed_count']}",
        f"- state_change_rejected_count: {summary['state_change_rejected_count']}",
        f"- state_change_candidate_remaining_count: {summary['state_change_candidate_remaining_count']}",
        f"- synthesized_state_count: {summary['synthesized_state_count']}",
        f"- auto_confirmed_state_count: {summary['auto_confirmed_state_count']}",
        f"- seeded_state_count: {summary['seeded_state_count']}",
        "",
        "## Quality Observations",
        "",
        *(f"- {item}" for item in summary["full_auto_quality_observations"]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _jsonable(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def parse_args(argv: list[str] | None = None) -> FullAutoPipelineOptions:
    parser = argparse.ArgumentParser(description="Run an experimental full-auto novel pipeline.")
    parser.add_argument("--novel-id", required=True, type=uuid.UUID)
    parser.add_argument("--chapter-start", required=True, type=int)
    parser.add_argument("--chapter-end", required=True, type=int)
    parser.add_argument("--block-size", type=int, default=20)
    parser.add_argument("--auto-confirm-events", action="store_true")
    parser.add_argument("--auto-review-state-changes", action="store_true")
    parser.add_argument("--auto-apply-reviewer-decisions", action="store_true")
    parser.add_argument("--auto-synthesize-states", action="store_true")
    parser.add_argument("--auto-confirm-synthesized-states", action="store_true")
    parser.add_argument("--auto-seed-missing-character-states", action="store_true")
    parser.add_argument("--confirm-threshold", type=float, default=0.85)
    parser.add_argument("--reject-threshold", type=float, default=0.9)
    parser.add_argument("--extraction-max-retries", type=int)
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    parser.add_argument("--stop-on-error", dest="continue_on_error", action="store_false")
    parser.add_argument("--force-reextract", action="store_true")
    parser.add_argument("--log-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    return FullAutoPipelineOptions(
        novel_id=args.novel_id,
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
        block_size=args.block_size,
        auto_confirm_events=args.auto_confirm_events,
        auto_review_state_changes=args.auto_review_state_changes,
        auto_apply_reviewer_decisions=args.auto_apply_reviewer_decisions,
        auto_synthesize_states=args.auto_synthesize_states,
        auto_confirm_synthesized_states=args.auto_confirm_synthesized_states,
        auto_seed_missing_character_states=args.auto_seed_missing_character_states,
        confirm_threshold=args.confirm_threshold,
        reject_threshold=args.reject_threshold,
        extraction_max_retries=args.extraction_max_retries,
        continue_on_error=args.continue_on_error,
        force_reextract=args.force_reextract,
        log_dir=args.log_dir,
    )


def main(argv: list[str] | None = None) -> None:
    options = parse_args(argv)
    settings = get_settings()
    provider = get_llm_provider(
        settings.llm_provider,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        json_mode=settings.llm_json_mode,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    with SessionLocal() as session:
        summary = run_full_auto_pipeline(
            session,
            options,
            extraction_provider=provider,
            review_provider=provider,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
