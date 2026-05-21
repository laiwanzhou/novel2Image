import json

import pytest

from scripts.crawl_novel_site import (
    ChapterContent,
    build_manifest,
    build_markdown,
    crawl_novel,
    extract_chapter_links,
    extract_next_page_url,
    main,
    normalize_title,
    parse_chapter_html,
)


DIRECTORY_HTML = """
<html><body>
  <a href="https://www.92yanqing.com/read/92502/50916992.html">第143章 【启程之前】</a>
  <a href="/read/92502/44142929.html">第1章 【隆多兰的魔王与穿越者的幽灵】</a>
  <a href="/read/92502/44142930.html">第2章 【塔莉亚与萨麦尔】</a>
  <a href="/read/92502/44142929.html">第1章 【隆多兰的魔王与穿越者的幽灵】</a>
  <a href="/read/99999/1.html">其他书</a>
</body></html>
"""


CHAPTER_HTML = """
<html><body>
  <h1>第1章 【隆多兰的魔王与穿越者的幽灵】（1/2）</h1>
  <div id="booktxt">
    第1章 【隆多兰的魔王与穿越者的幽灵】<br>
    正文第一段。<br><br>
    正文第二段。<br>
    上一章 返回目录 下一章<br>
    请收藏本站。<br>
  </div>
</body></html>
"""


CHAPTER_PAGE_ONE_HTML = """
<html><body>
  <h1>第1章 【隆多兰的魔王与穿越者的幽灵】（1/2）</h1>
  <div id="booktxt">
    第1章 【隆多兰的魔王与穿越者的幽灵】<br>
    第一页正文。<br>
    本章未完，点击下一页继续阅读。<br>
  </div>
  <a href="/read/92502/44142929_2.html" rel="next" id="next_url">下一页</a>
</body></html>
"""


CHAPTER_PAGE_TWO_HTML = """
<html><body>
  <h1>第1章 【隆多兰的魔王与穿越者的幽灵】（2/2）</h1>
  <div id="booktxt">
    第1章 【隆多兰的魔王与穿越者的幽灵】<br>
    第二页后续正文。<br>
  </div>
  <a href="/read/92502/44142930.html" rel="next" id="next_url">下一章</a>
</body></html>
"""


def test_normalize_title_removes_full_width_pagination_suffix():
    assert normalize_title("第1章 【隆多兰的魔王与穿越者的幽灵】（1/2）") == "第1章 【隆多兰的魔王与穿越者的幽灵】"


def test_normalize_title_removes_ascii_pagination_suffix():
    assert normalize_title("第2章 【塔莉亚与萨麦尔】 (1/2)") == "第2章 【塔莉亚与萨麦尔】"


def test_extract_chapter_links_keeps_catalog_order_and_deduplicates():
    links = extract_chapter_links(DIRECTORY_HTML, "https://www.92yanqing.com/read/92502/")

    assert [link.index for link in links[:2]] == [1, 2]
    assert links[0].title == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert links[0].url == "https://www.92yanqing.com/read/92502/44142929.html"


def test_extract_next_page_url_keeps_only_same_chapter_pagination():
    assert (
        extract_next_page_url(
            CHAPTER_PAGE_ONE_HTML,
            "https://www.92yanqing.com/read/92502/44142929.html",
            chapter_index=1,
        )
        == "https://www.92yanqing.com/read/92502/44142929_2.html"
    )

    assert (
        extract_next_page_url(
            CHAPTER_PAGE_TWO_HTML,
            "https://www.92yanqing.com/read/92502/44142929_2.html",
            chapter_index=1,
        )
        is None
    )

    assert (
        extract_next_page_url(
            '<a href="javascript:void(0)" rel="next" id="next_url">下一页</a>',
            "https://www.92yanqing.com/read/92502/44142929.html",
            chapter_index=1,
        )
        is None
    )


def test_parse_chapter_html_uses_h1_booktxt_and_cleans_noise():
    chapter = parse_chapter_html(CHAPTER_HTML, "https://www.92yanqing.com/read/92502/44142929.html")

    assert chapter.index == 1
    assert chapter.title == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert chapter.paragraphs == ["正文第一段。", "正文第二段。"]


def test_clean_paragraphs_removes_continue_reading_prompt():
    chapter = parse_chapter_html(CHAPTER_PAGE_ONE_HTML, "https://www.92yanqing.com/read/92502/44142929.html")

    assert chapter.paragraphs == ["第一页正文。"]


