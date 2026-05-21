# Novel Character Visualization Admin

Minimal React + Vite admin UI for the MVP backend.

This is intentionally a thin management surface. It does not implement upload, realtime task progress, auth, permissions, collaboration, or an image gallery.

## Pages

- `Workspace`: one-stop page that starts from a `novel_id`, loads chapter/chunk/status data, runs small synchronous processing actions, reviews candidates, inspects and confirms states, and generates/audits prompts.
- `Review`: load character/alias candidates by novel ID, accept/reject candidates, and confirm aliases against a character ID.
- `States`: load state versions by character ID and create an initial candidate CharacterState.
- `Prompts`: generate a single-character prompt, list prompt history by novel ID, and inspect saved evidence snapshots.

`Review`, `States`, and `Prompts` remain available as focused pages even though `Workspace` is the default day-to-day surface.

## Setup

```powershell
cd frontend
npm install
```

The API base URL defaults to:

```text
http://127.0.0.1:8000
```

Override it with:

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
```

## Run

Start the backend first:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Then start the frontend:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The backend currently allows CORS from `http://127.0.0.1:5173` and `http://localhost:5173`.

## Build

```powershell
cd frontend
npm run build
```

Expected result: TypeScript compilation and Vite production build succeed.

## Notes

The UI assumes data already exists in PostgreSQL. Use backend CLI/API flows to import novels, chunk chapters, create/confirm characters, and create confirmed CharacterState records before generating prompts.
