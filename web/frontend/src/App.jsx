import React, { useEffect, useMemo, useState } from "react";
import { API_BASE, loadDashboard, rateReviewItem } from "./api.js";

const fallbackSummary = {
  deck_count: 0,
  card_count: 0,
  occlusion_count: 0,
  due_items: 0,
  learning_items: 0,
  review_items: 0,
  source: "",
};

const ratings = [
  { label: "Again", quality: 1, tone: "danger" },
  { label: "Hard", quality: 3, tone: "hard" },
  { label: "Good", quality: 4, tone: "success" },
  { label: "Easy", quality: 5, tone: "warning" },
  { label: "Perfect", quality: 6, tone: "perfect" },
];

function flattenDecks(decks) {
  return decks.flatMap((deck) => {
    const children = Array.isArray(deck.children) ? deck.children : [];
    return [deck, ...flattenDecks(children)];
  });
}

function itemKey(item) {
  return `${item.deck_id}:${item.card_id}:${item.box_id ?? item.box_index ?? "card"}`;
}

function itemTargetLabel(item) {
  if (item.box_id || item.box_index !== null) {
    const n = Number.isFinite(Number(item.box_index))
      ? Number(item.box_index) + 1
      : "?";
    return `Occlusion ${n}`;
  }
  return "Whole card";
}

function DeckRow({ deck, selectedId, onSelect, depth = 0 }) {
  const selected = String(deck.id) === String(selectedId);
  const children = Array.isArray(deck.children) ? deck.children : [];
  return (
    <>
      <button
        className={`deck-row ${selected ? "selected" : ""}`}
        style={{ "--depth": depth }}
        onClick={() => onSelect(deck.id)}
        type="button"
      >
        <span className="deck-name">
          <span className="chevron">{children.length ? "▾" : "▸"}</span>
          {deck.name || "Untitled"}
        </span>
        <span className={deck.due_items ? "due-pill hot" : "due-pill"}>
          {deck.due_items || "✓"}
        </span>
      </button>
      {children.map((child) => (
        <DeckRow
          key={child.id}
          deck={child}
          selectedId={selectedId}
          onSelect={onSelect}
          depth={depth + 1}
        />
      ))}
    </>
  );
}

function StatCard({ tone, value, title, caption }) {
  return (
    <section className={`stat-card ${tone}`}>
      <div className="stat-glow" />
      <div className="stat-icon">★</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">
          {title}
          <span>{caption}</span>
        </div>
      </div>
    </section>
  );
}

