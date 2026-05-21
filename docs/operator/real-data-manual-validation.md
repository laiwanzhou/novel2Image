# Real Data Manual Validation

This operator flow is only for manual validation with a small amount of real novel text. It is not a product feature, not a crawler platform, and not part of Novel Workspace.

The current approved target is:

```text
https://www.92yanqing.com/read/92502/
```

The current approved range is the first 5 chapters of:

```text
幽魂骑士王的地下城工程
```

## Scope

This flow validates:

- real text can be crawled into local `novel.md` and `manifest.json`;
- `novel.md` can enter the existing backend CLI import path;
- imported chapters can be chunked;
- chunks can receive fake embeddings;
- Novel Workspace can inspect chapter, chunk, and embedding status by `novel_id`.

This flow does not validate real LLM extraction. The current extraction provider is still fake. Character candidates, state changes, and prompt quality are outside this manual text-ingestion check.

## Safety Boundary

Before crawling, confirm access remains allowed. If robots.txt or site access rules change, stop crawling and use locally available text instead.

Do not:

- bypass login;
- bypass anti-scraping controls;
- run concurrent crawling;
- crawl the full book at scale;
- write crawler output directly to PostgreSQL;
- connect the crawler to FastAPI, Novel Workspace, upload, FastGPT, real LLM extraction, or image generation.

The crawler only writes local files. The existing CLI remains responsible for import, chunking, and embedding.

## Crawl First 5 Chapters

Run from `backend/`:

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

Expected output:

```text
novel.md written: data\crawled\youhun-qishi-wang\novel.md
manifest.json written: data\crawled\youhun-qishi-wang\manifest.json
fetched_count=5
```

The crawler writes `novel.md` and `manifest.json` as UTF-8 with BOM so default Windows PowerShell reads Chinese text correctly.

## Resume A Larger Crawl

For a larger operator validation run, use a separate output directory and enable resume:

```powershell
cd backend
.\.venv\Scripts\python .\scripts\crawl_novel_site.py `
  --start-url "https://www.92yanqing.com/read/92502/" `
  --limit 0 `
  --title "幽魂骑士王的地下城工程" `
  --output-dir ".\data\crawled\youhun-qishi-wang-full" `
  --delay 1.5 `
  --on-error fail `
  --resume
```

`--limit 0` means all chapter links parsed from the approved directory page. `--resume` writes each completed chapter to `partial_chapters/0001.md`, `partial_chapters/0002.md`, and so on, and records progress in `crawl_state.json`.

If the run stops because of a network error, tool timeout, or operator interruption, run the same command again with `--resume`. The crawler validates that `crawl_state.json` matches the current `source_url`, `title`, and `limit`; if they differ, it stops instead of mixing partial files from another run.

The top-level `novel.md` and `manifest.json` are only regenerated after all selected chapters are complete. Existing top-level output files are backed up before a resume/full run so a failed attempt does not leave old results looking fresh.

## Inspect Crawl Output

Parse the manifest:

```powershell
Get-Content -Path ".\data\crawled\youhun-qishi-wang\manifest.json" -Raw | ConvertFrom-Json
```

Check the first lines of the Markdown:

```powershell
Get-Content -Path ".\data\crawled\youhun-qishi-wang\novel.md" -TotalCount 40
```

Expected:

- `chapter_count` is `5`;
- each chapter records `page_urls`; the current approved validation target has 2 fetched page URLs per chapter;
- chapter titles are readable Chinese;
- `novel.md` starts with `# 第1章 【隆多兰的魔王与穿越者的幽灵】`;
- `novel.md` does not contain `本章未完，点击下一页继续阅读`;
- obvious navigation or site chrome lines do not dominate the output.

## Import Markdown

The runtime PostgreSQL database must be available before import. The default backend runtime database is:

```text
postgresql+psycopg://postgres:postgres@localhost:5432/novel_visualization
```

If `localhost:5432` is not reachable, `import-book` may fail or hang while waiting for the database connection. Start the runtime PostgreSQL database first, then run:

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main import-book --path ".\data\crawled\youhun-qishi-wang\novel.md" --title "幽魂骑士王的地下城工程"
```

Record the returned `novel_id`.

## Chunk Chapters

Run:

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main chunk-book --novel-id <novel_id>
```

This creates paragraph-preserving `chapter_chunks` for the imported chapters.

## Embed Chunks

Run:

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.main embed-book --novel-id <novel_id>
```

This uses the configured embedding provider. In the current MVP, the default provider is fake and produces deterministic local embeddings.

## Start Backend

Run:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

## Start Frontend

Run in a second terminal:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Inspect Novel Workspace

In Novel Workspace:

1. Enter the imported `novel_id`.
2. Load the workspace.
3. Confirm novel metadata appears.
4. Confirm the chapter list shows 5 chapters.
5. Select a chapter and inspect chunk previews.
6. Confirm `chunk_count` is greater than 0.
7. Confirm `embedded_count` matches the generated embeddings after `embed-book`.

This completes the real-data text ingestion validation. Further candidate extraction remains fake until a real LLM or FastGPT provider is designed and implemented in a separate stage.

## Current Manual Verification Note

The first live validation generated:

```text
backend\data\crawled\youhun-qishi-wang\novel.md
backend\data\crawled\youhun-qishi-wang\manifest.json
```

The generated manifest parsed successfully and reported `chapter_count = 5`. The generated Markdown was readable Chinese after switching output to UTF-8 with BOM.

`import-book` was attempted, but runtime PostgreSQL on `localhost:5432` was not reachable, so import verification was deferred until the runtime database is running.
