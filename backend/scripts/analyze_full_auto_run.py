from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MOJIBAKE_PATTERNS = (
    "锛",
    "绗",
    "骞",
    "楠",
    "鐜",
    "鍦",
    "銆",
    "鈥",
    "�",
    "鎬",
    "绱",
    "琚",
    "壙",
    "璁",
    "涔",
    "惃",
    "榪",
)


def contains_mojibake(value: str) -> bool:
    return any(pattern in value for pattern in MOJIBAKE_PATTERNS)


def iter_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def scan_json_strings(payload: Any, path: str = "$") -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            matches.extend(scan_json_strings(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            matches.extend(scan_json_strings(value, f"{path}[{index}]"))
    elif isinstance(payload, str) and contains_mojibake(payload):
        matches.append({"path": path, "value": payload})
    return matches


def classify_extraction_failure(message: str) -> str:
    lowered = message.lower()
    if "valid json" in lowered:
        return "invalid_json"
    if "source_chunk_ids must reference chunks from the current chapter" in lowered:
        return "source_chunk_not_current_chapter"
    if "content is empty" in lowered:
        return "empty_content"
    if "ssl" in lowered or "eof" in lowered:
        return "ssl_eof"
    if "confirmed character" in lowered or "valid confirmed character" in lowered:
        return "invalid_character_reference"
    return "other"


def classify_synthesis_failure(message: str) -> str:
    lowered = message.lower()
    if "no previous confirmed characterstate" in lowered:
        return "missing_latest_state"
    if "unsupported characterstate field" in lowered:
        return "unsupported_field"
    if "change must be" in lowered:
        return "invalid_changed_fields"
    if "chapter_start must be after previous confirmed state" in lowered:
        return "duplicate_synthesis"
    if "constraint" in lowered or "transaction" in lowered or "psycopg" in lowered:
        return "db_constraint_or_transaction"
    if contains_mojibake(message):
        return "malformed_text_or_mojibake"
    return "unknown"


def load_raw_llm_diagnostics(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    diagnostics: dict[str, list[dict[str, Any]]] = {}
    for raw_dir in _raw_diagnostics_dirs(run_dir):
        if not raw_dir.exists():
            continue
        for path in sorted(raw_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            chapter_index = payload.get("chapter_index")
            failure_type = payload.get("failure_type")
            if chapter_index is None or not failure_type:
                continue
            entry = {
                **payload,
                "raw_diagnostics_file": str(path),
                "raw_response_available": bool(payload.get("raw_response") or payload.get("raw_response_text")),
                "raw_parsed_response_available": bool(
                    payload.get("raw_parsed_response")
                    or payload.get("parsed_response")
                    or payload.get("returned_source_chunk_ids")
                    or payload.get("returned_character_ids")
                ),
            }
            diagnostics.setdefault(_diagnostic_key(chapter_index, failure_type), []).append(entry)
    return diagnostics


def _raw_diagnostics_dirs(run_dir: Path) -> list[Path]:
    return [
        run_dir / "diagnostics" / "raw-llm-responses",
        run_dir.parent / "diagnostics" / "raw-llm-responses",
    ]


def _diagnostic_key(chapter_index, failure_type: str) -> str:
    return f"{chapter_index}:{failure_type}"


def _diagnostic_for_failure(failure: dict[str, Any], diagnostics: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    category = classify_extraction_failure(failure.get("error", ""))
    matches = diagnostics.get(_diagnostic_key(failure.get("chapter_index"), category), [])
    chapter_id = failure.get("chapter_id")
    for match in matches:
        if not chapter_id or match.get("chapter_id") == chapter_id:
            return match
    return matches[0] if matches else None


def analyze_run(run_dir: Path, *, database_url: str | None = None) -> dict[str, Any]:
    summary_path = run_dir / "full_auto_summary.json"
    report_path = run_dir / "full_auto_report.md"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    chapter_logs = {int(path.stem.split("-")[1]): path for path in run_dir.glob("chapter-*.jsonl")}

    db = DatabaseInspector(database_url) if database_url else NullDatabaseInspector()
    diagnostics_dir = run_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    raw_diagnostics = load_raw_llm_diagnostics(run_dir)

    mojibake = analyze_mojibake(summary, report_path, chapter_logs, db)
    synthesis = analyze_synthesis_failures(chapter_logs, db)
    extraction = analyze_extraction_failures(summary, chapter_logs, db, raw_diagnostics)
    source_chunks = analyze_source_chunk_failures(summary, db, raw_diagnostics)
    characters = analyze_character_reference_failures(summary, db, raw_diagnostics)
    quality = analyze_quality(summary, mojibake, synthesis, extraction, source_chunks, characters)

    _write_report_pair(
        diagnostics_dir / "mojibake_analysis",
        mojibake,
        render_mojibake_markdown(mojibake),
    )
    _write_report_pair(
        diagnostics_dir / "synthesis_failure_analysis",
        synthesis,
        render_synthesis_markdown(synthesis),
    )
    _write_report_pair(
        diagnostics_dir / "extraction_failure_analysis",
        extraction,
        render_extraction_markdown(extraction),
    )
    _write_report_pair(
        diagnostics_dir / "source_chunk_failure_analysis",
        source_chunks,
        render_source_chunk_markdown(source_chunks),
    )
    _write_report_pair(
        diagnostics_dir / "character_reference_failure_analysis",
        characters,
        render_character_reference_markdown(characters),
    )
    _write_report_pair(
        diagnostics_dir / "full_auto_quality_analysis",
        quality,
        render_quality_markdown(quality),
    )
    return {
        "mojibake": mojibake,
        "synthesis": synthesis,
        "extraction": extraction,
        "source_chunks": source_chunks,
        "characters": characters,
        "quality": quality,
        "diagnostics_dir": str(diagnostics_dir),
    }


def analyze_mojibake(
    summary: dict[str, Any],
    report_path: Path,
    chapter_logs: dict[int, Path],
    db,
) -> dict[str, Any]:
    summary_matches = scan_json_strings(summary)
    summary_examples = _limit_matches(summary_matches, 10)
    log_matches: list[dict[str, Any]] = []
    for chapter_index, path in sorted(chapter_logs.items()):
        for line_index, payload in enumerate(iter_jsonl(path), start=1):
            for match in scan_json_strings(payload):
                log_matches.append(
                    {
                        "chapter_index": chapter_index,
                        "file": str(path),
                        "line": line_index,
                        **match,
                    }
                )
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_matches = [
        {"line": index, "value": line}
        for index, line in enumerate(report_text.splitlines(), start=1)
        if contains_mojibake(line)
    ]
    db_matches = db.find_mojibake_samples(limit=20)
    source = "none_detected"
    if db_matches:
        source = "database_fields_or_before_database"
    elif log_matches:
        source = "llm_response_or_jsonl_logging"
    elif summary_matches:
        source = "summary_aggregation"
    elif report_matches:
        source = "markdown_report_rendering"
    return {
        "summary_has_mojibake": bool(summary_matches),
        "chapter_jsonl_has_mojibake": bool(log_matches),
        "database_fields_have_mojibake": bool(db_matches),
        "report_has_mojibake": bool(report_matches),
        "unicode_replacement_character_in_summary": any("�" in match["value"] for match in summary_matches),
        "summary_examples": summary_examples,
        "chapter_jsonl_examples": log_matches[:20],
        "database_examples": db_matches,
        "report_examples": report_matches[:20],
        "most_likely_source": source,
        "notes": [
            "Python json.loads can parse full_auto_summary.json; PowerShell ConvertFrom-Json is not reliable as sole evidence.",
            "If the same text is mojibake in DB and JSONL, corruption happened before or during persistence rather than only during report rendering.",
        ],
    }


def _limit_matches(matches: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    return [{"path": match["path"], "value": _snippet(match["value"])} for match in matches[:limit]]


def analyze_synthesis_failures(chapter_logs: dict[int, Path], db) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for chapter_index, path in sorted(chapter_logs.items()):
        for payload in iter_jsonl(path):
            if payload.get("type") != "synthesis":
                continue
            for result in payload.get("results", []):
                if not result.get("error"):
                    continue
                state_change_id = result.get("state_change_id")
                db_info = db.state_change_info(state_change_id) if state_change_id else {}
                latest_state = db.latest_state_for_change(state_change_id) if state_change_id else None
                has_state = db.has_state_for_change(state_change_id) if state_change_id else False
                category = classify_synthesis_failure(result["error"])
                failures.append(
                    {
                        "chapter_index": chapter_index,
                        "state_change_id": state_change_id,
                        "character_id": db_info.get("character_id"),
                        "character_name": db_info.get("character_name"),
                        "changed_fields": db_info.get("changed_fields"),
                        "event_id": db_info.get("event_id"),
                        "failure_message": result["error"],
                        "failure_category": category,
                        "current_state_change_status": db_info.get("status"),
                        "is_confirmed": db_info.get("status") == "confirmed",
                        "has_character_state": has_state,
                        "latest_confirmed_state_before_or_at": latest_state,
                        "maybe_unsupported_field": category == "unsupported_field",
                        "maybe_missing_prior_state": category == "missing_latest_state",
                        "maybe_duplicate_state_already_exists": category == "duplicate_synthesis" or has_state,
                        "maybe_mojibake_or_illegal_text": contains_mojibake(json.dumps(db_info, ensure_ascii=False)),
                        "maybe_missing_source_evidence": not bool(db_info.get("source_chunk_ids")),
                    }
                )
    distribution = Counter(failure["failure_category"] for failure in failures)
    return {
        "failure_count": len(failures),
        "category_distribution": dict(distribution),
        "failures": failures,
        "most_common_failure_category": distribution.most_common(1)[0][0] if distribution else None,
    }


def analyze_extraction_failures(
    summary: dict[str, Any],
    chapter_logs: dict[int, Path],
    db,
    raw_diagnostics: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    failures = []
    raw_diagnostics = raw_diagnostics or {}
    for failure in summary.get("failed_chapters", []):
        message = failure.get("error", "")
        chapter_index = failure.get("chapter_index")
        category = classify_extraction_failure(message)
        partial = db.chapter_has_events_or_changes(failure.get("chapter_id"))
        diagnostic = _diagnostic_for_failure(failure, raw_diagnostics)
        failures.append(
            {
                "chapter_index": chapter_index,
                "chapter_id": failure.get("chapter_id"),
                "failure_message": message,
                "failure_category": category,
                "has_partial_db_write": partial,
                "suitable_for_retry": category in {"invalid_json", "empty_content", "ssl_eof"},
                "needs_prompt_or_validation_fix_before_retry": category
                in {"source_chunk_not_current_chapter", "invalid_character_reference"},
                "possibly_max_tokens_timeout_or_json_mode": category in {"invalid_json", "empty_content", "ssl_eof"},
                "possibly_source_chunk_prompt_constraint": category == "source_chunk_not_current_chapter",
                "possibly_character_alias_or_confirmation_gap": category == "invalid_character_reference",
                "chapter_log_exists": chapter_index in chapter_logs,
                "raw_diagnostics_file": diagnostic.get("raw_diagnostics_file") if diagnostic else None,
                "raw_response_available": bool(diagnostic.get("raw_response_available")) if diagnostic else False,
                "raw_parsed_response_available": bool(diagnostic.get("raw_parsed_response_available"))
                if diagnostic
                else False,
                "returned_source_chunk_ids": diagnostic.get("returned_source_chunk_ids") if diagnostic else None,
                "returned_character_ids": diagnostic.get("returned_character_ids") if diagnostic else None,
            }
        )
    distribution = Counter(failure["failure_category"] for failure in failures)
    return {
        "failure_count": len(failures),
        "category_distribution": dict(distribution),
        "failures": failures,
    }


def analyze_source_chunk_failures(
    summary: dict[str, Any],
    db,
    raw_diagnostics: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    raw_diagnostics = raw_diagnostics or {}
    failures = [
        failure
        for failure in summary.get("failed_chapters", [])
        if classify_extraction_failure(failure.get("error", "")) == "source_chunk_not_current_chapter"
    ]
    details = []
    for failure in failures:
        chapter_id = failure.get("chapter_id")
        diagnostic = _diagnostic_for_failure(failure, raw_diagnostics)
        returned_ids = diagnostic.get("returned_source_chunk_ids") if diagnostic else None
        returned_analysis = (
            [db.chunk_id_info(chunk_id, current_chapter_id=chapter_id) for chunk_id in returned_ids]
            if returned_ids
            else None
        )
        details.append(
            {
                "chapter_index": failure.get("chapter_index"),
                "chapter_id": chapter_id,
                "failure_message": failure.get("error"),
                "current_chapter_chunk_ids": db.chunk_ids_for_chapter(chapter_id),
                "llm_returned_source_chunk_ids": returned_ids,
                "returned_source_chunk_id_analysis": returned_analysis,
                "raw_diagnostics_file": diagnostic.get("raw_diagnostics_file") if diagnostic else None,
                "wrong_chunk_id_lookup": None
                if diagnostic
                else "unavailable: raw invalid LLM response is not logged by current pipeline",
                "likely_reason": "model returned chunk ids outside current chapter or malformed ids; guard rejected entire chapter before partial DB write",
                "recommended_policy": "keep failing whole chapter until response repair/instrumentation is designed; do not silently map or drop evidence ids without review",
            }
        )
    return {
        "failure_count": len(details),
        "details": details,
        "limitation": None
        if any(detail.get("raw_diagnostics_file") for detail in details)
        else "The current logs only contain validation error text, not the raw invalid LLM response, so exact wrong source_chunk_ids cannot be recovered from this run.",
    }


def analyze_character_reference_failures(
    summary: dict[str, Any],
    db,
    raw_diagnostics: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    raw_diagnostics = raw_diagnostics or {}
    failures = [
        failure
        for failure in summary.get("failed_chapters", [])
        if classify_extraction_failure(failure.get("error", "")) == "invalid_character_reference"
    ]
    details = []
    for failure in failures:
        diagnostic = _diagnostic_for_failure(failure, raw_diagnostics)
        returned_ids = diagnostic.get("returned_character_ids") if diagnostic else None
        returned_analysis = [db.character_id_info(character_id) for character_id in returned_ids] if returned_ids else None
        details.append(
            {
                "chapter_index": failure.get("chapter_index"),
                "chapter_id": failure.get("chapter_id"),
                "failure_message": failure.get("error"),
                "llm_returned_character_id": returned_ids[0] if returned_ids else None,
                "returned_character_ids": returned_ids,
                "returned_character_id_analysis": returned_analysis,
                "character_exists": returned_analysis[0].get("exists") if returned_analysis else None,
                "character_confirmed": returned_analysis[0].get("confirmed") if returned_analysis else None,
                "raw_diagnostics_file": diagnostic.get("raw_diagnostics_file") if diagnostic else None,
                "likely_new_character_or_alias_gap": True,
                "should_enter_character_discovery": True,
                "should_allow_new_character_candidates": "consider later; current schema/prompt intentionally requires confirmed characters for state/event extraction",
                "prompt_constraint_note": "prompt already says use only confirmed characters, but raw bad response is not logged so exact failure cannot be attributed to id vs name.",
            }
        )
    return {
        "failure_count": len(details),
        "details": details,
        "limitation": None
        if any(detail.get("raw_diagnostics_file") for detail in details)
        else "The current logs only contain validation error text, not the raw invalid LLM response, so exact character_id/name cannot be recovered from this run.",
    }


def analyze_quality(
    summary: dict[str, Any],
    mojibake: dict[str, Any],
    synthesis: dict[str, Any],
    extraction: dict[str, Any],
    source_chunks: dict[str, Any],
    characters: dict[str, Any],
) -> dict[str, Any]:
    issues = [
        "Synthesis failed for many confirmed state_changes; automatic state chain is not reliable yet.",
        "Mojibake appears in generated state/reviewer text and can pollute final prompt context.",
        "LLM JSON stability remains weak: invalid JSON is the largest extraction failure class.",
        "Evidence validation is working, but source_chunk mismatch failures need raw-response instrumentation.",
        "Confirmed character coverage is insufficient for late novel chapters.",
    ]
    return {
        "technically_completed": len(summary.get("processed_chapters", [])) + len(summary.get("failed_chapters", []))
        == summary.get("total_chapters"),
        "biggest_bottlenecks": issues,
        "llm_stability_issues": extraction["category_distribution"],
        "pipeline_design_issues": synthesis["category_distribution"],
        "character_library_issues": characters,
        "encoding_or_logging_issues": {
            "summary": mojibake["summary_has_mojibake"],
            "chapter_jsonl": mojibake["chapter_jsonl_has_mojibake"],
            "database": mojibake["database_fields_have_mojibake"],
        },
        "prompt_impact": "High: mojibake and over-eager/failed state synthesis can flow into latest CharacterState and degrade final image prompts.",
        "continue_full_auto": False,
        "minimal_fix_order": [
            "Add raw invalid LLM response logging in ignored diagnostics for failed extraction only.",
            "Fix/mitigate mojibake at provider or prompt language boundary before persisting reviewer/state text.",
            "Make state synthesis order/range conflict handling explicit before auto-confirming synthesized CharacterState.",
            "Add character discovery/confirmation pass for late chapters before extraction.",
            "Add retry/repair strategy for invalid JSON and source_chunk mismatch, with evidence-preserving failure policy.",
        ],
        "source_chunk_failure_analysis": source_chunks,
    }


class NullDatabaseInspector:
    def find_mojibake_samples(self, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def state_change_info(self, state_change_id: str) -> dict[str, Any]:
        return {}

    def latest_state_for_change(self, state_change_id: str):
        return None

    def has_state_for_change(self, state_change_id: str) -> bool:
        return False

    def chapter_has_events_or_changes(self, chapter_id: str) -> bool:
        return False

    def chunk_ids_for_chapter(self, chapter_id: str) -> list[str]:
        return []

    def chunk_id_info(self, chunk_id: str, current_chapter_id: str | None = None) -> dict[str, Any]:
        return {"id": chunk_id, "status": "unknown_without_database"}

    def character_id_info(self, character_id: str) -> dict[str, Any]:
        return {"id": character_id, "exists": None, "status": None, "confirmed": None}


class DatabaseInspector:
    def __init__(self, database_url: str | None) -> None:
        self.engine = create_engine(database_url or "postgresql+psycopg://postgres:postgres@localhost:5432/novel_visualization", future=True)

    def find_mojibake_samples(self, limit: int = 20) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        queries = [
            (
                "character_states",
                """
                select id::text, chapter_start::text as chapter, 'identity' as field, identity as value from character_states
                union all select id::text, chapter_start::text, 'motivation', motivation from character_states
                union all select id::text, chapter_start::text, 'relationship_summary', relationship_summary from character_states
                """,
            ),
            (
                "character_state_changes",
                """
                select id::text, chapter_index::text as chapter, 'explanation' as field, explanation as value from character_state_changes
                """,
            ),
            (
                "character_events",
                """
                select id::text, chapter_index::text as chapter, 'event_summary' as field, event_summary as value from character_events
                union all select id::text, chapter_index::text, 'explanation', explanation from character_events
                """,
            ),
        ]
        with Session(self.engine) as session:
            for table, sql in queries:
                for row in session.execute(text(sql)).mappings():
                    value = row["value"]
                    if isinstance(value, str) and contains_mojibake(value):
                        samples.append(
                            {
                                "table": table,
                                "id": row["id"],
                                "chapter": row["chapter"],
                                "field": row["field"],
                                "value": _snippet(value),
                            }
                        )
                        if len(samples) >= limit:
                            return samples
        return samples

    def state_change_info(self, state_change_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.execute(
                text(
                    """
                    select sc.id::text, sc.character_id::text, c.canonical_name as character_name,
                           sc.changed_fields_json as changed_fields, sc.event_id::text, sc.source_chunk_ids,
                           sc.status, sc.chapter_index
                    from character_state_changes sc
                    left join characters c on c.id = sc.character_id
                    where sc.id = cast(:id as uuid)
                    """
                ),
                {"id": state_change_id},
            ).mappings().first()
            return dict(row) if row else {}

    def latest_state_for_change(self, state_change_id: str):
        with Session(self.engine) as session:
            change = session.execute(
                text(
                    """
                    select character_id, chapter_index
                    from character_state_changes
                    where id = cast(:id as uuid)
                    """
                ),
                {"id": state_change_id},
            ).mappings().first()
            if not change:
                return None
            state = session.execute(
                text(
                    """
                    select id::text, chapter_start, chapter_end, identity, motivation, relationship_summary
                    from character_states
                    where character_id = :character_id
                      and status = 'confirmed'
                      and chapter_start <= :chapter_index
                    order by chapter_start desc
                    limit 1
                    """
                ),
                {"character_id": change["character_id"], "chapter_index": change["chapter_index"]},
            ).mappings().first()
            return dict(state) if state else None

    def has_state_for_change(self, state_change_id: str) -> bool:
        with Session(self.engine) as session:
            return bool(
                session.execute(
                    text("select 1 from character_states where state_change_id = cast(:id as uuid) limit 1"),
                    {"id": state_change_id},
                ).first()
            )

    def chapter_has_events_or_changes(self, chapter_id: str) -> bool:
        if not chapter_id:
            return False
        with Session(self.engine) as session:
            event = session.execute(
                text("select 1 from character_events where chapter_id = cast(:id as uuid) limit 1"),
                {"id": chapter_id},
            ).first()
            change = session.execute(
                text("select 1 from character_state_changes where chapter_id = cast(:id as uuid) limit 1"),
                {"id": chapter_id},
            ).first()
            return bool(event or change)

    def chunk_ids_for_chapter(self, chapter_id: str) -> list[str]:
        if not chapter_id:
            return []
        with Session(self.engine) as session:
            rows = session.execute(
                text(
                    """
                    select id::text
                    from chapter_chunks
                    where chapter_id = cast(:id as uuid)
                    order by chunk_index
                    """
                ),
                {"id": chapter_id},
            ).scalars()
            return list(rows)

    def chunk_id_info(self, chunk_id: str, current_chapter_id: str | None = None) -> dict[str, Any]:
        try:
            uuid_value = str(uuid.UUID(str(chunk_id)))
        except (TypeError, ValueError):
            return {"id": str(chunk_id), "status": "malformed_uuid"}
        with Session(self.engine) as session:
            row = session.execute(
                text(
                    """
                    select cc.id::text, cc.chapter_id::text, cc.chunk_index,
                           ch.chapter_index, ch.novel_id::text
                    from chapter_chunks cc
                    join chapters ch on ch.id = cc.chapter_id
                    where cc.id = cast(:id as uuid)
                    """
                ),
                {"id": uuid_value},
            ).mappings().first()
        if not row:
            return {"id": uuid_value, "status": "missing"}
        status = "current_chapter" if current_chapter_id and str(row["chapter_id"]) == str(current_chapter_id) else "other_chapter"
        return {
            "id": row["id"],
            "status": status,
            "chapter_id": row["chapter_id"],
            "chapter_index": row["chapter_index"],
            "chunk_index": row["chunk_index"],
            "novel_id": row["novel_id"],
        }

    def character_id_info(self, character_id: str) -> dict[str, Any]:
        try:
            uuid_value = str(uuid.UUID(str(character_id)))
        except (TypeError, ValueError):
            return {"id": str(character_id), "exists": False, "status": "malformed_uuid", "confirmed": False}
        with Session(self.engine) as session:
            row = session.execute(
                text(
                    """
                    select id::text, canonical_name, status
                    from characters
                    where id = cast(:id as uuid)
                    """
                ),
                {"id": uuid_value},
            ).mappings().first()
        if not row:
            return {"id": uuid_value, "exists": False, "status": None, "confirmed": False}
        return {
            "id": row["id"],
            "exists": True,
            "canonical_name": row["canonical_name"],
            "status": row["status"],
            "confirmed": row["status"] == "confirmed",
        }


def _write_report_pair(base_path: Path, payload: dict[str, Any], markdown: str) -> None:
    base_path.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    base_path.with_suffix(".md").write_text(markdown, encoding="utf-8")


def render_mojibake_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Mojibake Analysis",
        "",
        f"- summary_has_mojibake: {data['summary_has_mojibake']}",
        f"- chapter_jsonl_has_mojibake: {data['chapter_jsonl_has_mojibake']}",
        f"- database_fields_have_mojibake: {data['database_fields_have_mojibake']}",
        f"- most_likely_source: {data['most_likely_source']}",
        "",
        "## Summary Examples",
    ]
    lines.extend(f"- `{item['path']}`: {item['value']}" for item in data["summary_examples"])
    lines.append("\n## Database Examples")
    lines.extend(
        f"- {item['table']} {item['id']} {item['field']}: {item['value']}" for item in data["database_examples"]
    )
    return "\n".join(lines) + "\n"


def render_synthesis_markdown(data: dict[str, Any]) -> str:
    lines = ["# Synthesis Failure Analysis", "", f"- failure_count: {data['failure_count']}", "## Distribution"]
    lines.extend(f"- {key}: {value}" for key, value in data["category_distribution"].items())
    lines.append("\n## Failures")
    for failure in data["failures"]:
        lines.append(
            f"- chapter {failure['chapter_index']} `{failure['state_change_id']}` "
            f"{failure['failure_category']}: {failure['failure_message']}"
        )
    return "\n".join(lines) + "\n"


def render_extraction_markdown(data: dict[str, Any]) -> str:
    lines = ["# Extraction Failure Analysis", "", f"- failure_count: {data['failure_count']}", "## Distribution"]
    lines.extend(f"- {key}: {value}" for key, value in data["category_distribution"].items())
    lines.append("\n## Failures")
    for failure in data["failures"]:
        lines.append(
            f"- chapter {failure['chapter_index']} `{failure['failure_category']}`: {failure['failure_message']}"
        )
    return "\n".join(lines) + "\n"


def render_source_chunk_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Source Chunk Failure Analysis",
        "",
        f"- failure_count: {data['failure_count']}",
        f"- limitation: {data['limitation']}",
        "",
        "## Details",
    ]
    for detail in data["details"]:
        returned = detail.get("llm_returned_source_chunk_ids")
        returned_text = returned if returned is not None else "unavailable"
        lines.append(
            f"- chapter {detail['chapter_index']}: current chunks={detail['current_chapter_chunk_ids']}; "
            f"returned ids={returned_text}"
        )
    return "\n".join(lines) + "\n"


def render_character_reference_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Character Reference Failure Analysis",
        "",
        f"- failure_count: {data['failure_count']}",
        f"- limitation: {data['limitation']}",
        "",
        "## Details",
    ]
    for detail in data["details"]:
        returned = detail.get("returned_character_ids")
        returned_text = returned if returned is not None else "unavailable"
        lines.append(
            f"- chapter {detail['chapter_index']}: {detail['failure_message']}; "
            f"returned character ids={returned_text}"
        )
    return "\n".join(lines) + "\n"


def render_quality_markdown(data: dict[str, Any]) -> str:
    lines = ["# Full Auto Quality Analysis", "", f"- technically_completed: {data['technically_completed']}"]
    lines.append("\n## Biggest Bottlenecks")
    lines.extend(f"- {item}" for item in data["biggest_bottlenecks"])
    lines.append("\n## Minimal Fix Order")
    lines.extend(f"{index}. {item}" for index, item in enumerate(data["minimal_fix_order"], start=1))
    return "\n".join(lines) + "\n"


def _snippet(value: str, limit: int = 240) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze full-auto pipeline logs without mutating data.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:postgres@localhost:5432/novel_visualization")
    parser.add_argument("--no-db", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = analyze_run(args.run_dir, database_url=None if args.no_db else args.database_url)
    print(json.dumps({"diagnostics_dir": result["diagnostics_dir"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
