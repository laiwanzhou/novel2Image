# Real Data Crawl Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small operator-only crawler script that fetches the first chapters from the approved 92yanqing directory page into local Markdown and manifest files, then document how to feed those files through the existing MVP CLI and Workspace validation flow.

**Architecture:** Keep this outside the product path. The crawler lives under `backend/scripts/`, writes `novel.md` and `manifest.json`, and does not call FastAPI routes, services, repositories, database sessions, or frontend code. Pure parsing and cleaning behavior is covered by offline tests; live network access is only a manual verification step.

**Tech Stack:** Python 3.11, standard library where practical, `requests` and `beautifulsoup4` if already available or added to backend dependencies, pytest, ruff, PowerShell operator commands.

---

## Scope Guardrails

This plan does not add:

- generic crawler platform;
- crawling for sites other than the approved `92yanqing.com/read/92502/` structure;
- login bypass or anti-scraping bypass;
- concurrent crawling;
- full-book large-scale crawling;
- direct database writes;
- FastAPI integration;
- Novel Workspace integration;
- browser upload;
- Celery, Redis, task queue, progress, cancellation, or retry;
- Qdrant or Neo4j;
- FastGPT integration;
- real LLM extraction;
- image generation;
- changes to prompt generation, CharacterState, or evidence lifecycle.

If the site becomes inaccessible, robots.txt changes to disallow crawling, a login gate appears, or requests are blocked, stop the live verification and report the blocker. Do not bypass restrictions.

## Target File Map

- Create `backend/scripts/crawl_novel_site.py`: standalone operator script and pure helper functions.
- Create `backend/tests/test_crawl_novel_site.py`: offline tests using inline HTML fixtures and `tmp_path`; no live network.
- Create `docs/operator/real-data-manual-validation.md`: operator instructions from crawl output through Workspace status inspection.
- Modify `backend/pyproject.toml` only if `requests` or `beautifulsoup4` is not already declared and the implementation chooses those packages.

## Checkpoint 1: Script Skeleton And Pure Function Tests

**Goal:** Create the crawler module with testable pure functions for title normalization, text cleanup, directory parsing, chapter parsing, Markdown building, and manifest building.

**Files:**

- Create: `backend/scripts/crawl_novel_site.py`
- Create: `backend/tests/test_crawl_novel_site.py`
- Modify: `backend/pyproject.toml` only if parser dependencies are needed

**Network access:** none. All tests use inline HTML strings.

**Functions to implement:**

```text
normalize_title(title: str) -> str
clean_paragraphs(raw_html: str, title: str) -> list[str]
extract_chapter_links(directory_html: str, start_url: str) -> list[ChapterLink]
parse_chapter_html(html: str, url: str) -> ChapterContent
build_markdown(chapters: list[ChapterContent]) -> str
build_manifest(source_url: str, title: str, chapters: list[ChapterContent]) -> dict[str, object]
```

Suggested dataclasses:

```python
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

    @property
    def word_count(self) -> int:
        return sum(len(paragraph) for paragraph in self.paragraphs)
```

- [x] **Step 1: Add failing tests for `normalize_title()`**

Create `backend/tests/test_crawl_novel_site.py` with:

```python
from scripts.crawl_novel_site import normalize_title


def test_normalize_title_removes_full_width_pagination_suffix():
    assert normalize_title("第1章 【隆多兰的魔王与穿越者的幽灵】（1/2）") == "第1章 【隆多兰的魔王与穿越者的幽灵】"


def test_normalize_title_removes_ascii_pagination_suffix():
    assert normalize_title("第2章 【塔莉亚与萨麦尔】 (1/2)") == "第2章 【塔莉亚与萨麦尔】"
```

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
```

Expected: fail because the script and function do not exist yet.

- [x] **Step 2: Create script skeleton and `normalize_title()`**

Create `backend/scripts/crawl_novel_site.py` with imports, dataclasses, and:

```python
from __future__ import annotations

import re
from dataclasses import dataclass


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

    @property
    def word_count(self) -> int:
        return sum(len(paragraph) for paragraph in self.paragraphs)


def normalize_title(title: str) -> str:
    normalized = re.sub(r"\s*[（(]\s*\d+\s*/\s*\d+\s*[）)]\s*$", "", title.strip())
    return re.sub(r"\s+", " ", normalized).strip()
