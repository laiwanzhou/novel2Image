from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ChapterLink:
    index: int
    title: str
    url: str


@dataclass(frozen=True)
class ChapterContent:
    index: int
    title: str
    url: str
    paragraphs: list[str]
    page_urls: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(len(paragraph) for paragraph in self.paragraphs)


@dataclass(frozen=True)
class CrawlResult:
    output_dir: Path
    markdown_path: Path
    manifest_path: Path
    fetched_count: int
    skipped: list[dict[str, str]]


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href is not None:
            self.links.append((self._current_href, "".join(self._current_text)))
            self._current_href = None
            self._current_text = []


class _NextPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if not href:
            return
        element_id = attrs_dict.get("id")
        rel = attrs_dict.get("rel")
        rel_values = {value.strip().lower() for value in rel.split()} if rel else set()
        if element_id == "next_url" or "next" in rel_values:
            self.candidates.append(href)


class _ElementTextParser(HTMLParser):
    def __init__(self, *, target_tag: str, target_id: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.text = ""
        self._target_tag = target_tag
        self._target_id = target_id
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._depth:
            if tag in {"br", "p", "div"}:
                self._parts.append("\n")
            if tag != "br":
                self._depth += 1
            return

        if tag != self._target_tag:
            return
        attrs_dict = dict(attrs)
        if self._target_id is None or attrs_dict.get("id") == self._target_id:
            self._depth = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth and tag.lower() == "br":
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag.lower() in {"br", "p", "div"}:
            self._parts.append("\n")
        self._depth -= 1
        if self._depth == 0:
            self.text = "".join(self._parts)


def normalize_title(title: str) -> str:
    normalized = re.sub(r"\s*[（(]\s*\d+\s*/\s*\d+\s*[）)]\s*$", "", title.strip())
    return re.sub(r"\s+", " ", normalized).strip()


def extract_chapter_links(directory_html: str, start_url: str) -> list[ChapterLink]:
    parser = _AnchorParser()
    parser.feed(directory_html)

    start = urlparse(start_url)
    path_match = re.search(r"^(/read/\d+/)", start.path)
    if not path_match:
        raise ValueError(f"Unsupported directory URL: {start_url}")
    book_path = path_match.group(1)

    seen_urls: set[str] = set()
    links: list[ChapterLink] = []
    for href, text in parser.links:
        absolute_url = urljoin(start_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc != start.netloc:
            continue
        if not re.fullmatch(rf"{re.escape(book_path)}\d+\.html", parsed.path):
            continue
        title = normalize_title(unescape(text))
        index_match = re.search(r"第\s*(\d+)\s*章", title)
        if not index_match or absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        links.append(ChapterLink(index=int(index_match.group(1)), title=title, url=absolute_url))

    return sorted(links, key=lambda link: link.index)


def extract_next_page_url(html: str, current_url: str, chapter_index: int) -> str | None:
    title_parser = _ElementTextParser(target_tag="h1")
    title_parser.feed(html)
    title = normalize_title(title_parser.text)
    title_index_match = re.search(r"第\s*(\d+)\s*章", title)
    if title_index_match and int(title_index_match.group(1)) != chapter_index:
        return None

    current = urlparse(current_url)
    current_match = re.fullmatch(r"(?P<prefix>/read/\d+/\d+)(?:_(?P<page>\d+))?\.html", current.path)
    if not current_match:
        return None

    parser = _NextPageParser()
    parser.feed(html)
    for href in parser.candidates:
        if href.strip().lower().startswith("javascript:"):
            continue
        absolute_url = urljoin(current_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc != current.netloc:
            continue
        candidate_match = re.fullmatch(r"(?P<prefix>/read/\d+/\d+)_(?P<page>\d+)\.html", parsed.path)
        if not candidate_match:
            continue
        if candidate_match.group("prefix") != current_match.group("prefix"):
            continue
        return absolute_url
    return None


def clean_paragraphs(raw_html: str, title: str) -> list[str]:
    text = unescape(raw_html).replace("\xa0", " ")
    paragraphs = [re.sub(r"\s+", " ", paragraph).strip() for paragraph in re.split(r"\n+", text)]
    noise_patterns = ("上一章", "下一章", "返回目录", "请收藏", "最新网址", "手机阅读", "本章未完，点击下一页继续阅读")

    cleaned: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        if not cleaned and normalize_title(paragraph) == title:
            continue
        if any(pattern in paragraph for pattern in noise_patterns):
            continue
        cleaned.append(paragraph)
    return cleaned


def parse_chapter_html(html: str, url: str) -> ChapterContent:
    title_parser = _ElementTextParser(target_tag="h1")
    title_parser.feed(html)
    title = normalize_title(title_parser.text)
    if not title:
        raise ValueError(f"Chapter title not found: {url}")

    body_parser = _ElementTextParser(target_tag="div", target_id="booktxt")
    body_parser.feed(html)
    if not body_parser.text:
        raise ValueError(f"Chapter body not found: {url}")

    index_match = re.search(r"第\s*(\d+)\s*章", title)
    if not index_match:
        raise ValueError(f"Chapter index not found in title: {title}")

    return ChapterContent(
        index=int(index_match.group(1)),
        title=title,
        url=url,
        paragraphs=clean_paragraphs(body_parser.text, title),
        page_urls=[url],
    )


def _merge_chapter_pages(first_page: ChapterContent, pages: list[ChapterContent]) -> ChapterContent:
    paragraphs: list[str] = []
    page_urls: list[str] = []
    for page in pages:
        if page.index != first_page.index:
            raise ValueError(f"Chapter pagination crossed chapter boundary: {first_page.url} -> {page.url}")
        paragraphs.extend(page.paragraphs)
        page_urls.extend(page.page_urls or [page.url])
    return ChapterContent(
        index=first_page.index,
        title=first_page.title,
        url=first_page.url,
        paragraphs=paragraphs,
        page_urls=page_urls,
    )


def _fetch_chapter_pages(
    *,
    link: ChapterLink,
    delay: float,
    fetch_text: Callable[[str], str],
    sleep: Callable[[float], None],
) -> ChapterContent:
    current_url = link.url
    visited: set[str] = set()
    pages: list[ChapterContent] = []

    while True:
        if current_url in visited:
            raise ValueError(f"Chapter pagination loop detected: {current_url}")
        visited.add(current_url)
        html = fetch_text(current_url)
        page = parse_chapter_html(html, current_url)
        if page.index != link.index:
            raise ValueError(f"Chapter index changed while fetching pagination: {link.url} -> {current_url}")
        pages.append(page)

        next_url = extract_next_page_url(html, current_url, link.index)
        if next_url is None:
            break
        if delay > 0:
            sleep(delay)
        current_url = next_url

    return _merge_chapter_pages(pages[0], pages)


def build_markdown(chapters: list[ChapterContent]) -> str:
    sections: list[str] = []
    for chapter in chapters:
        parts = [f"# {chapter.title}", *chapter.paragraphs]
        sections.append("\n\n".join(parts))
    return "\n\n".join(sections).rstrip() + "\n"


def build_manifest(source_url: str, title: str, chapters: list[ChapterContent]) -> dict[str, object]:
    parsed = urlparse(source_url)
    source_site = parsed.netloc.removeprefix("www.")
    return {
        "source_site": source_site,
        "source_url": source_url,
        "title": title,
        "chapter_count": len(chapters),
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "chapters": [
            {
                "index": chapter.index,
                "title": chapter.title,
                "url": chapter.url,
                "page_urls": chapter.page_urls or [chapter.url],
                "word_count": chapter.word_count,
            }
            for chapter in chapters
        ],
    }


def _chapter_to_state_entry(chapter: ChapterContent, partial_path: Path) -> dict[str, object]:
    return {
        "index": chapter.index,
        "title": chapter.title,
        "url": chapter.url,
        "page_urls": chapter.page_urls or [chapter.url],
        "word_count": chapter.word_count,
        "partial_path": partial_path.as_posix(),
    }


def _chapter_from_state_entry(entry: dict[str, object], output_dir: Path) -> ChapterContent:
    partial_path = output_dir / str(entry["partial_path"])
    markdown = partial_path.read_text(encoding="utf-8-sig")
    lines = markdown.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Invalid partial chapter file: {partial_path}")
    paragraphs = [block.strip() for block in "\n".join(lines[1:]).split("\n\n") if block.strip()]
    return ChapterContent(
        index=int(entry["index"]),
        title=str(entry["title"]),
        url=str(entry["url"]),
        paragraphs=paragraphs,
        page_urls=[str(url) for url in entry.get("page_urls", [])],
    )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(text, encoding="utf-8-sig")
    temp_path.replace(path)


def _write_json_atomic(path: Path, data: dict[str, object]) -> None:
    _write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _state_path(output_dir: Path) -> Path:
    return output_dir / "crawl_state.json"


def _initial_state(start_url: str, title: str, limit: int) -> dict[str, object]:
    return {
        "source_url": start_url,
        "title": title,
        "limit": limit,
        "completed_chapters": [],
        "skipped_chapters": [],
        "failed_chapter": None,
    }


def _load_or_create_state(output_dir: Path, start_url: str, title: str, limit: int, resume: bool) -> dict[str, object]:
    path = _state_path(output_dir)
    if resume and path.exists():
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        if state.get("source_url") != start_url or state.get("title") != title or state.get("limit") != limit:
            raise ValueError("crawl_state.json does not match current command")
        state.setdefault("completed_chapters", [])
        state.setdefault("skipped_chapters", [])
        state["failed_chapter"] = None
        return state
    return _initial_state(start_url, title, limit)


def _completed_by_index(state: dict[str, object]) -> dict[int, dict[str, object]]:
    return {int(entry["index"]): entry for entry in state.get("completed_chapters", [])}


def _update_completed_chapter(state: dict[str, object], entry: dict[str, object]) -> None:
    completed = [item for item in state.get("completed_chapters", []) if int(item["index"]) != int(entry["index"])]
    completed.append(entry)
    state["completed_chapters"] = sorted(completed, key=lambda item: int(item["index"]))
    state["skipped_chapters"] = [
        item for item in state.get("skipped_chapters", []) if int(item["index"]) != int(entry["index"])
    ]
    state["failed_chapter"] = None


def _record_skipped_chapter(state: dict[str, object], link: ChapterLink, exc: Exception) -> None:
    skipped = [item for item in state.get("skipped_chapters", []) if int(item["index"]) != link.index]
    skipped.append(
        {
            "index": link.index,
            "title": link.title,
            "url": link.url,
            "error": str(exc),
        }
    )
    state["skipped_chapters"] = sorted(skipped, key=lambda item: int(item["index"]))
    state["failed_chapter"] = state["skipped_chapters"][-1]


def _write_partial_chapter(output_dir: Path, chapter: ChapterContent) -> Path:
    relative_path = Path("partial_chapters") / f"{chapter.index:04d}.md"
    _write_text_atomic(output_dir / relative_path, build_markdown([chapter]))
    return relative_path


def _write_final_outputs_from_state(output_dir: Path, start_url: str, title: str, state: dict[str, object]) -> tuple[Path, Path, int]:
    chapters = [_chapter_from_state_entry(entry, output_dir) for entry in state.get("completed_chapters", [])]
    chapters.sort(key=lambda chapter: chapter.index)
    manifest = build_manifest(start_url, title, chapters)
    markdown_path = output_dir / "novel.md"
    manifest_path = output_dir / "manifest.json"
    _write_text_atomic(markdown_path, build_markdown(chapters))
    _write_json_atomic(manifest_path, manifest)
    return markdown_path, manifest_path, len(chapters)


def _backup_existing_top_level_outputs(output_dir: Path) -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    for filename in ("novel.md", "manifest.json"):
        path = output_dir / filename
        if path.exists():
            path.replace(output_dir / f"{filename}.bak-{timestamp}")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return slug.lower() or "novel"


def _default_output_dir(start_url: str, title: str | None) -> Path:
    base_dir = Path(__file__).resolve().parents[1] / "data" / "crawled"
    if title:
        return base_dir / _slugify(title)
    parsed = urlparse(start_url)
    path_slug = parsed.path.strip("/").replace("/", "-")
    return base_dir / _slugify(path_slug)


def crawl_novel(
    *,
    start_url: str,
    limit: int,
    output_dir: Path,
    title: str | None,
    delay: float,
    on_error: Literal["fail", "skip"],
    fetch_text: Callable[[str], str],
    sleep: Callable[[float], None] = time.sleep,
    resume: bool = False,
) -> CrawlResult:
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if on_error not in {"fail", "skip"}:
        raise ValueError("on_error must be 'fail' or 'skip'")

    directory_html = fetch_text(start_url)
    links = extract_chapter_links(directory_html, start_url)
    selected_links = links if limit == 0 else links[:limit]
    effective_title = title or "Untitled Novel"
    output_dir.mkdir(parents=True, exist_ok=True)
    _backup_existing_top_level_outputs(output_dir)

    if resume:
        state = _load_or_create_state(output_dir, start_url, effective_title, limit, resume=True)
        completed = _completed_by_index(state)
        for position, link in enumerate(selected_links):
            if link.index in completed:
                continue
            try:
                chapter = _fetch_chapter_pages(
                    link=link,
                    delay=delay,
                    fetch_text=fetch_text,
                    sleep=sleep,
                )
                partial_path = _write_partial_chapter(output_dir, chapter)
                _update_completed_chapter(state, _chapter_to_state_entry(chapter, partial_path))
                _write_json_atomic(_state_path(output_dir), state)
            except Exception as exc:
                state["failed_chapter"] = {
                    "index": link.index,
                    "title": link.title,
                    "url": link.url,
                    "error": str(exc),
                }
                if on_error == "skip":
                    _record_skipped_chapter(state, link, exc)
                _write_json_atomic(_state_path(output_dir), state)
                if on_error == "fail":
                    raise
            if position < len(selected_links) - 1 and delay > 0:
                sleep(delay)

        completed_indexes = set(_completed_by_index(state))
        missing_indexes = [link.index for link in selected_links if link.index not in completed_indexes]
        if missing_indexes:
            _write_json_atomic(_state_path(output_dir), state)
            raise ValueError(f"crawl incomplete; missing chapter indexes: {missing_indexes}")

        state["failed_chapter"] = None
        _write_json_atomic(_state_path(output_dir), state)
        markdown_path, manifest_path, fetched_count = _write_final_outputs_from_state(output_dir, start_url, effective_title, state)
        return CrawlResult(
            output_dir=output_dir,
            markdown_path=markdown_path,
            manifest_path=manifest_path,
            fetched_count=fetched_count,
            skipped=[],
        )

    chapters: list[ChapterContent] = []
    skipped: list[dict[str, str]] = []

    for position, link in enumerate(selected_links):
        try:
            chapters.append(
                _fetch_chapter_pages(
                    link=link,
                    delay=delay,
                    fetch_text=fetch_text,
                    sleep=sleep,
                )
            )
        except Exception as exc:
            if on_error == "fail":
                raise
            skipped.append(
                {
                    "index": str(link.index),
                    "title": link.title,
                    "url": link.url,
                    "error": str(exc),
                }
            )
        if position < len(selected_links) - 1 and delay > 0:
            sleep(delay)

    manifest = build_manifest(start_url, effective_title, chapters)
    if skipped:
        manifest["skipped"] = skipped

    markdown_path = output_dir / "novel.md"
    manifest_path = output_dir / "manifest.json"
    _write_text_atomic(markdown_path, build_markdown(chapters))
    _write_json_atomic(manifest_path, manifest)

    return CrawlResult(
        output_dir=output_dir,
        markdown_path=markdown_path,
        manifest_path=manifest_path,
        fetched_count=len(chapters),
        skipped=skipped,
    )


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "NovelVisManualValidationBot/0.1 (+local operator validation)",
        },
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
        return raw.decode(encoding, errors="replace")


def main(
    argv: list[str] | None = None,
    *,
    fetch_text: Callable[[str], str] = _fetch_text,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description="Crawl approved novel chapters into Markdown and manifest files.")
    parser.add_argument("--start-url", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--on-error", choices=["fail", "skip"], default="fail")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    output_dir = args.output_dir or _default_output_dir(args.start_url, args.title)
    result = crawl_novel(
        start_url=args.start_url,
        limit=args.limit,
        output_dir=output_dir,
        title=args.title,
        delay=args.delay,
        on_error=args.on_error,
        fetch_text=fetch_text,
        sleep=sleep,
        resume=args.resume,
    )
    print(f"novel.md written: {result.markdown_path}")
    print(f"manifest.json written: {result.manifest_path}")
    print(f"fetched_count={result.fetched_count}")
    if result.skipped:
        print(f"skipped_count={len(result.skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
