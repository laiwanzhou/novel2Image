from pathlib import Path

from app.services.import_service import ImportService


def test_txt_import_splits_chinese_chapters(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("第1章 初见\n第一章正文\n\n第2章 转折\n第二章正文", encoding="utf-8")

    manifest = ImportService().parse_path(path, title="样书")

    assert manifest.title == "样书"
    assert manifest.source_type == "txt"
    assert [chapter.chapter_index for chapter in manifest.chapters] == [1, 2]
    assert [chapter.title for chapter in manifest.chapters] == ["第1章 初见", "第2章 转折"]
    assert manifest.chapters[0].content == "第一章正文"
    assert manifest.chapters[1].content == "第二章正文"
    assert len(manifest.chapters[0].checksum) == 64


def test_markdown_import_removes_heading_marks(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text("# 第1章 初见\n第一章正文\n\n## 第2章 转折\n第二章正文", encoding="utf-8")

    manifest = ImportService().parse_path(path)

    assert manifest.source_type == "markdown"
    assert [chapter.title for chapter in manifest.chapters] == ["第1章 初见", "第2章 转折"]
    assert manifest.chapters[0].source_path == str(path)


def test_markdown_import_ignores_duplicate_leading_chapter_title_variant() -> None:
    text = """# 第24章 【帝国军方与诺曼帕萨特】

第24章 【帝国军方与诺曼·帕萨特】

正文第一段。
"""

    chapters = ImportService().parse_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].chapter_index == 24
    assert chapters[0].title == "第24章 【帝国军方与诺曼帕萨特】"
    assert "第24章 【帝国军方与诺曼·帕萨特】" not in chapters[0].content
    assert chapters[0].content == "正文第一段。"
    assert chapters[0].word_count > 0


def test_markdown_import_still_splits_normal_consecutive_chapters() -> None:
    text = """# 第1章 初见

正文一。

# 第2章 转折

正文二。
"""

    chapters = ImportService().parse_chapters(text)

    assert len(chapters) == 2
    assert [chapter.title for chapter in chapters] == ["第1章 初见", "第2章 转折"]
    assert [chapter.content for chapter in chapters] == ["正文一。", "正文二。"]


def test_import_does_not_split_inline_sentence_that_mentions_chapter_number() -> None:
    text = """# 第1章 初见

他说第24章的故事并没有结束，只是正文中的一句话。
"""

    chapters = ImportService().parse_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].content == "他说第24章的故事并没有结束，只是正文中的一句话。"


def test_txt_import_ignores_duplicate_leading_chapter_title_variant() -> None:
    text = """第24章 【帝国军方与诺曼帕萨特】

第24章 【帝国军方与诺曼·帕萨特】

正文第一段。
"""

    chapters = ImportService().parse_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].chapter_index == 24
    assert chapters[0].title == "第24章 【帝国军方与诺曼帕萨特】"
    assert chapters[0].content == "正文第一段。"


def test_import_without_chapter_heading_creates_single_chapter(tmp_path: Path) -> None:
    path = tmp_path / "single.txt"
    path.write_text("没有章节标题的正文", encoding="utf-8")

    manifest = ImportService().parse_path(path)

    assert len(manifest.chapters) == 1
    assert manifest.chapters[0].chapter_index == 1
    assert manifest.chapters[0].title == "正文"
    assert manifest.chapters[0].content == "没有章节标题的正文"


def test_epub_import_fails_with_clear_message(tmp_path: Path) -> None:
    path = tmp_path / "sample.epub"
    path.write_bytes(b"not a real epub")

    try:
        ImportService().parse_path(path)
    except NotImplementedError as exc:
        assert str(exc) == "EPUB import is not implemented yet"
    else:
        raise AssertionError("Expected EPUB import to fail clearly")