```

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
```

Expected: title tests pass.

- [x] **Step 3: Add failing tests for directory link extraction**

Append tests:

```python
from scripts.crawl_novel_site import extract_chapter_links


DIRECTORY_HTML = """
<html><body>
  <a href="https://www.92yanqing.com/read/92502/50916992.html">第143章 【启程之前】</a>
  <a href="/read/92502/44142929.html">第1章 【隆多兰的魔王与穿越者的幽灵】</a>
  <a href="/read/92502/44142930.html">第2章 【塔莉亚与萨麦尔】</a>
  <a href="/read/92502/44142929.html">第1章 【隆多兰的魔王与穿越者的幽灵】</a>
  <a href="/read/99999/1.html">其他书</a>
</body></html>
"""


def test_extract_chapter_links_keeps_catalog_order_and_deduplicates():
    links = extract_chapter_links(DIRECTORY_HTML, "https://www.92yanqing.com/read/92502/")

    assert [link.index for link in links[:2]] == [1, 2]
    assert links[0].title == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert links[0].url == "https://www.92yanqing.com/read/92502/44142929.html"
```

Run the same pytest command.

Expected: fail because `extract_chapter_links()` is not implemented.

- [x] **Step 4: Implement `extract_chapter_links()`**

Implement with BeautifulSoup or the standard `html.parser`. If using BeautifulSoup and it is not already installed, add `beautifulsoup4>=4.12` to `backend/pyproject.toml`.

Behavior:

- only include links matching the same `/read/92502/<id>.html` path as `start_url`;
- extract numeric chapter index from link text matching `第<digits>章`;
- remove duplicate URLs;
- sort by chapter index ascending so latest-chapter links near the top do not appear before chapter 1.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
```

Expected: link extraction tests pass.

- [x] **Step 5: Add failing tests for chapter parsing and cleanup**

Append tests:

```python
from scripts.crawl_novel_site import parse_chapter_html


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


def test_parse_chapter_html_uses_h1_booktxt_and_cleans_noise():
    chapter = parse_chapter_html(CHAPTER_HTML, "https://www.92yanqing.com/read/92502/44142929.html")

    assert chapter.index == 1
    assert chapter.title == "第1章 【隆多兰的魔王与穿越者的幽灵】"
    assert chapter.paragraphs == ["正文第一段。", "正文第二段。"]
```

Run the same pytest command.

Expected: fail because `parse_chapter_html()` and cleanup are not implemented.

- [x] **Step 6: Implement `clean_paragraphs()` and `parse_chapter_html()`**

Behavior:

- parse title from `h1`;
- normalize pagination suffixes with `normalize_title()`;
- parse body from `div#booktxt`;
- convert `<br>` and block boundaries into paragraph breaks;
- strip empty paragraphs;
- remove a first paragraph that duplicates the title;
- remove navigation and ad lines containing phrases like `上一章`, `下一章`, `返回目录`, `请收藏`, `最新网址`, `手机阅读`;
- keep story prose unchanged.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
```

Expected: parsing and cleanup tests pass.

- [x] **Step 7: Add failing tests for Markdown and manifest builders**

Append tests:

```python
from scripts.crawl_novel_site import ChapterContent, build_manifest, build_markdown


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
```

Run the same pytest command.

Expected: fail because builder functions are not implemented.

- [x] **Step 8: Implement `build_markdown()` and `build_manifest()`**

Implementation rules:

- `build_markdown()` writes one `# title` heading per chapter;
- separate heading and paragraphs with blank lines;
- end file with one newline;
- `build_manifest()` returns a JSON-serializable dict with `source_site`, `source_url`, `title`, `chapter_count`, `fetched_at`, and `chapters`.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
.\.venv\Scripts\python -m ruff check app tests alembic scripts
```

Expected: crawler tests pass and ruff passes.

**Verification method:** offline pytest and ruff only.

**Explicitly not in this checkpoint:** network fetching, file output command, real site access, database writes, FastAPI, frontend, Workspace integration.

## Checkpoint 2: CLI Arguments, File Output, And Error Strategy

**Goal:** Add the executable script flow, command-line parsing, file writing, and `--on-error fail|skip` behavior while keeping network behavior mockable in tests.

**Files:**

- Modify: `backend/scripts/crawl_novel_site.py`
- Modify: `backend/tests/test_crawl_novel_site.py`

**Network access:** none in automated tests. Tests use fake fetch functions.

**Functions to implement:**

```text
crawl_novel(start_url, limit, output_dir, title, delay, on_error, fetch_text, sleep) -> CrawlResult
main(argv: list[str] | None = None) -> int
```

Suggested result dataclass:

```python
@dataclass(frozen=True)
class CrawlResult:
    output_dir: Path
    markdown_path: Path
    manifest_path: Path
    fetched_count: int
    skipped: list[dict[str, str]]
