const API_BASE = import.meta.env?.VITE_API_BASE || "http://127.0.0.1:8000";

async function requestJson(path, options = {}) {
  const headers = {
    Accept: "application/json",
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

export async function loadDashboard(deckId = null) {
  const reviewPath =
    deckId === null || deckId === undefined
      ? "/api/review/items"
      : `/api/review/items?deck_id=${encodeURIComponent(deckId)}`;
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
      quality,
    }),
  });
}

export { API_BASE, requestJson };
