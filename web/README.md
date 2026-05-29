# Anki Occlusion Web

The web app is moving from a local review-console prototype toward the paid
browser product. The commercial direction is documented in
[`docs/WEB_MVP_ARCHITECTURE.md`](../docs/WEB_MVP_ARCHITECTURE.md).

## Current Status

- Existing review prototype: FastAPI reads/writes the desktop
  `anki_occlusion_data.json` and React shows deck/review data.
- New commercial foundation: SQLite-backed dev user entitlement, revision sync,
  and request-cost metrics.
- Frontend remains Vite + React and is still focused on review workflow testing.

Not built yet:

- Browser PDF.js review canvas.
- Browser occlusion editor.
- Real production auth provider.
- Stripe checkout/customer portal.
- Cloud PDF storage.

## Low-Cost Stack

- Frontend: Vite + React, deployable as static files.
- Backend: FastAPI + Pydantic.
- Local database: SQLite.
- Public database default: SQLite first, then Postgres only when usage proves it
  is needed.
- Payments: Stripe subscription.
- Cost control: client-side PDF rendering, IndexedDB local state, batched sync,
  metadata-only server storage for the MVP.

## Run Backend

Fast local start:

```powershell
.\start_web_app.cmd
```

This starts the FastAPI backend, starts the Vite frontend, opens
`http://127.0.0.1:5173`, and writes logs/PID files under `web\.run\`.

To stop both servers:

```powershell
.\stop_web_app.cmd
```

Manual backend start:

Install backend dependencies if needed:

```powershell
cd web\backend
python -m pip install -r requirements.txt
```

Start the API:

```powershell
cd web\backend
python -m uvicorn run:app --reload --host 127.0.0.1 --port 8000
```

Optional local settings:

```powershell
$env:ANKI_OCCLUSION_WEB_DATA="C:\path\to\anki_occlusion_data.json"
$env:ANKI_OCCLUSION_WEB_DB="C:\path\to\anki_web.sqlite3"
$env:ANKI_OCCLUSION_WEB_USER="dev-user"
```

If `ANKI_OCCLUSION_WEB_DB` is not set, the backend uses:

```text
web/backend/.data/anki_web.sqlite3
```

## Run Frontend

Manual frontend start:

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

## API Surface

Prototype review routes:

```text
GET  /api/health
GET  /api/summary
GET  /api/decks
GET  /api/review/items?limit=<n>
GET  /api/review/items?deck_id=<id>&limit=<n>
POST /api/review/rate
```

Commercial foundation routes:

```text
GET  /api/me
GET  /api/sync/pull?since_revision=<n>
POST /api/sync/push
POST /api/metrics/client
GET  /api/metrics/cost
```

Sync push payload:

```json
{
  "base_revision": 0,
  "changes": [
    {
      "collection": "cards",
      "item_id": "card-1",
      "payload": { "title": "Integrals" },
      "deleted": false
    }
  ]
}
```

The server stores metadata changes. PDFs/images should stay local in the browser
for the first MVP.

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
