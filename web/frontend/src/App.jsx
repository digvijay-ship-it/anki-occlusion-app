import React, { useEffect, useMemo, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
import {
  API_BASE,
  loadCostSnapshot,
  loadDashboard,
  mediaUrl,
  redoReviewRating,
  rateReviewItem,
  revealMediaPath,
  undoReviewRating,
} from "./api.js";
import {
  boxIdentity,
  itemTargetLabel as formatReviewTargetLabel,
  reviewItemKey,
  reviewQueueLabel,
  reviewRatingPreviews,
  zoomReviewScale,
  normalizeReviewBoxes,
} from "./reviewGeometry.js";
import { ReviewDocumentSurface } from "./reviewSurface.jsx";
import {
  openIndexedDbLocalFirstStore,
  getLocalDashboardPayload,
  saveLocalRating,
  importDecksToIndexedDb,
  flushQueuedChanges,
} from "./localFirstStore.js";

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
  { icon: "↻", label: "Again", quality: 1, shortcut: 1, tone: "danger" },
  { icon: "!", label: "Hard", quality: 3, shortcut: 2, tone: "hard" },
  { icon: "✓", label: "Good", quality: 4, shortcut: 3, tone: "success" },
  { icon: "⚡", label: "Easy", quality: 5, shortcut: 4, tone: "warning" },
  { icon: "★", label: "Perfect", quality: 6, shortcut: 5, tone: "perfect" },
];

const reviewPenColors = ["#ff4d5a", "#ffd166", "#66fcf1", "#ffffff"];

function createReviewStats(total = 0) {
  return {
    total,
    done: 0,
    startedAt: Date.now(),
    ratings: {
      1: 0,
      3: 0,
      4: 0,
      5: 0,
      6: 0,
    },
  };
}

function updateReviewStats(stats, quality) {
  const current = stats || createReviewStats();
  return {
    ...current,
    done: current.done + 1,
    ratings: {
      ...current.ratings,
      [quality]: (current.ratings?.[quality] || 0) + 1,
    },
  };
}

function reviewRetention(stats) {
  const counts = stats?.ratings || {};
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  if (!total) return 0;
  const retained = (counts[4] || 0) + (counts[5] || 0) + (counts[6] || 0);
  return Math.round((retained / total) * 100);
}

function createMathProblem(mode, seed) {
  const left = (seed * 7) % 18 + 2;
  const right = (seed * 5) % 11 + 2;
  if (mode === "squares") {
    return {
      prompt: `${left}²`,
      answer: left * left,
      label: "Square",
    };
  }
  if (mode === "cubes") {
    return {
      prompt: `${Math.min(left, 12)}³`,
      answer: Math.min(left, 12) ** 3,
      label: "Cube",
    };
  }
  return {
    prompt: `${left} × ${right}`,
    answer: left * right,
    label: "Table",
  };
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, value));
}