def test_build_markdown_preserves_chapter_headings_and_paragraph_breaks():
    chapters = [
        ChapterContent(1, "第1章 【隆多兰的魔王与穿越者的幽灵】", "https://example.test/1.html", ["正文段落一。"]),
        ChapterContent(2, "第2章 【塔莉亚与萨麦尔】", "https://example.test/2.html", ["正文段落二。"]),
    ]

    markdown = build_markdown(chapters)

    assert "# 第1章 【隆多兰的魔王与穿越者的幽灵】" in markdown
    assert "# 第2章 【塔莉亚与萨麦尔】" in markdown
    assert "正文段落一。\n\n# 第2章" in markdown


def test_build_manifest_is_serializable_and_contains_chapter_metadata():
    chapters = [
        ChapterContent(1, "第1章 【隆多兰的魔王与穿越者的幽灵】", "https://example.test/1.html", ["正文段落一。"]),
    ]

    manifest = build_manifest("https://www.92yanqing.com/read/92502/", "幽魂骑士王的地下城工程", chapters)

    assert manifest["source_site"] == "92yanqing.com"
    assert manifest["source_url"] == "https://www.92yanqing.com/read/92502/"
    assert manifest["title"] == "幽魂骑士王的地下城工程"
    assert manifest["chapter_count"] == 1
    assert manifest["chapters"][0]["title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    json.dumps(manifest, ensure_ascii=False)


def test_crawl_novel_writes_markdown_and_manifest(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fetch_text(url: str) -> str:
        return pages[url]

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=1,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    assert result.markdown_path.read_text(encoding="utf-8-sig").startswith("# 第1章 【隆多兰的魔王与穿越者的幽灵】")
    assert result.markdown_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert result.manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["title"] == "幽魂骑士王的地下城工程"
    assert manifest["chapter_count"] == 1
    assert result.fetched_count == 1
    assert result.skipped == []


def test_crawl_novel_merges_same_chapter_paginated_pages(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_PAGE_ONE_HTML,
        "https://www.92yanqing.com/read/92502/44142929_2.html": CHAPTER_PAGE_TWO_HTML,
    }
    calls = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        return pages[url]

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=1,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    markdown = result.markdown_path.read_text(encoding="utf-8-sig")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))

    assert calls == [
        "https://www.92yanqing.com/read/92502/",
        "https://www.92yanqing.com/read/92502/44142929.html",
        "https://www.92yanqing.com/read/92502/44142929_2.html",
    ]
    assert "第一页正文。" in markdown
    assert "第二页后续正文。" in markdown
    assert "本章未完，点击下一页继续阅读。" not in markdown
    assert manifest["chapters"][0]["word_count"] == len("第一页正文。") + len("第二页后续正文。")
    assert manifest["chapters"][0]["page_urls"] == [
        "https://www.92yanqing.com/read/92502/44142929.html",
        "https://www.92yanqing.com/read/92502/44142929_2.html",
    ]


def test_crawl_novel_fail_stops_on_chapter_error(tmp_path):
    def fetch_text(url: str) -> str:
        if url.endswith("44142929.html"):
            raise RuntimeError("network failed")
        return DIRECTORY_HTML

    with pytest.raises(RuntimeError, match="network failed"):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=1,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="fail",
            fetch_text=fetch_text,
            sleep=lambda seconds: None,
        )

    assert not (tmp_path / "novel.md").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_crawl_novel_skip_records_failed_chapter(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142930.html": CHAPTER_HTML.replace("第1章", "第2章").replace(
            "隆多兰的魔王与穿越者的幽灵",
            "塔莉亚与萨麦尔",
        ),
    }

    def fetch_text(url: str) -> str:
        if url.endswith("44142929.html"):
            raise RuntimeError("network failed")
        return pages[url]

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=2,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="skip",
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert result.fetched_count == 1
    assert manifest["chapter_count"] == 1
    assert manifest["skipped"][0]["title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"


def test_crawl_novel_limit_zero_fetches_all_discovered_chapters(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
        "https://www.92yanqing.com/read/92502/44142930.html": CHAPTER_HTML.replace("第1章", "第2章").replace(
            "隆多兰的魔王与穿越者的幽灵",
            "塔莉亚与萨麦尔",
        ),
        "https://www.92yanqing.com/read/92502/50916992.html": CHAPTER_HTML.replace("第1章", "第143章").replace(
            "隆多兰的魔王与穿越者的幽灵",
            "启程之前",
        ),
    }

    def fetch_text(url: str) -> str:
        return pages[url]

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=0,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert result.fetched_count == 3
    assert manifest["chapter_count"] == 3
    assert [chapter["index"] for chapter in manifest["chapters"]] == [1, 2, 143]


def test_crawl_novel_rejects_negative_limit(tmp_path):
    with pytest.raises(ValueError, match="limit must be zero or greater"):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=-1,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="fail",
            fetch_text=lambda url: DIRECTORY_HTML,
            sleep=lambda seconds: None,
        )


