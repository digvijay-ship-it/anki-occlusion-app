import assert from "node:assert/strict";
import test from "node:test";

import {
  createMemoryLocalFirstStore,
  flushQueuedChanges,
  localFirstCostPolicy,
  normalizeSyncChange,
} from "./localFirstStore.js";

test("local-first policy keeps heavy work and large files on the browser", () => {
  assert.deepEqual(localFirstCostPolicy(), {
    heavyWork: "browser",
    largeFiles: "local-only",
    serverData: "metadata-only",
    sync: "batched",
    cache: "IndexedDB",
  });
});

test("normalizeSyncChange accepts metadata and rejects large file collections", () => {
  assert.deepEqual(normalizeSyncChange({
    collection: "cards",
    item_id: "card-1",
    payload: { title: "Integrals" },
  }), {
    collection: "cards",
    item_id: "card-1",
    payload: { title: "Integrals" },
    deleted: false,
  });

  assert.throws(
    () =>
      normalizeSyncChange({
        collection: "files",
        item_id: "pdf-1",
        payload: { name: "huge.pdf" },
      }),
    /Large files stay local/,
  );
});

test("memory local store queues and flushes batched metadata changes", async () => {
  const store = createMemoryLocalFirstStore();
  await store.queueChange({
    collection: "cards",
    item_id: "card-1",
    payload: { title: "Integrals" },
  });
  await store.queueChange({
    collection: "masks",
    item_id: "mask-1",
    payload: { card_id: "card-1" },
  });

  const pushed = [];
  const result = await flushQueuedChanges(store, {
    baseRevision: 7,
    pull: async (revision) => {
      return { revision, changes: [] };
    },
    push: async (changes, revision) => {
      pushed.push({ changes, revision });
      return { accepted: changes.length, revision: 9, conflicts: [] };
    },
  });

  assert.equal(result.sent, 2);
  assert.equal(result.accepted, 2);
  assert.equal(result.revision, 9);
  assert.equal(pushed[0].revision, 7);
  assert.deepEqual(pushed[0].changes.map((change) => change.collection), [
    "cards",
    "masks",
  ]);
  assert.deepEqual(await store.pendingChanges(), []);
});

test("queue compaction folds multiple updates and discards temporary offline creations deleted offline", async () => {
  const store = createMemoryLocalFirstStore();
  
  // 1. Temporary creation and deletion offline -> should be discarded entirely
  await store.queueChange({
    collection: "cards",
    item_id: "local-card-1",
    payload: { title: "Draft Card" },
  });
  await store.queueChange({
    collection: "cards",
    item_id: "local-card-1",
    payload: {},
    deleted: true,
  });

  // 2. Multiple updates to an existing item -> should fold to the latest update
  await store.queueChange({
    collection: "decks",
    item_id: "deck-1",
    payload: { name: "First Update", updated_at: "2026-06-10T12:00:00Z" },
  });
  await store.queueChange({
    collection: "decks",
    item_id: "deck-1",
    payload: { name: "Second Update", updated_at: "2026-06-10T13:00:00Z" },
  });

  const pushed = [];
  const result = await flushQueuedChanges(store, {
    baseRevision: 1,
    pull: async (revision) => ({ revision, changes: [] }),
    push: async (changes, revision) => {
      pushed.push({ changes, revision });
      return { accepted: changes.length, revision: 2, conflicts: [] };
    },
  });

  // The draft card should be cleared from queue, and only the latest deck update sent
  assert.equal(result.sent, 1);
  assert.equal(pushed[0].changes[0].collection, "decks");
  assert.equal(pushed[0].changes[0].payload.name, "Second Update");
  assert.deepEqual(await store.pendingChanges(), []);
});

test("conflict resolution applies LWW and progress wins correctly", async () => {
  const store = createMemoryLocalFirstStore();
  
  // Setup: place initial item in local store and queue a local update
  const localCard = { id: "card-1", title: "Local Title", updated_at: "2026-06-10T14:00:00Z" };
  await store.put("cards", localCard);
  await store.queueChange({
    collection: "cards",
    item_id: "card-1",
    payload: localCard,
  });

  // Case 1: LWW conflict where remote is newer (Remote Wins)
  const remoteCardNewer = { id: "card-1", title: "Remote Title Newer", updated_at: "2026-06-10T15:00:00Z" };
  
  // Case 2: review_state progress conflict where local is further progressed (Local Wins)
  const localReviewState = { id: "state-1", sm2_repetitions: 5, reviews: 5 };
  await store.put("review_state", localReviewState);
  await store.queueChange({
    collection: "review_state",
    item_id: "state-1",
    payload: localReviewState,
  });
  
  const remoteReviewStateOlder = { id: "state-1", sm2_repetitions: 3, reviews: 3 };

  const pushed = [];
  const result = await flushQueuedChanges(store, {
    baseRevision: 10,
    pull: async (revision) => ({
      revision: 11,
      changes: [
        { collection: "cards", item_id: "card-1", payload: remoteCardNewer, deleted: false },
        { collection: "review_state", item_id: "state-1", payload: remoteReviewStateOlder, deleted: false },
      ],
    }),
    push: async (changes, revision) => {
      pushed.push({ changes, revision });
      return { accepted: changes.length, revision: 12, conflicts: [] };
    },
  });

  // Verify:
  // - card-1 LWW conflict: remote wins, so local card is updated to remote Title, and local queue for card-1 is discarded
  // - state-1 conflict: local wins, so local review state remains, and is pushed to server
  const finalCard = await store.get("cards", "card-1");
  assert.equal(finalCard.title, "Remote Title Newer");
  
  assert.equal(result.sent, 1);
  assert.equal(pushed[0].changes[0].collection, "review_state");
  assert.equal(pushed[0].changes[0].item_id, "state-1");
});
