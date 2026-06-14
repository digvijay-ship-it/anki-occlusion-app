import { pushSync, pullSync } from "./api.js";

const DB_NAME = "anki-occlusion-local";
const DB_VERSION = 3;

const LOCAL_STORE_NAMES = [
  "decks",
  "cards",
  "masks",
  "review_state",
  "sync_queue",
  "files",
  "metadata",
];

const SYNCABLE_COLLECTIONS = new Set(["decks", "cards", "masks", "review_state"]);

function makeLocalId() {
  const random =
    globalThis.crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `local-${random}`;
}

function recordKey(record) {
  return record.local_id || record.id || record.item_id;
}

export function normalizeSyncChange(change) {
  const collection = String(change.collection || "");
  const itemId = String(change.item_id || change.id || "");
  const payload = change.payload || {};

  if (!SYNCABLE_COLLECTIONS.has(collection)) {
    throw new Error("Large files stay local; only metadata collections can sync.");
  }
  if (!itemId) {
    throw new Error("item_id is required for sync changes.");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("payload must be an object.");
  }

  return {
    collection,
    item_id: itemId,
    payload,
    deleted: Boolean(change.deleted),
  };
}

export function localFirstCostPolicy() {
  return {
    heavyWork: "browser",
    largeFiles: "local-only",
    serverData: "metadata-only",
    sync: "batched",
    cache: "IndexedDB",
  };
}

export function createMemoryLocalFirstStore(initial = {}) {
  const stores = new Map(
    LOCAL_STORE_NAMES.map((name) => [
      name,
      new Map((initial[name] || []).map((record) => [recordKey(record), record])),
    ]),
  );

  function requireStore(storeName) {
    const store = stores.get(storeName);
    if (!store) {
      throw new Error(`Unknown local store: ${storeName}`);
    }
    return store;
  }

  return {
    async put(storeName, record) {
      const key = recordKey(record);
      if (!key) {
        throw new Error("Local records need id, item_id, or local_id.");
      }
      requireStore(storeName).set(key, { ...record });
      return { ...record };
    },

    async get(storeName, key) {
      const record = requireStore(storeName).get(key);
      return record ? { ...record } : null;
    },

    async list(storeName) {
      return Array.from(requireStore(storeName).values()).map((record) => ({
        ...record,
      }));
    },

    async delete(storeName, key) {
      requireStore(storeName).delete(key);
    },

    async queueChange(change) {
      const normalized = normalizeSyncChange(change);
      if (!normalized.payload.updated_at) {
        normalized.payload.updated_at = new Date().toISOString();
      }
      try {
        const currentItem = await this.get(normalized.collection, normalized.item_id);
        if (currentItem && !currentItem.updated_at) {
          currentItem.updated_at = normalized.payload.updated_at;
          await this.put(normalized.collection, currentItem);
        }
      } catch (err) {
        // ignore
      }
      const queued = {
        ...normalized,
        local_id: makeLocalId(),
        queued_at: new Date().toISOString(),
      };
      await this.put("sync_queue", queued);
      return queued;
    },

    async pendingChanges() {
      const queued = await this.list("sync_queue");
      return queued.sort((left, right) => left.queued_at.localeCompare(right.queued_at));
    },

    async clearQueuedChanges(localIds) {
      await Promise.all(localIds.map((id) => this.delete("sync_queue", id)));
    },
  };
}

export function openIndexedDbLocalFirstStore(indexedDBImpl = globalThis.indexedDB) {
  if (!indexedDBImpl) {
    throw new Error("IndexedDB is not available in this browser.");
  }

  return new Promise((resolve, reject) => {
    const request = indexedDBImpl.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error);
    request.onupgradeneeded = () => {
      const db = request.result;
      for (const name of LOCAL_STORE_NAMES) {
        if (!db.objectStoreNames.contains(name)) {
          db.createObjectStore(name, {
            keyPath: name === "sync_queue" ? "local_id" : "id",
          });
        }
      }
    };
    request.onsuccess = () => resolve(createIndexedDbAdapter(request.result));
  });
}

