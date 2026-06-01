from pathlib import Path
import json

from scripts.analyze_full_auto_run import (
    NullDatabaseInspector,
    analyze_character_reference_failures,
    analyze_extraction_failures,
    analyze_source_chunk_failures,
    classify_extraction_failure,
    classify_synthesis_failure,
    contains_mojibake,
    iter_jsonl,
    load_raw_llm_diagnostics,
    scan_json_strings,
)


def test_detects_common_mojibake_patterns() -> None:
    assert contains_mojibake("鎬ф牸绱х环")
    assert contains_mojibake("琚壙璁や负")
    assert contains_mojibake("normal text") is False


def test_scans_nested_json_strings_with_paths() -> None:
    payload = {"state": {"identity": "琚壙璁や负"}, "items": ["ok", {"reason": "normal"}]}

    matches = scan_json_strings(payload)

    assert matches == [{"path": "$.state.identity", "value": "琚壙璁や负"}]


def test_classifies_extraction_failures() -> None:
    assert classify_extraction_failure("ValueError: FastGPT LLM response must be valid JSON") == "invalid_json"
    assert classify_extraction_failure("ValueError: event source_chunk_ids must reference chunks from the current chapter") == "source_chunk_not_current_chapter"
    assert classify_extraction_failure("ValueError: FastGPT LLM response content is empty") == "empty_content"
    assert classify_extraction_failure("ValueError: [SSL: UNEXPECTED_EOF_WHILE_READING]") == "ssl_eof"
    assert classify_extraction_failure("ValueError: Extraction output must reference a confirmed character") == "invalid_character_reference"


def test_classifies_synthesis_failures() -> None:
    assert classify_synthesis_failure("No previous confirmed CharacterState exists") == "missing_latest_state"
    assert classify_synthesis_failure("visual_keywords change must be a list of strings") == "invalid_changed_fields"
    assert classify_synthesis_failure("Unsupported CharacterState field change: clothes") == "unsupported_field"
    assert classify_synthesis_failure("New CharacterState chapter_start must be after previous confirmed state") == "duplicate_synthesis"
    assert classify_synthesis_failure("psycopg.errors.CheckViolation") == "db_constraint_or_transaction"


def test_iter_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "chapter-0001.jsonl"
    path.write_text(json.dumps({"type": "a"}) + "\n\n" + json.dumps({"type": "b"}) + "\n", encoding="utf-8")

    assert list(iter_jsonl(path)) == [{"type": "a"}, {"type": "b"}]


