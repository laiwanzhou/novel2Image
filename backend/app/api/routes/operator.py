from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter


router = APIRouter(prefix="/operator", tags=["operator"])

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PREVIEW_DIR = PROJECT_ROOT / "backend" / "data" / "samples" / "crawled-novel"
CRAWLED_DIR = Path(os.getenv("NOVEL_VIS_CRAWLED_PREVIEW_DIR", str(DEFAULT_PREVIEW_DIR)))
NOVEL_MD_PATH = CRAWLED_DIR / "novel.md"
MANIFEST_PATH = CRAWLED_DIR / "manifest.json"
PREVIEW_CHAR_LIMIT = 1800
CHAPTER_HEADING_RE = re.compile(r"^#\s*(第\s*(?P<index>\d+)\s*章[^\n]*)$", re.MULTILINE)


@router.get("/crawled-novel-preview")
def crawled_novel_preview(chapter_index: int = 1) -> dict:
    if not NOVEL_MD_PATH.exists():
        raise ValueError(f"Crawled novel Markdown not found: {NOVEL_MD_PATH}")
    if not MANIFEST_PATH.exists():
        raise ValueError(f"Crawled novel manifest not found: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    markdown = NOVEL_MD_PATH.read_text(encoding="utf-8-sig")
    preview_text = markdown[:PREVIEW_CHAR_LIMIT]
    selected_chapter = _extract_chapter(markdown, chapter_index)
    return {
        "novel_md_path": str(NOVEL_MD_PATH),
        "manifest_path": str(MANIFEST_PATH),
        "title": manifest["title"],
        "chapter_count": manifest["chapter_count"],
        "chapters": [
            {
                "index": chapter["index"],
                "title": chapter["title"],
                "word_count": chapter["word_count"],
                "page_urls": chapter.get("page_urls", [chapter["url"]]),
            }
            for chapter in manifest["chapters"]
        ],
        "preview_text": preview_text,
        "selected_chapter_index": selected_chapter["index"],
        "selected_chapter_title": selected_chapter["title"],
        "chapter_text": selected_chapter["text"],
    }


def _extract_chapter(markdown: str, chapter_index: int) -> dict[str, str | int]:
    matches = list(CHAPTER_HEADING_RE.finditer(markdown))
    for position, match in enumerate(matches):
        if int(match.group("index")) != chapter_index:
            continue
        body_start = match.end()
        body_end = matches[position + 1].start() if position + 1 < len(matches) else len(markdown)
        return {
            "index": chapter_index,
            "title": match.group(1).strip(),
            "text": markdown[body_start:body_end].strip(),
        }
    raise ValueError(f"Chapter index not found in crawled novel Markdown: {chapter_index}")