function createIndexedDbAdapter(db) {
  function transaction(storeName, mode = "readonly") {
    return db.transaction(storeName, mode).objectStore(storeName);
  }

  return {
    put(storeName, record) {
      const payload =
        storeName === "sync_queue"
          ? record
          : { id: record.id || record.item_id, ...record };
      return requestToPromise(transaction(storeName, "readwrite").put(payload)).then(
        () => payload,
      );
    },

    get(storeName, key) {
      return requestToPromise(transaction(storeName).get(key)).then(
        (record) => record || null,
      );
    },

    list(storeName) {
      return requestToPromise(transaction(storeName).getAll());
    },

    delete(storeName, key) {
      return requestToPromise(transaction(storeName, "readwrite").delete(key));
    },

    async queueChange(change) {
      const normalized = normalizeSyncChange(change);
      if (!normalized.payload.updated_at) {
        normalized.payload.updated_at = new Date().toISOString();
      }
      try {
        const currentItem = await this.get(normalized.collection, normalized.item_id);
        if (currentItem && !currentItem.updated_at) {
          currentItem.updated_at = normalized.payload.updated_at;
          await this.put(normalized.collection, currentItem);
        }
      } catch (err) {
        // ignore
      }
      const queued = {
        ...normalized,
        local_id: makeLocalId(),
        queued_at: new Date().toISOString(),
      };
      await this.put("sync_queue", queued);
      return queued;
    },

    async pendingChanges() {
      const queued = await this.list("sync_queue");
      return queued.sort((left, right) => left.queued_at.localeCompare(right.queued_at));
    },

    async clearQueuedChanges(localIds) {
      await Promise.all(localIds.map((id) => this.delete("sync_queue", id)));
    },
  };
}

function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

export async function getLastSyncedRevision(localStore) {
  try {
    const record = await localStore.get("metadata", "last_synced_revision");
    return record ? Number(record.value) : 0;
  } catch (err) {
    console.error("Failed to get last_synced_revision:", err);
    return 0;
  }
}

export async function setLastSyncedRevision(localStore, revision) {
  try {
    await localStore.put("metadata", { id: "last_synced_revision", value: Number(revision) });
  } catch (err) {
    console.error("Failed to set last_synced_revision:", err);
  }
}

export function resolveConflict(localChange, remoteChange) {
  if (remoteChange.deleted) {
    return "remote";
  }
  if (localChange.deleted) {
    return "local";
  }

  const collection = remoteChange.collection;
  if (collection === "review_state") {
    const localRep = localChange.payload?.sm2_repetitions || 0;
    const remoteRep = remoteChange.payload?.sm2_repetitions || 0;
    const localReviews = localChange.payload?.reviews || 0;
    const remoteReviews = remoteChange.payload?.reviews || 0;

    if (localRep > remoteRep) {
      return "local";
    } else if (remoteRep > localRep) {
      return "remote";
    } else {
      return localReviews >= remoteReviews ? "local" : "remote";
    }
  } else {
    const localTime = localChange.payload?.updated_at ? new Date(localChange.payload.updated_at).getTime() : 0;
    const remoteTime = remoteChange.payload?.updated_at ? new Date(remoteChange.payload.updated_at).getTime() : 0;

    if (localTime > remoteTime) {
      return "local";
    } else if (remoteTime > localTime) {
      return "remote";
    } else {
      return "remote";
    }
  }
}

