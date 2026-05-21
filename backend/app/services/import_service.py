from pathlib import Path
import hashlib
import re

from app.schemas.import_schema import BookManifest, ChapterInput


CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<title>"
    r"(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节卷回部篇](?:\s+.*|[：:、.-].*)?)"
    r"|(?:Chapter\s+\d+(?:\s+.*)?)"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class ImportService:
    def parse_path(self, path: Path, title: str | None = None, author: str | None = None) -> BookManifest:
        source_type = self._source_type_for(path)
        if source_type == "epub":
            raise NotImplementedError("EPUB import is not implemented yet")
        text = path.read_text(encoding="utf-8-sig")
        chapters = self.parse_chapters(text, source_path=str(path))
        return BookManifest(
            title=title or path.stem,
            author=author,
            source_type=source_type,
            chapters=chapters,
        )

    def parse_chapters(self, text: str, source_path: str | None = None) -> list[ChapterInput]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []

        matches = list(CHAPTER_HEADING_RE.finditer(normalized))
        if not matches:
            return [
                ChapterInput(
                    chapter_index=1,
                    title="正文",
                    content=normalized,
                    source_path=source_path,
                    word_count=self._count_words(normalized),
                    checksum=self._checksum(normalized),
                )
            ]

        chapters: list[ChapterInput] = []
        for index, match in enumerate(matches, start=1):
            content_start = match.end()
            content_end = matches[index].start() if index < len(matches) else len(normalized)
            content = normalized[content_start:content_end].strip()
            title = self._clean_heading(match.group("title"))
            chapters.append(
                ChapterInput(
                    chapter_index=index,
                    title=title,
                    content=content,
                    source_path=source_path,
                    word_count=self._count_words(content),
                    checksum=self._checksum(content),
                )
            )
        return chapters

    def _source_type_for(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return "txt"
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix == ".epub":
            return "epub"
        raise ValueError(f"Unsupported import file type: {suffix}")

    def _clean_heading(self, heading: str) -> str:
        return re.sub(r"^\s*#{1,6}\s*", "", heading).strip()

    def _count_words(self, text: str) -> int:
        return len(re.sub(r"\s+", "", text))

    def _checksum(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
