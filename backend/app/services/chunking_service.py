from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    char_count: int
    token_count: int
    checksum: str


@dataclass(frozen=True)
class ParagraphSpan:
    text: str
    start_char: int
    end_char: int


class ChunkingService:
    def chunk_chapter(self, content: str, target_chars: int = 1200, max_chars: int = 1500) -> list[ChunkDraft]:
        """Aggregate complete paragraphs into chunks, using max_chars as the hard split boundary."""
        paragraphs = self._paragraphs(content)
        if not paragraphs:
            return []

        chunks: list[ChunkDraft] = []
        current: list[ParagraphSpan] = []
        current_len = 0

        for paragraph in paragraphs:
            next_len = current_len + len(paragraph.text)
            if current and next_len > max_chars:
                chunks.append(self._build_chunk(len(chunks) + 1, current))
                current = [paragraph]
                current_len = len(paragraph.text)
                continue

            current.append(paragraph)
            current_len = next_len

        if current:
            chunks.append(self._build_chunk(len(chunks) + 1, current))

        return chunks

    def _paragraphs(self, content: str) -> list[ParagraphSpan]:
        spans: list[ParagraphSpan] = []
        for match in re.finditer(r"\S(?:.*\S)?", content):
            text = match.group(0).strip()
            if text:
                spans.append(ParagraphSpan(text=text, start_char=match.start(), end_char=match.end()))
        return spans

    def _build_chunk(self, chunk_index: int, paragraphs: list[ParagraphSpan]) -> ChunkDraft:
        text = "\n\n".join(paragraph.text for paragraph in paragraphs)
        start_char = paragraphs[0].start_char
        end_char = paragraphs[-1].end_char
        return ChunkDraft(
            chunk_index=chunk_index,
            text=text,
            start_char=start_char,
            end_char=end_char,
            char_count=len(text),
            token_count=self._estimate_tokens(text),
            checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    def _estimate_tokens(self, text: str) -> int:
        compact_length = len(re.sub(r"\s+", "", text))
        return max(1, compact_length)