export async function flushQueuedChanges(
  localStore,
  { baseRevision = null, pull = pullSync, push = pushSync } = {},
) {
  // 1. Pull Phase
  let resolvedBaseRevision = baseRevision;
  if (resolvedBaseRevision === null || resolvedBaseRevision === undefined) {
    resolvedBaseRevision = await getLastSyncedRevision(localStore);
  }

  const pullResult = await pull(resolvedBaseRevision);
  const serverRevision = Number(pullResult?.revision ?? resolvedBaseRevision);
  const remoteChanges = pullResult?.changes || [];

  let pending = await localStore.pendingChanges();
  for (const remoteChange of remoteChanges) {
    const conflictIndex = pending.findIndex(
      (p) => p.collection === remoteChange.collection && p.item_id === remoteChange.item_id,
    );

    if (conflictIndex === -1) {
      if (remoteChange.deleted) {
        await localStore.delete(remoteChange.collection, remoteChange.item_id);
      } else {
        await localStore.put(remoteChange.collection, remoteChange.payload);
      }
    } else {
      const localChange = pending[conflictIndex];
      const winner = resolveConflict(localChange, remoteChange);

      if (winner === "remote") {
        if (remoteChange.deleted) {
          await localStore.delete(remoteChange.collection, remoteChange.item_id);
        } else {
          await localStore.put(remoteChange.collection, remoteChange.payload);
        }
        await localStore.clearQueuedChanges([localChange.local_id]);
        pending.splice(conflictIndex, 1);
      }
    }
  }

  await setLastSyncedRevision(localStore, serverRevision);

  // 2. Push Phase
  const freshPending = await localStore.pendingChanges();
  if (!freshPending.length) {
    return { accepted: 0, revision: serverRevision, conflicts: [], sent: 0 };
  }

  const groups = {};
  for (const change of freshPending) {
    const key = `${change.collection}|${change.item_id}`;
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(change);
  }

  const folded = [];
  for (const key in groups) {
    const group = groups[key];
    group.sort((a, b) => a.queued_at.localeCompare(b.queued_at));
    const lastChange = group[group.length - 1];

    if (lastChange.deleted) {
      if (lastChange.item_id.startsWith("local-")) {
        const idsToDelete = group.map((c) => c.local_id);
        await localStore.clearQueuedChanges(idsToDelete);
        try {
          await localStore.delete(lastChange.collection, lastChange.item_id);
        } catch (err) {
          // ignore
        }
      } else {
        folded.push({
          change: normalizeSyncChange(lastChange),
          sourceIds: group.map((c) => c.local_id),
        });
      }
    } else {
      folded.push({
        change: normalizeSyncChange(lastChange),
        sourceIds: group.map((c) => c.local_id),
      });
    }
  }

  if (!folded.length) {
    return { accepted: 0, revision: serverRevision, conflicts: [], sent: 0 };
  }

  const changesToPush = folded.map((f) => f.change);
  const result = await push(changesToPush, serverRevision);
  const accepted = Number(result?.accepted ?? 0);

  if (accepted > 0) {
    const sourceIdsToClear = [];
    for (let i = 0; i < accepted; i++) {
      sourceIdsToClear.push(...folded[i].sourceIds);
    }
    await localStore.clearQueuedChanges(sourceIdsToClear);

    const finalRevision = Number(result?.revision ?? serverRevision);
    await setLastSyncedRevision(localStore, finalRevision);
    return {
      accepted,
      revision: finalRevision,
      conflicts: result?.conflicts || [],
      sent: changesToPush.length,
    };
  }

  return {
    accepted: 0,
    revision: serverRevision,
    conflicts: result?.conflicts || [],
    sent: changesToPush.length,
  };
}

// ── LOCAL-FIRST SCHEDULER & DASHBOARD HELPERS ──

export function isDueToday(item) {
  const state = item.sched_state || "new";
  const dueStr = item.sm2_due;
  if (!dueStr) return true;

  const due = new Date(dueStr);
  const now = new Date();

  if (state === "new") {
    return due <= now;
  }

  if (state === "learning" || state === "relearn") {
    const lastQuality = item.sm2_last_quality ?? item.last_quality ?? -1;
    if (lastQuality !== -1) {
      const dueStrOnly = due.toISOString().slice(0, 10);
      const todayStrOnly = now.toISOString().slice(0, 10);
      return dueStrOnly <= todayStrOnly;
    }
    return due <= now;
  }

  // review state: compare by date only
  const dueStrOnly = due.toISOString().slice(0, 10);
  const todayStrOnly = now.toISOString().slice(0, 10);
  return dueStrOnly <= todayStrOnly;
}

function stableSeed(parts) {
  let h = 0;
  const text = parts.join("|");
  for (let i = 0; i < text.length; i++) {
    h = (Math.imul(31, h) + text.charCodeAt(i)) | 0;
  }
  return h;
}

function fuzzInterval(iv, seedVal) {
  if (iv <= 2) return iv;
  
  let rand;
  if (seedVal !== undefined) {
    let s = Math.abs(seedVal);
    rand = () => {
      s = (Math.imul(1664525, s) + 1013904223) | 0;
      return (s >>> 0) / 0xffffffff;
    };
  } else {
    rand = Math.random;
  }

  let min, max;
  if (iv <= 7) {
    min = -1;
    max = 1;
  } else if (iv <= 30) {
    min = -2;
    max = 2;
  } else if (iv <= 90) {
    min = -3;
    max = 4;
  } else {
    min = -4;
    max = 7;
  }

  const fuzz = Math.floor(rand() * (max - min + 1)) + min;
  return Math.max(1, iv + fuzz);
}

