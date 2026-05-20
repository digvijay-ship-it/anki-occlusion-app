import React, { useEffect, useMemo, useState } from "react";
import { API_BASE, loadDashboard } from "./api.js";

const fallbackSummary = {
  deck_count: 0,
  card_count: 0,
  occlusion_count: 0,
  due_items: 0,
  learning_items: 0,
  review_items: 0,
  source: "",
};

function flattenDecks(decks) {
  return decks.flatMap((deck) => {
    const children = Array.isArray(deck.children) ? deck.children : [];
    return [deck, ...flattenDecks(children)];
  });
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

function App() {
  const [data, setData] = useState({
    summary: fallbackSummary,
    decks: [],
    reviewItems: [],
  });
  const [selectedDeckId, setSelectedDeckId] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

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

  return (
    <div className="app-shell">
      <div className="scanlines" />
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◇</span>
          <h1 data-text="ANKI OCCLUSION">ANKI OCCLUSION</h1>
        </div>
        <nav className="nav-links">
          <button type="button">Math</button>
          <button type="button">Journal</button>
          <button type="button">Classic Mode</button>
          <button type="button">More ▾</button>
        </nav>
        <div className="top-actions">
          <button className="icon-button" title="Save" type="button">
            ▣
          </button>
          <button className="icon-button" title="Settings" type="button">
            ⚙
          </button>
          <button className="music-button" type="button">
            BGM
          </button>
          <div className="mentor-chip">
            <span>"FOCUS. TRAIN. MASTER."</span>
            <small>DONATELLO</small>
          </div>
        </div>
      </header>

      <div className="workspace">
        <aside className="left-rail">
          <div className="rail-header">
            <h2>Dojo Cave</h2>
            <input placeholder="Search scrolls..." type="search" />
          </div>
          <div className="deck-list">
            <div className="section-title">YOUR DOJOS</div>
            {status === "loading" ? (
              <div className="empty-line">Loading dojos...</div>
            ) : data.decks.length ? (
              data.decks.map((deck) => (
                <DeckRow
                  key={deck.id}
                  deck={deck}
                  selectedId={selectedDeck?.id}
                  onSelect={setSelectedDeckId}
                />
              ))
            ) : (
              <div className="empty-line">No decks found</div>
            )}
          </div>
          <div className="rail-actions">
            <button type="button">New Dojo</button>
            <button type="button">Sub</button>
            <button type="button">Open</button>
          </div>
        </aside>

        <main className="main-panel">
          <section className="deck-hero">
            <div className="selected-deck-icon">√</div>
            <div>
              <h2>{selectedDeck?.name || "No Deck Selected"}</h2>
              <p>
                Scrolls: {selectedDeck?.total_cards || 0}
                <span>◆</span>
                Due: {selectedDeck?.due_items || 0}
              </p>
            </div>
            <button className="forge-button" type="button">
              Forge Scroll
            </button>
          </section>

          <section className="stats-grid">
            <StatCard
              tone="red"
              value={data.summary.due_items}
              title="Remaining Missions"
              caption="Cards due for review"
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
              title="Scrolls"
              caption="Total cards"
            />
          </section>

          <section className="mission-card">
            <div className="mission-copy">
              <h3>Training Mission</h3>
              <p>{selectedReviewItems.length} due in selected dojo</p>
              <code>&gt; ready_</code>
            </div>
            <div className="mission-actions">
              <button className="start-button" type="button">
                Start Training
                <span>Press Start</span>
              </button>
              <button className="secondary-button" type="button">
                Train Selected Scroll
              </button>
            </div>
          </section>

          <section className="scroll-stage">
            {selectedReviewItems.length ? (
              <div className="review-list">
                {selectedReviewItems.slice(0, 8).map((item) => (
                  <article
                    className="review-row"
                    key={`${item.card_id}-${item.box_id ?? item.box_index ?? "card"}`}
                  >
                    <span>{item.card_title}</span>
                    <small>
                      {item.box_id ? `box ${item.box_index + 1}` : "card"}
                    </small>
                  </article>
                ))}
              </div>
            ) : (
              <div className="stage-empty">- SELECT A SCROLL TO BEGIN -</div>
            )}
          </section>
        </main>

        <aside className="right-rail">
          <section>
            <h3>Banga Lab</h3>
            <div className="section-title">SYSTEM STATUS</div>
            <dl className="status-grid">
              <dt>Algorithm</dt>
              <dd>SM-2</dd>
              <dt>Scheduler</dt>
              <dd className="active">Active</dd>
              <dt>PDF Engine</dt>
              <dd>PyMuPDF</dd>
              <dt>API</dt>
              <dd className={status === "ready" ? "active" : "warn"}>
                {status === "error" ? "Offline" : "Online"}
              </dd>
            </dl>
          </section>

          <section className="resources">
            <div className="section-title">DOJO RESOURCES</div>
            <ResourceBar label="Decks" value={data.summary.deck_count} max={20} />
            <ResourceBar label="Due" value={data.summary.due_items} max={50} />
            <ResourceBar label="Learning" value={data.summary.learning_items} max={50} />
          </section>

          <section className="fuel-card">
            <strong>Fuel Up</strong>
            <span>Take breaks. Keep the streak clean.</span>
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

export default App;