function createMaskId() {
  return `local-mask-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeMask(start, end) {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const width = Math.abs(start.x - end.x);
  const height = Math.abs(start.y - end.y);
  if (width < 2 || height < 2) return null;
  return {
    id: createMaskId(),
    x: clampPercent(left),
    y: clampPercent(top),
    width: clampPercent(width),
    height: clampPercent(height),
  };
}

function maskStyle(mask) {
  return {
    left: `${mask.x}%`,
    top: `${mask.y}%`,
    width: `${mask.width}%`,
    height: `${mask.height}%`,
  };
}

function createDemoImage() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="900" height="560" viewBox="0 0 900 560">
      <rect width="900" height="560" fill="#11161e"/>
      <rect x="54" y="52" width="792" height="456" rx="18" fill="#f4f0df"/>
      <path d="M104 134h692M104 224h692M104 314h692M104 404h692" stroke="#c8bda0" stroke-width="4"/>
      <text x="104" y="176" fill="#263238" font-family="Arial, sans-serif" font-size="54" font-weight="700">A = pi r^2</text>
      <text x="104" y="274" fill="#263238" font-family="Arial, sans-serif" font-size="48">Area of a circle</text>
      <text x="104" y="372" fill="#263238" font-family="Arial, sans-serif" font-size="42">Mask the formula, reveal later</text>
    </svg>
  `.trim();
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function flattenDecks(decks) {
  return decks.flatMap((deck) => {
    const children = Array.isArray(deck.children) ? deck.children : [];
    return [deck, ...flattenDecks(children)];
  });
}

function filterDecks(decks, query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return decks;
  return decks
    .map((deck) => {
      const children = filterDecks(deck.children || [], query);
      const matches = (deck.name || "").toLowerCase().includes(trimmed);
      return matches || children.length ? { ...deck, children } : null;
    })
    .filter(Boolean);
}

function itemKey(item) {
  return reviewItemKey(item);
}

function itemTargetLabel(item) {
  return formatReviewTargetLabel(item);
}

function deckDisplayName(deck) {
  return deck?.name || "No Deck Selected";
}

function isLocalDeckId(deckId) {
  return String(deckId || "").startsWith("local-deck-");
}

function isLocalReviewItem(item) {
  return isLocalDeckId(item?.deck_id) || item?.label === "browser-local";
}

function createLocalDeck(name) {
  return {
    id: `local-deck-${Date.now()}`,
    name,
    direct_cards: 0,
    total_cards: 0,
    occlusion_count: 0,
    due_items: 0,
    learning_items: 0,
    review_items: 0,
    children: [],
  };
}

function collectDeckIds(deck) {
  return [deck.id, ...(deck.children || []).flatMap(collectDeckIds)];
}

function deckSubtreeStats(deck) {
  return {
    deck_count: collectDeckIds(deck).length,
    card_count: deck.total_cards || 0,
    occlusion_count: deck.occlusion_count || 0,
    due_items: deck.due_items || 0,
    review_items: deck.review_items || 0,
  };
}

function addDeckToTree(decks, parentId, newDeck) {
  if (!parentId) return [...decks, newDeck];
  let inserted = false;

  function visit(nodes) {
    return nodes.map((deck) => {
      if (String(deck.id) === String(parentId)) {
        inserted = true;
        return { ...deck, children: [...(deck.children || []), newDeck] };
      }
      if (!deck.children?.length) return deck;
      return { ...deck, children: visit(deck.children) };
    });
  }

  const nextDecks = visit(decks);
  return inserted ? nextDecks : [...decks, newDeck];
}

function removeDeckFromTree(decks, deckId) {
  return decks.flatMap((deck) => {
    if (String(deck.id) === String(deckId)) return [];
    return [{ ...deck, children: removeDeckFromTree(deck.children || [], deckId) }];
  });
}

function updateDeckById(decks, deckId, updater) {
  return decks.map((deck) => {
    const children = updateDeckById(deck.children || [], deckId, updater);
    const nextDeck = children.length ? { ...deck, children } : { ...deck };
    return String(deck.id) === String(deckId) ? updater(nextDeck) : nextDeck;
  });
}

function DeckRow({ deck, selectedId, onSelect, depth = 0, collapsedDeckIds, onToggleCollapse }) {
  const selected = String(deck.id) === String(selectedId);
  const children = Array.isArray(deck.children) ? deck.children : [];
  const isCollapsed = collapsedDeckIds ? collapsedDeckIds.has(deck.id) : false;
  return (
    <>
      <button
        className={`deck-row dojo-row ${selected ? "selected" : ""}`}
        style={{ "--depth": depth }}
        onClick={() => onSelect(deck.id)}
        type="button"
      >
        <span className="deck-name">
          <span
            className="chevron"
            onClick={(e) => {
              if (children.length > 0 && onToggleCollapse) {
                e.stopPropagation();
                onToggleCollapse(deck.id);
              }
            }}
            style={{
              visibility: children.length > 0 ? "visible" : "hidden",
              cursor: "pointer",
              marginRight: "6px",
            }}
          >
            {isCollapsed ? "▸" : "▾"}
          </span>
          {deck.name || "Untitled"}
        </span>
        <span className={deck.due_items ? "due-pill hot" : "due-pill"}>
          {deck.due_items || "✓"}
        </span>
      </button>
      {!isCollapsed && children.map((child) => (
        <DeckRow
          key={child.id}
          deck={child}
          selectedId={selectedId}
          onSelect={onSelect}
          depth={depth + 1}
          collapsedDeckIds={collapsedDeckIds}
          onToggleCollapse={onToggleCollapse}
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

function LocalImageReview({ item, revealed, onReveal, reviewStyle, zoom }) {
  const masks = item?.local_masks || [];
  const hiddenMasks =
    !revealed && reviewStyle === "hide_one" && masks.length ? masks.slice(0, 1) : masks;
  const visibleMasks = revealed ? masks : hiddenMasks;
  return (
    <div className={`review-image-frame ${revealed ? "revealed" : ""}`}>
      <div className="review-image-zoom-layer" style={{ "--review-zoom": zoom }}>
        <img alt="" src={item.image_data_url} />
        {visibleMasks.map((mask) => (
          <span
            className={`review-mask ${revealed ? "revealed" : ""}`}
            key={mask.id}
            style={maskStyle(mask)}
          />
        ))}
      </div>
      {revealed ? (
        <div className="answer-chip">
          <strong>Answer revealed</strong>
          <span>{itemTargetLabel(item)}</span>
        </div>
      ) : (
        <button
          className="reveal-button image-reveal"
          disabled={!item}
          onClick={onReveal}
          type="button"
        >
          Show Answer <span>[Space]</span>
        </button>
      )}
    </div>
  );
}

export function ReviewQualityButtons({ activeItem, busyQuality, onRate, previews }) {
  return (
    <div className="quality-grid review-quality-buttons">
      {ratings.map((rating) => {
        const preview = previews?.[rating.quality] || previews?.[String(rating.quality)] || "?";
        return (
          <button
            className={`quality-button ${rating.tone}`}
            disabled={!activeItem || busyQuality !== null}
            key={rating.quality}
            onClick={() => onRate(rating.quality)}
            type="button"
          >
            <span>{rating.shortcut} {rating.icon}</span>
            <strong>{busyQuality === rating.quality ? "Saving" : preview}</strong>
            <em>{rating.label}</em>
          </button>
        );
      })}
    </div>
  );
}

function getMaskGroupLabel(mask, allMasks) {
  if (!mask.group_id) return "";
  const uniqueGroups = Array.from(new Set(allMasks.map(m => m.group_id).filter(Boolean)));
  const index = uniqueGroups.indexOf(mask.group_id);
  return index !== -1 ? `G${index + 1}` : "G";
}

function formatTimer(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${h ? h + ":" : ""}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function App() {
  const searchInputRef = useRef(null);
  const maskStageRef = useRef(null);
  const editorStageRef = useRef(null);
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
  const [screen, setScreen] = useState("home");
  const [actionPanel, setActionPanel] = useState("");
  const [reviewSessionKeys, setReviewSessionKeys] = useState([]);
  const [reviewStats, setReviewStats] = useState(() => createReviewStats());
  const [reviewStyle, setReviewStyle] = useState("hide_all");
  const [reviewZoom, setReviewZoom] = useState(1);
  const [reviewFocusMode, setReviewFocusMode] = useState(false);
  const [reviewPenActive, setReviewPenActive] = useState(true);
  const [reviewPenColorIndex, setReviewPenColorIndex] = useState(0);
  const [reviewPenWidth, setReviewPenWidth] = useState(2.6);
  const [reviewInkByKey, setReviewInkByKey] = useState({});
  const [reviewFitRequest, setReviewFitRequest] = useState(0);
  const [reviewCenterRequest, setReviewCenterRequest] = useState(0);
  const [reviewSessionSnapshot, setReviewSessionSnapshot] = useState([]);
  const [reviewDoneKeys, setReviewDoneKeys] = useState(() => new Set());
  const [reviewRevealedBoxes, setReviewRevealedBoxes] = useState(() => new Set());
  const [reviewPageState, setReviewPageState] = useState({
    pageZero: 0,
    pageCount: 0,
    hasPages: false,
  });
  const [reviewPageCommand, setReviewPageCommand] = useState(null);
  const [reviewUndoStack, setReviewUndoStack] = useState([]);
  const [reviewRedoStack, setReviewRedoStack] = useState([]);
  const [queueOpen, setQueueOpen] = useState(true);
  const [queueLocked, setQueueLocked] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [newDojoName, setNewDojoName] = useState("");
  const [newScrollTitle, setNewScrollTitle] = useState("");
  const [draftImage, setDraftImage] = useState(null);
  const [draftPdfDoc, setDraftPdfDoc] = useState(null);
  const [draftPdfPageZero, setDraftPdfPageZero] = useState(0);
  const [draftPdfBlob, setDraftPdfBlob] = useState(null);
  const [draftPdfName, setDraftPdfName] = useState("");
  const [draftMasks, setDraftMasks] = useState([]);
  const [draftMaskDrag, setDraftMaskDrag] = useState(null);
  const [editingKey, setEditingKey] = useState("");
  const [editorTitle, setEditorTitle] = useState("");
  const [editorImage, setEditorImage] = useState(null);
  const [editorMasks, setEditorMasks] = useState([]);
  const [editorMaskDrag, setEditorMaskDrag] = useState(null);
  const [editorReturnScreen, setEditorReturnScreen] = useState("home");
  const [editTitle, setEditTitle] = useState("");

  const [editorPdfDoc, setEditorPdfDoc] = useState(null);
  const [editorPdfPageZero, setEditorPdfPageZero] = useState(0);
  const [editorPdfName, setEditorPdfName] = useState("");
  const [editorPdfBlob, setEditorPdfBlob] = useState(null);
  const [editorSelectedMaskIds, setEditorSelectedMaskIds] = useState(new Set());
  const [editorAction, setEditorAction] = useState(null); // 'drawing', 'moving', 'resizing'
  const [editorDragStartClient, setEditorDragStartClient] = useState(null); // { x, y }
  const [editorActiveHandle, setEditorActiveHandle] = useState(null); // 'nw', 'ne', 'se', 'sw'
  const [editorDragMaskStartStates, setEditorDragMaskStartStates] = useState({});
  const [editorUndoStack, setEditorUndoStack] = useState([]);
  const [editorRedoStack, setEditorRedoStack] = useState([]);
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [bgmEnabled, setBgmEnabled] = useState(false);
  const [classicMode, setClassicMode] = useState(false);
  const [answerRevealed, setAnswerRevealed] = useState(false);
  const [dismissedKeys, setDismissedKeys] = useState(() => new Set());
  const [collapsedDeckIds, setCollapsedDeckIds] = useState(() => new Set());

  function toggleDeckCollapse(deckId) {
    setCollapsedDeckIds((prev) => {
      const next = new Set(prev);
      if (next.has(deckId)) {
        next.delete(deckId);
      } else {
        next.add(deckId);
      }
      return next;
    });
  }
  const [activityLog, setActivityLog] = useState([]);
  const [costSnapshot, setCostSnapshot] = useState(null);
  const [mathMode, setMathMode] = useState("tables");
  const [mathSeed, setMathSeed] = useState(1);
  const [mathAnswer, setMathAnswer] = useState("");
  const [mathResult, setMathResult] = useState("");

  const [localDb, setLocalDb] = useState(null);

  function recordAction(message) {
    setNotice(message);
    setActivityLog((current) => [
      { id: `${Date.now()}-${current.length}`, message, at: new Date().toLocaleTimeString() },
      ...current,
    ].slice(0, 8));
  }

  async function refreshDashboard(deckId = selectedDeckId, dbInstance = localDb) {
    setStatus((current) => (current === "ready" ? "refreshing" : "loading"));
    setError("");
    try {
      if (dbInstance) {
        const payload = await getLocalDashboardPayload(dbInstance, deckId);
        setData(payload);
        const nextDeckId = deckId ?? payload.decks[0]?.id ?? null;
        setSelectedDeckId(nextDeckId);
        setStatus("ready");
        return payload;
      } else {
        const payload = await loadDashboard(deckId);
        setData(payload);
        const nextDeckId = deckId ?? payload.decks[0]?.id ?? null;
        setSelectedDeckId(nextDeckId);
        setStatus("ready");
        return payload;
      }
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  useEffect(() => {
    let alive = true;
    openIndexedDbLocalFirstStore()
      .then(async (db) => {
        if (!alive) return;
        setLocalDb(db);
        
        try {
          const existingDecks = await db.list("decks");
          if (existingDecks.length === 0) {
            recordAction("IndexedDB is empty. Bootstrapping from API...");
            const apiData = await loadDashboard();
            await importDecksToIndexedDb(apiData.decks, db);
            recordAction("IndexedDB populated from backend JSON data.");
          }
        } catch (e) {
          console.error("IndexedDB bootstrap check failed", e);
        }
        
        if (alive) {
          await refreshDashboard(selectedDeckId, db);
        }
      })
      .catch((err) => {
        console.error("IndexedDB load failed, falling back to API", err);
        loadDashboard()
          .then((payload) => {
            if (!alive) return;
            setData(payload);
            setSelectedDeckId(payload.decks[0]?.id ?? null);
            setStatus("ready");
          })
          .catch((apiErr) => {
            if (!alive) return;
            setError(apiErr.message);
            setStatus("error");
          });
      });
    return () => {
      alive = false;
    };
  }, []);

  const draftCanvasRef = useRef(null);
  const editorCanvasRef = useRef(null);
  const editorDragInitialMasksRef = useRef(null);
  const lastActivityTimeRef = useRef(Date.now());

  useEffect(() => {
    if (!draftPdfDoc || !draftCanvasRef.current) return;
    let cancelled = false;
    async function renderPage() {
      try {
        const page = await draftPdfDoc.getPage(draftPdfPageZero + 1);
        const viewport = page.getViewport({ scale: 1.5 });
        const canvas = draftCanvasRef.current;
        if (!canvas || cancelled) return;
        const ctx = canvas.getContext("2d");
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = "100%";
        canvas.style.height = "auto";
        ctx.setTransform(outputScale, 0, 0, outputScale, 0, 0);
        await page.render({ canvasContext: ctx, viewport }).promise;
      } catch (err) {
        console.warn("Draft PDF page render failed", err);
      }
    }
    renderPage();
    return () => {
      cancelled = true;
    };
  }, [draftPdfDoc, draftPdfPageZero]);

  useEffect(() => {
    if (!editorPdfDoc || !editorCanvasRef.current) return;
    let cancelled = false;
    async function renderPage() {
      try {
        const page = await editorPdfDoc.getPage(editorPdfPageZero + 1);
        const viewport = page.getViewport({ scale: 1.5 });
        const canvas = editorCanvasRef.current;
        if (!canvas || cancelled) return;
        const ctx = canvas.getContext("2d");
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = "100%";
        canvas.style.height = "auto";
        ctx.setTransform(outputScale, 0, 0, outputScale, 0, 0);
        await page.render({ canvasContext: ctx, viewport }).promise;
      } catch (err) {
        console.warn("Editor PDF page render failed", err);
      }
    }
    renderPage();
    return () => {
      cancelled = true;
    };
  }, [editorPdfDoc, editorPdfPageZero]);

  useEffect(() => {
    if (screen !== "review") {
      setSessionSeconds(0);
      return;
    }

    lastActivityTimeRef.current = Date.now();

    const handleUserActivity = () => {
      lastActivityTimeRef.current = Date.now();
    };

    window.addEventListener("pointermove", handleUserActivity);
    window.addEventListener("keydown", handleUserActivity);
    window.addEventListener("pointerdown", handleUserActivity);
    window.addEventListener("wheel", handleUserActivity);

    const interval = setInterval(() => {
      if (Date.now() - lastActivityTimeRef.current <= 60000) {
        setSessionSeconds((prev) => prev + 1);
      }
    }, 1000);

    return () => {
      clearInterval(interval);
      window.removeEventListener("pointermove", handleUserActivity);
      window.removeEventListener("keydown", handleUserActivity);
      window.removeEventListener("pointerdown", handleUserActivity);
      window.removeEventListener("wheel", handleUserActivity);
    };
  }, [screen]);

  useEffect(() => {
    function handleShortcut(event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  const visibleDecks = useMemo(
    () => filterDecks(data.decks, searchQuery),
    [data.decks, searchQuery],
  );
  const allDecks = useMemo(() => flattenDecks(data.decks), [data.decks]);
  const selectedDeck =
    allDecks.find((deck) => String(deck.id) === String(selectedDeckId)) ||
    allDecks[0] ||
    null;
  const rawReviewItems = selectedDeck
    ? data.reviewItems.filter(
        (item) => String(item.deck_id) === String(selectedDeck.id),
      )
    : data.reviewItems;
  const selectedReviewItems = rawReviewItems.filter(
    (item) => !dismissedKeys.has(itemKey(item)),
  );
  const reviewItemsByKey = useMemo(
    () => new Map(selectedReviewItems.map((item) => [itemKey(item), item])),
    [selectedReviewItems],
  );
  const reviewSessionSnapshotByKey = useMemo(
    () => new Map(reviewSessionSnapshot.map((item) => [itemKey(item), item])),
    [reviewSessionSnapshot],
  );
  const reviewSessionItems = useMemo(
    () =>
      reviewSessionKeys.length
        ? reviewSessionKeys
            .map((key) => reviewItemsByKey.get(key) || reviewSessionSnapshotByKey.get(key))
            .filter(Boolean)
        : selectedReviewItems,
    [reviewItemsByKey, reviewSessionKeys, reviewSessionSnapshotByKey, selectedReviewItems],
  );
  const activeReviewCandidates =
    screen === "review" && reviewSessionKeys.length
      ? reviewSessionItems
      : selectedReviewItems;

  useEffect(() => {
    if (!activeReviewCandidates.length) {
      setActiveKey("");
      return;
    }
    if (!activeReviewCandidates.some((item) => itemKey(item) === activeKey)) {
      setActiveKey(itemKey(activeReviewCandidates[0]));
    }
  }, [activeKey, activeReviewCandidates]);

  const activeItem =
    activeReviewCandidates.find((item) => itemKey(item) === activeKey) ||
    activeReviewCandidates[0] ||
    null;
  const activeInkKey = activeItem ? itemKey(activeItem) : "";
  const activeInkStrokes = activeInkKey ? reviewInkByKey[activeInkKey] || [] : [];
  const activeReviewIndex = Math.max(
    0,
    reviewSessionItems.findIndex((item) => itemKey(item) === activeKey),
  );
  const activeReviewKey = activeItem ? itemKey(activeItem) : "";
  const activeReviewDone = activeReviewKey ? reviewDoneKeys.has(activeReviewKey) : false;
  const activeRatingPreviews = activeItem ? reviewRatingPreviews(activeItem) : {};
  const reviewPendingCount = reviewSessionKeys.length
    ? reviewSessionKeys.filter((key) => !reviewDoneKeys.has(key)).length
    : selectedReviewItems.length;
  const dueCount = selectedDeck?.due_items ?? data.summary.due_items;
  const scrollCount = selectedDeck?.total_cards ?? data.summary.card_count;
  const reviewLog = notice || error || "Ready.";

  useEffect(() => {
    setReviewRevealedBoxes(new Set());
    setReviewPageState({ pageZero: 0, pageCount: 0, hasPages: false });
    if (activeInkKey) {
      fitAndCenterReviewSurface("load");
    }
  }, [activeInkKey]);
  const draftPreviewMasks = useMemo(() => {
    if (!draftMaskDrag) return draftMasks;
    const mask = normalizeMask(draftMaskDrag.start, draftMaskDrag.end);
    return mask ? [...draftMasks, { ...mask, id: "draft-mask-preview" }] : draftMasks;
  }, [draftMaskDrag, draftMasks]);
  const editorPreviewMasks = useMemo(() => {
    if (!editorMaskDrag) return editorMasks;
    const mask = normalizeMask(editorMaskDrag.start, editorMaskDrag.end);
    return mask ? [...editorMasks, { ...mask, id: "editor-mask-preview" }] : editorMasks;
  }, [editorMaskDrag, editorMasks]);
  const mathProblem = useMemo(
    () => createMathProblem(mathMode, mathSeed),
    [mathMode, mathSeed],
  );

  function setActiveInkStrokes(strokes) {
    if (!activeInkKey) return;
    setReviewInkByKey((current) => ({ ...current, [activeInkKey]: strokes }));
  }

  function clearActiveInk() {
    if (!activeInkKey) return;
    setReviewInkByKey((current) => ({ ...current, [activeInkKey]: [] }));
    recordAction("Review pen marks cleared.");
  }

  function zoomReviewSurface(direction) {
    setReviewZoom((current) => zoomReviewScale(current, direction));
    recordAction(direction > 0 ? "Review zoomed in." : "Review zoomed out.");
  }

  function fitReviewSurface(source = "toolbar") {
    setReviewFitRequest((current) => current + 1);
    recordAction(source === "shortcut" ? "Review fit applied from keyboard." : "Review fit applied.");
  }

  function centerReviewSurface(source = "toolbar") {
    setReviewCenterRequest((current) => current + 1);
    recordAction(source === "shortcut" ? "Review centered from keyboard." : "Centered active mask.");
  }

  function fitAndCenterReviewSurface(source = "toolbar") {
    fitReviewSurface(source);
    window.setTimeout(() => centerReviewSurface(source), 0);
  }

  function sendReviewPageCommand(action) {
    setReviewPageCommand({ id: `${Date.now()}-${action}`, action });
  }

  function refitReviewAfterQueueChange() {
    window.setTimeout(() => {
      setReviewFitRequest((current) => current + 1);
      setReviewCenterRequest((current) => current + 1);
    }, 0);
  }

  function hideReviewQueue() {
    setQueueLocked(false);
    setQueueOpen(false);
    refitReviewAfterQueueChange();
    recordAction("Queue hidden.");
  }

  function showReviewQueue() {
    setQueueOpen(true);
    refitReviewAfterQueueChange();
    recordAction("Queue shown.");
  }

  function toggleReviewFocusMode(source = "toolbar") {
    setReviewFocusMode((current) => !current);
    refitReviewAfterQueueChange();
    recordAction(
      source === "shortcut" ? "Review focus toggled from keyboard." : "Review focus toggled.",
    );
  }

  function toggleReviewBoxReveal(box, index) {
    if (!activeItem) return;
    const boxes = normalizeReviewBoxes(activeItem);
    const targetGroupId = box?.group_id;
    
    const identitiesToToggle = [];
    if (targetGroupId) {
      boxes.forEach((b, idx) => {
        if (b.group_id === targetGroupId) {
          identitiesToToggle.push(boxIdentity(b, b.box_index ?? idx));
        }
      });
    } else {
      identitiesToToggle.push(boxIdentity(box, box?.box_index ?? index));
    }
    
    setReviewRevealedBoxes((current) => {
      const next = new Set(current);
      const anyRevealed = identitiesToToggle.some(id => next.has(id));
      if (anyRevealed) {
        identitiesToToggle.forEach(id => next.delete(id));
      } else {
        identitiesToToggle.forEach(id => next.add(id));
      }
      return next;
    });
  }

  async function copyCurrentPdfPath() {
    if (!activeItem?.pdf_path) {
      recordAction("No PDF path on this card.");
      return;
    }
    try {
      await navigator.clipboard.writeText(activeItem.pdf_path);
      recordAction("PDF path copied.");
    } catch {
      recordAction(activeItem.pdf_path);
    }
  }

  function openCurrentPdf() {
    if (!activeItem?.pdf_path) {
      recordAction("No PDF file on this card.");
      return;
    }
    window.open(mediaUrl(activeItem.pdf_path), "_blank", "noopener");
  }

  async function revealCurrentPdfFolder() {
    if (!activeItem?.pdf_path) {
      recordAction("No PDF file on this card.");
      return;
    }
    try {
      await revealMediaPath(activeItem.pdf_path);
      recordAction("Opened PDF folder.");
    } catch (err) {
      recordAction(`Could not open folder: ${err.message}`);
    }
  }

  function captureReviewUiState(overrides = {}) {
    return {
      activeKey,
      answerRevealed,
      reviewDoneKeys: Array.from(reviewDoneKeys),
      reviewSessionKeys: [...reviewSessionKeys],
      reviewSessionSnapshot: [...reviewSessionSnapshot],
      reviewStats,
      screen,
      ...overrides,
    };
  }

  function restoreReviewUiState(state) {
    setScreen(state?.screen || "review");
    setActiveKey(state?.activeKey || "");
    setAnswerRevealed(false);
    setReviewDoneKeys(new Set(state?.reviewDoneKeys || []));
    setReviewSessionKeys(state?.reviewSessionKeys || []);
    setReviewSessionSnapshot(state?.reviewSessionSnapshot || []);
    setReviewStats(state?.reviewStats || createReviewStats());
    setReviewRevealedBoxes(new Set());
  }

  async function handleReviewUndo() {
    if (!reviewUndoStack.length || busyQuality !== null) {
      recordAction("Nothing to undo.");
      return;
    }
    const historyEntry = reviewUndoStack[reviewUndoStack.length - 1];
    setBusyQuality(0);
    try {
      const result = await undoReviewRating();
      if (!result.updated) {
        recordAction(result.message || "Nothing to undo.");
        return;
      }
      restoreReviewUiState(historyEntry.before);
      setReviewUndoStack((current) => current.slice(0, -1));
      setReviewRedoStack((current) => [...current, historyEntry].slice(-50));
      await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
      recordAction("Undo rating.");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    } finally {
      setBusyQuality(null);
    }
  }

  async function handleReviewRedo() {
    if (!reviewRedoStack.length || busyQuality !== null) {
      recordAction("Nothing to redo.");
      return;
    }
    const historyEntry = reviewRedoStack[reviewRedoStack.length - 1];
    setBusyQuality(0);
    try {
      const result = await redoReviewRating();
      if (!result.updated) {
        recordAction(result.message || "Nothing to redo.");
        return;
      }
      restoreReviewUiState(historyEntry.after);
      setReviewRedoStack((current) => current.slice(0, -1));
      setReviewUndoStack((current) => [...current, historyEntry].slice(-50));
      await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
      recordAction("Redo rating.");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    } finally {
      setBusyQuality(null);
    }
  }

  useEffect(() => {
    function handleReviewShortcut(event) {
      const target = event.target;
      const isTyping =
        target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
      if (isTyping || screen !== "review") return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (reviewFocusMode) {
          setReviewFocusMode(false);
          refitReviewAfterQueueChange();
          recordAction("Review focus closed.");
          return;
        }
        setScreen("home");
        setAnswerRevealed(false);
        setReviewSessionKeys([]);
        setReviewSessionSnapshot([]);
        setReviewDoneKeys(new Set());
        setReviewUndoStack([]);
        setReviewRedoStack([]);
        setReviewRevealedBoxes(new Set());
        setReviewFocusMode(false);
        recordAction("Returned to dojo home.");
        return;
      }
      if (event.key === " ") {
        event.preventDefault();
        setAnswerRevealed((current) => !current);
        setReviewRevealedBoxes(new Set());
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          handleReviewRedo();
        } else {
          handleReviewUndo();
        }
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        handleReviewRedo();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
        event.preventDefault();
        zoomReviewSurface(1);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "-") {
        event.preventDefault();
        zoomReviewSurface(-1);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "0") {
        event.preventDefault();
        fitReviewSurface("shortcut");
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "e") {
        event.preventDefault();
        openCurrentPdf();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l") {
        event.preventDefault();
        revealCurrentPdfFolder();
        return;
      }
      if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "ArrowLeft") {
        event.preventDefault();
        sendReviewPageCommand("prev");
        return;
      }
      if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "ArrowRight") {
        event.preventDefault();
        sendReviewPageCommand("next");
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.key.toLowerCase() === "c"
      ) {
        event.preventDefault();
        fitAndCenterReviewSurface("shortcut");
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.key.toLowerCase() === "f"
      ) {
        event.preventDefault();
        toggleReviewFocusMode("shortcut");
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.key.toLowerCase() === "e"
      ) {
        event.preventDefault();
        openEditorMode("review");
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.key.toLowerCase() === "l"
      ) {
        event.preventDefault();
        copyCurrentPdfPath();
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.key.toLowerCase() === "t"
      ) {
        event.preventDefault();
        recordAction("Use Pen or Edit Card for web annotation.");
        return;
      }
      if (event.key === "`" || event.key.toLowerCase() === "p") {
        event.preventDefault();
        setReviewPenActive((current) => !current);
        return;
      }
      if (event.key.toLowerCase() === "x") {
        event.preventDefault();
        setReviewPenColorIndex((current) => (current + 1) % reviewPenColors.length);
        return;
      }
      if (event.key === "Delete") {
        event.preventDefault();
        clearActiveInk();
        return;
      }
      if (reviewPenActive && (event.key === "+" || event.key === "=")) {
        event.preventDefault();
        setReviewPenWidth((current) => Math.min(8, Number((current + 0.4).toFixed(1))));
        return;
      }
      if (reviewPenActive && event.key === "-") {
        event.preventDefault();
        setReviewPenWidth((current) => Math.max(1, Number((current - 0.4).toFixed(1))));
        return;
      }
      const shortcutQuality = {
        1: 1,
        2: 3,
        3: 4,
        4: 5,
        5: 6,
      }[event.key];
      if (answerRevealed && shortcutQuality && activeItem && busyQuality === null) {
        event.preventDefault();
        handleRate(shortcutQuality);
      }
    }

    window.addEventListener("keydown", handleReviewShortcut);
    return () => window.removeEventListener("keydown", handleReviewShortcut);
  }, [
    screen,
    answerRevealed,
    activeItem,
    busyQuality,
    reviewPenActive,
    reviewFocusMode,
    activeInkKey,
    reviewPageState,
    reviewUndoStack,
    reviewRedoStack,
    selectedDeck,
    selectedDeckId,
  ]);

  useEffect(() => {
    if (screen !== "editor") return;
    function handleEditorKeys(event) {
      if (document.activeElement?.tagName === "INPUT") return;
      
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "z") {
        event.preventDefault();
        handleEditorUndo();
      } else if ((event.ctrlKey || event.metaKey) && key === "y") {
        event.preventDefault();
        handleEditorRedo();
      } else if (key === "g") {
        event.preventDefault();
        if (event.shiftKey) {
          handleEditorUngroup();
        } else {
          handleEditorGroup();
        }
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        handleEditorDeleteSelected();
      } else if (key === "arrowleft") {
        if (editorPdfDoc && editorPdfPageZero > 0) {
          event.preventDefault();
          setEditorPdfPageZero((prev) => Math.max(0, prev - 1));
        }
      } else if (key === "arrowright") {
        if (editorPdfDoc && editorPdfPageZero < editorPdfDoc.numPages - 1) {
          event.preventDefault();
          setEditorPdfPageZero((prev) => Math.min(editorPdfDoc.numPages - 1, prev + 1));
        }
      }
    }
    window.addEventListener("keydown", handleEditorKeys);
    return () => window.removeEventListener("keydown", handleEditorKeys);
  }, [screen, editorMasks, editorUndoStack, editorRedoStack, editorSelectedMaskIds, editorPdfDoc, editorPdfPageZero]);

  async function handleSelectDeck(deckId) {
    setSelectedDeckId(deckId);
    setActiveKey("");
    setActionPanel("");
    setScreen("home");
    setReviewSessionKeys([]);
    setReviewSessionSnapshot([]);
    setReviewDoneKeys(new Set());
    setReviewUndoStack([]);
    setReviewRedoStack([]);
    setReviewFocusMode(false);
    setReviewStats(createReviewStats());
    setNotice("");
    if (isLocalDeckId(deckId)) {
      recordAction("Local dojo selected.");
      return;
    }
    try {
      await refreshDashboard(deckId);
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  async function handleRefresh() {
    if (isLocalDeckId(selectedDeck?.id ?? selectedDeckId)) {
      recordAction("Local dojo kept in this browser session.");
      return;
    }
    try {
      await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
      recordAction("Dashboard refreshed from the local API.");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  async function handleRate(quality) {
    if (!activeItem || busyQuality !== null) return;
    const ratedTitle = activeItem.card_title;
    const key = itemKey(activeItem);
    const sessionKeys = reviewSessionKeys.length
      ? reviewSessionKeys
      : selectedReviewItems.map(itemKey);
    const currentIndex = Math.max(0, sessionKeys.indexOf(key));
    const nextDoneKeys = new Set([...reviewDoneKeys, key]);
    const nextActiveKey =
      sessionKeys.slice(currentIndex + 1).find((sessionKey) => !nextDoneKeys.has(sessionKey)) ||
      sessionKeys.find((sessionKey) => !nextDoneKeys.has(sessionKey)) ||
      "";
    const beforeRatingState = captureReviewUiState();
    const nextReviewStats = updateReviewStats(reviewStats, quality);
    const afterRatingState = captureReviewUiState({
      activeKey: nextActiveKey || key,
      answerRevealed: false,
      reviewDoneKeys: Array.from(nextDoneKeys),
      reviewStats: nextReviewStats,
      screen: !nextActiveKey && screen === "review" ? "review-summary" : screen,
    });
    if (localDb) {
      setBusyQuality(quality);
      setNotice("");
      try {
        const result = await saveLocalRating(localDb, {
          card_id: activeItem.card_id,
          deck_id: activeItem.deck_id,
          box_id: activeItem.box_id,
          box_index: activeItem.box_index,
          group_id: activeItem.group_id,
          quality,
        });
        if (!result.updated) {
          recordAction("No matching review target was found in local DB.");
        } else {
          recordAction(`${ratedTitle} rated ${quality} locally.`);
          setReviewDoneKeys(nextDoneKeys);
          setReviewStats(nextReviewStats);
          setReviewUndoStack((current) =>
            [...current, { before: beforeRatingState, after: afterRatingState }].slice(-50),
          );
          setReviewRedoStack([]);
          if (!nextActiveKey && screen === "review") {
            setScreen("review-summary");
          } else if (nextActiveKey) {
            setActiveKey(nextActiveKey);
          }
        }
        setAnswerRevealed(false);
        setReviewRevealedBoxes(new Set());
        await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
      } catch (err) {
        setError(err.message);
        setStatus("error");
      } finally {
        setBusyQuality(null);
      }
      return;
    }
    if (isLocalReviewItem(activeItem)) {
      setDismissedKeys((current) => new Set([...current, key]));
      setReviewDoneKeys(nextDoneKeys);
      setReviewStats(nextReviewStats);
      setData((current) => ({
        ...current,
        summary: {
          ...current.summary,
          due_items: Math.max(0, current.summary.due_items - 1),
          review_items: current.summary.review_items + 1,
        },
        decks: updateDeckById(current.decks, activeItem.deck_id, (deck) => ({
          ...deck,
          due_items: Math.max(0, (deck.due_items || 0) - 1),
          review_items: (deck.review_items || 0) + 1,
        })),
        reviewItems: current.reviewItems.filter((item) => itemKey(item) !== key),
      }));
      setAnswerRevealed(false);
      setReviewRevealedBoxes(new Set());
      if (!nextActiveKey && screen === "review") {
        setScreen("review-summary");
      } else if (nextActiveKey) {
        setActiveKey(nextActiveKey);
      }
      recordAction(`${ratedTitle} rated ${quality} locally.`);
      return;
    }
    setBusyQuality(quality);
    setNotice("");
    try {
      const result = await rateReviewItem(activeItem, quality);
      if (!result.updated) {
        recordAction("No matching review target was found.");
      } else {
        recordAction(`${ratedTitle} rated ${quality}.`);
        setReviewDoneKeys(nextDoneKeys);
        setReviewStats(nextReviewStats);
        setReviewUndoStack((current) =>
          [...current, { before: beforeRatingState, after: afterRatingState }].slice(-50),
        );
        setReviewRedoStack([]);
        if (!nextActiveKey && screen === "review") {
          setScreen("review-summary");
        } else if (nextActiveKey) {
          setActiveKey(nextActiveKey);
        }
      }
      setAnswerRevealed(false);
      setReviewRevealedBoxes(new Set());
      await refreshDashboard(selectedDeck?.id ?? selectedDeckId);
    } catch (err) {
      setError(err.message);
      setStatus("error");
    } finally {
      setBusyQuality(null);
    }
  }

  function openReviewScreen(mode = "due") {
    const queue =
      mode === "selected" && activeItem ? [activeItem] : selectedReviewItems;
    if (!queue.length) {
      recordAction("No due scrolls in this dojo.");
      return;
    }
    const queueKeys = queue.map(itemKey);
    setReviewSessionKeys(queueKeys);
    setReviewSessionSnapshot(queue);
    setReviewDoneKeys(new Set());
    setReviewUndoStack([]);
    setReviewRedoStack([]);
    setReviewStats(createReviewStats(queue.length));
    setActiveKey(queueKeys[0]);
    setScreen("review");
    setAnswerRevealed(false);
    setReviewRevealedBoxes(new Set());
    setReviewZoom(1);
    setReviewFitRequest((current) => current + 1);
    setReviewCenterRequest((current) => current + 1);
    setReviewPenActive(true);
    setReviewFocusMode(false);
    setReviewPageState({ pageZero: 0, pageCount: 0, hasPages: false });
    setReviewPageCommand(null);
    setQueueOpen(true);
    setActionPanel("");
    recordAction(
      mode === "selected" ? "Selected scroll review opened." : "Due review opened.",
    );
  }

  function openActionPanel(panel) {
    setScreen("home");
    setActionPanel(panel);
    if (panel === "new-dojo" || panel === "sub-dojo") setNewDojoName("");
    if (panel === "forge-scroll") {
      setNewScrollTitle("");
      setDraftImage(null);
      setDraftPdfDoc(null);
      setDraftPdfPageZero(0);
      setDraftPdfBlob(null);
      setDraftPdfName("");
      setDraftMasks([]);
      setDraftMaskDrag(null);

      setEditingKey("");
      setEditorTitle("");
      setEditorImage(null);
      setEditorPdfDoc(null);
      setEditorPdfBlob(null);
      setEditorPdfName("");
      setEditorPdfPageZero(0);
      setEditorSelectedMaskIds(new Set());
      setEditorUndoStack([]);
      setEditorRedoStack([]);
      setEditorMasks([]);
      setEditorMaskDrag(null);
      setEditorReturnScreen("home");
      setActionPanel("");
      setScreen("editor");
      recordAction("Editor mode opened for forging new scroll.");
    }
    if (panel === "edit-scroll") setEditTitle(activeItem?.card_title || "");
  }

  function maskPointFromEvent(event, stageRef = maskStageRef) {
    const stage = stageRef.current;
    if (!stage) return null;
    const rect = stage.getBoundingClientRect();
    return {
      x: clampPercent(((event.clientX - rect.left) / rect.width) * 100),
      y: clampPercent(((event.clientY - rect.top) / rect.height) * 100),
    };
  }

  function handleImageFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.type === "application/pdf") {
      setDraftImage(null);
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const arrayBuffer = reader.result;
          const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
          const doc = await loadingTask.promise;
          setDraftPdfDoc(doc);
          setDraftPdfPageZero(0);
          setDraftPdfBlob(file);
          setDraftPdfName(file.name);
          setDraftMasks([]);
          setDraftMaskDrag(null);
          recordAction(`${file.name} (PDF, ${doc.numPages} pages) loaded.`);
        } catch (e) {
          recordAction(`Failed to load PDF: ${e.message}`);
        }
      };
      reader.readAsArrayBuffer(file);
    } else if (file.type.startsWith("image/")) {
      setDraftPdfDoc(null);
      setDraftPdfBlob(null);
      const reader = new FileReader();
      reader.onload = () => {
        setDraftImage({
          name: file.name,
          src: String(reader.result || ""),
          blob: file,
        });
        setDraftMasks([]);
        setDraftMaskDrag(null);
        recordAction(`${file.name} loaded locally.`);
      };
      reader.readAsDataURL(file);
    } else {
      recordAction("Unsupported file type. Choose an image or PDF.");
    }
  }

  function handleUseDemoImage() {
    setDraftImage({
      name: "browser-demo-image.svg",
      src: createDemoImage(),
    });
    setDraftMasks([
      {
        id: createMaskId(),
        x: 13,
        y: 19,
        width: 33,
        height: 14,
      },
    ]);
    setDraftMaskDrag(null);
    recordAction("Demo image loaded locally.");
  }

  function handleMaskPointerDown(event) {
    if (!draftImage && !draftPdfDoc) return;
    const point = maskPointFromEvent(event);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDraftMaskDrag({ start: point, end: point });
  }

  function handleMaskPointerMove(event) {
    if (!draftMaskDrag) return;
    const point = maskPointFromEvent(event);
    if (!point) return;
    setDraftMaskDrag((current) => (current ? { ...current, end: point } : current));
  }

  function handleMaskPointerUp(event) {
    if (!draftMaskDrag) return;
    const point = maskPointFromEvent(event);
    const mask = point ? normalizeMask(draftMaskDrag.start, point) : null;
    if (mask) {
      const finalMask = {
        ...mask,
        page_num: draftPdfDoc ? draftPdfPageZero : 0,
      };
      setDraftMasks((current) => [...current, finalMask]);
      recordAction("Mask added locally.");
    }
    setDraftMaskDrag(null);
  }

  function handleAddCenterMask() {
    if (!draftImage && !draftPdfDoc) return;
    setDraftMasks((current) => [
      ...current,
      {
        id: createMaskId(),
        x: 33,
        y: 34,
        width: 34,
        height: 18,
        page_num: draftPdfDoc ? draftPdfPageZero : 0,
      },
    ]);
    recordAction("Mask added locally.");
  }

  function handleRemoveDraftMask(maskId) {
    setDraftMasks((current) => current.filter((mask) => mask.id !== maskId));
    recordAction("Mask removed locally.");
  }

  function openEditorMode(returnScreen = "home") {
    if (!activeItem) {
      recordAction("No scroll selected.");
      return;
    }
    setEditingKey(itemKey(activeItem));
    setEditorTitle(activeItem.card_title || "");
    
    // Clear editor states
    setEditorImage(null);
    setEditorPdfDoc(null);
    setEditorPdfName("");
    setEditorPdfPageZero(0);
    setEditorSelectedMaskIds(new Set());
    setEditorUndoStack([]);
    setEditorRedoStack([]);

    if (activeItem.image_data_url || activeItem.image_path) {
      if (activeItem.image_data_url) {
        setEditorImage({
          name: activeItem.image_path || "browser-local-image",
          src: activeItem.image_data_url,
        });
      } else if (localDb && activeItem.image_path) {
        localDb.get("files", activeItem.image_path).then((fileRecord) => {
          if (fileRecord && fileRecord.blob) {
            const src = URL.createObjectURL(fileRecord.blob);
            setEditorImage({
              name: activeItem.image_path,
              src: src,
            });
          }
        }).catch(e => console.warn(e));
      }
    }

    if (activeItem.pdf_path) {
      setEditorPdfName(activeItem.pdf_path);
      setEditorPdfPageZero(activeItem.page_num || 0);
      
      let pdfSource = mediaUrl(activeItem.pdf_path);
      if (localDb) {
        localDb.get("files", activeItem.pdf_path).then((fileRecord) => {
          if (fileRecord && fileRecord.blob) {
            pdfSource = URL.createObjectURL(fileRecord.blob);
          }
          pdfjsLib.getDocument(pdfSource).promise.then((doc) => {
            setEditorPdfDoc(doc);
          }).catch(err => recordAction(`Failed to load PDF in editor: ${err.message}`));
        }).catch(e => {
          console.warn(e);
          pdfjsLib.getDocument(pdfSource).promise.then((doc) => {
            setEditorPdfDoc(doc);
          }).catch(err => recordAction(`Failed to load PDF in editor: ${err.message}`));
        });
      } else {
        pdfjsLib.getDocument(pdfSource).promise.then((doc) => {
          setEditorPdfDoc(doc);
        }).catch(err => recordAction(`Failed to load PDF in editor: ${err.message}`));
      }
    }

    setEditorMasks(activeItem.local_masks || []);
    setEditorMaskDrag(null);
    setEditorReturnScreen(returnScreen);
    setActionPanel("");
    setScreen("editor");
    recordAction("Editor mode opened.");
  }

  function updateEditorMasksWithHistory(newMasks) {
    setEditorUndoStack((prev) => [...prev, editorMasks]);
    setEditorRedoStack([]);
    setEditorMasks(newMasks);
  }

  function handleEditorUndo() {
    if (editorUndoStack.length === 0) return;
    const prev = editorUndoStack[editorUndoStack.length - 1];
    setEditorUndoStack((stack) => stack.slice(0, -1));
    setEditorRedoStack((stack) => [...stack, editorMasks]);
    setEditorMasks(prev);
    recordAction("Editor action undone.");
  }

  function handleEditorRedo() {
    if (editorRedoStack.length === 0) return;
    const next = editorRedoStack[editorRedoStack.length - 1];
    setEditorRedoStack((stack) => stack.slice(0, -1));
    setEditorUndoStack((stack) => [...stack, editorMasks]);
    setEditorMasks(next);
    recordAction("Editor action redone.");
  }

  function handleEditorGroup() {
    if (editorSelectedMaskIds.size < 2) {
      recordAction("Select at least 2 masks to group.");
      return;
    }
    const groupId = `group-${Date.now()}`;
    const newMasks = editorMasks.map((mask) => {
      if (editorSelectedMaskIds.has(mask.id)) {
        return { ...mask, group_id: groupId };
      }
      return mask;
    });
    updateEditorMasksWithHistory(newMasks);
    recordAction(`Grouped ${editorSelectedMaskIds.size} masks.`);
  }

  function handleEditorUngroup() {
    const groupsToClear = new Set();
    editorMasks.forEach((mask) => {
      if (editorSelectedMaskIds.has(mask.id) && mask.group_id) {
        groupsToClear.add(mask.group_id);
      }
    });
    if (groupsToClear.size === 0) {
      recordAction("No grouped masks selected.");
      return;
    }
    const newMasks = editorMasks.map((mask) => {
      if (mask.group_id && groupsToClear.has(mask.group_id)) {
        return { ...mask, group_id: null };
      }
      return mask;
    });
    updateEditorMasksWithHistory(newMasks);
    recordAction("Ungrouped selected masks.");
  }

  function handleEditorDeleteSelected() {
    if (editorSelectedMaskIds.size === 0) return;
    const newMasks = editorMasks.filter((mask) => !editorSelectedMaskIds.has(mask.id));
    updateEditorMasksWithHistory(newMasks);
    setEditorSelectedMaskIds(new Set());
    recordAction(`Deleted ${editorSelectedMaskIds.size} masks.`);
  }

  function handleEditorUseDemoImage() {
    setEditorImage({
      name: "browser-demo-image.svg",
      src: createDemoImage(),
    });
    setEditorPdfDoc(null);
    setEditorPdfBlob(null);
    setEditorPdfName("");
    setEditorPdfPageZero(0);
    setEditorMasks([
      {
        id: createMaskId(),
        x: 13,
        y: 19,
        width: 33,
        height: 14,
      },
    ]);
    setEditorMaskDrag(null);
    setEditorSelectedMaskIds(new Set());
    recordAction("Demo image loaded in editor.");
  }

  function handleEditorFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.type === "application/pdf") {
      setEditorImage(null);
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const arrayBuffer = reader.result;
          const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
          const doc = await loadingTask.promise;
          setEditorPdfDoc(doc);
          setEditorPdfPageZero(0);
          setEditorPdfBlob(file);
          setEditorPdfName(file.name);
          updateEditorMasksWithHistory([]);
          setEditorSelectedMaskIds(new Set());
          recordAction(`${file.name} (PDF, ${doc.numPages} pages) loaded in editor.`);
        } catch (e) {
          recordAction(`Failed to load PDF in editor: ${e.message}`);
        }
      };
      reader.readAsArrayBuffer(file);
    } else if (file.type.startsWith("image/")) {
      setEditorPdfDoc(null);
      setEditorPdfBlob(null);
      const reader = new FileReader();
      reader.onload = () => {
        setEditorImage({
          name: file.name,
          src: String(reader.result || ""),
          blob: file,
        });
        updateEditorMasksWithHistory([]);
        setEditorSelectedMaskIds(new Set());
        recordAction(`${file.name} loaded in editor.`);
      };
      reader.readAsDataURL(file);
    } else {
      recordAction("Unsupported file type. Choose an image or PDF.");
    }
  }

  function handleEditorPointerDown(event) {
    if (!editorImage && !editorPdfDoc) return;
    
    // Check if clicked a resize handle
    const handleEl = event.target.closest(".resize-handle");
    if (handleEl) {
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      
      const handleType = handleEl.dataset.handle; // 'nw', 'ne', 'se', 'sw'
      const maskId = handleEl.dataset.maskId;
      const mask = editorMasks.find(m => m.id === maskId);
      if (mask) {
        setEditorAction("resizing");
        setEditorActiveHandle(handleType);
        setEditorDragStartClient({ x: event.clientX, y: event.clientY });
        setEditorDragMaskStartStates({ [maskId]: { ...mask } });
        editorDragInitialMasksRef.current = editorMasks;
      }
      return;
    }
    
    // Check if clicked a mask
    const maskEl = event.target.closest(".mask-box");
    if (maskEl) {
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      
      const maskId = maskEl.dataset.maskId;
      
      // Update selection on click
      let nextSelected = new Set(editorSelectedMaskIds);
      if (event.shiftKey || event.ctrlKey) {
        if (nextSelected.has(maskId)) {
          nextSelected.delete(maskId);
        } else {
          nextSelected.add(maskId);
        }
      } else {
        if (!nextSelected.has(maskId)) {
          nextSelected.clear();
          nextSelected.add(maskId);
        }
      }
      setEditorSelectedMaskIds(nextSelected);
      
      // Start moving selected masks
      setEditorAction("moving");
      setEditorDragStartClient({ x: event.clientX, y: event.clientY });
      const starts = {};
      editorMasks.forEach(m => {
        if (nextSelected.has(m.id)) {
          starts[m.id] = { ...m };
        }
      });
      setEditorDragMaskStartStates(starts);
      editorDragInitialMasksRef.current = editorMasks;
      return;
    }
    
    // Clicked background
    if (event.target.classList.contains("mask-stage") || event.target.tagName === "IMG" || event.target.tagName === "CANVAS") {
      // Clear selection if not shifting
      if (!event.shiftKey && !event.ctrlKey) {
        setEditorSelectedMaskIds(new Set());
      }
      
      // Start drawing
      const point = maskPointFromEvent(event, editorStageRef);
      if (!point) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      setEditorAction("drawing");
      setEditorMaskDrag({ start: point, end: point });
    }
  }

  function handleEditorPointerMove(event) {
    if (!editorAction) return;
    
    if (editorAction === "drawing" && editorMaskDrag) {
      const point = maskPointFromEvent(event, editorStageRef);
      if (!point) return;
      setEditorMaskDrag((current) => (current ? { ...current, end: point } : current));
    } else if (editorAction === "moving" && editorDragStartClient) {
      const stage = editorStageRef.current;
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      const dxPercent = ((event.clientX - editorDragStartClient.x) / rect.width) * 100;
      const dyPercent = ((event.clientY - editorDragStartClient.y) / rect.height) * 100;
      
      const newMasks = editorMasks.map((mask) => {
        const startState = editorDragMaskStartStates[mask.id];
        if (startState) {
          return {
            ...mask,
            x: clampPercent(startState.x + dxPercent),
            y: clampPercent(startState.y + dyPercent),
          };
        }
        return mask;
      });
      setEditorMasks(newMasks);
    } else if (editorAction === "resizing" && editorDragStartClient && editorActiveHandle) {
      const stage = editorStageRef.current;
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      const dxPercent = ((event.clientX - editorDragStartClient.x) / rect.width) * 100;
      const dyPercent = ((event.clientY - editorDragStartClient.y) / rect.height) * 100;
      
      const targetId = Object.keys(editorDragMaskStartStates)[0];
      const startState = editorDragMaskStartStates[targetId];
      if (startState) {
        const newMasks = editorMasks.map((mask) => {
          if (mask.id === targetId) {
            let { x, y, width, height } = startState;
            if (editorActiveHandle === "se") {
              width = Math.max(1, width + dxPercent);
              height = Math.max(1, height + dyPercent);
            } else if (editorActiveHandle === "sw") {
              const newX = x + dxPercent;
              width = Math.max(1, width - dxPercent);
              x = clampPercent(newX);
              height = Math.max(1, height + dyPercent);
            } else if (editorActiveHandle === "ne") {
              const newY = y + dyPercent;
              height = Math.max(1, height - dyPercent);
              y = clampPercent(newY);
              width = Math.max(1, width + dxPercent);
            } else if (editorActiveHandle === "nw") {
              const newX = x + dxPercent;
              const newY = y + dyPercent;
              width = Math.max(1, width - dxPercent);
              height = Math.max(1, height - dyPercent);
              x = clampPercent(newX);
              y = clampPercent(newY);
            }
            return { ...mask, x, y, width, height };
          }
          return mask;
        });
        setEditorMasks(newMasks);
      }
    }
  }

  function handleEditorPointerUp(event) {
    if (!editorAction) return;
    
    if (editorAction === "drawing" && editorMaskDrag) {
      const point = maskPointFromEvent(event, editorStageRef);
      const mask = point ? normalizeMask(editorMaskDrag.start, point) : null;
      if (mask) {
        // Set page_num for the new mask if PDF
        const finalMask = {
          ...mask,
          page_num: editorPdfDoc ? editorPdfPageZero : 0,
        };
        updateEditorMasksWithHistory([...editorMasks, finalMask]);
        recordAction("Editor mask added locally.");
      }
      setEditorMaskDrag(null);
    } else if (editorAction === "moving" || editorAction === "resizing") {
      // If masks changed, push initial states to history
      if (editorDragInitialMasksRef.current && JSON.stringify(editorDragInitialMasksRef.current) !== JSON.stringify(editorMasks)) {
        setEditorUndoStack((prev) => [...prev, editorDragInitialMasksRef.current]);
        setEditorRedoStack([]);
      }
      setEditorDragMaskStartStates({});
      setEditorDragStartClient(null);
      setEditorActiveHandle(null);
      editorDragInitialMasksRef.current = null;
    }
    
    setEditorAction(null);
  }

  function handleEditorAddCenterMask() {
    if (!editorImage && !editorPdfDoc) return;
    const newMask = {
      id: createMaskId(),
      x: 33,
      y: 34,
      width: 34,
      height: 18,
      page_num: editorPdfDoc ? editorPdfPageZero : 0,
    };
    updateEditorMasksWithHistory([...editorMasks, newMask]);
    recordAction("Editor mask added locally.");
  }

  function handleSaveEditor(event) {
    event.preventDefault();
    if (!selectedDeck) {
      recordAction("Choose a dojo before saving.");
      return;
    }
    const title = editorTitle.trim() || "Untitled Scroll";
    if (!editingKey) {
      if (!editorImage && !editorPdfDoc) {
        recordAction("Load an image or PDF first.");
        return;
      }
      const cardId = `local-card-${Date.now()}`;
      const cardRecord = {
        id: cardId,
        deck_id: selectedDeck.id,
        title: title,
        pdf_path: editorPdfDoc ? editorPdfName : null,
        image_path: editorImage?.name || null,
        image_data_url: editorImage?.src || null,
        label: "browser-local",
      };
      
      if (localDb) {
        localDb.put("cards", cardRecord).then(async () => {
          await localDb.queueChange({
            collection: "cards",
            item_id: cardId,
            payload: cardRecord,
          });

          if (editorPdfDoc && editorPdfBlob) {
            await localDb.put("files", {
              id: editorPdfName,
              blob: editorPdfBlob,
            });
          } else if (editorImage && editorImage.blob) {
            await localDb.put("files", {
              id: editorImage.name,
              blob: editorImage.blob,
            });
          }

          for (let idx = 0; idx < editorMasks.length; idx++) {
            const mask = editorMasks[idx];
            const maskRecord = {
              id: mask.id,
              card_id: cardId,
              box_index: idx,
              rect: [mask.x, mask.y, mask.width, mask.height],
              shape: mask.shape || "rect",
              angle: mask.angle || 0,
              group_id: mask.group_id || null,
              page_num: editorPdfDoc ? editorPdfPageZero : 0,
              label: mask.label || "",
            };
            await localDb.put("masks", maskRecord);
            await localDb.queueChange({
              collection: "masks",
              item_id: maskRecord.id,
              payload: maskRecord,
            });

            const stateRecord = {
              id: mask.id,
              card_id: cardId,
              box_id: mask.id,
              sched_state: "new",
              sched_step: 0,
              sm2_interval: 1,
              sm2_ease: 2.5,
              sm2_due: new Date().toISOString(),
              sm2_repetitions: 0,
              reviews: 0,
            };
            await localDb.put("review_state", stateRecord);
            await localDb.queueChange({
              collection: "review_state",
              item_id: stateRecord.id,
              payload: stateRecord,
            });
          }

          setActiveKey(`${selectedDeck.id}:${cardId}:0`);
          setScreen(editorReturnScreen === "review" ? "review" : "home");
          setActionPanel("");
          setEditorImage(null);
          setEditorPdfDoc(null);
          setEditorPdfBlob(null);
          setEditorPdfName("");
          setEditorMasks([]);
          setEditorMaskDrag(null);
          recordAction(`${title} forged in editor.`);
          await refreshDashboard(selectedDeck.id);
        }).catch(err => {
          recordAction(`Failed to forge scroll: ${err.message}`);
        });
      }
      return;
    }
    const previousItem =
      data.reviewItems.find((item) => itemKey(item) === editingKey) || activeItem;
    if (!previousItem) return;
    if (localDb) {
      const cardId = previousItem.card_id;
      const cardRecord = {
        id: cardId,
        deck_id: previousItem.deck_id,
        title: title,
        image_path: editorImage?.name || previousItem.image_path || null,
        image_data_url: editorImage?.src || previousItem.image_data_url || null,
        pdf_path: previousItem.pdf_path || null,
        pdf_box_render_zoom: previousItem.pdf_box_render_zoom || 1.5,
        label: previousItem.label || "browser-local",
      };
      localDb.put("cards", cardRecord).then(async () => {
        await localDb.queueChange({
          collection: "cards",
          item_id: cardId,
          payload: cardRecord,
        });
        const allMasks = await localDb.list("masks");
        const cardMasks = allMasks.filter(m => m.card_id === cardId);
        for (const mask of cardMasks) {
          await localDb.delete("masks", mask.id);
          await localDb.queueChange({
            collection: "masks",
            item_id: mask.id,
            deleted: true,
            payload: {},
          });
        }
        for (let idx = 0; idx < editorMasks.length; idx++) {
          const mask = editorMasks[idx];
          const maskRecord = {
            id: mask.id,
            card_id: cardId,
            box_index: idx,
            rect: [mask.x, mask.y, mask.width, mask.height],
            shape: mask.shape || "rect",
            angle: mask.angle || 0,
            group_id: mask.group_id || null,
            page_num: mask.page_num !== undefined ? mask.page_num : (editorPdfDoc ? editorPdfPageZero : 0),
            label: mask.label || "",
          };
          await localDb.put("masks", maskRecord);
          await localDb.queueChange({
            collection: "masks",
            item_id: maskRecord.id,
            payload: maskRecord,
          });
          const existingState = await localDb.get("review_state", mask.id);
          if (!existingState) {
            const stateRecord = {
              id: mask.id,
              card_id: cardId,
              box_id: mask.id,
              sched_state: "new",
              sched_step: 0,
              sm2_interval: 1,
              sm2_ease: 2.5,
              sm2_due: new Date().toISOString(),
              sm2_repetitions: 0,
              reviews: 0,
            };
            await localDb.put("review_state", stateRecord);
            await localDb.queueChange({
              collection: "review_state",
              item_id: stateRecord.id,
              payload: stateRecord,
            });
          }
        }
        setScreen(editorReturnScreen === "review" ? "review" : "home");
        setActionPanel("");
        recordAction(`${title} saved in editor.`);
        await refreshDashboard(previousItem.deck_id);
      }).catch(err => {
        recordAction(`Failed to save editor changes: ${err.message}`);
      });
      return;
    }
    const oldMaskCount = previousItem?.local_masks?.length || 0;
    const newMaskCount = editorMasks.length;
    const maskDelta = newMaskCount - oldMaskCount;
    setData((current) => ({
      ...current,
      summary: {
        ...current.summary,
        occlusion_count: Math.max(0, current.summary.occlusion_count + maskDelta),
      },
      decks: updateDeckById(current.decks, previousItem?.deck_id, (deck) => ({
        ...deck,
        occlusion_count: Math.max(0, (deck.occlusion_count || 0) + maskDelta),
      })),
      reviewItems: current.reviewItems.map((item) =>
        itemKey(item) === editingKey
          ? {
              ...item,
              card_title: title,
              image_path: editorImage?.name || item.image_path || null,
              image_data_url: editorImage?.src || item.image_data_url || null,
              local_masks: editorMasks,
            }
          : item,
      ),
    }));
    setScreen(editorReturnScreen === "review" ? "review" : "home");
    setActionPanel("");
    recordAction(`${title} saved locally in editor.`);
  }

  function handleCheckMathAnswer(event) {
    event.preventDefault();
    const answer = Number(mathAnswer.trim());
    if (Number.isFinite(answer) && answer === mathProblem.answer) {
      setMathResult("Correct.");
      recordAction("Math answer correct.");
      return;
    }
    setMathResult(`Answer: ${mathProblem.answer}`);
    recordAction("Math answer checked.");
  }

  function handleNextMathProblem() {
    setMathSeed((current) => current + 1);
    setMathAnswer("");
    setMathResult("");
    recordAction("Next math problem loaded.");
  }

  function handleCreateDojo(event) {
    event.preventDefault();
    const name = newDojoName.trim() || (actionPanel === "sub-dojo" ? "New Sub Dojo" : "New Dojo");
    const newDeck = createLocalDeck(name);
    
    if (localDb) {
      const deckRecord = {
        id: newDeck.id,
        name: name,
        parent_id: actionPanel === "sub-dojo" ? selectedDeck?.id : null,
      };
      localDb.put("decks", deckRecord).then(async () => {
        await localDb.queueChange({
          collection: "decks",
          item_id: deckRecord.id,
          payload: deckRecord,
        });
        setSelectedDeckId(newDeck.id);
        setActionPanel("");
        recordAction(`${name} created locally.`);
        await refreshDashboard(newDeck.id);
      }).catch(err => {
        recordAction(`Failed to create dojo: ${err.message}`);
      });
      return;
    }

    setData((current) => ({
      ...current,
      summary: { ...current.summary, deck_count: current.summary.deck_count + 1 },
      decks: addDeckToTree(
        current.decks,
        actionPanel === "sub-dojo" ? selectedDeck?.id : null,
        newDeck,
      ),
    }));
    setSelectedDeckId(newDeck.id);
    setActionPanel("");
    recordAction(`${name} created in this browser session.`);
  }

  function handleCreateScroll(event) {
    event.preventDefault();
    if (!selectedDeck) {
      recordAction("Choose a dojo before forging a scroll.");
      return;
    }
    const title = newScrollTitle.trim() || "Untitled Scroll";
    const cardId = `local-card-${Date.now()}`;
    const newItem = {
      deck_id: selectedDeck.id,
      deck_name: selectedDeck.name,
      card_id: cardId,
      card_title: title,
      box_id: null,
      box_index: null,
      label: "browser-local",
      sched_state: "new",
      page_num: draftPdfDoc ? draftPdfPageZero : null,
      rect: null,
      shape: null,
      angle: 0,
      group_id: null,
      pdf_path: draftPdfDoc ? draftPdfName : null,
      image_path: draftImage?.name || null,
      image_data_url: draftImage?.src || null,
      local_masks: draftMasks,
    };

    if (localDb) {
      const cardRecord = {
        id: cardId,
        deck_id: selectedDeck.id,
        title: title,
        pdf_path: draftPdfDoc ? draftPdfName : null,
        image_path: draftImage?.name || null,
        image_data_url: draftImage?.src || null,
        label: "browser-local",
      };
      
      localDb.put("cards", cardRecord).then(async () => {
        await localDb.queueChange({
          collection: "cards",
          item_id: cardId,
          payload: cardRecord,
        });

        if (draftPdfDoc && draftPdfBlob) {
          await localDb.put("files", {
            id: draftPdfName,
            blob: draftPdfBlob,
          });
        } else if (draftImage && draftImage.blob) {
          await localDb.put("files", {
            id: draftImage.name,
            blob: draftImage.blob,
          });
        }

        for (let idx = 0; idx < draftMasks.length; idx++) {
          const mask = draftMasks[idx];
          const maskRecord = {
            id: mask.id,
            card_id: cardId,
            box_index: idx,
            rect: [mask.x, mask.y, mask.width, mask.height],
            shape: mask.shape || "rect",
            angle: mask.angle || 0,
            group_id: mask.group_id || null,
            page_num: draftPdfDoc ? draftPdfPageZero : 0,
            label: mask.label || "",
          };
          await localDb.put("masks", maskRecord);
          await localDb.queueChange({
            collection: "masks",
            item_id: maskRecord.id,
            payload: maskRecord,
          });

          const stateRecord = {
            id: mask.id,
            card_id: cardId,
            box_id: mask.id,
            sched_state: "new",
            sched_step: 0,
            sm2_interval: 1,
            sm2_ease: 2.5,
            sm2_due: new Date().toISOString(),
            sm2_repetitions: 0,
            reviews: 0,
          };
          await localDb.put("review_state", stateRecord);
          await localDb.queueChange({
            collection: "review_state",
            item_id: stateRecord.id,
            payload: stateRecord,
          });
        }

        setActiveKey(`${selectedDeck.id}:${cardId}:0`);
        setActionPanel("");
        setDraftImage(null);
        setDraftPdfDoc(null);
        setDraftPdfBlob(null);
        setDraftPdfName("");
        setDraftMasks([]);
        setDraftMaskDrag(null);
        recordAction(`${title} forged locally.`);
        await refreshDashboard(selectedDeck.id);
      }).catch(err => {
        recordAction(`Failed to forge scroll: ${err.message}`);
      });
      return;
    }

    const localMaskCount = draftMasks.length;
    setData((current) => ({
      ...current,
      summary: {
        ...current.summary,
        card_count: current.summary.card_count + 1,
        occlusion_count: current.summary.occlusion_count + localMaskCount,
        due_items: current.summary.due_items + 1,
      },
      decks: updateDeckById(current.decks, selectedDeck.id, (deck) => ({
        ...deck,
        direct_cards: (deck.direct_cards || 0) + 1,
        total_cards: (deck.total_cards || 0) + 1,
        occlusion_count: (deck.occlusion_count || 0) + localMaskCount,
        due_items: (deck.due_items || 0) + 1,
      })),
      reviewItems: [newItem, ...current.reviewItems],
    }));
    setActiveKey(itemKey(newItem));
    setActionPanel("");
    setDraftImage(null);
    setDraftMasks([]);
    setDraftMaskDrag(null);
    recordAction(`${title} forged locally.`);
  }

  function handleSaveEdit(event) {
    event.preventDefault();
    if (!activeItem) return;
    const title = editTitle.trim() || activeItem.card_title;
    const cardId = activeItem.card_id;
    
    if (localDb) {
      localDb.get("cards", cardId).then((cardRecord) => {
        if (!cardRecord) return;
        const updatedRecord = { ...cardRecord, title };
        localDb.put("cards", updatedRecord).then(async () => {
          await localDb.queueChange({
            collection: "cards",
            item_id: cardId,
            payload: updatedRecord,
          });
          setActionPanel("");
          recordAction(`${title} updated locally.`);
          await refreshDashboard(selectedDeckId);
        });
      }).catch(err => {
        recordAction(`Failed to save edit: ${err.message}`);
      });
      return;
    }

    const key = itemKey(activeItem);
    setData((current) => ({
      ...current,
      reviewItems: current.reviewItems.map((item) =>
        itemKey(item) === key ? { ...item, card_title: title } : item,
      ),
    }));
    setActionPanel("");
    recordAction(`${title} updated locally.`);
  }

  function handleDeleteSelected() {
    if (!activeItem) {
      recordAction("No scroll selected.");
      return;
    }
    const key = itemKey(activeItem);
    const title = activeItem.card_title;
    const cardId = activeItem.card_id;
    
    if (localDb) {
      localDb.delete("cards", cardId).then(async () => {
        await localDb.queueChange({
          collection: "cards",
          item_id: cardId,
          deleted: true,
          payload: {},
        });
        
        const allMasks = await localDb.list("masks");
        const cardMasks = allMasks.filter(m => m.card_id === cardId);
        for (const mask of cardMasks) {
          await localDb.delete("masks", mask.id);
          await localDb.queueChange({
            collection: "masks",
            item_id: mask.id,
            deleted: true,
            payload: {},
          });
          
          await localDb.delete("review_state", mask.id);
          await localDb.queueChange({
            collection: "review_state",
            item_id: mask.id,
            deleted: true,
            payload: {},
          });
        }
        
        setDismissedKeys((current) => new Set([...current, key]));
        setAnswerRevealed(false);
        setActionPanel("");
        recordAction(`${title} deleted locally.`);
        await refreshDashboard(selectedDeckId);
      }).catch(err => {
        recordAction(`Failed to delete scroll: ${err.message}`);
      });
      return;
    }

    const removesLocalCard = activeItem.label === "browser-local";
    const removedMaskCount = removesLocalCard ? activeItem.local_masks?.length || 0 : 0;
    setDismissedKeys((current) => new Set([...current, key]));
    setAnswerRevealed(false);
    setData((current) => ({
      ...current,
      summary: {
        ...current.summary,
        card_count: removesLocalCard
          ? Math.max(0, current.summary.card_count - 1)
          : current.summary.card_count,
        occlusion_count: Math.max(0, current.summary.occlusion_count - removedMaskCount),
        due_items: Math.max(0, current.summary.due_items - 1),
      },
      decks: updateDeckById(current.decks, activeItem.deck_id, (deck) => ({
        ...deck,
        direct_cards: removesLocalCard
          ? Math.max(0, (deck.direct_cards || 0) - 1)
          : deck.direct_cards,
        total_cards: removesLocalCard
          ? Math.max(0, (deck.total_cards || 0) - 1)
          : deck.total_cards,
        occlusion_count: Math.max(
          0,
          (deck.occlusion_count || 0) - removedMaskCount,
        ),
        due_items: Math.max(0, (deck.due_items || 0) - 1),
      })),
      reviewItems: current.reviewItems.filter((item) => itemKey(item) !== key),
    }));
    setActionPanel("");
    recordAction(`${title} hidden from this browser session.`);
  }

  function handleDeleteDojo() {
    if (!selectedDeck) {
      recordAction("No dojo selected.");
      return;
    }
    const deckId = selectedDeck.id;
    const deletedDeck = selectedDeck;
    const deletedIds = new Set(collectDeckIds(deletedDeck).map(String));
    
    if (localDb) {
      localDb.delete("decks", deckId).then(async () => {
        await localDb.queueChange({
          collection: "decks",
          item_id: deckId,
          deleted: true,
          payload: {},
        });
        
        const allCards = await localDb.list("cards");
        for (const card of allCards) {
          if (deletedIds.has(String(card.deck_id))) {
            await localDb.delete("cards", card.id);
            await localDb.queueChange({
              collection: "cards",
              item_id: card.id,
              deleted: true,
              payload: {},
            });
            const allMasks = await localDb.list("masks");
            const cardMasks = allMasks.filter(m => m.card_id === card.id);
            for (const mask of cardMasks) {
              await localDb.delete("masks", mask.id);
              await localDb.queueChange({
                collection: "masks",
                item_id: mask.id,
                deleted: true,
                payload: {},
              });
              await localDb.delete("review_state", mask.id);
              await localDb.queueChange({
                collection: "review_state",
                item_id: mask.id,
                deleted: true,
                payload: {},
              });
            }
          }
        }
        
        setSelectedDeckId(null);
        setActiveKey("");
        setActionPanel("");
        setScreen("home");
        recordAction(`${deletedDeck.name} deleted locally.`);
        await refreshDashboard();
      }).catch(err => {
        recordAction(`Failed to delete dojo: ${err.message}`);
      });
      return;
    }

    const stats = deckSubtreeStats(deletedDeck);
    const nextDecks = removeDeckFromTree(data.decks, deletedDeck.id);
    const nextDeck = flattenDecks(nextDecks)[0] || null;
    setData((current) => ({
      ...current,
      summary: {
        ...current.summary,
        deck_count: Math.max(0, current.summary.deck_count - stats.deck_count),
        card_count: Math.max(0, current.summary.card_count - stats.card_count),
        occlusion_count: Math.max(
          0,
          current.summary.occlusion_count - stats.occlusion_count,
        ),
        due_items: Math.max(0, current.summary.due_items - stats.due_items),
        review_items: Math.max(0, current.summary.review_items - stats.review_items),
      },
      decks: nextDecks,
      reviewItems: current.reviewItems.filter(
        (item) => !deletedIds.has(String(item.deck_id)),
      ),
    }));
    setSelectedDeckId(nextDeck?.id ?? null);
    setActiveKey("");
    setActionPanel("");
    setScreen("home");
    setAnswerRevealed(false);
    setReviewSessionKeys([]);
    setReviewSessionSnapshot([]);
    setReviewDoneKeys(new Set());
    setReviewUndoStack([]);
    setReviewRedoStack([]);
    setReviewRevealedBoxes(new Set());
    recordAction(`${deletedDeck.name} removed from this browser session.`);
  }

  function handleMathNav() {
    setScreen("math");
    setActionPanel("");
    setReviewSessionKeys([]);
    setReviewSessionSnapshot([]);
    setReviewDoneKeys(new Set());
    setReviewUndoStack([]);
    setReviewRedoStack([]);
    setMathAnswer("");
    setMathResult("");
    recordAction("Math trainer opened.");
  }

  function handleJournalNav() {
    setScreen("journal");
    setActionPanel("");
    recordAction("Journal opened.");
  }

  function handleClassicToggle() {
    const next = !classicMode;
    setClassicMode(next);
    setScreen("home");
    setActionPanel("");
    recordAction(`Classic mode ${next ? "enabled" : "disabled"}.`);
  }

  async function handleMoreNav() {
    setScreen("more");
    setActionPanel("");
    recordAction("System panel opened.");
    try {
      const snapshot = await loadCostSnapshot();
      setCostSnapshot(snapshot);
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  function handleSettingsNav() {
    setScreen("settings");
    setActionPanel("");
    recordAction("Settings opened.");
  }

  function handleBgmToggle() {
    const next = !bgmEnabled;
    setBgmEnabled(next);
    recordAction(`BGM ${next ? "enabled" : "disabled"} for this browser session.`);
  }

  function renderActionPanel() {
    if (actionPanel === "new-dojo" || actionPanel === "sub-dojo") {
      return (
        <section className="action-panel">
          <div>
            <h3>{actionPanel === "sub-dojo" ? "Create Sub Dojo" : "Create Dojo"}</h3>
            <p>
              {actionPanel === "sub-dojo"
                ? `Parent: ${deckDisplayName(selectedDeck)}`
                : "Create a browser-local dojo for planning."}
            </p>
          </div>
          <form className="inline-form" onSubmit={handleCreateDojo}>
            <input
              autoFocus
              onChange={(event) => setNewDojoName(event.target.value)}
              placeholder="Dojo name"
              value={newDojoName}
            />
            <button className="secondary-button" type="submit">
              Create
            </button>
            <button
              className="ghost-button"
              onClick={() => setActionPanel("")}
              type="button"
            >
              Cancel
            </button>
          </form>
        </section>
      );
    }

    if (actionPanel === "forge-scroll") {
      return (
        <section className="action-panel forge-panel">
          <div>
            <h3>Forge Scroll</h3>
            <p>{selectedDeck ? `Target dojo: ${selectedDeck.name}` : "Choose a dojo first."}</p>
          </div>
          <form className="forge-form" onSubmit={handleCreateScroll}>
            <div className="forge-fields">
              <input
                autoFocus
                onChange={(event) => setNewScrollTitle(event.target.value)}
                placeholder="Scroll title"
                value={newScrollTitle}
              />
              <label className="file-button">
                Image
                <input
                  accept="image/*"
                  onChange={handleImageFileChange}
                  type="file"
                />
              </label>
              <label className="file-button">
                PDF
                <input
                  accept="application/pdf"
                  onChange={handleImageFileChange}
                  type="file"
                />
              </label>
              <button className="ghost-button" onClick={handleUseDemoImage} type="button">
                Demo
              </button>
              {draftPdfDoc && (
                <div className="forge-pdf-nav" style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', padding: '6px 0' }}>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={draftPdfPageZero <= 0}
                    onClick={() => setDraftPdfPageZero((prev) => Math.max(0, prev - 1))}
                  >
                    Prev Page
                  </button>
                  <span style={{ fontSize: '12px', color: 'var(--muted)', fontWeight: 'bold' }}>
                    Page {draftPdfPageZero + 1} of {draftPdfDoc.numPages}
                  </span>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={draftPdfPageZero >= draftPdfDoc.numPages - 1}
                    onClick={() => setDraftPdfPageZero((prev) => Math.min(draftPdfDoc.numPages - 1, prev + 1))}
                  >
                    Next Page
                  </button>
                </div>
              )}
              <button
                className="ghost-button"
                disabled={!draftImage && !draftPdfDoc}
                onClick={handleAddCenterMask}
                type="button"
              >
                Mask
              </button>
              <button
                className="ghost-button"
                disabled={!draftMasks.length}
                onClick={() => {
                  setDraftMasks([]);
                  recordAction("Masks cleared locally.");
                }}
                type="button"
              >
                Clear
              </button>
              <button className="secondary-button" disabled={!selectedDeck} type="submit">
                Forge
              </button>
              <button
                className="ghost-button"
                onClick={() => setActionPanel("")}
                type="button"
              >
                Cancel
              </button>
            </div>
            <div className="mask-editor">
              {(draftImage || draftPdfDoc) ? (
                <>
                  <div
                    className="mask-stage"
                    onPointerDown={handleMaskPointerDown}
                    onPointerMove={handleMaskPointerMove}
                    onPointerUp={handleMaskPointerUp}
                    ref={maskStageRef}
                  >
                    {draftImage ? (
                      <img alt="" draggable="false" src={draftImage.src} />
                    ) : (
                      <canvas ref={draftCanvasRef} style={{ width: '100%', height: 'auto', display: 'block' }} />
                    )}
                    {draftPreviewMasks.map((mask) => (
                      <span
                        className={
                          mask.id === "draft-mask-preview"
                            ? "draft-mask mask-box"
                            : "mask-box"
                        }
                        key={mask.id}
                        style={maskStyle(mask)}
                      />
                    ))}
                  </div>
                  <div className="mask-strip">
                    <strong>{draftImage ? draftImage.name : draftPdfName}</strong>
                    <span>{draftMasks.length} masks</span>
                    {draftMasks.map((mask, index) => (
                      <button
                        aria-label={`Remove mask ${index + 1}`}
                        key={mask.id}
                        onClick={() => handleRemoveDraftMask(mask.id)}
                        type="button"
                      >
                        {index + 1}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <div className="mask-empty">Upload an image or PDF to start forging scrolls</div>
              )}
            </div>
          </form>
        </section>
      );
    }

    if (actionPanel === "edit-scroll") {
      return (
        <section className="action-panel">
          <div>
            <h3>Edit Scroll</h3>
            <p>{activeItem ? itemTargetLabel(activeItem) : "No selected scroll."}</p>
          </div>
          <form className="inline-form" onSubmit={handleSaveEdit}>
            <input
              autoFocus
              disabled={!activeItem}
              onChange={(event) => setEditTitle(event.target.value)}
              placeholder="Scroll title"
              value={editTitle}
            />
            <button className="secondary-button" disabled={!activeItem} type="submit">
              Save
            </button>
            <button
              className="ghost-button"
              onClick={() => setActionPanel("")}
              type="button"
            >
              Cancel
            </button>
          </form>
        </section>
      );
    }

    return null;
  }

  function renderModePanel() {
    if (screen === "review") {
      const reviewTotal = reviewStats.total || reviewSessionItems.length;
      const reviewPosition = reviewTotal ? activeReviewIndex + 1 : 0;
      const reviewProgress = reviewTotal
        ? Math.round((reviewStats.done / reviewTotal) * 100)
        : 0;
      const queueVisible = !reviewFocusMode && (queueLocked || queueOpen);
      return (
        <section
          className={`mode-panel review-mode desktop-review-mode ${
            reviewFocusMode ? "review-focus-mode" : ""
          }`}
        >
          <div className="review-toolbar">
            <div className="review-progress-block">
              <strong>
                Card {reviewPosition || 0}/{reviewTotal || 0}
              </strong>
              <span>{activeItem?.sched_state || "review"}</span>
              <div className="review-progress-track">
                <i style={{ width: `${reviewProgress}%` }} />
              </div>
            </div>
            <button
              className="review-tool"
              onClick={() => zoomReviewSurface(1)}
              type="button"
            >
              +
            </button>
            <button
              className="review-tool"
              onClick={() => zoomReviewSurface(-1)}
              type="button"
            >
              -
            </button>
            <button className="review-tool" onClick={() => fitReviewSurface()} type="button">
              Fit
            </button>
            <button
              className="review-tool"
              onClick={() => centerReviewSurface()}
              type="button"
            >
              Center
            </button>
            <button
              className={`review-tool ${reviewFocusMode ? "active-toggle" : ""}`}
              onClick={() => toggleReviewFocusMode()}
              type="button"
            >
              Focus
            </button>
            <button
              className="review-tool"
              disabled={!reviewUndoStack.length || busyQuality !== null}
              onClick={handleReviewUndo}
              type="button"
            >
              Undo
            </button>
            <button
              className="review-tool"
              disabled={!reviewRedoStack.length || busyQuality !== null}
              onClick={handleReviewRedo}
              type="button"
            >
              Redo
            </button>
            <button
              className="review-tool"
              disabled={!reviewPageState.hasPages || reviewPageState.pageZero <= 0}
              onClick={() => sendReviewPageCommand("prev")}
              type="button"
            >
              Prev
            </button>
            <button
              className="review-tool"
              disabled={
                !reviewPageState.hasPages ||
                reviewPageState.pageZero >= reviewPageState.pageCount - 1
              }
              onClick={() => sendReviewPageCommand("next")}
              type="button"
            >
              Next
            </button>
            <span className="review-page-chip">
              {reviewPageState.hasPages
                ? `${reviewPageState.pageZero + 1}/${reviewPageState.pageCount}`
                : "-"}
            </span>
            <button
              className="review-tool primary"
              disabled={!activeItem}
              onClick={() => openEditorMode("review")}
              type="button"
            >
              Edit Card
            </button>
            <button
              className="review-tool"
              onClick={() => recordAction("Use Pen or Edit Card for web annotation.")}
              type="button"
            >
              Annotate
            </button>
            <button
              className="review-tool"
              onClick={() => recordAction("Browser cache is local-first.")}
              type="button"
            >
              Cache
            </button>
            <button
              className="review-tool"
              disabled={!activeItem?.pdf_path}
              onClick={revealCurrentPdfFolder}
              type="button"
            >
              Folder
            </button>
            <button
              className="review-tool mode-toggle"
              onClick={() =>
                setReviewStyle((current) =>
                  current === "hide_all" ? "hide_one" : "hide_all",
                )
              }
              type="button"
            >
              {reviewStyle === "hide_all" ? "Hide All" : "Hide One"}
            </button>
            <button
              className={`review-tool ${reviewPenActive ? "active-toggle" : ""}`}
              onClick={() => setReviewPenActive((current) => !current)}
              type="button"
            >
              Pen
            </button>
            <button
              className="review-tool"
              onClick={() =>
                setReviewPenColorIndex((current) => (current + 1) % reviewPenColors.length)
              }
              style={{ color: reviewPenColors[reviewPenColorIndex] }}
              type="button"
            >
              Color
            </button>
            <button
              className="review-tool"
              onClick={() =>
                setReviewPenWidth((current) =>
                  current >= 8 ? 2.6 : Number((current + 0.4).toFixed(1)),
                )
              }
              type="button"
            >
              {reviewPenWidth.toFixed(1)}
            </button>
            <button className="review-tool" onClick={clearActiveInk} type="button">
              Clear Pen
            </button>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                setAnswerRevealed(false);
                setReviewSessionKeys([]);
                setReviewSessionSnapshot([]);
                setReviewDoneKeys(new Set());
                setReviewUndoStack([]);
                setReviewRedoStack([]);
                setReviewRevealedBoxes(new Set());
                setReviewFocusMode(false);
                recordAction("Returned to dojo home.");
              }}
              type="button"
            >
              Exit
            </button>
          </div>

          <div className={`review-workbench ${queueVisible ? "" : "queue-hidden"}`}>
            {queueVisible ? (
              <aside className="review-queue-panel open">
                <div className="review-queue-head">
                  <strong>Queue ({reviewPendingCount})</strong>
                  <button onClick={() => setQueueLocked((current) => !current)} type="button">
                    {queueLocked ? "Lock" : "Free"}
                  </button>
                  <button onClick={hideReviewQueue} type="button">
                    Hide
                  </button>
                </div>
                <div className="review-queue-list">
                  {reviewSessionItems.map((item, index) => {
                    const key = itemKey(item);
                    const rowState = reviewDoneKeys.has(key)
                      ? "done"
                      : key === activeKey
                        ? "current"
                        : item.sched_state === "learning" || item.sched_state === "relearn"
                          ? "relearn"
                          : "pending";
                    return (
                      <button
                        className={rowState}
                        key={key}
                        onClick={() => {
                          if (reviewDoneKeys.has(key)) return;
                          setActiveKey(key);
                          setAnswerRevealed(false);
                          setReviewRevealedBoxes(new Set());
                          recordAction(`Queue item ${index + 1} opened.`);
                        }}
                        type="button"
                      >
                        <span>{index + 1}</span>
                        {reviewQueueLabel(item)}
                      </button>
                    );
                  })}
                </div>
              </aside>
            ) : null}

            <div className="review-study-panel">
              <div className="mode-heading">
                <div>
                  <h3>{activeItem?.card_title || "No Due Scroll"}</h3>
                </div>
                {!queueVisible ? (
                  <button className="review-queue-restore" onClick={showReviewQueue} type="button">
                    Show Queue
                  </button>
                ) : null}
              </div>
              <div className={`review-preview ${answerRevealed ? "revealed" : ""}`}>
                <div className="review-timer-overlay">
                  <span className="timer-icon">⏱</span>
                  <span className="timer-text">{formatTimer(sessionSeconds)}</span>
                </div>
                <ReviewDocumentSurface
                  centerRequest={reviewCenterRequest}
                  fitRequest={reviewFitRequest}
                  inkStrokes={activeInkStrokes}
                  item={activeItem}
                  onCenterComplete={() => {}}
                  onFitScale={setReviewZoom}
                  onInkChange={setActiveInkStrokes}
                  onPageStateChange={setReviewPageState}
                  onReveal={() => setAnswerRevealed(true)}
                  onToggleBoxReveal={toggleReviewBoxReveal}
                  pageCommand={reviewPageCommand}
                  penActive={reviewPenActive}
                  penColor={reviewPenColors[reviewPenColorIndex]}
                  penWidth={reviewPenWidth}
                  ratingOverlay={
                    <ReviewQualityButtons
                      activeItem={activeReviewDone ? null : activeItem}
                      busyQuality={busyQuality}
                      onRate={handleRate}
                      previews={activeRatingPreviews}
                    />
                  }
                  revealed={answerRevealed}
                  revealedBoxes={reviewRevealedBoxes}
                  reviewStyle={reviewStyle}
                  zoom={reviewZoom}
                />
                {reviewFocusMode ? (
                  <button
                    className="review-focus-exit"
                    onClick={() => toggleReviewFocusMode()}
                    type="button"
                  >
                    Exit Focus
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        </section>
      );
    }

    if (screen === "review-summary") {
      const retention = reviewRetention(reviewStats);
      return (
        <section className="mode-panel review-summary-panel">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">Mission Complete</span>
              <h3>{retention}% Retention</h3>
              <p>{reviewStats.done} scrolls reviewed this session.</p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                setReviewSessionKeys([]);
                setReviewSessionSnapshot([]);
                setReviewDoneKeys(new Set());
                setReviewUndoStack([]);
                setReviewRedoStack([]);
                setReviewRevealedBoxes(new Set());
                setReviewFocusMode(false);
                setAnswerRevealed(false);
                recordAction("Mission summary closed.");
              }}
              type="button"
            >
              Close
            </button>
          </div>
          <div className="summary-grid">
            {ratings.map((rating) => (
              <div className={`summary-pill ${rating.tone}`} key={rating.quality}>
                <span>{rating.label}</span>
                <strong>{reviewStats.ratings?.[rating.quality] || 0}</strong>
              </div>
            ))}
          </div>
        </section>
      );
    }

    if (screen === "math") {
      return (
        <section className="mode-panel math-panel">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">Math Trainer</span>
              <h3>{mathProblem.label}</h3>
              <p>Practice mode</p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                recordAction("Math trainer closed.");
              }}
              type="button"
            >
              Back
            </button>
          </div>
          <div className="math-mode-row">
            {["tables", "squares", "cubes"].map((mode) => (
              <button
                className={mathMode === mode ? "active-toggle" : ""}
                key={mode}
                onClick={() => {
                  setMathMode(mode);
                  setMathAnswer("");
                  setMathResult("");
                  recordAction(`${mode} practice opened.`);
                }}
                type="button"
              >
                {mode}
              </button>
            ))}
          </div>
          <form className="math-card" onSubmit={handleCheckMathAnswer}>
            <strong>{mathProblem.prompt}</strong>
            <input
              onChange={(event) => setMathAnswer(event.target.value)}
              placeholder="Answer"
              type="number"
              value={mathAnswer}
            />
            <button className="secondary-button" type="submit">
              Check
            </button>
            <button className="ghost-button" onClick={handleNextMathProblem} type="button">
              Next
            </button>
            <span>{mathResult || "Ready."}</span>
          </form>
        </section>
      );
    }

    if (screen === "editor") {
      return (
        <section className="mode-panel editor-mode">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">{editingKey ? "Editor Mode" : "Forge New Scroll"}</span>
              <h3>{editorTitle || (editingKey ? "Untitled Scroll" : "New Dojo Scroll")}</h3>
              <p>{editorMasks.length} masks</p>
            </div>
            <div className="mode-heading-actions" style={{ display: 'flex', gap: '8px' }}>
              <button className="secondary-button" onClick={handleSaveEditor} type="button">
                {editingKey ? "Save Changes" : "Forge Scroll"}
              </button>
              <button
                className="ghost-button"
                onClick={() => {
                  setScreen(editorReturnScreen === "review" ? "review" : "home");
                  recordAction("Editor closed.");
                }}
                type="button"
              >
                Cancel
              </button>
            </div>
          </div>

          <div className="editor-workspace" style={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr)', gap: '16px', marginTop: '12px' }}>
            {/* Left Sidebar: Controls & Metadata */}
            <div className="editor-sidebar" style={{ display: 'flex', flexDirection: 'column', gap: '16px', background: 'var(--panel-2)', padding: '12px', borderRadius: '4px', border: '1px solid var(--border)' }}>
              <div className="sidebar-section">
                <h4 style={{ color: 'var(--neon)', margin: '0 0 8px 0', textTransform: 'uppercase', fontSize: '12px', letterSpacing: '1px' }}>Card Info</h4>
                <div className="field-group" style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 'bold' }}>Title</label>
                  <input
                    onChange={(event) => setEditorTitle(event.target.value)}
                    placeholder="Scroll title..."
                    value={editorTitle}
                    style={{
                      border: '1px solid var(--border)',
                      borderRadius: '4px',
                      background: 'var(--panel-3)',
                      color: 'var(--text)',
                      padding: '8px',
                      outline: '0',
                    }}
                  />
                </div>
              </div>

              {!editingKey && (
                <div className="sidebar-section">
                  <h4 style={{ color: 'var(--neon)', margin: '0 0 8px 0', textTransform: 'uppercase', fontSize: '12px', letterSpacing: '1px' }}>Load Source File</h4>
                  <div className="file-buttons-group" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <label className="file-button" style={{
                      display: 'block',
                      background: 'var(--panel-3)',
                      border: '1px solid var(--border)',
                      borderRadius: '4px',
                      color: 'var(--text)',
                      padding: '8px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: 'bold'
                    }}>
                      🖼 Image
                      <input
                        accept="image/*"
                        onChange={handleEditorFileChange}
                        type="file"
                        style={{ display: 'none' }}
                      />
                    </label>
                    <label className="file-button" style={{
                      display: 'block',
                      background: 'var(--panel-3)',
                      border: '1px solid var(--border)',
                      borderRadius: '4px',
                      color: 'var(--text)',
                      padding: '8px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: 'bold'
                    }}>
                      📄 PDF
                      <input
                        accept="application/pdf"
                        onChange={handleEditorFileChange}
                        type="file"
                        style={{ display: 'none' }}
                      />
                    </label>
                    <button className="ghost-button" onClick={handleEditorUseDemoImage} type="button" style={{ width: '100%' }}>
                      Demo Image
                    </button>
                  </div>
                </div>
              )}

              <div className="sidebar-section" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: '200px' }}>
                <h4 style={{ color: 'var(--neon)', margin: '0 0 8px 0', textTransform: 'uppercase', fontSize: '12px', letterSpacing: '1px' }}>Mask Inventory ({editorMasks.length})</h4>
                <div className="editor-mask-list" style={{
                  flex: 1,
                  overflowY: 'auto',
                  border: '1px solid var(--border)',
                  background: 'var(--panel-3)',
                  borderRadius: '4px',
                  padding: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px'
                }}>
                  {editorMasks.length === 0 ? (
                    <div className="empty-placeholder" style={{ color: 'var(--muted)', fontSize: '11px', textAlign: 'center', padding: '12px 4px' }}>
                      No masks drawn yet. Use crosshair on canvas to draw.
                    </div>
                  ) : (
                    editorMasks.map((mask, index) => {
                      const isSelected = editorSelectedMaskIds.has(mask.id);
                      return (
                        <div
                          key={mask.id}
                          className={`editor-mask-item ${isSelected ? "selected" : ""}`}
                          onClick={() => {
                            const next = new Set();
                            next.add(mask.id);
                            setEditorSelectedMaskIds(next);
                          }}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '6px 8px',
                            background: isSelected ? 'rgba(167, 125, 255, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                            border: isSelected ? '1px solid var(--purple)' : '1px solid transparent',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '11px',
                          }}
                        >
                          <span className="mask-number" style={{ fontWeight: 'bold', color: isSelected ? 'var(--purple)' : 'var(--text)' }}>
                            Mask #{index + 1}
                          </span>
                          {mask.group_id && (
                            <span className="mask-group-tag" style={{
                              background: 'rgba(167, 125, 255, 0.2)',
                              color: 'var(--purple)',
                              fontSize: '9px',
                              padding: '1px 4px',
                              borderRadius: '2px',
                              fontWeight: 'bold'
                            }}>
                              G: {getMaskGroupLabel(mask, editorMasks)}
                            </span>
                          )}
                          <button
                            className="mask-delete-btn"
                            title="Remove mask"
                            onClick={(e) => {
                              e.stopPropagation();
                              const newMasks = editorMasks.filter((item) => item.id !== mask.id);
                              updateEditorMasksWithHistory(newMasks);
                              const nextSelected = new Set(editorSelectedMaskIds);
                              nextSelected.delete(mask.id);
                              setEditorSelectedMaskIds(nextSelected);
                            }}
                            type="button"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--muted)',
                              cursor: 'pointer',
                              padding: '2px 6px',
                              fontSize: '11px',
                            }}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>

            {/* Right Main Area: Canvas & Toolbar */}
            <div className="editor-canvas-container" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div className="editor-canvas-toolbar" style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--panel-2)',
                padding: '8px 12px',
                borderRadius: '4px',
                border: '1px solid var(--border)'
              }}>
                <div className="toolbar-left" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    className="toolbar-btn"
                    disabled={!editorUndoStack.length}
                    onClick={handleEditorUndo}
                    title="Undo (Ctrl+Z)"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    ↩ Undo
                  </button>
                  <button
                    className="toolbar-btn"
                    disabled={!editorRedoStack.length}
                    onClick={handleEditorRedo}
                    title="Redo (Ctrl+Y)"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    ↪ Redo
                  </button>
                  <span style={{ width: '1px', height: '16px', background: 'var(--border)', margin: '0 4px' }} />
                  <button
                    className="toolbar-btn"
                    disabled={editorSelectedMaskIds.size < 2}
                    onClick={handleEditorGroup}
                    title="Group selected masks (G)"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    ⛓ Group
                  </button>
                  <button
                    className="toolbar-btn"
                    disabled={editorSelectedMaskIds.size === 0}
                    onClick={handleEditorUngroup}
                    title="Ungroup selected masks (Shift+G)"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    ⛓ Ungroup
                  </button>
                  <button
                    className="toolbar-btn danger"
                    disabled={editorSelectedMaskIds.size === 0}
                    onClick={handleEditorDeleteSelected}
                    title="Delete selected masks (Del)"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--red)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    🗑 Delete
                  </button>
                  <button
                    className="toolbar-btn"
                    disabled={!editorMasks.length}
                    onClick={() => {
                      updateEditorMasksWithHistory([]);
                      recordAction("Editor masks cleared locally.");
                    }}
                    title="Clear all masks"
                    type="button"
                    style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontWeight: 'bold' }}
                  >
                    ✕ Clear All
                  </button>
                </div>
              </div>

              {editorPdfDoc && (
                <div className="editor-pdf-nav" style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '12px',
                  background: 'var(--panel-2)',
                  padding: '8px',
                  borderRadius: '4px',
                  border: '1px solid var(--border)'
                }}>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={editorPdfPageZero <= 0}
                    onClick={() => setEditorPdfPageZero((prev) => Math.max(0, prev - 1))}
                  >
                    ← Previous Page
                  </button>
                  <span className="pdf-page-indicator" style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--text)' }}>
                    Page {editorPdfPageZero + 1} of {editorPdfDoc.numPages}
                  </span>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={editorPdfPageZero >= editorPdfDoc.numPages - 1}
                    onClick={() => setEditorPdfPageZero((prev) => Math.min(editorPdfDoc.numPages - 1, prev + 1))}
                  >
                    Next Page →
                  </button>
                </div>
              )}

              <div className="mask-editor editor-mask-editor-viewport" style={{ flex: 1, minHeight: '480px', display: 'grid', gridTemplateRows: '1fr', padding: '0', border: '1px solid var(--border)', borderRadius: '4px', background: 'var(--panel-3)' }}>
                {(editorImage || editorPdfDoc) ? (
                  <div
                    className="mask-stage"
                    onPointerDown={handleEditorPointerDown}
                    onPointerMove={handleEditorPointerMove}
                    onPointerUp={handleEditorPointerUp}
                    ref={editorStageRef}
                    style={{ border: 'none', borderRadius: '0' }}
                  >
                    {editorImage ? (
                      <img alt="" draggable="false" src={editorImage.src} style={{ maxHeight: '600px', margin: '0 auto' }} />
                    ) : (
                      <canvas ref={editorCanvasRef} style={{ maxWidth: '100%', maxHeight: '600px', display: 'block', margin: '0 auto' }} />
                    )}
                    {editorPreviewMasks.map((mask) => {
                      const isSelected = editorSelectedMaskIds.has(mask.id);
                      return (
                        <span
                          className={
                            mask.id === "editor-mask-preview"
                              ? "draft-mask mask-box"
                              : `mask-box ${isSelected ? "selected" : ""}`
                          }
                          key={mask.id}
                          style={maskStyle(mask)}
                          data-mask-id={mask.id}
                        >
                          {mask.group_id && (
                            <span className="mask-group-badge" style={{
                              position: "absolute",
                              top: "2px",
                              left: "2px",
                              background: "rgba(167, 125, 255, 0.9)",
                              color: "white",
                              fontSize: "8px",
                              padding: "1px 3px",
                              borderRadius: "2px",
                              pointerEvents: "none",
                              lineHeight: "1",
                              fontWeight: "bold",
                            }}>
                              {getMaskGroupLabel(mask, editorMasks)}
                            </span>
                          )}
                          {isSelected && mask.id !== "editor-mask-preview" && (
                            <>
                              <span className="resize-handle nw" data-handle="nw" data-mask-id={mask.id} />
                              <span className="resize-handle ne" data-handle="ne" data-mask-id={mask.id} />
                              <span className="resize-handle se" data-handle="se" data-mask-id={mask.id} />
                              <span className="resize-handle sw" data-handle="sw" data-mask-id={mask.id} />
                            </>
                          )}
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <div className="mask-empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', gap: '8px' }}>
                    <p style={{ margin: 0, fontSize: '13px' }}>No scroll loaded.</p>
                    <p style={{ margin: 0, fontSize: '11px' }}>Please choose an Image or PDF from the sidebar.</p>
                  </div>
                )}
              </div>

              <div className="editor-status-bar" style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--muted)', padding: '4px' }}>
                <span>V = Select | Drag to draw masks | Drag borders/handles to move or resize</span>
                <span>G = Group | Shift+G = Ungroup | Del = Delete | Arrow Keys = PDF Pages</span>
              </div>
            </div>
          </div>
        </section>
      );
    }

    if (screen === "journal") {
      return (
        <section className="mode-panel">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">Journal</span>
              <h3>Session Log</h3>
              <p>Recent browser-side actions for this local run.</p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                recordAction("Journal closed.");
              }}
              type="button"
            >
              Back
            </button>
          </div>
          <div className="journal-list">
            {activityLog.length ? (
              activityLog.map((entry) => (
                <div className="journal-row" key={entry.id}>
                  <span>{entry.at}</span>
                  <strong>{entry.message}</strong>
                </div>
              ))
            ) : (
              <div className="stage-empty">- NO JOURNAL ENTRIES YET -</div>
            )}
          </div>
        </section>
      );
    }

    if (screen === "settings") {
      return (
        <section className="mode-panel">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">Settings</span>
              <h3>Browser Preferences</h3>
              <p>Prototype settings stay local to this browser session.</p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                recordAction("Settings closed.");
              }}
              type="button"
            >
              Back
            </button>
          </div>
          <div className="settings-grid">
            <button className="toggle-row" onClick={handleBgmToggle} type="button">
              <span>BGM</span>
              <strong>{bgmEnabled ? "ON" : "OFF"}</strong>
            </button>
            <button className="toggle-row" onClick={handleClassicToggle} type="button">
              <span>Classic Mode</span>
              <strong>{classicMode ? "ON" : "OFF"}</strong>
            </button>
            <button className="toggle-row" onClick={handleRefresh} type="button">
              <span>Local API</span>
              <strong>{status === "error" ? "OFFLINE" : "SYNC"}</strong>
            </button>
          </div>
        </section>
      );
    }

    if (screen === "more") {
      return (
        <section className="mode-panel">
          <div className="mode-heading">
            <div>
              <span className="mode-kicker">System</span>
              <h3>Cost And Sync</h3>
              <p>API {API_BASE}</p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setScreen("home");
                recordAction("System panel closed.");
              }}
              type="button"
            >
              Back
            </button>
          </div>
          <div className="system-grid">
            <div>
              <span>API Calls</span>
              <strong>{costSnapshot?.request_count ?? 0}</strong>
            </div>
            <div>
              <span>DB Reads</span>
              <strong>{costSnapshot?.db_reads ?? 0}</strong>
            </div>
            <div>
              <span>DB Writes</span>
              <strong>{costSnapshot?.db_writes ?? 0}</strong>
            </div>
            <button
              onClick={async () => {
                if (localDb) {
                  recordAction("Syncing changes with server...");
                  try {
                    const res = await flushQueuedChanges(localDb);
                    recordAction(`Synced successfully! Sent ${res.sent} changes.`);
                    loadCostSnapshot().then(setCostSnapshot).catch(() => {});
                    await refreshDashboard();
                  } catch (err) {
                    recordAction(`Sync failed: ${err.message}`);
                  }
                }
              }}
              type="button"
              style={{ background: "rgba(106, 88, 224, 0.1)", border: "1px dashed #6A58E0", borderRadius: "8px", cursor: "pointer", display: "flex", flexDirection: "column", padding: "12px", alignItems: "center", justifyContent: "center" }}
            >
              <span>Sync Changes</span>
              <strong>{costSnapshot?.sync_changes ?? 0}</strong>
            </button>
          </div>
        </section>
      );
    }

    return null;
  }

  const isReviewScreen = screen === "review";
  const isEditorScreen = screen === "editor";

  return (
    <div
      className={`app-shell ${classicMode ? "classic-mode" : ""} ${
        isReviewScreen ? "review-fullscreen" : ""
      } ${isEditorScreen ? "editor-fullscreen review-fullscreen" : ""}`}
    >
      <div className="scanlines" />
      <header className="topbar local-topbar">
        <div className="brand">
          <h1 data-text="ANKI OCCLUSION">ANKI OCCLUSION</h1>
        </div>
        <nav className="nav-links local-nav">
          <button onClick={handleMathNav} type="button">
            ▣ Math
          </button>
          <button onClick={handleJournalNav} type="button">
            ▤ Journal
          </button>
          <button
            className={classicMode ? "active-toggle" : ""}
            onClick={handleClassicToggle}
            type="button"
          >
            ▰ Classic Mode
          </button>
          <button onClick={handleMoreNav} type="button">
            More ▾
          </button>
        </nav>
        <div className="top-actions">
          <button
            className="icon-button"
            disabled={status === "loading" || status === "refreshing"}
            onClick={handleRefresh}
            title="Save and refresh"
            type="button"
          >
            ▣
          </button>
          <button
            className="icon-button"
            onClick={handleSettingsNav}
            title="Settings"
            type="button"
          >
            ⚙
          </button>
          <button
            className={`bgm-button ${bgmEnabled ? "active-toggle" : ""}`}
            onClick={handleBgmToggle}
            type="button"
          >
            ♫ BGM <span>{bgmEnabled ? "ON" : "OFF"}</span>
          </button>
          <div className="mentor-chip">
            <span>{status === "error" ? "API OFFLINE" : '"FOCUS. TRAIN. MASTER."'}</span>
            <small>DONATELLO</small>
          </div>
        </div>
      </header>

      <div className="workspace local-workspace">
        <aside className="left-rail dojo-rail">
          <div className="rail-header dojo-header">
            <div className="dojo-title">
              <span>╥</span>
              <h2>Dojo Cave</h2>
            </div>
            <label className="search-box">
              <span>⌕</span>
              <input
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search scrolls..."
                ref={searchInputRef}
                type="search"
                value={searchQuery}
              />
              <kbd>CTRL+K</kbd>
            </label>
          </div>
          <div className="deck-list dojo-list">
            <div className="section-title">- YOUR DOJOS -</div>
            {status === "loading" ? (
              <div className="empty-line">Loading dojos...</div>
            ) : visibleDecks.length ? (
              visibleDecks.map((deck) => (
                <DeckRow
                  key={deck.id}
                  deck={deck}
                  selectedId={selectedDeck?.id}
                  onSelect={handleSelectDeck}
                  collapsedDeckIds={collapsedDeckIds}
                  onToggleCollapse={toggleDeckCollapse}
                />
              ))
            ) : (
              <div className="empty-line">No dojos found</div>
            )}
          </div>
          <div className="rail-actions dojo-actions">
            <button onClick={() => openActionPanel("new-dojo")} type="button">
              ⊕ New Dojo
            </button>
            <button
              disabled={!selectedDeck}
              onClick={() => openActionPanel("sub-dojo")}
              type="button"
            >
              ⊕ Sub Dojo
            </button>
            <button
              aria-label="Delete selected dojo"
              className="dojo-delete-button"
              disabled={!selectedDeck}
              onClick={handleDeleteDojo}
              title="Delete selected dojo"
              type="button"
            >
              ◎
            </button>
          </div>
        </aside>

        <main className="main-panel dojo-main">
          <section className="deck-hero dojo-hero">
            <div className="selected-deck-icon dojo-icon">▣</div>
            <div>
              <h2>{deckDisplayName(selectedDeck)}</h2>
              <p>
                Scrolls: {scrollCount || 0}
                <span>❖</span>
                Due: {dueCount || 0}
              </p>
            </div>
            <button
              className="forge-button"
              disabled={status === "loading"}
              onClick={() => openActionPanel("forge-scroll")}
              type="button"
            >
              Forge Scroll
            </button>
          </section>

          {renderModePanel()}

          {screen === "home" ? (
            <>
              <section className="stats-grid dojo-stats">
                <StatCard
                  tone="red"
                  value={dueCount || 0}
                  title="Remaining Missions"
                  caption="Cards due for review"
                />
                <StatCard
                  tone="purple"
                  value={data.summary.occlusion_count}
                  title="New Techniques"
                  caption="Total active scrolls"
                />
                <StatCard
                  tone="green"
                  value={data.summary.review_items}
                  title="Battles Won"
                  caption="Reviews completed"
                />
              </section>

              {renderActionPanel()}

              <section className="mission-card training-mission">
                <div className="mission-copy">
                  <h3>⚔ Training Mission</h3>
                  <p>Continue your training and defeat the due cards!</p>
                  <code>&gt; Cowabunga! _</code>
                </div>
                <div className="mission-actions">
                  <button
                    className="start-button"
                    disabled={!selectedReviewItems.length}
                    onClick={() => openReviewScreen("due")}
                    type="button"
                  >
                    <span>▶ Start Training</span>
                    <strong>Review Due Scrolls</strong>
                  </button>
                  <button
                    className="secondary-button"
                    disabled={!activeItem}
                    onClick={() => openReviewScreen("selected")}
                    type="button"
                  >
                    ⊙ Train Selected Scroll
                  </button>
                </div>
              </section>

              <div className="inventory-title">Scroll Inventory</div>
              <section className="scroll-stage">
                {selectedReviewItems.length ? (
                  <div className="review-list">
                    {selectedReviewItems.slice(0, 12).map((item) => {
                      const key = itemKey(item);
                      return (
                        <button
                          className={`review-row ${key === activeKey ? "active" : ""}`}
                          key={key}
                          onClick={() => {
                            setActiveKey(key);
                            setAnswerRevealed(false);
                            recordAction(`${item.card_title} selected.`);
                          }}
                          type="button"
                        >
                          <span>{item.card_title}</span>
                          <small>{itemTargetLabel(item)}</small>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="stage-empty">- FORGE FIRST SCROLL TO BEGIN -</div>
                )}
              </section>

              <section className="main-actions">
                <button
                  className="secondary-button"
                  disabled={!activeItem}
                  onClick={() => openEditorMode("home")}
                  type="button"
                >
                  ▭ Edit
                </button>
                <button
                  className="danger-button"
                  disabled={!activeItem}
                  onClick={handleDeleteSelected}
                  type="button"
                >
                  ▥ Delete
                </button>
                <div className="review-log-chip">
                  <strong>Review Log</strong>
                  <span>{reviewLog}</span>
                </div>
              </section>
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default App;
