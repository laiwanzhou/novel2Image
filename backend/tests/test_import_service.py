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
