# Anki Occlusion Web

The web port is now a working review-console prototype over the existing
desktop app data file. It is intentionally thin: the backend reuses the current
Python scheduler/data logic, and the frontend focuses on fast review workflows
instead of duplicating the full PyQt editor.

## Current Status

- FastAPI backend reads and writes the existing `anki_occlusion_data.json`.
- Dashboard summary shows deck, card, occlusion, due, learning, and review counts.
- Recursive deck tree supports selecting a deck and loading its due review queue.
- Review console shows the active due item and posts SM-2 ratings back to Python.
- Frontend has lightweight API tests with Node's built-in test runner.

Not built yet:

- Browser-based occlusion editor.
- PDF/image canvas rendering in the browser.
- Authentication or remote sync.
- SQLite/web migration. The web backend still uses the desktop JSON store.

## Stack Decision

This repo should stay on this stack for the next phase:

- Backend: `FastAPI` + `Pydantic` because it lets the web API reuse the existing
  Python scheduler, storage, and PDF code safely.
- Frontend: `Vite` + `React` because it is fast to iterate and a good fit for a
  dense review dashboard.
- Tests: Python `unittest` for backend/store behavior, Node `node:test` for
  frontend API helpers.

Future upgrades that make sense after the review UI stabilizes:

- TypeScript for the frontend API contracts.
- SQLite or SQLModel-backed persistence when web editing/sync becomes serious.
- Browser PDF rendering with PDF.js when the web editor begins.

## Run Backend

Install backend dependencies if needed:

```powershell
python -m pip install -r requirements.txt
```

Start the API:

```powershell
cd web\backend
python -m uvicorn run:app --reload --host 127.0.0.1 --port 8000
```

Use a separate data file for testing:

```powershell
$env:ANKI_OCCLUSION_WEB_DATA="C:\path\to\anki_occlusion_data.json"
python -m uvicorn run:app --reload --host 127.0.0.1 --port 8000
```

## Run Frontend

```powershell
cd web\frontend
npm install
npm run dev
```

The frontend defaults to:

```text
http://127.0.0.1:5173
```

The API defaults to:

```text
http://127.0.0.1:8000
```

Override the API base:

```powershell
$env:VITE_API_BASE="http://127.0.0.1:8000"
npm run dev
```

## Tests And Build

From the repo root:

```powershell
python -m unittest tests.test_web_api
```

From `web\frontend`:

```powershell
npm test
npm run build
```

## API Surface

```text
GET  /api/health
GET  /api/summary
GET  /api/decks
GET  /api/review/items
GET  /api/review/items?deck_id=<id>
POST /api/review/rate
```

Rating payload:

```json
{
  "deck_id": 1,
  "card_id": "card-1",
  "box_id": "box-1",
  "box_index": 0,
  "quality": 4
}
```
