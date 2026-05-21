from app.services.chunking_service import ChunkingService


def test_chunking_preserves_paragraph_boundaries_and_offsets() -> None:
    content = "第一段描述角色。\n\n第二段继续描述。\n\n第三段转入事件。"

    chunks = ChunkingService().chunk_chapter(content, target_chars=8, max_chars=20)

    assert [chunk.chunk_index for chunk in chunks] == [1, 2]
    assert chunks[0].text == "第一段描述角色。\n\n第二段继续描述。"
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == content.index("第三段转入事件。") - 2
    assert chunks[1].text == "第三段转入事件。"
    assert content[chunks[1].start_char : chunks[1].end_char] == "第三段转入事件。"


def test_chunking_records_counts_and_checksum() -> None:
    content = "第一段。\n\n第二段。"

    [chunk] = ChunkingService().chunk_chapter(content, target_chars=100, max_chars=150)

    assert chunk.char_count == len("第一段。\n\n第二段。")
    assert chunk.token_count == len("第一段。第二段。")
    assert len(chunk.checksum) == 64


def test_chunking_empty_content_returns_no_chunks() -> None:
    assert ChunkingService().chunk_chapter(" \n\n ") == []