function ResourceBar({ label, value, max }) {
  const pct = Math.min(100, Math.round((Number(value || 0) / max) * 100));
  return (
    <div className="resource">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className="bar">
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function App() {
  const [data, setData] = useState({
    summary: fallbackSummary,
    decks: [],
    reviewItems: [],
  });
  const [selectedDeckId, setSelectedDeckId] = useState(null);
  const [activeKey, setActiveKey] = useState("");
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyQuality, setBusyQuality] = useState(null);

  async function refreshDashboard(deckId = selectedDeckId) {
    setStatus((current) => (current === "ready" ? "refreshing" : "loading"));
    setError("");
    const payload = await loadDashboard(deckId);
    setData(payload);
    const nextDeckId = deckId ?? payload.decks[0]?.id ?? null;
    setSelectedDeckId(nextDeckId);
    setStatus("ready");
    return payload;
  }

  useEffect(() => {
    let alive = true;
    loadDashboard()
      .then((payload) => {
        if (!alive) return;
        setData(payload);
        setSelectedDeckId(payload.decks[0]?.id ?? null);
        setStatus("ready");
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
        setStatus("error");
      });
    return () => {
      alive = false;
    };
  }, []);

  const allDecks = useMemo(() => flattenDecks(data.decks), [data.decks]);
  const selectedDeck =
    allDecks.find((deck) => String(deck.id) === String(selectedDeckId)) ||
    allDecks[0] ||
    null;
  const selectedReviewItems = selectedDeck
    ? data.reviewItems.filter(
        (item) => String(item.deck_id) === String(selectedDeck.id),
      )
    : data.reviewItems;

  useEffect(() => {
    if (!selectedReviewItems.length) {
      setActiveKey("");
      return;
    }
    if (!selectedReviewItems.some((item) => itemKey(item) === activeKey)) {
      setActiveKey(itemKey(selectedReviewItems[0]));
    }
  }, [activeKey, selectedReviewItems]);

  const activeItem =
    selectedReviewItems.find((item) => itemKey(item) === activeKey) ||
    selectedReviewItems[0] ||
    null;

  async function handleSelectDeck(deckId) {
    setSelectedDeckId(deckId);
    setActiveKey("");
    setNotice("");
    try {
      await refreshDashboard(deckId);
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  async function handleRate(quality) {
    if (!activeItem || busyQuality !== null) return;
    setBusyQuality(quality);
    setNotice("");
    try {
      const result = await rateReviewItem(activeItem, quality);
      if (!result.updated) {
        setNotice("No matching review target was found.");
      } else {
        setNotice(`${activeItem.card_title} rated ${quality}.`);
      }
      await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
    } catch (err) {
      setError(err.message);
      setStatus("error");
    } finally {
      setBusyQuality(null);
    }
  }

  return (
    <div className="app-shell">
      <div className="scanlines" />
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◇</span>
          <h1 data-text="ANKI OCCLUSION">ANKI OCCLUSION</h1>
        </div>
        <nav className="nav-links">
          <button type="button">Review</button>
          <button type="button">Decks</button>
          <button type="button">Journal</button>
          <button type="button">Settings</button>
        </nav>
        <div className="top-actions">
          <button
            className="icon-button"
            disabled={status === "loading" || status === "refreshing"}
            onClick={() => refreshDashboard().catch((err) => setError(err.message))}
            title="Refresh"
            type="button"
          >
            ↻
          </button>
          <div className="mentor-chip">
            <span>{status === "error" ? "API OFFLINE" : "FOCUS. TRAIN. MASTER."}</span>
            <small>{status === "refreshing" ? "SYNCING" : "WEB DOJO"}</small>
          </div>
        </div>
      </header>

      <div className="workspace">
        <aside className="left-rail">
          <div className="rail-header">
            <h2>Decks</h2>
            <input placeholder="Search comes next..." type="search" />
          </div>
          <div className="deck-list">
            <div className="section-title">YOUR DECKS</div>
            {status === "loading" ? (
              <div className="empty-line">Loading decks...</div>
            ) : data.decks.length ? (
              data.decks.map((deck) => (
                <DeckRow
                  key={deck.id}
                  deck={deck}
                  selectedId={selectedDeck?.id}
                  onSelect={handleSelectDeck}
                />
              ))
            ) : (
              <div className="empty-line">No decks found</div>
            )}
          </div>
          <div className="rail-actions">
            <button type="button">New</button>
            <button type="button">Import</button>
            <button type="button">Open</button>
          </div>
        </aside>

        <main className="main-panel">
          <section className="deck-hero">
            <div className="selected-deck-icon">√</div>
            <div>
              <h2>{selectedDeck?.name || "No Deck Selected"}</h2>
              <p>
                Cards: {selectedDeck?.total_cards || 0}
                <span>◆</span>
                Due: {selectedDeck?.due_items || 0}
              </p>
            </div>
            <button
              className="forge-button"
              disabled={!selectedReviewItems.length}
              onClick={() => setActiveKey(itemKey(selectedReviewItems[0]))}
              type="button"
            >
              Start Review
            </button>
          </section>

          <section className="stats-grid">
            <StatCard
              tone="red"
              value={data.summary.due_items}
              title="Due Items"
              caption="Ready for review"
            />
            <StatCard
              tone="purple"
              value={data.summary.occlusion_count}
              title="Occlusions"
              caption="Active masks"
            />
            <StatCard
              tone="green"
              value={data.summary.card_count}
              title="Cards"
              caption="Across all decks"
            />
          </section>

          <section className="review-console">
            <div className="review-item-detail">
              <div className="section-title">ACTIVE REVIEW</div>
              {activeItem ? (
                <>
                  <h3>{activeItem.card_title}</h3>
                  <p>
                    {activeItem.deck_name}
                    <span>◆</span>
                    {itemTargetLabel(activeItem)}
                    <span>◆</span>
                    {activeItem.sched_state}
                  </p>
                  {activeItem.label ? <code>{activeItem.label}</code> : null}
                </>
              ) : (
                <div className="stage-empty">NO DUE ITEMS IN THIS DECK</div>
              )}
            </div>
            <div className="quality-grid">
              {ratings.map((rating) => (
                <button
                  className={`quality-button ${rating.tone}`}
                  disabled={!activeItem || busyQuality !== null}
                  key={rating.quality}
                  onClick={() => handleRate(rating.quality)}
                  type="button"
                >
                  <span>{rating.quality}</span>
                  {busyQuality === rating.quality ? "Saving..." : rating.label}
                </button>
              ))}
            </div>
          </section>

          <section className="scroll-stage">
            {selectedReviewItems.length ? (
              <div className="review-list">
                {selectedReviewItems.slice(0, 12).map((item) => {
                  const key = itemKey(item);
                  return (
                    <button
                      className={`review-row ${key === itemKey(activeItem || {}) ? "active" : ""}`}
                      key={key}
                      onClick={() => setActiveKey(key)}
                      type="button"
                    >
                      <span>{item.card_title}</span>
                      <small>{itemTargetLabel(item)}</small>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="stage-empty">- ALL CLEAR -</div>
            )}
          </section>
        </main>

        <aside className="right-rail">
          <section>
            <h3>System</h3>
            <div className="section-title">STATUS</div>
            <dl className="status-grid">
              <dt>Algorithm</dt>
              <dd>SM-2</dd>
              <dt>Scheduler</dt>
              <dd className="active">Active</dd>
              <dt>PDF Engine</dt>
              <dd>PyMuPDF</dd>
              <dt>API</dt>
              <dd className={status === "error" ? "warn" : "active"}>
                {status === "error" ? "Offline" : "Online"}
              </dd>
            </dl>
          </section>

          <section className="resources">
            <div className="section-title">COUNTS</div>
            <ResourceBar label="Decks" value={data.summary.deck_count} max={20} />
            <ResourceBar label="Due" value={data.summary.due_items} max={50} />
            <ResourceBar label="Learning" value={data.summary.learning_items} max={50} />
          </section>

          <section className="fuel-card">
            <strong>Review Log</strong>
            <span>{notice || error || "Ready."}</span>
          </section>
        </aside>
      </div>

      <footer className="statusbar">
        <span>SM-2 Active</span>
        <span>API {API_BASE}</span>
        {error ? <span className="footer-error">{error}</span> : null}
      </footer>
    </div>
  );
}

export default App;