def test_crawl_novel_keeps_partial_chapter_and_state_when_later_chapter_fails(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fetch_text(url: str) -> str:
        if url.endswith("44142930.html"):
            raise RuntimeError("ssl eof")
        return pages[url]

    with pytest.raises(RuntimeError, match="ssl eof"):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=2,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="fail",
            resume=True,
            fetch_text=fetch_text,
            sleep=lambda seconds: None,
        )

    partial = tmp_path / "partial_chapters" / "0001.md"
    state = json.loads((tmp_path / "crawl_state.json").read_text(encoding="utf-8-sig"))
    assert partial.read_text(encoding="utf-8-sig").startswith("# 第1章 【隆多兰的魔王与穿越者的幽灵】")
    assert state["completed_chapters"][0]["index"] == 1
    assert state["completed_chapters"][0]["partial_path"] == "partial_chapters/0001.md"
    assert state["failed_chapter"]["index"] == 2
    assert not (tmp_path / "novel.md").exists()
    assert not (tmp_path / "manifest.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_crawl_novel_resume_skips_completed_chapters_and_builds_final_outputs(tmp_path):
    first_pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fail_on_second_chapter(url: str) -> str:
        if url.endswith("44142930.html"):
            raise RuntimeError("ssl eof")
        return first_pages[url]

    with pytest.raises(RuntimeError):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=2,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="fail",
            resume=True,
            fetch_text=fail_on_second_chapter,
            sleep=lambda seconds: None,
        )

    calls = []
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142930.html": CHAPTER_HTML.replace("第1章", "第2章").replace(
            "隆多兰的魔王与穿越者的幽灵",
            "塔莉亚与萨麦尔",
        ),
    }

    def resume_fetch(url: str) -> str:
        calls.append(url)
        return pages[url]

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=2,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        resume=True,
        fetch_text=resume_fetch,
        sleep=lambda seconds: None,
    )

    markdown = result.markdown_path.read_text(encoding="utf-8-sig")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    state = json.loads((tmp_path / "crawl_state.json").read_text(encoding="utf-8-sig"))
    assert "https://www.92yanqing.com/read/92502/44142929.html" not in calls
    assert "https://www.92yanqing.com/read/92502/44142930.html" in calls
    assert "# 第1章 【隆多兰的魔王与穿越者的幽灵】" in markdown
    assert "# 第2章 【塔莉亚与萨麦尔】" in markdown
    assert manifest["chapter_count"] == 2
    assert [chapter["index"] for chapter in manifest["chapters"]] == [1, 2]
    assert [chapter["index"] for chapter in state["completed_chapters"]] == [1, 2]
    assert state.get("failed_chapter") is None