export function updateLocalScheduleState(currentState, quality, now = new Date()) {
  const current = {
    sched_state: currentState.sched_state || "new",
    sched_step: Number(currentState.sched_step || 0),
    sm2_interval: Number(currentState.sm2_interval || 1),
    sm2_ease: Number(currentState.sm2_ease || 2.5),
    sm2_due: currentState.sm2_due ? new Date(currentState.sm2_due) : now,
    sm2_repetitions: Number(currentState.sm2_repetitions || 0),
    reviews: Number(currentState.reviews || 0),
    id: currentState.id || currentState.box_id || currentState.card_id || "",
  };

  let state = current.sched_state === "new" ? "learning" : current.sched_state;
  let step = current.sched_step;
  let ease = current.sm2_ease;
  let interval = current.sm2_interval;
  let due = current.sm2_due;
  let repetitions = current.sm2_repetitions;

  const seedVal = stableSeed([current.id, repetitions, interval]);

  const goodIntervalRaw =
    state === "review"
      ? current.sm2_repetitions === 0
        ? 1
        : current.sm2_repetitions === 1
          ? 6
          : Math.min(365, Math.max(1, Math.round(interval * ease)))
      : 1;

  if (quality <= 1) {
    if (state === "review") ease = Math.max(1.3, ease - 0.2);
    const steps = state === "review" ? [10] : [1, 10];
    state = state === "review" ? "relearn" : "learning";
    step = 0;
    due = new Date(now.getTime() + steps[0] * 60000);
  } else if (quality === 3) {
    if (state === "learning" || state === "relearn") {
      const steps = state === "relearn" ? [10] : [1, 10];
      const hardMinutes = step === 0 && steps.length > 1 ? Math.floor((steps[0] + steps[1]) / 2) : steps[Math.min(step, steps.length - 1)];
      due = new Date(now.getTime() + hardMinutes * 60000);
    } else {
      ease = Math.max(1.3, ease - 0.15);
      state = "review";
      step = 0;
      let hardIvRaw = Math.min(365, Math.max(1, Math.round(interval * 1.2)));
      if (goodIntervalRaw > 1) {
        hardIvRaw = Math.min(hardIvRaw, goodIntervalRaw - 1);
      }
      const hardIv = fuzzInterval(hardIvRaw, seedVal);
      const goodIvOrder = fuzzInterval(goodIntervalRaw, seedVal);
      interval = Math.min(hardIv, goodIvOrder);
      due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + interval);
    }
  } else if (quality === 5) {
    if (state === "review") ease = Math.min(2.5, ease + 0.15);
    state = "review";
    step = 0;
    if (current.sched_state === "review") {
      const easyIvRaw = Math.min(365, Math.max(4, Math.round(interval * ease * 1.3)));
      const easyIv = fuzzInterval(easyIvRaw, seedVal);
      const goodIvOrder = fuzzInterval(goodIntervalRaw, seedVal);
      interval = Math.max(easyIv, goodIvOrder + 1);
    } else {
      interval = fuzzInterval(4, seedVal);
    }
    due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + interval);
  } else if (quality >= 6) {
    if (state === "review") ease = Math.min(2.5, ease + 0.3);
    state = "review";
    step = 0;
    if (current.sched_state === "review") {
      const easyIvRaw = Math.max(Math.min(365, Math.max(4, Math.round(interval * ease * 1.3))), goodIntervalRaw + 1);
      const perfectIvRaw = Math.max(Math.min(365, Math.max(7, Math.round(interval * ease * 1.6))), easyIvRaw + 1);
      const perfectIv = fuzzInterval(perfectIvRaw, seedVal);
      const easyIvOrder = fuzzInterval(easyIvRaw, seedVal);
      interval = Math.max(perfectIv, easyIvOrder + 1);
    } else {
      interval = fuzzInterval(7, seedVal);
    }
    due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + interval);
  } else if (state === "learning" || state === "relearn") {
    const steps = state === "relearn" ? [10] : [1, 10];
    const nextStep = step + 1;
    if (nextStep >= steps.length) {
      state = "review";
      step = 0;
      interval = 1;
      due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + interval);
    } else {
      step = nextStep;
      due = new Date(now.getTime() + steps[nextStep] * 60000);
    }
  } else {
    state = "review";
    step = 0;
    interval = fuzzInterval(goodIntervalRaw, seedVal);
    due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + interval);
  }

  if (state === "review") {
    due.setHours(0, 0, 0, 0);
  }

  return {
    sched_state: state,
    sched_step: step,
    sm2_interval: interval,
    sm2_ease: ease,
    sm2_due: due.toISOString(),
    sm2_repetitions: repetitions + (quality >= 3 ? 1 : 0),
    reviews: current.reviews + 1,
    sm2_last_quality: quality,
  };
}

