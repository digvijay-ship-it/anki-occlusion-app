const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function getJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function loadDashboard() {
  const [summary, decks, reviewItems] = await Promise.all([
    getJson("/api/summary"),
    getJson("/api/decks"),
    getJson("/api/review/items"),
  ]);
  return { summary, decks, reviewItems };
}

export { API_BASE };