```

- [x] **Step 1: Add failing tests for file output**

Add tests using a fake fetcher:

```python
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

    assert result.markdown_path.read_text(encoding="utf-8").startswith("# 第1章")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["title"] == "幽魂骑士王的地下城工程"
    assert manifest["chapter_count"] == 1
```

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
```

Expected: fail because `crawl_novel()` does not exist.

- [x] **Step 2: Implement `crawl_novel()` file output**

Behavior:

- fetch directory page;
- extract links;
- fetch up to `limit` chapters sequentially;
- call `sleep(delay)` between chapter requests when another chapter remains;
- write `novel.md` and `manifest.json` using UTF-8;
- include skipped chapters in manifest when `on_error="skip"`.

Run the same pytest command.

Expected: file output test passes.

- [x] **Step 3: Add failing tests for `--on-error fail`**

Add:

```python
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
```

Run the same pytest command.

Expected: fail until error behavior is implemented.

- [x] **Step 4: Implement `--on-error fail` behavior**

For `on_error="fail"`, propagate the chapter fetch or parse exception and avoid writing partial `novel.md` and `manifest.json`.

Run the same pytest command.

Expected: fail behavior test passes.

- [x] **Step 5: Add failing tests for `--on-error skip`**

Add:

```python
def test_crawl_novel_skip_records_failed_chapter(tmp_path):
    pages = {
        "https://www.92yanqing.com/read/92502/": DIRECTORY_HTML,
        "https://www.92yanqing.com/read/92502/44142930.html": CHAPTER_HTML.replace("第1章", "第2章").replace("隆多兰的魔王与穿越者的幽灵", "塔莉亚与萨麦尔"),
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

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.fetched_count == 1
    assert manifest["chapter_count"] == 1
    assert manifest["skipped"][0]["title"] == "第1章 【隆多兰的魔王与穿越者的幽灵】"
```

Run the same pytest command.

Expected: fail until skip behavior is implemented.

- [x] **Step 6: Implement `--on-error skip` behavior**

For `on_error="skip"`:

- catch chapter fetch or parse exceptions;
- append `{index, title, url, error}` to `skipped`;
- continue through attempted links until `limit` links have been attempted;
- write successful chapters and skipped metadata.

Run the same pytest command.

Expected: skip behavior test passes.

- [x] **Step 7: Add CLI argument parsing tests**

Add a test that monkeypatches `crawl_novel()` or calls `main()` with a fake fetcher injection if the script exposes a small internal `_main(args, fetch_text)` helper. Verify:

- `--start-url` is required;
- `--limit` defaults to `5`;
- `--on-error` rejects values outside `fail` and `skip`;
- explicit `--output-dir` is used.

Run the same pytest command.

Expected: fail until argument parsing is implemented.

- [x] **Step 8: Implement CLI `main()`**

Use `argparse` with:

```text
--start-url required
--limit default 5
--output-dir optional
--title optional
--delay default 1.5
--on-error choices fail, skip; default fail
```

Default `output_dir` should be `backend/data/crawled/<slug>`, where `<slug>` is a filesystem-safe slug derived from `--title` when present or from the directory path when title is absent.