function getReviewEntriesForCard(card, cardBoxes, reviewStatesMap) {
  if (!cardBoxes || !cardBoxes.length) {
    const state = reviewStatesMap.get(card.id) || { sched_state: "new" };
    return [
      {
        target: card,
        state: state,
        box_index: null,
        group_id: "",
        target_box_indexes: [],
        target_box_ids: [],
        due: isDueToday({ ...card, ...state }),
      }
    ];
  }

  const entries = [];
  const seenGroups = new Set();

  for (let idx = 0; idx < cardBoxes.length; idx++) {
    const box = cardBoxes[idx];
    const boxState = reviewStatesMap.get(box.id) || { sched_state: "new" };
    const groupId = box.group_id ? String(box.group_id) : "";

    if (groupId) {
      if (seenGroups.has(groupId)) continue;
      seenGroups.add(groupId);

      const groupMembers = [];
      for (let mIdx = 0; mIdx < cardBoxes.length; mIdx++) {
        const member = cardBoxes[mIdx];
        if (member.group_id && String(member.group_id) === groupId) {
          const mState = reviewStatesMap.get(member.id) || { sched_state: "new" };
          groupMembers.push({ index: mIdx, box: member, state: mState });
        }
      }

      const primary = groupMembers.find(m => isDueToday({ ...m.box, ...m.state })) || groupMembers[0];
      const isDue = groupMembers.some(m => isDueToday({ ...m.box, ...m.state }));

      entries.push({
        target: primary.box,
        state: primary.state,
        box_index: primary.index,
        group_id: groupId,
        target_box_indexes: groupMembers.map(m => m.index),
        target_box_ids: groupMembers.map(m => m.box.id),
        due: isDue,
      });
      continue;
    }

    entries.push({
      target: box,
      state: boxState,
      box_index: idx,
      group_id: "",
      target_box_indexes: [idx],
      target_box_ids: [box.id],
      due: isDueToday({ ...box, ...boxState }),
    });
  }
  return entries;
}

function calculateDeckTotals(deck, cardsMap, masksMap, reviewStatesMap) {
  const totals = {
    deck_count: 1,
    card_count: 0,
    occlusion_count: 0,
    due_items: 0,
    learning_items: 0,
    review_items: 0,
  };

  const deckCards = deck.cards || [];
  totals.card_count += deckCards.length;

  for (const card of deckCards) {
    const cardBoxes = card.boxes || [];
    totals.occlusion_count += cardBoxes.length;

    const entries = getReviewEntriesForCard(card, cardBoxes, reviewStatesMap);
    for (const entry of entries) {
      if (entry.due) {
        totals.due_items += 1;
      }
      const state = entry.state.sched_state || "new";
      if (state === "learning" || state === "relearn") {
        totals.learning_items += 1;
      } else if (state === "review") {
        totals.review_items += 1;
      }
    }
  }

  for (const child of deck.children || []) {
    const childTotals = calculateDeckTotals(child, cardsMap, masksMap, reviewStatesMap);
    totals.deck_count += childTotals.deck_count;
    totals.card_count += childTotals.card_count;
    totals.occlusion_count += childTotals.occlusion_count;
    totals.due_items += childTotals.due_items;
    totals.learning_items += childTotals.learning_items;
    totals.review_items += childTotals.review_items;
  }

  return totals;
}

function getDeckSummaryTree(deck, cardsMap, masksMap, reviewStatesMap) {
  const childrenSummaries = (deck.children || []).map(child =>
    getDeckSummaryTree(child, cardsMap, masksMap, reviewStatesMap)
  );
  const totals = calculateDeckTotals(deck, cardsMap, masksMap, reviewStatesMap);
  return {
    id: deck.id,
    name: deck.name || "Untitled",
    direct_cards: (deck.cards || []).length,
    total_cards: totals.card_count,
    due_items: totals.due_items,
    children: childrenSummaries,
  };
}

