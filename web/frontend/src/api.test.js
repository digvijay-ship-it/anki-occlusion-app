import assert from "node:assert/strict";
import test from "node:test";

import { API_BASE, loadDashboard, rateReviewItem } from "./api.js";

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
      `${API_BASE}/api/review/items?deck_id=7`,
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
      quality: 4,
    });
    assert.equal(result.updated, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