Use a real HTTP fetch helper only from `main()`, so tests can keep `crawl_novel()` offline.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_crawl_novel_site.py -q
.\.venv\Scripts\python -m ruff check app tests alembic scripts
```

Expected: crawler tests pass and ruff passes.

**Verification method:** offline pytest, temporary file assertions, ruff.

**Explicitly not in this checkpoint:** live site access, import-book execution, database writes, FastAPI, frontend, Workspace integration.

## Checkpoint 3: Real Site Manual Verification

**Goal:** Run the approved first-5-chapter crawl once against the real site if access remains allowed, then verify that the generated Markdown is accepted by the existing import command.

**Files:**

- No code files required.
- Generated local output under `backend/data/crawled/<slug>/`.

**Network access:** yes, manual only. Do not add live network pytest.

- [x] **Step 1: Recheck robots/access before crawling**

Run:

```powershell
Invoke-WebRequest https://www.92yanqing.com/robots.txt -UseBasicParsing
```

Expected: response is accessible and does not disallow the target path.

If robots.txt disallows crawling, the site blocks access, or login is required, stop this checkpoint and report the blocker.

- [x] **Step 2: Run the crawler for the first 5 chapters**

Run:

```powershell
cd backend
.\.venv\Scripts\python .\scripts\crawl_novel_site.py `
  --start-url "https://www.92yanqing.com/read/92502/" `
  --limit 5 `
  --title "幽魂骑士王的地下城工程" `
  --output-dir ".\data\crawled\youhun-qishi-wang" `
  --delay 1.5 `
  --on-error fail
```

Expected:

```text
novel.md written
manifest.json written
fetched_count=5
```

- [x] **Step 3: Inspect generated files**

Run:

```powershell
Get-Content -Path ".\data\crawled\youhun-qishi-wang\manifest.json" -Raw | ConvertFrom-Json
Get-Content -Path ".\data\crawled\youhun-qishi-wang\novel.md" -TotalCount 40
```

Expected:

- manifest parses as JSON;
- `chapter_count` is `5`;
- `novel.md` begins with `# 第1章 【隆多兰的魔王与穿越者的幽灵】`;
- paragraphs are readable Chinese text;
- no obvious navigation-only lines dominate the output.

- [ ] **Step 4: Verify import-book can recognize the Markdown**

Checkpoint 3 run note: crawl files were generated and validated, but runtime PostgreSQL on `localhost:5432` was unavailable, so `import-book` verification is deferred until the runtime database is running.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main import-book --path ".\data\crawled\youhun-qishi-wang\novel.md" --title "幽魂骑士王的地下城工程"
```

Expected:

- command completes successfully against the configured local database;
- output includes a `novel_id`;
- imported chapter count is `5`.

If no runtime PostgreSQL database is available, document that the crawl files were created and defer import verification until the runtime DB is running.

**Verification method:** manual command output and generated file inspection.

**Explicitly not in this checkpoint:** writing live network tests, all-book crawl, bypassing access restrictions, extraction, fake or real LLM use, Workspace code changes.

## Checkpoint 4: Operator Documentation

**Goal:** Add an operator document that explains the real-data manual validation flow from crawler output to Novel Workspace inspection.

**Files:**

- Create: `docs/operator/real-data-manual-validation.md`

**Network access:** none.

- [x] **Step 1: Write the operator document**

Create the document with these sections:

```markdown
# Real Data Manual Validation

## Scope

This operator flow fetches a small number of chapters from the approved 92yanqing directory page into local files, then reuses the existing backend CLI and Novel Workspace to validate that real text enters the MVP pipeline.

## Crawl First 5 Chapters

```powershell
cd backend
.\.venv\Scripts\python .\scripts\crawl_novel_site.py `
  --start-url "https://www.92yanqing.com/read/92502/" `
  --limit 5 `
  --title "幽魂骑士王的地下城工程" `
  --output-dir ".\data\crawled\youhun-qishi-wang" `
  --delay 1.5 `
  --on-error fail
```

## Import Markdown

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main import-book --path ".\data\crawled\youhun-qishi-wang\novel.md" --title "幽魂骑士王的地下城工程"
```

## Chunk Chapters

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main chunk-book --novel-id <novel_id>
```

## Embed Chunks

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main embed-book --novel-id <novel_id>
```

## Start Backend

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

## Start Frontend

```powershell
cd frontend
npm run dev
```

## Inspect Workspace

Open http://127.0.0.1:5173 and enter novel_id.

## Current Limitations

Fake LLM extraction remains fake. This flow validates real text ingestion, chunking, embedding status, and Workspace inspection only.
```

