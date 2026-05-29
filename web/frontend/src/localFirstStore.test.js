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
