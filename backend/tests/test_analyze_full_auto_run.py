from pathlib import Path
import json

from scripts.analyze_full_auto_run import (
    classify_extraction_failure,
    classify_synthesis_failure,
    contains_mojibake,
    iter_jsonl,
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
