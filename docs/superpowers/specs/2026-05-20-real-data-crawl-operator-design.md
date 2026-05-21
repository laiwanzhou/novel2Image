# Real Data Crawl Operator Design

Date: 2026-05-20

## Goal

Add a small operator-only crawler script for manual real-data validation of the completed novel character visualization MVP.

This is an operator tool, not a product feature. It exists only to fetch a small amount of text from one confirmed site structure, write local files, and let the existing CLI flow import and process those files.

The validation loop is:

```text
crawl first chapters
-> write Markdown and manifest
-> import-book
-> chunk-book
-> embed-book
-> start backend and frontend
-> inspect Novel Workspace status by novel_id
```

The crawler does not write to PostgreSQL and does not integrate with Novel Workspace.

## Target Site And Scope

The script supports only the currently inspected site structure:

```text
directory page: https://www.92yanqing.com/read/92502/
chapter body:   div#booktxt
chapter title:  h1
```

The confirmed book is:

```text
幽魂骑士王的地下城工程
```

The default run fetches only the first 5 chapters. The script supports `--limit`, but operator documentation should recommend small-range validation first, such as 3-5 chapters.

The crawler is not a general parser for all sites, all novels, or all future layout variations of the same site.

## Compliance And Access Boundary

At design time, `https://www.92yanqing.com/robots.txt` returns:

```text
User-agent: *
Disallow:
```

This means robots.txt does not currently prohibit crawling. This does not remove copyright or terms-of-use risk. The script is intended for limited local manual validation only.

If the site rules change, robots.txt disallows access, pages become login-gated, requests are blocked, or the operator is unsure about permitted use, stop crawling and use locally available text instead.

The script must not bypass login, paywalls, anti-bot protections, rate limits, or access controls.

## Script Location

Create:

```text
backend/scripts/crawl_novel_site.py
```

The script should be runnable from the backend directory:

```powershell
cd backend
.\.venv\Scripts\python .\scripts\crawl_novel_site.py `
  --start-url "https://www.92yanqing.com/read/92502/" `
  --limit 5 `
  --title "幽魂骑士王的地下城工程"
```

## Output

Default output directory:

```text
backend/data/crawled/<slug>/
```

For this book, the slug can be derived from the title or passed by output path. The implementation should create the output directory if it does not exist.

Required output files:

```text
backend/data/crawled/<slug>/novel.md
backend/data/crawled/<slug>/manifest.json
```

### novel.md

Write one Markdown file containing the fetched chapters in importable form:

```markdown
# 第1章 【隆多兰的魔王与穿越者的幽灵】

正文段落……

# 第2章 【塔莉亚与萨麦尔】

正文段落……
```

Each chapter title should be a single level-1 heading. Chapter body should preserve paragraph structure and separate paragraphs with blank lines.

### manifest.json

Write a manifest for audit and operator visibility:

```json
{
  "source_site": "92yanqing.com",
  "source_url": "https://www.92yanqing.com/read/92502/",
  "title": "幽魂骑士王的地下城工程",
  "chapter_count": 5,
  "fetched_at": "2026-05-20T00:00:00Z",
  "chapters": [
    {
      "index": 1,
      "title": "第1章 【隆多兰的魔王与穿越者的幽灵】",
      "url": "https://www.92yanqing.com/read/92502/44142929.html",
      "page_urls": [
        "https://www.92yanqing.com/read/92502/44142929.html",
        "https://www.92yanqing.com/read/92502/44142929_2.html"
      ],
      "word_count": 1234
    },
    {
      "index": 2,
      "title": "第2章 【塔莉亚与萨麦尔】",
      "url": "https://www.92yanqing.com/read/92502/44142930.html",
      "page_urls": [
        "https://www.92yanqing.com/read/92502/44142930.html",
        "https://www.92yanqing.com/read/92502/44142930_2.html"
      ],
      "word_count": 1234
    }
  ]
}
```

`word_count` can be a Chinese-character-oriented character count consistent with the existing MVP's lightweight counting approach.

## Command-Line Interface

The script should support:

```text
--start-url   directory page URL
--limit       number of chapters to fetch; default 5
--output-dir  output directory; default backend/data/crawled/<slug>
--title       book title override
--delay       seconds between chapter requests; default 1.5
--on-error    fail or skip; default fail
```

`--on-error fail` stops on the first failed chapter and exits non-zero.

`--on-error skip` records skipped chapters in `manifest.json` and continues with later chapters until it has attempted the requested limit.

The script must send a User-Agent header that clearly identifies this as a local manual validation crawler.

The script must wait at least `--delay` seconds between chapter page requests.

## Crawling Strategy

1. Fetch the directory page with User-Agent.
2. Parse chapter links matching the confirmed book path:

```text
/read/92502/<chapter_id>.html
```

3. Remove duplicate links.
4. Keep real chapter entries in story order. The directory includes latest-chapter links near the top, so ordering must prefer the main catalog sequence beginning with chapter 1.
5. Select the first `--limit` chapters.
6. Fetch each chapter page sequentially.
7. Follow same-chapter pagination links such as `_2.html` and `_3.html` from `a#next_url` or `a[rel=next]`, but do not follow links that point to the next chapter, the directory page, JavaScript placeholders, or another chapter id.
8. Parse title from `h1`.
9. Normalize title by removing pagination suffixes such as `（1/2）` or `(1/2)`.
10. Parse body from `div#booktxt`.
11. Clean body text and merge all same-chapter page paragraphs in page order.
12. Write `novel.md` and `manifest.json`; each manifest chapter records its canonical first-page `url` and all fetched `page_urls`.