function buildReviewItemRecord(deck, card, entry) {
  const boxes = card.boxes || [];
  const box = entry.box_index !== null ? entry.target : null;

  return {
    deck_id: deck.id,
    deck_name: deck.name || "Untitled",
    card_id: card.id,
    card_title: card.title || "Untitled",
    box_id: box ? box.id : null,
    box_index: entry.box_index,
    label: card.label || "browser-local",
    sched_state: entry.state.sched_state || "new",
    sched_step: entry.state.sched_step || 0,
    sm2_interval: entry.state.sm2_interval || 1,
    sm2_ease: entry.state.sm2_ease || 2.5,
    sm2_due: entry.state.sm2_due,
    sm2_repetitions: entry.state.sm2_repetitions || 0,
    reviews: entry.state.reviews || 0,
    rating_previews: {}, 
    page_num: entry.target.page_num || 0,
    rect: entry.target.rect || [],
    shape: entry.target.shape || "rect",
    angle: entry.target.angle || 0,
    group_id: entry.group_id || "",
    target_kind: entry.group_id ? "group" : (box ? "box" : "card"),
    target_box_ids: entry.target_box_ids || [],
    target_box_indexes: entry.target_box_indexes || [],
    boxes: boxes.map((b, bIdx) => ({
      box_index: bIdx,
      box_id: b.id,
      label: b.label || "",
      rect: b.rect || [],
      shape: b.shape || "rect",
      angle: b.angle || 0,
      group_id: b.group_id || "",
      page_num: b.page_num || 0,
    })),
    pdf_box_render_zoom: card.pdf_box_render_zoom || 1.5,
    pdf_path: card.pdf_path || null,
    image_path: card.image_path || null,
    image_data_url: card.image_data_url || null,
  };
}

function findDeckInTree(nodes, deckId) {
  for (const node of nodes) {
    if (String(node.id) === String(deckId)) {
      return node;
    }
    if (node.children && node.children.length > 0) {
      const found = findDeckInTree(node.children, deckId);
      if (found) return found;
    }
  }
  return null;
}

export async function getLocalDashboardPayload(localStore, selectedDeckId = null) {
  const flatDecks = await localStore.list("decks");
  const flatCards = await localStore.list("cards");
  const flatMasks = await localStore.list("masks");
  const flatReviewStates = await localStore.list("review_state");

  const reviewStatesMap = new Map(flatReviewStates.map(rs => [rs.id, rs]));

  const deckMap = new Map(flatDecks.map(d => [d.id, { ...d, children: [], cards: [] }]));
  const cardMap = new Map(flatCards.map(c => [c.id, { ...c, boxes: [] }]));

  for (const mask of flatMasks) {
    const card = cardMap.get(mask.card_id);
    if (card) {
      card.boxes.push(mask);
    }
  }

  for (const card of cardMap.values()) {
    card.boxes.sort((a, b) => (a.box_index ?? 0) - (b.box_index ?? 0));
  }

  for (const card of cardMap.values()) {
    const deck = deckMap.get(card.deck_id);
    if (deck) {
      deck.cards.push(card);
    }
  }

  const roots = [];
  for (const deck of deckMap.values()) {
    if (deck.parent_id) {
      const parent = deckMap.get(deck.parent_id);
      if (parent) {
        parent.children.push(deck);
      } else {
        roots.push(deck);
      }
    } else {
      roots.push(deck);
    }
  }

  const decksTree = roots.map(root => getDeckSummaryTree(root, cardMap, null, reviewStatesMap));

  const reviewItems = [];
  
  function collectDueItems(deck) {
    const deckRecord = deckMap.get(deck.id);
    if (deckRecord) {
      for (const card of deckRecord.cards) {
        const entries = getReviewEntriesForCard(card, card.boxes, reviewStatesMap);
        for (const entry of entries) {
          if (entry.due) {
            reviewItems.push(buildReviewItemRecord(deckRecord, card, entry));
          }
        }
      }
    }
    for (const child of deck.children || []) {
      collectDueItems(child);
    }
  }

  if (selectedDeckId) {
    const targetRoot = findDeckInTree(decksTree, selectedDeckId) || decksTree[0];
    if (targetRoot) {
      collectDueItems(targetRoot);
    }
  } else {
    for (const root of decksTree) {
      collectDueItems(root);
    }
  }

  const summary = {
    deck_count: flatDecks.length,
    card_count: flatCards.length,
    occlusion_count: flatMasks.length,
    due_items: reviewItems.length,
    learning_items: flatReviewStates.filter(s => s.sched_state === "learning" || s.sched_state === "relearn").length,
    review_items: flatReviewStates.filter(s => s.sched_state === "review").length,
    source: "IndexedDB Local",
  };

  return { summary, decks: decksTree, reviewItems };
}