def test_crawl_novel_resume_skip_failure_keeps_partials_without_final_outputs(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fetch_text(url: str) -> str:
        if url.endswith("44142930.html"):
            raise RuntimeError("ssl eof")
        return pages[url]

    with pytest.raises(ValueError, match="crawl incomplete"):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=2,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="skip",
            resume=True,
            fetch_text=fetch_text,
            sleep=lambda seconds: None,
        )

    partial = tmp_path / "partial_chapters" / "0001.md"
    state = json.loads((tmp_path / "crawl_state.json").read_text(encoding="utf-8-sig"))
    assert partial.exists()
    assert state["completed_chapters"][0]["index"] == 1
    assert state["skipped_chapters"][0]["index"] == 2
    assert "ssl eof" in state["skipped_chapters"][0]["error"]
    assert not (tmp_path / "novel.md").exists()
    assert not (tmp_path / "manifest.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_crawl_novel_resume_refuses_state_from_different_command(tmp_path):
    (tmp_path / "partial_chapters").mkdir()
    (tmp_path / "crawl_state.json").write_text(
        json.dumps(
            {
                "source_url": "https://www.92yanqing.com/read/92502/",
                "title": "幽魂骑士王的地下城工程",
                "limit": 5,
                "completed_chapters": [],
                "failed_chapter": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    with pytest.raises(ValueError, match="crawl_state.json does not match current command"):
        crawl_novel(
            start_url="https://www.92yanqing.com/read/92502/",
            limit=0,
            output_dir=tmp_path,
            title="幽魂骑士王的地下城工程",
            delay=0,
            on_error="fail",
            resume=True,
            fetch_text=lambda url: DIRECTORY_HTML,
            sleep=lambda seconds: None,
        )


def test_crawl_novel_resume_does_not_overwrite_completed_partial(tmp_path):
    sentinel = "# 第1章 【隆多兰的魔王与穿越者的幽灵】\n\nSENTINEL 完成章节。"
    partial_dir = tmp_path / "partial_chapters"
    partial_dir.mkdir()
    (partial_dir / "0001.md").write_text(sentinel, encoding="utf-8-sig")
    (tmp_path / "crawl_state.json").write_text(
        json.dumps(
            {
                "source_url": "https://www.92yanqing.com/read/92502/",
                "title": "幽魂骑士王的地下城工程",
                "limit": 1,
                "completed_chapters": [
                    {
                        "index": 1,
                        "title": "第1章 【隆多兰的魔王与穿越者的幽灵】",
                        "url": "https://www.92yanqing.com/read/92502/44142929.html",
                        "page_urls": ["https://www.92yanqing.com/read/92502/44142929.html"],
                        "word_count": len("SENTINEL 完成章节。"),
                        "partial_path": "partial_chapters/0001.md",
                    }
                ],
                "failed_chapter": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    result = crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=1,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        resume=True,
        fetch_text=lambda url: DIRECTORY_HTML,
        sleep=lambda seconds: None,
    )

    assert (partial_dir / "0001.md").read_text(encoding="utf-8-sig") == sentinel
    assert "SENTINEL 完成章节。" in result.markdown_path.read_text(encoding="utf-8-sig")


def test_crawl_novel_backs_up_existing_top_level_outputs_before_resume(tmp_path):
    (tmp_path / "novel.md").write_text("old novel", encoding="utf-8-sig")
    (tmp_path / "manifest.json").write_text('{"old": true}', encoding="utf-8-sig")
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fetch_text(url: str) -> str:
        return pages[url]

    crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=1,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        resume=True,
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    backups = sorted(path.name for path in tmp_path.glob("*.bak-*"))
    assert any(name.startswith("novel.md.bak-") for name in backups)
    assert any(name.startswith("manifest.json.bak-") for name in backups)
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8-sig"))["chapter_count"] == 1


def test_crawl_novel_backs_up_existing_top_level_outputs_before_fresh_crawl(tmp_path):
    (tmp_path / "novel.md").write_text("old novel", encoding="utf-8-sig")
    (tmp_path / "manifest.json").write_text('{"old": true}', encoding="utf-8-sig")
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142929.html": CHAPTER_HTML,
    }

    def fetch_text(url: str) -> str:
        return pages[url]

    crawl_novel(
        start_url="https://www.92yanqing.com/read/92502/",
        limit=1,
        output_dir=tmp_path,
        title="幽魂骑士王的地下城工程",
        delay=0,
        on_error="fail",
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    backups = sorted(path.name for path in tmp_path.glob("*.bak-*"))
    assert any(name.startswith("novel.md.bak-") for name in backups)
    assert any(name.startswith("manifest.json.bak-") for name in backups)
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8-sig"))["chapter_count"] == 1


def test_main_passes_cli_arguments_to_crawler(tmp_path):
    calls = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url.endswith("44142929.html"):
            return CHAPTER_HTML
        return DIRECTORY_HTML

    exit_code = main(
        [
            "--start-url",
            "https://www.92yanqing.com/read/92502/",
            "--limit",
            "1",
            "--output-dir",
            str(tmp_path),
            "--title",
            "幽魂骑士王的地下城工程",
            "--delay",
            "0",
            "--on-error",
            "fail",
        ],
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    assert exit_code == 0
    assert calls == [
        "https://www.92yanqing.com/read/92502/",
        "https://www.92yanqing.com/read/92502/44142929.html",
    ]
    assert (tmp_path / "novel.md").exists()


def test_main_accepts_resume_flag(tmp_path):
    calls = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url.endswith("44142929.html"):
            return CHAPTER_HTML
        return DIRECTORY_HTML

    exit_code = main(
        [
            "--start-url",
            "https://www.92yanqing.com/read/92502/",
            "--limit",
            "1",
            "--output-dir",
            str(tmp_path),
            "--title",
            "幽魂骑士王的地下城工程",
            "--delay",
            "0",
            "--on-error",
            "fail",
            "--resume",
        ],
        fetch_text=fetch_text,
        sleep=lambda seconds: None,
    )

    assert exit_code == 0
    assert calls == [
        "https://www.92yanqing.com/read/92502/",
        "https://www.92yanqing.com/read/92502/44142929.html",
    ]
    assert (tmp_path / "partial_chapters" / "0001.md").exists()


def test_main_requires_start_url():
    with pytest.raises(SystemExit) as exc_info:
        main([], fetch_text=lambda url: "", sleep=lambda seconds: None)

    assert exc_info.value.code == 2


def test_main_rejects_invalid_on_error():
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--start-url",
                "https://www.92yanqing.com/read/92502/",
                "--on-error",
                "continue",
            ],
            fetch_text=lambda url: "",
            sleep=lambda seconds: None,
        )

    assert exc_info.value.code == 2