def test_analyzer_links_raw_source_chunk_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "diagnostics" / "raw-llm-responses"
    raw_dir.mkdir(parents=True)
    chapter_id = "11111111-1111-1111-1111-111111111111"
    raw_file = raw_dir / f"20260601T010203000000Z-chapter-0033-{chapter_id}-source_chunk_not_current_chapter.json"
    raw_file.write_text(
        json.dumps(
            {
                "chapter_index": 33,
                "chapter_id": chapter_id,
                "failure_type": "source_chunk_not_current_chapter",
                "returned_source_chunk_ids": [
                    "22222222-2222-2222-2222-222222222222",
                    "33333333-3333-3333-3333-333333333333",
                ],
                "returned_character_ids": ["44444444-4444-4444-4444-444444444444"],
                "raw_response_text": '{"events": [',
                "prompt_hash": "abc",
            }
        ),
        encoding="utf-8",
    )
    diagnostics = load_raw_llm_diagnostics(run_dir)
    db = FakeDiagnosticsDb(
        current_chunk_ids=["22222222-2222-2222-2222-222222222222"],
        chunk_lookup={
            "22222222-2222-2222-2222-222222222222": {"status": "current_chapter"},
            "33333333-3333-3333-3333-333333333333": {"status": "other_chapter", "chapter_index": 32},
        },
    )
    summary = {
        "failed_chapters": [
            {
                "chapter_index": 33,
                "chapter_id": chapter_id,
                "error": "ValueError: event source_chunk_ids must reference chunks from the current chapter",
            }
        ]
    }

    extraction = analyze_extraction_failures(summary, {}, db, diagnostics)
    source_chunks = analyze_source_chunk_failures(summary, db, diagnostics)

    failure = extraction["failures"][0]
    assert failure["raw_response_available"] is True
    assert failure["raw_parsed_response_available"] is True
    assert failure["returned_source_chunk_ids"] == [
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    assert "sk-" not in json.dumps(failure)
    assert "prompt text" not in json.dumps(failure)
    detail = source_chunks["details"][0]
    assert detail["llm_returned_source_chunk_ids"] == failure["returned_source_chunk_ids"]
    assert detail["returned_source_chunk_id_analysis"] == [
        {"id": "22222222-2222-2222-2222-222222222222", "status": "current_chapter"},
        {"id": "33333333-3333-3333-3333-333333333333", "status": "other_chapter", "chapter_index": 32},
    ]
    assert source_chunks["limitation"] is None


def test_analyzer_links_raw_character_reference_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw_dir = run_dir.parent / "diagnostics" / "raw-llm-responses"
    raw_dir.mkdir(parents=True)
    chapter_id = "11111111-1111-1111-1111-111111111111"
    raw_file = raw_dir / f"20260601T010203000000Z-chapter-0009-{chapter_id}-invalid_character_reference.json"
    raw_file.write_text(
        json.dumps(
            {
                "chapter_index": 9,
                "chapter_id": chapter_id,
                "failure_type": "invalid_character_reference",
                "returned_character_ids": [
                    "44444444-4444-4444-4444-444444444444",
                    "55555555-5555-5555-5555-555555555555",
                ],
            }
        ),
        encoding="utf-8",
    )
    diagnostics = load_raw_llm_diagnostics(run_dir)
    db = FakeDiagnosticsDb(
        character_lookup={
            "44444444-4444-4444-4444-444444444444": {"exists": True, "status": "candidate"},
            "55555555-5555-5555-5555-555555555555": {"exists": False, "status": None},
        }
    )
    summary = {
        "failed_chapters": [
            {
                "chapter_index": 9,
                "chapter_id": chapter_id,
                "error": "ValueError: Extraction output must reference a confirmed character",
            }
        ]
    }

    characters = analyze_character_reference_failures(summary, db, diagnostics)

    detail = characters["details"][0]
    assert detail["returned_character_ids"] == [
        "44444444-4444-4444-4444-444444444444",
        "55555555-5555-5555-5555-555555555555",
    ]
    assert detail["returned_character_id_analysis"] == [
        {"id": "44444444-4444-4444-4444-444444444444", "exists": True, "status": "candidate", "confirmed": False},
        {"id": "55555555-5555-5555-5555-555555555555", "exists": False, "status": None, "confirmed": False},
    ]
    assert characters["limitation"] is None


class FakeDiagnosticsDb(NullDatabaseInspector):
    def __init__(
        self,
        *,
        current_chunk_ids: list[str] | None = None,
        chunk_lookup: dict[str, dict] | None = None,
        character_lookup: dict[str, dict] | None = None,
    ) -> None:
        self.current_chunk_ids = current_chunk_ids or []
        self.chunk_lookup = chunk_lookup or {}
        self.character_lookup = character_lookup or {}

    def chunk_ids_for_chapter(self, chapter_id: str) -> list[str]:
        return self.current_chunk_ids

    def chunk_id_info(self, chunk_id: str, current_chapter_id: str | None = None) -> dict:
        return {"id": chunk_id, **self.chunk_lookup.get(chunk_id, {"status": "missing"})}

    def character_id_info(self, character_id: str) -> dict:
        value = self.character_lookup.get(character_id, {"exists": False, "status": None})
        return {
            "id": character_id,
            "exists": value["exists"],
            "status": value["status"],
            "confirmed": value["status"] == "confirmed",
        }
