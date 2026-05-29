from __future__ import annotations

import argparse
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
from app.models.novel import Chapter  # noqa: E402
from app.models.state import CharacterState  # noqa: E402
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
class BlockPipelineOptions:
    novel_id: uuid.UUID
    chapter_start: int
    chapter_end: int
    auto_confirm_events: bool = False
    review_state_changes: bool = False
    review_dry_run: bool = True
    apply_high_confidence_rejects: bool = False
    auto_reject_threshold: float = 0.9
    limit_state_changes_per_chapter: int | None = None
    continue_on_error: bool = True
    log_dir: Path = Path(".pipeline-runs/block")
    skip_existing_logs: bool = False
    stop_before_next_block: bool = False


def run_chapter_block_pipeline(
    session: Session,
    options: BlockPipelineOptions,
    *,
    extraction_provider: LlmProvider,
    review_provider: LlmProvider,
) -> dict[str, Any]:
    log_dir = Path(options.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    chapters = _list_chapters(session, options)
    state_repository = StateRepository(session)
    chunk_repository = ChunkRepository(session)
    character_repository = CharacterRepository(session)
    state_service = StateService(state_repository)

    summary = _empty_summary(options)
    created_state_change_ids: list[uuid.UUID] = []

    for chapter in chapters:
        chapter_log = log_dir / f"chapter-{chapter.chapter_index:04d}.jsonl"
        if options.skip_existing_logs and chapter_log.exists():
            summary["skipped_chapters"].append(chapter.chapter_index)
            _append_log(chapter_log, {"type": "skipped", "chapter_index": chapter.chapter_index})
            continue

        try:
            before_event_ids = {event.id for event in state_repository.list_events(novel_id=options.novel_id)}
            before_change_ids = {
                change.id for change in state_repository.list_state_changes(novel_id=options.novel_id)
            }
            extraction = ExtractionService(
                state_repository=state_repository,
                chunk_repository=chunk_repository,
                character_repository=character_repository,
                llm_provider=extraction_provider,
                auto_confirm_events=options.auto_confirm_events,
            ).extract_chapter_candidates(chapter.id)
            new_events = [event for event in extraction.events if event.id not in before_event_ids]
            new_changes = [change for change in extraction.state_changes if change.id not in before_change_ids]
            created_state_change_ids.extend(change.id for change in new_changes)
            summary["processed_chapters"].append(chapter.chapter_index)
            summary["event_created_count"] += len(new_events)
            summary["event_confirmed_count"] += sum(
                1 for event in new_events if event.status == ReviewStatus.CONFIRMED.value
            )
            summary["state_change_created_count"] += len(new_changes)
            _append_log(
                chapter_log,
                {
                    "type": "extraction",
                    "chapter_index": chapter.chapter_index,
                    "event_ids": [str(event.id) for event in new_events],
                    "state_change_ids": [str(change.id) for change in new_changes],
                },
            )

            if options.review_state_changes:
                review_decisions = _review_chapter_state_changes(
                    state_repository=state_repository,
                    chunk_repository=chunk_repository,
                    character_repository=character_repository,
                    state_service=state_service,
                    review_provider=review_provider,
                    chapter=chapter,
                    options=options,
                )
                for payload in review_decisions:
                    _count_review_decision(summary, payload)
                _append_log(
                    chapter_log,
                    {
                        "type": "review",
                        "chapter_index": chapter.chapter_index,
                        "decisions": review_decisions,
                    },
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
            _append_log(chapter_log, {"type": "failed", **failure})
            if not options.continue_on_error:
                break

    _fill_db_counts(session, options, summary)
    report = _build_boundary_report(session, options, summary, created_state_change_ids)
    _write_json(log_dir / "block_summary.json", summary)
    _write_json(log_dir / "block_boundary_report.json", report)
    return summary


def _list_chapters(session: Session, options: BlockPipelineOptions) -> list[Chapter]:
    if options.chapter_end < options.chapter_start:
        raise ValueError("chapter_end must be greater than or equal to chapter_start")
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


def _review_chapter_state_changes(
    *,
    state_repository: StateRepository,
    chunk_repository: ChunkRepository,
    character_repository: CharacterRepository,
    state_service: StateService,
    review_provider: LlmProvider,
    chapter: Chapter,
    options: BlockPipelineOptions,
) -> list[dict[str, Any]]:
    service = LlmReviewService(
        state_repository=state_repository,
        chunk_repository=chunk_repository,
        character_repository=character_repository,
        state_service=state_service,
        llm_provider=review_provider,
    )
    candidates = state_repository.list_state_changes(
        novel_id=options.novel_id,
        chapter_id=chapter.id,
        status=ReviewStatus.CANDIDATE.value,
    )
    if options.limit_state_changes_per_chapter is not None:
        candidates = candidates[: options.limit_state_changes_per_chapter]

    decisions: list[dict[str, Any]] = []
    for state_change in candidates:
        decision = service.review_state_change_candidate(
            state_change.id,
            auto_apply=False,
            confidence_threshold=options.auto_reject_threshold,
        )
        applied = False
        if (
            options.apply_high_confidence_rejects
            and not options.review_dry_run
            and decision.decision == "reject"
            and decision.confidence >= options.auto_reject_threshold
            and AUTO_REJECT_FLAGS.intersection(decision.risk_flags)
        ):
            state_service.reject_state_change(
                state_change.id,
                "llm-reviewer",
                _review_note(decision),
            )
            applied = True
        decisions.append(_decision_payload(decision, applied=applied))
    return decisions


def _empty_summary(options: BlockPipelineOptions) -> dict[str, Any]:
    return {
        "block_start": options.chapter_start,
        "block_end": options.chapter_end,
        "auto_reject_threshold": options.auto_reject_threshold,
        "processed_chapters": [],
        "skipped_chapters": [],
        "failed_chapters": [],
        "event_created_count": 0,
        "event_confirmed_count": 0,
        "state_change_created_count": 0,
        "state_change_candidate_count": 0,
        "state_change_confirmed_count": 0,
        "state_change_rejected_count": 0,
        "reviewer_decision_distribution": {"confirm": 0, "reject": 0, "needs_human": 0},
        "high_confidence_reject_count": 0,
        "high_confidence_reject_applied_count": 0,
        "needs_human_count": 0,
        "warnings": [],
    }


def _count_review_decision(summary: dict[str, Any], decision: dict[str, Any]) -> None:
    if decision["decision"] in summary["reviewer_decision_distribution"]:
        summary["reviewer_decision_distribution"][decision["decision"]] += 1
    if decision["decision"] == "needs_human":
        summary["needs_human_count"] += 1
    if (
        decision["decision"] == "reject"
        and decision["confidence"] >= summary.get("auto_reject_threshold", 0.9)
        and AUTO_REJECT_FLAGS.intersection(decision["risk_flags"])
    ):
        summary["high_confidence_reject_count"] += 1
    if decision["applied"]:
        summary["high_confidence_reject_applied_count"] += 1


def _fill_db_counts(session: Session, options: BlockPipelineOptions, summary: dict[str, Any]) -> None:
    state_repository = StateRepository(session)
    block_changes = [
        change
        for change in state_repository.list_state_changes(novel_id=options.novel_id)
        if options.chapter_start <= change.chapter_index <= options.chapter_end
    ]
    summary["state_change_candidate_count"] = sum(
        1 for change in block_changes if change.status == ReviewStatus.CANDIDATE.value
    )
    summary["state_change_confirmed_count"] = sum(
        1 for change in block_changes if change.status == ReviewStatus.CONFIRMED.value
    )
    summary["state_change_rejected_count"] = sum(
        1 for change in block_changes if change.status == ReviewStatus.REJECTED.value
    )


def _build_boundary_report(
    session: Session,
    options: BlockPipelineOptions,
    summary: dict[str, Any],
    created_state_change_ids: list[uuid.UUID],
) -> dict[str, Any]:
    state_repository = StateRepository(session)
    block_changes = [
        change
        for change in state_repository.list_state_changes(novel_id=options.novel_id)
        if options.chapter_start <= change.chapter_index <= options.chapter_end
    ]
    character_ids = sorted({str(change.character_id) for change in block_changes if change.character_id is not None})
    latest_states: dict[str, Any] = {}
    pending_counts: dict[str, int] = {}
    candidate_may_affect_next: list[dict[str, Any]] = []
    confirmed_not_synthesized: list[str] = []
    warnings: list[str] = list(summary["warnings"])

    important_fields = {"identity", "relationship_summary", "motivation"}
    for character_id_text in character_ids:
        character_id = uuid.UUID(character_id_text)
        latest = state_repository.latest_confirmed_state_before_or_at(character_id, options.chapter_end)
        if latest is not None:
            latest_states[character_id_text] = {
                "id": str(latest.id),
                "chapter_start": latest.chapter_start,
                "chapter_end": latest.chapter_end,
            }
            if latest.chapter_start == 1:
                character_changes = [change for change in block_changes if str(change.character_id) == character_id_text]
                if len(character_changes) >= 3:
                    warnings.append(
                        f"Character {character_id_text} has many block state_changes while latest confirmed state starts at chapter 1"
                    )
        pending = [
            change
            for change in block_changes
            if str(change.character_id) == character_id_text and change.status == ReviewStatus.CANDIDATE.value
        ]
        pending_counts[character_id_text] = len(pending)
        for change in pending:
            changed_field_names = [field.get("field") for field in change.changed_fields or []]
            if important_fields.intersection(changed_field_names):
                candidate_may_affect_next.append(
                    {
                        "id": str(change.id),
                        "character_id": character_id_text,
                        "chapter_index": change.chapter_index,
                        "changed_fields": changed_field_names,
                    }
                )
                warnings.append(
                    f"Pending important state_change {change.id} may affect next block continuity"
                )
        confirmed_changes = [
            change
            for change in block_changes
            if str(change.character_id) == character_id_text and change.status == ReviewStatus.CONFIRMED.value
        ]
        for change in confirmed_changes:
            synthesized = session.scalar(
                select(CharacterState).where(CharacterState.state_change_id == change.id).limit(1)
            )
            if synthesized is None:
                confirmed_not_synthesized.append(str(change.id))
                warnings.append(f"Confirmed state_change {change.id} has not been synthesized into CharacterState")

    return {
        **summary,
        "per_character_latest_confirmed_state_at_block_end": latest_states,
        "per_character_pending_state_changes_in_block": pending_counts,
        "confirmed_state_changes_not_synthesized": confirmed_not_synthesized,
        "candidate_state_changes_that_may_affect_next_block": candidate_may_affect_next,
        "warnings": warnings,
    }


def _decision_payload(decision: ReviewDecision, *, applied: bool) -> dict[str, Any]:
    return {
        "target_type": decision.target_type,
        "target_id": str(decision.target_id),
        "decision": decision.decision,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "risk_flags": decision.risk_flags,
        "applied": applied,
    }


def _review_note(decision: ReviewDecision) -> str:
    flags = ",".join(decision.risk_flags) if decision.risk_flags else "-"
    return (
        f"llm-reviewer decision={decision.decision}; "
        f"confidence={decision.confidence:g}; "
        f"reason={decision.reason}; "
        f"risk_flags={flags}"
    )


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    payload = {"created_at": datetime.now(UTC).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_jsonable(payload), ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


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


def parse_args(argv: list[str] | None = None) -> BlockPipelineOptions:
    parser = argparse.ArgumentParser(description="Run an experimental chapter block extraction/review pipeline.")
    parser.add_argument("--novel-id", required=True, type=uuid.UUID)
    parser.add_argument("--chapter-start", required=True, type=int)
    parser.add_argument("--chapter-end", required=True, type=int)
    parser.add_argument("--auto-confirm-events", action="store_true")
    parser.add_argument("--review-state-changes", action="store_true")
    parser.add_argument("--review-dry-run", action="store_true", default=True)
    parser.add_argument("--apply-high-confidence-rejects", action="store_true")
    parser.add_argument("--auto-reject-threshold", type=float, default=0.9)
    parser.add_argument("--limit-state-changes-per-chapter", type=int)
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    parser.add_argument("--stop-on-error", dest="continue_on_error", action="store_false")
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--skip-existing-logs", action="store_true")
    parser.add_argument("--stop-before-next-block", action="store_true")
    args = parser.parse_args(argv)
    return BlockPipelineOptions(
        novel_id=args.novel_id,
        chapter_start=args.chapter_start,
        chapter_end=args.chapter_end,
        auto_confirm_events=args.auto_confirm_events,
        review_state_changes=args.review_state_changes,
        review_dry_run=args.review_dry_run or not args.apply_high_confidence_rejects,
        apply_high_confidence_rejects=args.apply_high_confidence_rejects,
        auto_reject_threshold=args.auto_reject_threshold,
        limit_state_changes_per_chapter=args.limit_state_changes_per_chapter,
        continue_on_error=args.continue_on_error,
        log_dir=args.log_dir,
        skip_existing_logs=args.skip_existing_logs,
        stop_before_next_block=args.stop_before_next_block,
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
        summary = run_chapter_block_pipeline(
            session,
            options,
            extraction_provider=provider,
            review_provider=provider,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