## Text Cleaning

Cleaning must preserve paragraph structure while removing site chrome and noisy lines.

Required cleanup:

- convert `<br>` boundaries and block boundaries into paragraph breaks;
- decode HTML entities;
- trim whitespace;
- drop empty paragraphs;
- remove repeated chapter title text from the top of the body when it duplicates `h1`;
- remove advertisement lines;
- remove navigation lines such as previous chapter, next chapter, return directory, or bookmark prompts;
- remove same-chapter continuation prompts such as `本章未完，点击下一页继续阅读`;
- remove pagination artifacts that are not story text.

The cleaner should be conservative. It should not rewrite story prose, normalize character names, or merge unrelated paragraphs.

## Relationship To Existing System

The crawler only produces files. The existing CLI remains responsible for ingestion:

```text
crawler -> novel.md + manifest.json
import-book -> PostgreSQL novels / chapters
chunk-book -> chapter_chunks
embed-book -> pgvector embeddings
Novel Workspace -> inspect status
```

The crawler does not call:

- `ImportService`;
- `ChunkingService`;
- `EmbeddingService`;
- FastAPI routes;
- database repositories;
- Novel Workspace APIs.

## Operator Documentation Plan

Create:

```text
docs/operator/real-data-manual-validation.md
```

The document must explain this manual validation path:

1. Run the crawler and produce `novel.md`.
2. Import:

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main import-book --path <novel.md> --title "<title>"
```

3. Chunk:

```powershell
.\.venv\Scripts\python -m app.cli.main chunk-book --novel-id <novel_id>
```

4. Embed:

```powershell
.\.venv\Scripts\python -m app.cli.main embed-book --novel-id <novel_id>
```

5. Start backend:

```powershell
.\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

6. Start frontend:

```powershell
cd frontend
npm run dev
```

7. Open:

```text
http://127.0.0.1:5173
```

8. In Novel Workspace, enter `novel_id` and inspect:

- novel metadata;
- chapter list;
- chunk counts;
- embedding counts;
- selected chapter chunk previews.

The document should remind operators that fake LLM extraction remains fake in the current system, and this stage is only for validating that real text can enter the MVP pipeline.

## Testing And Verification Scope

The implementation plan should include tests for pure parsing and cleaning helpers using saved HTML snippets or minimal inline fixtures. Tests should not depend on live network access.

Manual verification can use the real URL once after implementation, with `--limit 5`, if the site remains accessible and robots.txt remains permissive.

Expected verification commands after implementation:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

The implementation should also run the crawler manually for the approved first 5 chapters and confirm that `novel.md` and `manifest.json` are created.

## Non-Goals

This round does not include:

- generic crawler platform;
- crawling sites other than the confirmed target structure;
- login bypass;
- anti-scraping bypass;
- concurrent crawling;
- full-book large-scale crawling;
- direct database writes;
- Novel Workspace integration;
- browser upload;
- Celery, Redis, task queue, progress, cancellation, or retry;
- Qdrant or Neo4j;
- FastGPT integration;
- real LLM extraction;
- image generation;
- changes to prompt generation;
- changes to CharacterState or evidence lifecycle.

## Self-Review

### Placeholder Check

The spec contains no unfinished placeholder markers or open-ended implementation placeholders.

### Scope Check

The work is limited to an operator script, local files, and an operator document. It does not add product crawler features, direct database ingestion, Workspace integration, upload, task queues, FastGPT, real LLM extraction, image generation, Qdrant, or Neo4j.

### Site Boundary Check

The parser is scoped to the inspected `92yanqing.com/read/92502/` directory structure, `h1` titles, and `div#booktxt` chapter bodies. It is not a general crawler.

### Safety Check

The design requires User-Agent, delay, small default limit, robots/access caveat, no login bypass, no anti-bot bypass, and no concurrency.

### System Boundary Check

The existing CLI remains the ingestion path. The crawler writes `novel.md` and `manifest.json` only.
