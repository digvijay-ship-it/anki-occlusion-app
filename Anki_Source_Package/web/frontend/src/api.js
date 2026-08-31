const API_BASE = import.meta.env?.VITE_API_BASE || "http://127.0.0.1:8000";

async function requestJson(path, options = {}) {
  const headers = {
    Accept: "application/json",
    "x-anki-user": "e2e-test-user",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function getJson(path) {
  return requestJson(path);
}

export async function loadDashboard(deckId = null, { reviewLimit = 100 } = {}) {
  const reviewParams = new URLSearchParams();
  reviewParams.set("limit", String(reviewLimit));
  if (deckId !== null && deckId !== undefined) {
    reviewParams.set("deck_id", String(deckId));
  }
  const reviewPath = `/api/review/items?${reviewParams.toString()}`;
  const [summary, decks, reviewItems] = await Promise.all([
    getJson("/api/summary"),
    getJson("/api/decks"),
    getJson(reviewPath),
  ]);
  return { summary, decks, reviewItems };
}

export async function rateReviewItem(item, quality) {
  return requestJson("/api/review/rate", {
    method: "POST",
    body: JSON.stringify({
      card_id: item.card_id,
      deck_id: item.deck_id,
      box_id: item.box_id || null,
      box_index: item.box_index ?? null,
      group_id: item.group_id || null,
      quality,
    }),
  });
}

export async function undoReviewRating() {
  return requestJson("/api/review/undo", {
    method: "POST",
  });
}

export async function redoReviewRating() {
  return requestJson("/api/review/redo", {
    method: "POST",
  });
}

export function mediaUrl(path) {
  if (!path) return "";
  return `${API_BASE}/api/media?path=${encodeURIComponent(path)}`;
}

export async function revealMediaPath(path) {
  return requestJson("/api/media/reveal", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function loadCurrentUser() {
  return getJson("/api/me");
}

export async function pullSync(sinceRevision = 0) {
  return getJson(`/api/sync/pull?since_revision=${encodeURIComponent(sinceRevision)}`);
}

export async function pushSync(changes = [], baseRevision = 0) {
  return requestJson("/api/sync/push", {
    method: "POST",
    body: JSON.stringify({
      base_revision: baseRevision,
      changes,
    }),
  });
}

export async function sendClientMetric(event, payload = {}) {
  return requestJson("/api/metrics/client", {
    method: "POST",
    body: JSON.stringify({ event, payload }),
  });
}

export async function loadCostSnapshot() {
  return getJson("/api/metrics/cost");
}

export async function loadJournal() {
  return getJson("/api/journal");
}

export async function saveJournal(data) {
  return requestJson("/api/journal", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function loadRawData() {
  return getJson("/api/data/raw");
}


export { API_BASE, requestJson };