export async function saveLocalRating(localStore, request) {
  const now = new Date();
  const flatCards = await localStore.list("cards");
  const flatMasks = await localStore.list("masks");

  const card = flatCards.find(c => c.id === request.card_id);
  if (!card) return { updated: false, message: "Card not found" };

  const boxes = flatMasks.filter(m => m.card_id === request.card_id);
  let targets = [];

  if (boxes.length) {
    if (request.group_id) {
      targets = boxes.filter(b => String(b.group_id) === String(request.group_id));
    } else if (request.box_id) {
      const box = boxes.find(b => b.id === request.box_id);
      if (box) {
        const groupId = box.group_id ? String(box.group_id) : "";
        if (groupId) {
          targets = boxes.filter(b => String(b.group_id) === groupId);
        } else {
          targets = [box];
        }
      }
    } else if (request.box_index !== null && request.box_index !== undefined) {
      const box = boxes.find(b => b.box_index === Number(request.box_index));
      if (box) {
        const groupId = box.group_id ? String(box.group_id) : "";
        if (groupId) {
          targets = boxes.filter(b => String(b.group_id) === groupId);
        } else {
          targets = [box];
        }
      }
    }
  } else {
    targets = [card];
  }

  if (!targets.length) return { updated: false, message: "Review targets not found" };

  for (const target of targets) {
    const currentState = (await localStore.get("review_state", target.id)) || {
      id: target.id,
      sched_state: "new",
      sched_step: 0,
      sm2_interval: 1,
      sm2_ease: 2.5,
      sm2_due: now.toISOString(),
      sm2_repetitions: 0,
      reviews: 0,
    };

    const nextState = updateLocalScheduleState(currentState, request.quality, now);
    await localStore.put("review_state", nextState);

    await localStore.queueChange({
      collection: "review_state",
      item_id: target.id,
      payload: nextState,
    });
  }

  return { updated: true };
}

export async function importDecksToIndexedDb(decksTree, localStore) {
  async function traverse(deck, parentId = null) {
    const deckRecord = {
      id: String(deck.id || deck._id),
      name: deck.name || "Untitled Dojo",
      parent_id: parentId ? String(parentId) : null,
    };
    await localStore.put("decks", deckRecord);

    const cards = deck.cards || [];
    for (const card of cards) {
      const cardId = String(card.id || card._id || card.title);
      const cardRecord = {
        id: cardId,
        deck_id: deckRecord.id,
        title: card.title || "Untitled Scroll",
        pdf_path: card.pdf_path || null,
        image_path: card.image_path || null,
        image_data_url: card.image_data_url || null,
        pdf_box_render_zoom: card.pdf_box_render_zoom || 1.5,
        label: card.label || "browser-local",
      };
      await localStore.put("cards", cardRecord);

      const boxes = card.boxes || [];
      for (let idx = 0; idx < boxes.length; idx++) {
        const box = boxes[idx];
        const boxId = box.box_id || `${cardRecord.id}-box-${idx}`;
        const maskRecord = {
          id: boxId,
          card_id: cardRecord.id,
          box_index: idx,
          rect: box.rect,
          shape: box.shape || "rect",
          angle: box.angle || 0,
          group_id: box.group_id || null,
          page_num: box.page_num || 0,
          label: box.label || "",
        };
        await localStore.put("masks", maskRecord);

        const stateRecord = {
          id: boxId,
          card_id: cardRecord.id,
          box_id: boxId,
          sched_state: box.sched_state || "new",
          sched_step: box.sched_step || 0,
          sm2_interval: box.sm2_interval || 1,
          sm2_ease: box.sm2_ease || 2.5,
          sm2_due: box.sm2_due || new Date().toISOString(),
          sm2_repetitions: box.sm2_repetitions || 0,
          reviews: box.reviews || 0,
        };
        await localStore.put("review_state", stateRecord);
      }
    }

    const children = deck.children || [];
    for (const child of children) {
      await traverse(child, deckRecord.id);
    }
  }

  for (const deck of decksTree) {
    await traverse(deck);
  }
}

export { LOCAL_STORE_NAMES, SYNCABLE_COLLECTIONS };
