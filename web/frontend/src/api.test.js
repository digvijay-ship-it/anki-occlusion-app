import assert from "node:assert/strict";
import test from "node:test";

import {
  API_BASE,
  loadCostSnapshot,
  loadCurrentUser,
  loadDashboard,
  mediaUrl,
  pullSync,
  pushSync,
  rateReviewItem,
  redoReviewRating,
  revealMediaPath,
  sendClientMetric,
  undoReviewRating,
} from "./api.js";

test("loadDashboard fetches summary, deck tree, and selected review items", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const path = String(url).replace(API_BASE, "");
    const body =
      path === "/api/summary"
        ? { card_count: 2 }
        : path === "/api/decks"
          ? [{ id: 7, name: "History" }]
          : [{ deck_id: 7, card_id: "card-1" }];
    return Response.json(body);
  };
  try {
    const result = await loadDashboard(7);

    assert.deepEqual(calls, [
      `${API_BASE}/api/summary`,
      `${API_BASE}/api/decks`,
      `${API_BASE}/api/review/items?limit=100&deck_id=7`,
    ]);
    assert.equal(result.summary.card_count, 2);
    assert.equal(result.decks[0].name, "History");
    assert.equal(result.reviewItems[0].card_id, "card-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rateReviewItem posts the SM-2 grade target", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody = null;
  globalThis.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return Response.json({ updated: true, target: { sched_state: "learning" } });
  };
  try {
    const result = await rateReviewItem(
      {
        deck_id: 7,
        card_id: "card-1",
        box_id: "box-2",
        box_index: 1,
      },
      4,
    );

    assert.deepEqual(requestBody, {
      card_id: "card-1",
      deck_id: 7,
      box_id: "box-2",
      box_index: 1,
      group_id: null,
      quality: 4,
    });
    assert.equal(result.updated, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("review parity helpers call undo, redo, and folder reveal routes", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({
      path: String(url).replace(API_BASE, ""),
      method: options.method || "GET",
      body: options.body ? JSON.parse(options.body) : null,
    });
    return Response.json({ updated: true, opened: true });
  };
  try {
    await undoReviewRating();
    await redoReviewRating();
    await revealMediaPath("C:\\notes\\math.pdf");

    assert.deepEqual(calls, [
      { path: "/api/review/undo", method: "POST", body: null },
      { path: "/api/review/redo", method: "POST", body: null },
      {
        path: "/api/media/reveal",
        method: "POST",
        body: { path: "C:\\notes\\math.pdf" },
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("mediaUrl points at the API media route", () => {
  assert.equal(
    mediaUrl("C:\\notes\\math.pdf"),
    `${API_BASE}/api/media?path=C%3A%5Cnotes%5Cmath.pdf`,
  );
});

test("commercial API helpers call entitlement, sync, and metrics routes", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({
      path: String(url).replace(API_BASE, ""),
      method: options.method || "GET",
      body: options.body ? JSON.parse(options.body) : null,
    });
    return Response.json({ ok: true, accepted: 1, revision: 3 });
  };
  try {
    await loadCurrentUser();
    await pullSync(2);
    await pushSync([{ collection: "cards", item_id: "card-1", payload: {} }], 2);
    await sendClientMetric("sync.flush", { count: 1 });
    await loadCostSnapshot();

    assert.deepEqual(calls, [
      { path: "/api/me", method: "GET", body: null },
      { path: "/api/sync/pull?since_revision=2", method: "GET", body: null },
      {
        path: "/api/sync/push",
        method: "POST",
        body: {
          base_revision: 2,
          changes: [{ collection: "cards", item_id: "card-1", payload: {} }],
        },
      },
      {
        path: "/api/metrics/client",
        method: "POST",
        body: { event: "sync.flush", payload: { count: 1 } },
      },
      { path: "/api/metrics/cost", method: "GET", body: null },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
