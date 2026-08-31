# Web MVP Architecture

## Goal

The web MVP is a paid browser app for Anki Occlusion. The desktop app remains
the mature local product, while the browser version becomes the commercial path
for subscriptions, account-gated usage, and public deployment.

The first web version should be cheap to run. User devices should do the heavy
PDF and canvas work. The server should store only the metadata needed for login,
subscription checks, review sync, and cost monitoring.

## MVP Shape

- Browser app: Vite + React static frontend.
- Local testing: React dev server plus FastAPI on `127.0.0.1`.
- Production: static frontend CDN plus a small FastAPI API server.
- Database: SQLite first; Postgres only after real usage requires it.
- Billing gate: Stripe subscription plus server-side entitlement checks.
- Anti-piracy stance: protect the paid service with login, entitlement, sync,
  quotas, and account value. Do not assume frontend code can remain secret.

## Client Responsibilities

The browser should handle expensive work:

- Render PDFs with PDF.js.
- Draw masks and annotations on canvas.
- Keep source PDFs and large images local for the first MVP.
- Store working deck/card/mask/review state in IndexedDB.
- Batch local changes before syncing.
- Cache page previews and local review state.

Large files should not be uploaded by default. Cloud PDF storage can become a
paid upgrade later if cross-device document sync proves valuable.

## Server Responsibilities

The server should stay small:

- Authenticate the user.
- Confirm active subscription entitlement.
- Store metadata for decks, cards, masks, schedule state, and sync revisions.
- Accept batched sync pushes and serve revision-based pulls.
- Record lightweight cost/performance metrics.

Avoid per-click writes where possible. Review sessions should update local state
immediately, then sync as a batch.

## API Direction

Prototype routes may continue to exist while the current review console is
useful:

```text
GET  /api/health
GET  /api/summary
GET  /api/decks
GET  /api/review/items
POST /api/review/rate
```

Commercial web routes should become the stable path:

```text
GET  /api/me              Account, plan, and entitlement status
GET  /api/sync/pull       Revision-based metadata sync
POST /api/sync/push       Batched local changes
POST /api/metrics/client  Lightweight client telemetry
GET  /api/metrics/cost    Local/dev cost snapshot
```

`POST /api/review/rate` can remain as a server-validated path if needed, but the
cost-efficient default is batched review-state sync.

## Cost Monitoring

Track these before public deployment:

- API calls per user per day.
- Request and response bytes.
- Estimated database reads and writes.
- Sync batch size and frequency.
- Stored bytes per account.
- Slow routes and failed sync attempts.

Use this data to tune batching, debounce intervals, payload shape, and storage
limits before charging real users.

## Launch Defaults

- Subscription model first.
- Metadata sync first.
- PDFs/images local by default.
- SQLite for the first deployment.
- Browser-side PDF rendering only for normal review/edit flows.
- No server-side TensorFlow OCR in the MVP.