Use the exact PowerShell commands from the spec.

- [x] **Step 2: Include safety and boundary notes**

Document:

- stop if robots.txt or access rules change;
- do not crawl at scale;
- do not bypass login or blocking;
- crawler does not write to database;
- import/chunk/embed remain existing CLI commands;
- Workspace starts from `novel_id`.

- [x] **Step 3: Verify document readability**

Run:

```powershell
Get-Content -Path "docs\operator\real-data-manual-validation.md" -Raw
```

Expected: document renders as normal UTF-8 text with readable Chinese title examples and valid PowerShell commands.

**Verification method:** direct document readback.

**Explicitly not in this checkpoint:** code changes, live crawling, Workspace integration, upload/import API, task queue.

## Checkpoint 5: Final Verification And Boundary Self-Review

**Goal:** Run the final automated checks and verify the crawler remains an operator-only tool.

**Files:**

- No new files unless Checkpoints 1-4 reveal a documentation mismatch that must be corrected.

**Network access:** none for automated verification.

- [x] **Step 1: Run backend tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

Expected:

```text
all tests passed
```

- [x] **Step 2: Run backend lint**

Run:

```powershell
cd backend
.\.venv\Scripts\python -m ruff check app tests alembic scripts
```

Expected:

```text
All checks passed
```

- [x] **Step 3: Check for forbidden integration creep**

Inspect changed files and confirm:

- no FastAPI route was added for crawling;
- no frontend file was modified for crawling;
- no service or repository imports the crawler;
- crawler does not import database sessions, SQLAlchemy models, FastAPI routes, `ImportService`, `ChunkingService`, `EmbeddingService`, `ExtractionService`, `StateService`, or `PromptGenerationService`;
- no task queue, progress, cancellation, retry, or concurrency was added.

Use:

```powershell
rg -n "crawl_novel_site|crawl|crawler" backend\app frontend docs\operator backend\scripts backend\tests
```

Expected:

- crawler references appear only in `backend/scripts/`, `backend/tests/`, and `docs/operator/`;
- no product route or frontend integration appears.

- [x] **Step 4: Check plan/spec scope remained intact**

Verify no work introduced:

- generic crawler platform;
- login or anti-scraping bypass;
- concurrent crawling;
- full-book large-scale crawling;
- direct database writes;
- Workspace integration;
- upload;
- Celery or task queue;
- FastGPT;
- real LLM extraction;
- image generation.

**Verification method:** test output, lint output, and manual boundary inspection.

**Explicitly not in this checkpoint:** new features beyond verification and documentation corrections.

## Overall Testing Strategy

Automated tests:

- use inline directory and chapter HTML fixtures;
- test parsing and cleanup without live network;
- test output files with `tmp_path`;
- test error strategy with fake fetch functions;
- never depend on `92yanqing.com` being reachable.

Manual verification:

- recheck robots/access first;
- run the crawler once with `--limit 5`;
- inspect generated files;
- run `import-book` if a local runtime PostgreSQL database is available.

## Plan Self-Review

### Spec Coverage

This plan covers the approved operator crawler spec: site-specific parsing for `92yanqing.com/read/92502/`, `h1` titles, `div#booktxt` body parsing, first-5 default limit, Markdown and manifest output, delay and User-Agent, `--on-error fail|skip`, operator documentation, and existing CLI-based ingestion.

### Placeholder Scan

The plan contains no unfinished placeholder markers or open-ended implementation placeholders.

### Checkpoint Independence

Each checkpoint can be reviewed independently:

- Checkpoint 1 proves parsing and builders offline.
- Checkpoint 2 proves CLI output and error policy offline.
- Checkpoint 3 proves real-site manual validation without adding live tests.
- Checkpoint 4 adds operator documentation.
- Checkpoint 5 verifies tests, lint, and boundary guardrails.

### Network Boundary Check

No automated test uses live network. Real network access appears only in Checkpoint 3 and must stop if robots/access rules change or access is blocked.

### Product Boundary Check

The crawler remains outside FastAPI, frontend, database, services, Workspace, FastGPT, LLM extraction, image generation, and task orchestration.
