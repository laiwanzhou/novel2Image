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

CHAPTER_NUMBER_RE = re.compile(r"第\s*(?P<number>\d+)\s*[章节卷回部篇]")


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

        matches = self._deduplicate_heading_matches(list(CHAPTER_HEADING_RE.finditer(normalized)), normalized)
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
        for sequence_index, match in enumerate(matches, start=1):
            content_start = match.end()
            content_end = matches[sequence_index].start() if sequence_index < len(matches) else len(normalized)
            title = self._clean_heading(match.group("title"))
            content = self._strip_duplicate_leading_title(normalized[content_start:content_end], title)
            chapter_index = self._chapter_index_from_title(title, sequence_index)
            chapters.append(
                ChapterInput(
                    chapter_index=chapter_index,
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

    def _deduplicate_heading_matches(self, matches: list[re.Match[str]], text: str) -> list[re.Match[str]]:
        deduplicated: list[re.Match[str]] = []
        for match in matches:
            if deduplicated:
                previous = deduplicated[-1]
                gap = text[previous.end() : match.start()]
                if not gap.strip() and self._chapter_titles_equivalent(previous.group("title"), match.group("title")):
                    continue
            deduplicated.append(match)
        return deduplicated

    def _strip_duplicate_leading_title(self, content: str, title: str) -> str:
        lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        non_empty_seen = 0
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            non_empty_seen += 1
            if non_empty_seen > 3:
                break
            if self._chapter_titles_equivalent(title, line):
                del lines[index]
            break
        return "\n".join(lines).strip()

    def _chapter_titles_equivalent(self, left: str, right: str) -> bool:
        return self._normalize_chapter_title_for_compare(left) == self._normalize_chapter_title_for_compare(right)

    def _normalize_chapter_title_for_compare(self, value: str) -> str:
        cleaned = self._clean_heading(value)
        return re.sub(r"[\s#·・.。:：、,\-—_\[\]【】()（）《》<>〈〉「」『』“”\"'`]+", "", cleaned)

    def _chapter_index_from_title(self, title: str, fallback: int) -> int:
        match = CHAPTER_NUMBER_RE.search(title)
        if match is None:
            return fallback
        return int(match.group("number"))

    def _count_words(self, text: str) -> int:
        return len(re.sub(r"\s+", "", text))

    def _checksum(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
