# novel2Image

novel2Image is a Phase 1 MVP for turning long-form novel text into a character-state knowledge base and evidence-backed image prompts.

The current system supports local novel import, chapter and chunk processing, PostgreSQL + pgvector retrieval, character state and event review, evidence-chain prompt generation, a thin FastAPI backend, and a Vite React workspace UI.

## Tech Stack

- Backend: FastAPI
- Database: PostgreSQL + pgvector
- Frontend: React + Vite
- Offline tools: CLI commands and operator scripts

## Current Scope

Included:

- TXT / Markdown import through local CLI flows
- chapter and chunk storage
- fake embedding provider for MVP validation
- character, alias, event, and state review workflows
- evidence-backed prompt generation
- thin Novel Workspace UI
- operator crawler scripts for local validation artifacts

Not included in the current implementation:

- Qdrant
- Neo4j
- FastGPT integration
- real LLM extraction
- image generation API
- crawler integration in the product UI

## Local Startup

See `启动服务说明.txt` for local startup notes.
