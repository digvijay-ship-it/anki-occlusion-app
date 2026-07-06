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
  loadJournal,
  saveJournal,
  loadRawData,
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


// ── Web Client-Side OCR Engine using ONNX Runtime Web ────────────────────────

let onnxSession = null;

async function loadOnnxSession() {
  if (onnxSession) return onnxSession;
  try {
    if (!window.ort) {
      console.warn("ONNX Runtime Web (window.ort) is not loaded yet.");
      return null;
    }
    onnxSession = await window.ort.InferenceSession.create("/model/mnist_math_cnn.onnx");
    console.log("ONNX model loaded successfully client-side!");
    return onnxSession;
  } catch (error) {
    console.error("Failed to load ONNX model client-side:", error);
    return null;
  }
}

function preprocessCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imgData.data;

  // Step 1: Scan columns to check if they contain drawn stroke pixels
  const colHasPixels = new Array(canvas.width).fill(false);
  for (let x = 0; x < canvas.width; x++) {
    for (let y = 0; y < canvas.height; y++) {
      const idx = (y * canvas.width + x) * 4;
      const a = data[idx + 3];
      const r = data[idx];
      const g = data[idx + 1];
      const b = data[idx + 2];
      if (a > 50 && (r < 220 || g < 220 || b < 220)) {
        colHasPixels[x] = true;
        break;
      }
    }
  }

  // Step 2: Group columns into digit segments
  const segments = [];
  let inSegment = false;
  let startX = 0;
  const minGap = 6;
  let gapCount = 0;

  for (let x = 0; x < canvas.width; x++) {
    if (colHasPixels[x]) {
      if (!inSegment) {
        startX = x;
        inSegment = true;
      }
      gapCount = 0;
    } else {
      if (inSegment) {
        gapCount++;
        if (gapCount >= minGap || x === canvas.width - 1) {
          segments.push({ startX, endX: x - gapCount });
          inSegment = false;
        }
      }
    }
  }
  
  if (inSegment) {
    segments.push({ startX, endX: canvas.width - 1 });
  }

  // Step 3: For each segmented column range, crop vertical bounds and center-scale
  const digitTensors = [];

  for (const seg of segments) {
    let minY = canvas.height, maxY = 0;
    let hasPixels = false;

    for (let x = seg.startX; x <= seg.endX; x++) {
      for (let y = 0; y < canvas.height; y++) {
        const idx = (y * canvas.width + x) * 4;
        const a = data[idx + 3];
        const r = data[idx];
        const g = data[idx + 1];
        const b = data[idx + 2];
        if (a > 50 && (r < 220 || g < 220 || b < 220)) {
          hasPixels = true;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }

    if (!hasPixels) continue;

    const w = seg.endX - seg.startX + 1;
    const h = maxY - minY + 1;
    
    // Ignore extremely small stroke noise
    if (w < 4 || h < 4) continue;

    const side = Math.max(w, h);
    const centerX = seg.startX + w / 2;
    const centerY = minY + h / 2;
    
    const cropX = Math.max(0, centerX - side / 2);
    const cropY = Math.max(0, centerY - side / 2);
    const cropW = Math.min(canvas.width - cropX, side);
    const cropH = Math.min(canvas.height - cropY, side);

    // Create 20x20 centered offscreen canvas
    const offscreen = document.createElement("canvas");
    offscreen.width = 20;
    offscreen.height = 20;
    const oCtx = offscreen.getContext("2d");
    oCtx.fillStyle = "#ffffff";
    oCtx.fillRect(0, 0, 20, 20);
    oCtx.drawImage(canvas, cropX, cropY, cropW, cropH, 0, 0, 20, 20);

    // Create 28x28 centered canvas with 4px padding
    const finalCanvas = document.createElement("canvas");
    finalCanvas.width = 28;
    finalCanvas.height = 28;
    const fCtx = finalCanvas.getContext("2d");
    fCtx.fillStyle = "#ffffff";
    fCtx.fillRect(0, 0, 28, 28);
    fCtx.drawImage(offscreen, 4, 4);

    // Get normalized tensor data
    const finalImgData = fCtx.getImageData(0, 0, 28, 28);
    const finalData = finalImgData.data;
    const tensorData = new Float32Array(28 * 28);

    for (let i = 0; i < 28 * 28; i++) {
      const r = finalData[i * 4];
      const g = finalData[i * 4 + 1];
      const b = finalData[i * 4 + 2];
      const brightness = (r + g + b) / 3;
      tensorData[i] = 1.0 - brightness / 255.0; // Invert: white digit on black background
    }

    digitTensors.push(tensorData);
  }

  return digitTensors;
}

async function predictDigitDrawing(canvas) {
  const session = await loadOnnxSession();
  if (!session) return { error: "ONNX model session not loaded." };

  const digitTensors = preprocessCanvas(canvas);
  if (!digitTensors || digitTensors.length === 0) {
    return { error: "No drawing detected. Write your answer on the board." };
  }

  let predictedValue = "";

  for (const tensorData of digitTensors) {
    const inputTensor = new window.ort.Tensor("float32", tensorData, [1, 28, 28, 1]);
    const feeds = { [session.inputNames[0]]: inputTensor };
    const results = await session.run(feeds);
    const output = results[session.outputNames[0]].data;

    let maxIdx = 0;
    let maxVal = output[0];
    for (let i = 1; i < output.length; i++) {
      if (output[i] > maxVal) {
        maxVal = output[i];
        maxIdx = i;
      }
    }
    predictedValue += maxIdx.toString();
  }

  return { result: predictedValue };
}


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

function normalizeMask(start, end, isPdf = false) {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const width = Math.abs(start.x - end.x);
  const height = Math.abs(start.y - end.y);
  if (isPdf) {
    if (width < 1 || height < 1) return null;
    return {
      id: createMaskId(),
      x: left,
      y: top,
      width: width,
      height: height,
    };
  }
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

function matchesShortcut(event, shortcut) {
  if (!shortcut) return false;
  const parts = shortcut.split("+").map(p => p.trim().toLowerCase());
  const needsCtrl = parts.includes("ctrl") || parts.includes("control");
  const needsAlt = parts.includes("alt");
  const needsShift = parts.includes("shift");
  const needsMeta = parts.includes("meta") || parts.includes("cmd") || parts.includes("win");
  
  const hasCtrl = event.ctrlKey;
  const hasAlt = event.altKey;
  const hasShift = event.shiftKey;
  const hasMeta = event.metaKey;
  
  if (needsCtrl !== hasCtrl) return false;
  if (needsAlt !== hasAlt) return false;
  if (needsShift !== hasShift) return false;
  if (needsMeta !== hasMeta) return false;
  
  const keyPart = parts.find(p => !["ctrl", "control", "alt", "shift", "meta", "cmd", "win"].includes(p));
  if (!keyPart) return false;
  
  let eventKey = event.key.toLowerCase();
  
  if (eventKey === " ") eventKey = "space";
  let targetKey = keyPart;
  if (targetKey === "space") targetKey = " ";
  
  if (targetKey === "+") {
    return eventKey === "+" || eventKey === "=";
  }
  
  return eventKey === targetKey;
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
  const [editorPdfPageDims, setEditorPdfPageDims] = useState({ width: 0, height: 0 });
  const [isDragOver, setIsDragOver] = useState(false);
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [bgmEnabled, setBgmEnabled] = useState(false);
  const [classicMode, setClassicMode] = useState(false);
  const [answerRevealed, setAnswerRevealed] = useState(false);
  const [dismissedKeys, setDismissedKeys] = useState(() => new Set());
  const [collapsedDeckIds, setCollapsedDeckIds] = useState(() => new Set());

  const defaultShortcuts = {
    "review.cancel": "Escape",
    "review.reveal": "Space",
    "review.rate_again": "1",
    "review.rate_hard": "2",
    "review.rate_good": "3",
    "review.rate_easy": "4",
    "review.rate_perfect": "5",
    "review.zoom_in": "Ctrl+=",
    "review.zoom_out": "Ctrl+-",
    "review.zoom_reset": "Ctrl+0",
    "review.center": "c",
    "review.focus_toggle": "f",
    "review.edit_card": "e",
    "review.copy_pdf": "l",
    "review.pen_toggle": "p",
    "review.pen_color": "x",
    "review.pen_clear": "Delete",
    "review.prev_page": "ArrowLeft",
    "review.next_page": "ArrowRight"
  };

  const shortcutLabels = {
    "review.cancel": "Leave Review",
    "review.reveal": "Reveal Answer",
    "review.rate_again": "Rate Again (Quality 1)",
    "review.rate_hard": "Rate Hard (Quality 3)",
    "review.rate_good": "Rate Good (Quality 4)",
    "review.rate_easy": "Rate Easy (Quality 5)",
    "review.rate_perfect": "Rate Perfect (Quality 6)",
    "review.zoom_in": "Zoom In",
    "review.zoom_out": "Zoom Out",
    "review.zoom_reset": "Reset Zoom",
    "review.center": "Center Current Mask",
    "review.focus_toggle": "Toggle Focus Mode",
    "review.edit_card": "Edit Active Card",
    "review.copy_pdf": "Copy PDF Path",
    "review.pen_toggle": "Toggle Drawing Pen",
    "review.pen_color": "Cycle Pen Color",
    "review.pen_clear": "Clear Pen Drawings",
    "review.prev_page": "Navigate Prev PDF Page",
    "review.next_page": "Navigate Next PDF Page"
  };

  const [shortcuts, setShortcuts] = useState(() => {
    try {
      const saved = localStorage.getItem("anki_shortcuts");
      if (saved) {
        return { ...defaultShortcuts, ...JSON.parse(saved) };
      }
    } catch (e) {
      console.error(e);
    }
    return defaultShortcuts;
  });

  const [activeRecordingId, setActiveRecordingId] = useState(null);

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
  const [mathStage, setMathStage] = useState("loading"); // 'loading', 'discipline', 'configure', 'practice', 'report'
  const [mathMode, setMathMode] = useState("tables"); // 'tables', 'squares', 'cubes'
  const [mathTablesConfig, setMathTablesConfig] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("anki_math_tables")) || {};
    } catch {
      return {};
    }
  });
  const [mathSquaresConfig, setMathSquaresConfig] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("anki_math_squares")) || {};
    } catch {
      return {};
    }
  });
  const [mathCubesConfig, setMathCubesConfig] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("anki_math_cubes")) || {};
    } catch {
      return {};
    }
  });
  const [mathTimerConfig, setMathTimerConfig] = useState(() => {
    const val = localStorage.getItem("anki_math_timer");
    return val !== null ? Number(val) : 0;
  });

  const [mathProblem, setMathProblem] = useState({ prompt: "", answer: 0, label: "" });
  const [mathCorrectCount, setMathCorrectCount] = useState(0);
  const [mathWrongCount, setMathWrongCount] = useState(0);
  const [mathTimeLeft, setMathTimeLeft] = useState(0);
  const [mathQAttempted, setMathQAttempted] = useState(false);
  const [mathStreak, setMathStreak] = useState(0);
  const [mathAnswer, setMathAnswer] = useState("");
  const [mathResult, setMathResult] = useState("");
  const [mathRecognised, setMathRecognised] = useState("");
  const [mathModelStatus, setMathModelStatus] = useState("idle"); // 'idle', 'loading', 'loaded', 'error'
  const [mathLastQuestion, setMathLastQuestion] = useState(null);
  const [mathRevealTable, setMathRevealTable] = useState(false);

  // Daily Journal State
  const [journalData, setJournalData] = useState({});
  const [journalDate, setJournalDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [journalMode, setJournalMode] = useState("pen"); // 'pen', 'eraser', 'text'
  const [journalColorIdx, setJournalColorIdx] = useState(0);
  const [journalTextSize, setJournalTextSize] = useState(14);
  const [journalTextBuf, setJournalTextBuf] = useState("");
  const [journalTextPos, setJournalTextPos] = useState(null);
  const [journalCanvasHeight, setJournalCanvasHeight] = useState(1200);

  const [localDb, setLocalDb] = useState(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [isApiReachable, setIsApiReachable] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);

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
        
        try {
          const pending = await dbInstance.pendingChanges();
          setPendingCount(pending.length);
        } catch (e) {
          console.warn("Failed to get pending changes count", e);
        }
        
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
            const rawData = await loadRawData();
            await importDecksToIndexedDb(rawData.decks || [], db);
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

  // Network connectivity and periodic heartbeat
  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      checkHeartbeat();
    };
    const handleOffline = () => {
      setIsOnline(false);
      setIsApiReachable(false);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    checkHeartbeat();
    const interval = setInterval(checkHeartbeat, 10000);

    async function checkHeartbeat() {
      if (localDb) {
        try {
          const pending = await localDb.pendingChanges();
          setPendingCount(pending.length);
        } catch (e) {
          // ignore
        }
      }
      if (!navigator.onLine) {
        setIsApiReachable(false);
        return;
      }
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);
        const response = await fetch(`${import.meta.env?.VITE_API_BASE || "http://127.0.0.1:8000"}/api/health`, {
          method: "GET",
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (response.ok) {
          setIsApiReachable(true);
        } else {
          setIsApiReachable(false);
        }
      } catch (err) {
        setIsApiReachable(false);
      }
    }

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      clearInterval(interval);
    };
  }, [localDb]);

  const draftCanvasRef = useRef(null);
  const editorCanvasRef = useRef(null);
  const editorDragInitialMasksRef = useRef(null);
  const lastActivityTimeRef = useRef(Date.now());
  const mathCanvasRef = useRef(null);
  const journalCanvasRef = useRef(null);
  const journalTextInputRef = useRef(null);

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
        const nativeViewport = page.getViewport({ scale: 1.0 });
        if (!cancelled) {
          setEditorPdfPageDims({ width: nativeViewport.width, height: nativeViewport.height });
        }
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

  useEffect(() => {
    function handleGlobalEscape(event) {
      if (event.key === "Escape") {
        if (
          event.target.tagName === "INPUT" ||
          event.target.tagName === "TEXTAREA"
        ) {
          return;
        }
        if (screen === "math") {
          event.preventDefault();
          if (mathStage === "practice") {
            setMathStage("configure");
            recordAction("Math practice exited via Escape.");
          } else if (mathStage === "configure") {
            setMathStage("discipline");
            recordAction("Math config exited via Escape.");
          } else {
            setScreen("home");
            recordAction("Math trainer closed via Escape.");
          }
        } else if (screen === "editor") {
          event.preventDefault();
          setScreen(editorReturnScreen === "review" ? "review" : "home");
          recordAction("Editor closed via Escape.");
        } else if (
          screen === "journal" ||
          screen === "settings" ||
          screen === "more" ||
          screen === "review-summary"
        ) {
          event.preventDefault();
          setScreen("home");
          recordAction("Screen closed via Escape.");
        }
      }
    }
    window.addEventListener("keydown", handleGlobalEscape);
    return () => window.removeEventListener("keydown", handleGlobalEscape);
  }, [screen, mathStage, editorReturnScreen]);


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

  useEffect(() => {
    if (screen === "math" && mathModelStatus === "idle") {
      setMathModelStatus("loading");
      loadOnnxSession().then((session) => {
        if (session) {
          setMathModelStatus("loaded");
          setMathStage("discipline");
          recordAction("AI OCR model loaded client-side successfully.");
        } else {
          setMathModelStatus("error");
          setMathStage("discipline");
          recordAction("Failed to load local AI OCR model.");
        }
      });
    }
  }, [screen, mathModelStatus]);

  useEffect(() => {
    if (screen === "journal") {
      loadJournal()
        .then((data) => {
          setJournalData(data || {});
          recordAction("Daily journal loaded from local server.");
        })
        .catch((err) => {
          console.error("Failed to load daily journal", err);
          recordAction("Failed to fetch daily journal.");
        });
    }
  }, [screen]);

  // Handle timer countdown
  useEffect(() => {
    if (screen === "math" && mathStage === "practice" && mathTimerConfig > 0) {
      const interval = setInterval(() => {
        setMathTimeLeft((prev) => {
          if (prev <= 1) {
            clearInterval(interval);
            setMathStage("report");
            playMathSound("powerup");
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [screen, mathStage, mathTimerConfig]);

  // Auto check input when target digit length is met
  useEffect(() => {
    if (screen === "math" && mathStage === "practice" && mathAnswer && mathProblem.answer) {
      const digits = mathAnswer.replace(/\D/g, "");
      const targetStr = String(mathProblem.answer);
      if (digits.length === targetStr.length) {
        const timer = setTimeout(() => {
          runMathCheck(digits);
        }, 300);
        return () => clearTimeout(timer);
      }
    }
  }, [mathAnswer, mathProblem.answer, mathStage, screen]);
  const draftPreviewMasks = useMemo(() => {
    if (!draftMaskDrag) return draftMasks;
    const mask = normalizeMask(draftMaskDrag.start, draftMaskDrag.end);
    return mask ? [...draftMasks, { ...mask, id: "draft-mask-preview" }] : draftMasks;
  }, [draftMaskDrag, draftMasks]);
  const editorPreviewMasks = useMemo(() => {
    const pageMasks = editorPdfDoc
      ? editorMasks.filter((m) => m.page_num === editorPdfPageZero)
      : editorMasks;
    if (!editorMaskDrag) return pageMasks;
    const mask = normalizeMask(editorMaskDrag.start, editorMaskDrag.end, !!editorPdfDoc);
    return mask ? [...pageMasks, { ...mask, id: "editor-mask-preview" }] : pageMasks;
  }, [editorMaskDrag, editorMasks, editorPdfPageZero, editorPdfDoc]);

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
    if (!activeRecordingId) return;

    function handleRecordKeyDown(event) {
      event.preventDefault();
      event.stopPropagation();
      
      const key = event.key;
      if (key === "Escape") {
        setActiveRecordingId(null);
        return;
      }
      
      if (["Control", "Shift", "Alt", "Meta"].includes(key)) {
        return;
      }
      
      const parts = [];
      if (event.ctrlKey) parts.push("Ctrl");
      if (event.altKey) parts.push("Alt");
      if (event.shiftKey) parts.push("Shift");
      if (event.metaKey) parts.push("Meta");
      
      let keyName = key;
      if (keyName === " ") keyName = "Space";
      
      parts.push(keyName);
      const sequence = parts.join("+");
      
      setShortcuts(current => {
        const next = { ...current, [activeRecordingId]: sequence };
        localStorage.setItem("anki_shortcuts", JSON.stringify(next));
        return next;
      });
      
      setActiveRecordingId(null);
      recordAction(`Shortcut for ${shortcutLabels[activeRecordingId]} updated to ${sequence}`);
    }

    window.addEventListener("keydown", handleRecordKeyDown, true);
    return () => window.removeEventListener("keydown", handleRecordKeyDown, true);
  }, [activeRecordingId]);

  useEffect(() => {
    function handleReviewShortcut(event) {
      const target = event.target;
      const isTyping =
        target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
      if (isTyping || screen !== "review" || activeRecordingId) return;

      if (matchesShortcut(event, shortcuts["review.cancel"])) {
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
      if (matchesShortcut(event, shortcuts["review.reveal"])) {
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
      if (matchesShortcut(event, shortcuts["review.zoom_in"])) {
        event.preventDefault();
        zoomReviewSurface(1);
        return;
      }
      if (matchesShortcut(event, shortcuts["review.zoom_out"])) {
        event.preventDefault();
        zoomReviewSurface(-1);
        return;
      }
      if (matchesShortcut(event, shortcuts["review.zoom_reset"])) {
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
      if (matchesShortcut(event, shortcuts["review.prev_page"])) {
        event.preventDefault();
        sendReviewPageCommand("prev");
        return;
      }
      if (matchesShortcut(event, shortcuts["review.next_page"])) {
        event.preventDefault();
        sendReviewPageCommand("next");
        return;
      }
      if (matchesShortcut(event, shortcuts["review.center"])) {
        event.preventDefault();
        fitAndCenterReviewSurface("shortcut");
        return;
      }
      if (matchesShortcut(event, shortcuts["review.focus_toggle"])) {
        event.preventDefault();
        toggleReviewFocusMode("shortcut");
        return;
      }
      if (matchesShortcut(event, shortcuts["review.edit_card"])) {
        event.preventDefault();
        openEditorMode("review");
        return;
      }
      if (matchesShortcut(event, shortcuts["review.copy_pdf"])) {
        event.preventDefault();
        copyCurrentPdfPath();
        return;
      }
      if (matchesShortcut(event, shortcuts["review.pen_toggle"])) {
        event.preventDefault();
        setReviewPenActive((current) => !current);
        return;
      }
      if (matchesShortcut(event, shortcuts["review.pen_color"])) {
        event.preventDefault();
        setReviewPenColorIndex((current) => (current + 1) % reviewPenColors.length);
        return;
      }
      if (matchesShortcut(event, shortcuts["review.pen_clear"])) {
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
      if (answerRevealed && activeItem && busyQuality === null) {
        if (matchesShortcut(event, shortcuts["review.rate_again"])) {
          event.preventDefault();
          handleRate(1);
          return;
        }
        if (matchesShortcut(event, shortcuts["review.rate_hard"])) {
          event.preventDefault();
          handleRate(3);
          return;
        }
        if (matchesShortcut(event, shortcuts["review.rate_good"])) {
          event.preventDefault();
          handleRate(4);
          return;
        }
        if (matchesShortcut(event, shortcuts["review.rate_easy"])) {
          event.preventDefault();
          handleRate(5);
          return;
        }
        if (matchesShortcut(event, shortcuts["review.rate_perfect"])) {
          event.preventDefault();
          handleRate(6);
          return;
        }
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
    shortcuts,
    activeRecordingId
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

  async function handleForceResetFromBackend() {
    if (!localDb) {
      alert("Local IndexedDB is not loaded yet.");
      return;
    }
    if (!isOnline || !isApiReachable) {
      alert("Cannot reset from backend while offline.");
      return;
    }
    if (!window.confirm("This will clear all browser-cached decks and reload everything fresh from your local server's database. Proceed?")) {
      return;
    }
    setStatus("loading");
    try {
      const storeNames = ["decks", "cards", "masks", "review_state", "sync_queue", "files"];
      for (const store of storeNames) {
        const list = await localDb.list(store);
        for (const item of list) {
          const key = item.local_id || item.id || item.item_id;
          if (key) {
            await localDb.delete(store, key);
          }
        }
      }
      
      const rawData = await loadRawData();
      await importDecksToIndexedDb(rawData.decks || [], localDb);
      await refreshDashboard(null, localDb);
      setSelectedDeckId(rawData.decks[0]?.id ?? rawData.decks[0]?._id ?? null);
      
      recordAction("IndexedDB reset and re-populated from backend JSON data.");
      setStatus("ready");
      alert("Local cache reset successfully! Real PyQt database is now loaded.");
    } catch (err) {
      console.error("Force reset failed", err);
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

  function processLoadedFile(file) {
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

  function handleEditorFileChange(event) {
    const file = event.target.files?.[0];
    processLoadedFile(file);
  }

  function editorPointFromEvent(event) {
    if (editorPdfDoc) {
      const canvas = editorCanvasRef.current;
      if (!canvas) return null;
      const canvasRect = canvas.getBoundingClientRect();
      const clientXOnCanvas = event.clientX - canvasRect.left;
      const clientYOnCanvas = event.clientY - canvasRect.top;
      const pageWidth = editorPdfPageDims.width || 1;
      const pageHeight = editorPdfPageDims.height || 1;
      const pdfX = Math.max(0, Math.min(pageWidth, (clientXOnCanvas / canvasRect.width) * pageWidth));
      const pdfY = Math.max(0, Math.min(pageHeight, (clientYOnCanvas / canvasRect.height) * pageHeight));
      return { x: pdfX, y: pdfY };
    } else {
      return maskPointFromEvent(event, editorStageRef);
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
      const point = editorPointFromEvent(event);
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
      const point = editorPointFromEvent(event);
      if (!point) return;
      setEditorMaskDrag((current) => (current ? { ...current, end: point } : current));
    } else if (editorAction === "moving" && editorDragStartClient) {
      let dx, dy;
      if (editorPdfDoc) {
        const canvas = editorCanvasRef.current;
        if (!canvas) return;
        const canvasRect = canvas.getBoundingClientRect();
        const pageWidth = editorPdfPageDims.width || 1;
        const pageHeight = editorPdfPageDims.height || 1;
        dx = ((event.clientX - editorDragStartClient.x) / canvasRect.width) * pageWidth;
        dy = ((event.clientY - editorDragStartClient.y) / canvasRect.height) * pageHeight;
      } else {
        const stage = editorStageRef.current;
        if (!stage) return;
        const rect = stage.getBoundingClientRect();
        dx = ((event.clientX - editorDragStartClient.x) / rect.width) * 100;
        dy = ((event.clientY - editorDragStartClient.y) / rect.height) * 100;
      }
      
      const newMasks = editorMasks.map((mask) => {
        const startState = editorDragMaskStartStates[mask.id];
        if (startState) {
          if (editorPdfDoc) {
            const pageWidth = editorPdfPageDims.width || 1;
            const pageHeight = editorPdfPageDims.height || 1;
            return {
              ...mask,
              x: Math.max(0, Math.min(pageWidth, startState.x + dx)),
              y: Math.max(0, Math.min(pageHeight, startState.y + dy)),
            };
          } else {
            return {
              ...mask,
              x: clampPercent(startState.x + dx),
              y: clampPercent(startState.y + dy),
            };
          }
        }
        return mask;
      });
      setEditorMasks(newMasks);
    } else if (editorAction === "resizing" && editorDragStartClient && editorActiveHandle) {
      let dx, dy;
      if (editorPdfDoc) {
        const canvas = editorCanvasRef.current;
        if (!canvas) return;
        const canvasRect = canvas.getBoundingClientRect();
        const pageWidth = editorPdfPageDims.width || 1;
        const pageHeight = editorPdfPageDims.height || 1;
        dx = ((event.clientX - editorDragStartClient.x) / canvasRect.width) * pageWidth;
        dy = ((event.clientY - editorDragStartClient.y) / canvasRect.height) * pageHeight;
      } else {
        const stage = editorStageRef.current;
        if (!stage) return;
        const rect = stage.getBoundingClientRect();
        dx = ((event.clientX - editorDragStartClient.x) / rect.width) * 100;
        dy = ((event.clientY - editorDragStartClient.y) / rect.height) * 100;
      }
      
      const targetId = Object.keys(editorDragMaskStartStates)[0];
      const startState = editorDragMaskStartStates[targetId];
      if (startState) {
        const newMasks = editorMasks.map((mask) => {
          if (mask.id === targetId) {
            let { x, y, width, height } = startState;
            if (editorPdfDoc) {
              const pageWidth = editorPdfPageDims.width || 1;
              const pageHeight = editorPdfPageDims.height || 1;
              if (editorActiveHandle === "se") {
                width = Math.max(1, Math.min(pageWidth - x, width + dx));
                height = Math.max(1, Math.min(pageHeight - y, height + dy));
              } else if (editorActiveHandle === "sw") {
                const newX = Math.max(0, Math.min(pageWidth, x + dx));
                width = Math.max(1, x + width - newX);
                x = newX;
                height = Math.max(1, Math.min(pageHeight - y, height + dy));
              } else if (editorActiveHandle === "ne") {
                const newY = Math.max(0, Math.min(pageHeight, y + dy));
                height = Math.max(1, y + height - newY);
                y = newY;
                width = Math.max(1, Math.min(pageWidth - x, width + dx));
              } else if (editorActiveHandle === "nw") {
                const newX = Math.max(0, Math.min(pageWidth, x + dx));
                const newY = Math.max(0, Math.min(pageHeight, y + dy));
                width = Math.max(1, x + width - newX);
                height = Math.max(1, y + height - newY);
                x = newX;
                y = newY;
              }
            } else {
              if (editorActiveHandle === "se") {
                width = Math.max(1, width + dx);
                height = Math.max(1, height + dy);
              } else if (editorActiveHandle === "sw") {
                const newX = x + dx;
                width = Math.max(1, width - dx);
                x = clampPercent(newX);
                height = Math.max(1, height + dy);
              } else if (editorActiveHandle === "ne") {
                const newY = y + dy;
                height = Math.max(1, height - dy);
                y = clampPercent(newY);
                width = Math.max(1, width + dx);
              } else if (editorActiveHandle === "nw") {
                const newX = x + dx;
                const newY = y + dy;
                width = Math.max(1, width - dx);
                height = Math.max(1, height - dy);
                x = clampPercent(newX);
                y = clampPercent(newY);
              }
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
      const point = editorPointFromEvent(event);
      const mask = point ? normalizeMask(editorMaskDrag.start, point, !!editorPdfDoc) : null;
      if (mask) {
        const finalMask = {
          ...mask,
          page_num: editorPdfDoc ? editorPdfPageZero : 0,
        };
        updateEditorMasksWithHistory([...editorMasks, finalMask]);
        recordAction("Editor mask added locally.");
      }
      setEditorMaskDrag(null);
    } else if (editorAction === "moving" || editorAction === "resizing") {
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
    let newMask;
    if (editorPdfDoc) {
      const pageWidth = editorPdfPageDims.width || 612;
      const pageHeight = editorPdfPageDims.height || 792;
      newMask = {
        id: createMaskId(),
        x: pageWidth * 0.33,
        y: pageHeight * 0.34,
        width: pageWidth * 0.34,
        height: pageHeight * 0.18,
        page_num: editorPdfPageZero,
      };
    } else {
      newMask = {
        id: createMaskId(),
        x: 33,
        y: 34,
        width: 34,
        height: 18,
        page_num: 0,
      };
    }
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

  const mathDrawingRef = useRef({ isDrawing: false, lastX: 0, lastY: 0, idleTimer: null });
  const journalDrawingRef = useRef({ isDrawing: false, lastX: 0, lastY: 0, currentStrokePoints: [] });

  function playMathSound(type) {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      const ctx = new AudioContext();
      
      if (type === "coin") {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "square";
        osc.connect(gain);
        gain.connect(ctx.destination);
        
        const now = ctx.currentTime;
        osc.frequency.setValueAtTime(587.33, now); // D5
        osc.frequency.setValueAtTime(880, now + 0.08); // A5
        
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.35);
        
        osc.start(now);
        osc.stop(now + 0.35);
      } else if (type === "powerup") {
        const now = ctx.currentTime;
        const freqs = [330, 392, 659, 523, 587, 784];
        freqs.forEach((f, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "triangle";
          osc.connect(gain);
          gain.connect(ctx.destination);
          
          osc.frequency.setValueAtTime(f, now + idx * 0.06);
          gain.gain.setValueAtTime(0.06, now + idx * 0.06);
          gain.gain.exponentialRampToValueAtTime(0.01, now + idx * 0.06 + 0.12);
          
          osc.start(now + idx * 0.06);
          osc.stop(now + idx * 0.06 + 0.15);
        });
      } else if (type === "hit") {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sawtooth";
        osc.connect(gain);
        gain.connect(ctx.destination);
        
        const now = ctx.currentTime;
        osc.frequency.setValueAtTime(180, now);
        osc.frequency.exponentialRampToValueAtTime(40, now + 0.25);
        
        gain.gain.setValueAtTime(0.12, now);
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
        
        osc.start(now);
        osc.stop(now + 0.3);
      }
    } catch (e) {
      console.warn("Failed to play synth sound:", e);
    }
  }

  function getMathCanvasCoordinates(e, canvas) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches && e.touches[0] ? e.touches[0].clientY : e.clientY;
    
    const scaleX = rect.width > 0 ? canvas.width / rect.width : 1;
    const scaleY = rect.height > 0 ? canvas.height / rect.height : 1;

    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY
    };
  }

  function startMathDrawing(e, canvas) {
    mathDrawingRef.current.isDrawing = true;
    const coords = getMathCanvasCoordinates(e, canvas);
    mathDrawingRef.current.lastX = coords.x;
    mathDrawingRef.current.lastY = coords.y;
    
    if (mathDrawingRef.current.idleTimer) {
      clearTimeout(mathDrawingRef.current.idleTimer);
      mathDrawingRef.current.idleTimer = null;
    }

    const ctx = canvas.getContext("2d");
    const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let isClean = true;
    for (let i = 3; i < imgData.data.length; i += 4) {
      if (imgData.data[i] !== 0) {
        isClean = false;
        break;
      }
    }
    if (isClean) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
  }

  function drawMath(e, canvas) {
    if (!mathDrawingRef.current.isDrawing) return;
    const coords = getMathCanvasCoordinates(e, canvas);
    const ctx = canvas.getContext("2d");
    
    ctx.beginPath();
    ctx.strokeStyle = "#1a1a2e"; // Dark stroke color
    ctx.lineWidth = 10;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.moveTo(mathDrawingRef.current.lastX, mathDrawingRef.current.lastY);
    ctx.lineTo(coords.x, coords.y);
    ctx.stroke();
    
    mathDrawingRef.current.lastX = coords.x;
    mathDrawingRef.current.lastY = coords.y;
  }

  function stopMathDrawing(canvas) {
    if (!mathDrawingRef.current.isDrawing) return;
    mathDrawingRef.current.isDrawing = false;
    
    if (mathDrawingRef.current.idleTimer) {
      clearTimeout(mathDrawingRef.current.idleTimer);
    }
    
    mathDrawingRef.current.idleTimer = setTimeout(async () => {
      if (!canvas) return;
      setMathResult("Predicting...");
      const predictionResult = await predictDigitDrawing(canvas);
      if (predictionResult.error) {
        setMathResult(predictionResult.error);
      } else {
        const recognised = predictionResult.result;
        setMathRecognised(recognised);
        setMathAnswer(recognised);
        
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }
    }, 800);
  }

  function generateNextMathProblem(mode, tablesConfig, squaresConfig, cubesConfig) {
    if (mode === "tables") {
      const activeTables = Object.keys(tablesConfig).filter(k => tablesConfig[k]).map(Number);
      if (activeTables.length === 0) return null;
      let n1;
      let n2;
      for (let attempt = 0; attempt < 10; attempt++) {
        n1 = activeTables[Math.floor(Math.random() * activeTables.length)];
        n2 = [2, 3, 4, 5, 6, 7, 8, 9][Math.floor(Math.random() * 8)];
        const key = `${n1}x${n2}`;
        if (mathLastQuestion !== key || activeTables.length === 1) {
          setMathLastQuestion(key);
          break;
        }
      }
      return {
        prompt: `${n1} × ${n2} = ?`,
        answer: n1 * n2,
        label: "Table",
        n1,
        n2
      };
    } else {
      const config = mode === "squares" ? squaresConfig : cubesConfig;
      const activeRanges = Object.keys(config).filter(k => config[k]);
      if (activeRanges.length === 0) return null;
      let num;
      for (let attempt = 0; attempt < 10; attempt++) {
        const range = activeRanges[Math.floor(Math.random() * activeRanges.length)];
        const [start, end] = range.split("-").map(Number);
        num = Math.floor(Math.random() * (end - start + 1)) + start;
        const key = `${num}`;
        if (mathLastQuestion !== key || (activeRanges.length === 1 && start === end)) {
          setMathLastQuestion(key);
          break;
        }
      }
      if (mode === "squares") {
        return {
          prompt: `${num}² = ?`,
          answer: num * num,
          label: "Square",
          num
        };
      } else {
        return {
          prompt: `${num}³ = ?`,
          answer: num * num * num,
          label: "Cube",
          num
        };
      }
    }
  }

  function runMathCheck(ansVal) {
    const answer = parseInt(ansVal, 10);
    const correctVal = mathProblem.answer;
    
    if (isNaN(answer)) return;
    
    if (answer === correctVal) {
      if (!mathQAttempted) {
        setMathCorrectCount((c) => c + 1);
      }
      setMathStreak((st) => {
        const nextStreak = st + 1;
        if (nextStreak > 0 && nextStreak % 5 === 0) {
          playMathSound("powerup");
        } else {
          playMathSound("coin");
        }
        return nextStreak;
      });
      
      const msgs = ["COWABUNGA!", "CORRECT!", "LETHAL!", "PERFECT!", "NAILED IT!", "KAME-HA!"];
      const randomMsg = msgs[Math.floor(Math.random() * msgs.length)];
      setMathResult(randomMsg);
      recordAction(`Math practice correct: ${ansVal}`);
      
      setTimeout(() => {
        const next = generateNextMathProblem(mathMode, mathTablesConfig, mathSquaresConfig, mathCubesConfig);
        if (next) {
          setMathProblem(next);
          setMathAnswer("");
          setMathResult("");
          setMathRecognised("");
          setMathQAttempted(false);
          setMathRevealTable(false);
          handleClearMathCanvas();
        } else {
          setMathStage("report");
        }
      }, 1000);
    } else {
      playMathSound("hit");
      if (!mathQAttempted) {
        setMathWrongCount((w) => w + 1);
      }
      setMathQAttempted(true);
      setMathStreak(0);
      setMathResult("WRONG! ADJUST OR REVEAL.");
      recordAction(`Math practice wrong: ${ansVal}, correct: ${correctVal}`);
    }
  }

  async function handleCheckMathAnswer(event) {
    if (event && event.preventDefault) event.preventDefault();
    
    if (mathAnswer.trim()) {
      runMathCheck(mathAnswer.trim());
      return;
    }

    if (!mathCanvasRef.current) return;
    setMathResult("Predicting...");
    
    const predictionResult = await predictDigitDrawing(mathCanvasRef.current);
    
    if (predictionResult.error) {
      setMathResult(predictionResult.error);
      return;
    }
    
    const recognised = predictionResult.result;
    setMathRecognised(recognised);
    setMathAnswer(recognised);
    runMathCheck(recognised);
  }

  function handleNextMathProblem() {
    setMathAnswer("");
    setMathResult("");
    setMathRecognised("");
    setMathQAttempted(false);
    setMathRevealTable(false);
    recordAction("Next math problem loaded.");
    handleClearMathCanvas();
    
    const next = generateNextMathProblem(mathMode, mathTablesConfig, mathSquaresConfig, mathCubesConfig);
    if (next) {
      setMathProblem(next);
    } else {
      setMathStage("report");
    }
  }

  function handleClearMathCanvas() {
    setMathResult("");
    setMathRecognised("");
    if (mathCanvasRef.current) {
      const canvas = mathCanvasRef.current;
      const rect = canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      recordAction("Math canvas cleared.");
    }
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

  // ── Daily Journal Features & Canvas Managers ──────────────────────────────
  const JOURNAL_COLORS = ["#72FF4F", "#A86CFF", "#E0E0FF", "#FF4444", "#F1FA8C", "#F7916A"];

  function redrawJournalContent(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dateEntry = journalData[journalDate] || { strokes: [], texts: [] };
    
    // Clear canvas
    ctx.fillStyle = classicMode ? "#1e1e2e" : "#07070b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Grid lines
    ctx.strokeStyle = classicMode ? "#2a2a4a" : "#0d1220";
    ctx.lineWidth = 1;
    for (let y = 40; y < canvas.height; y += 32) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }
    
    // Margin line
    ctx.strokeStyle = classicMode ? "#3a2a3a" : "#0f1a10";
    ctx.beginPath();
    const marginX = classicMode ? 48 : 60;
    ctx.moveTo(marginX, 0);
    ctx.lineTo(marginX, canvas.height);
    ctx.stroke();
    
    // Strokes
    const strokes = dateEntry.strokes || [];
    for (const stroke of strokes) {
      if (!stroke.pts || stroke.pts.length === 0) continue;
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = 2.0;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      
      const pts = stroke.pts;
      if (pts.length === 1) {
        ctx.arc(pts[0][0], pts[0][1], 1, 0, 2 * Math.PI);
        ctx.fillStyle = stroke.color;
        ctx.fill();
      } else {
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) {
          ctx.lineTo(pts[i][0], pts[i][1]);
        }
        ctx.stroke();
      }
    }
    
    // Texts
    const texts = dateEntry.texts || [];
    for (const t of texts) {
      ctx.font = `${t.size || 14}px Segoe UI, sans-serif`;
      ctx.fillStyle = t.color;
      ctx.fillText(t.text, t.x, t.y);
    }
  }

  useEffect(() => {
    if (screen === "journal" && journalCanvasRef.current) {
      const canvas = journalCanvasRef.current;
      canvas.width = 900;
      canvas.height = journalCanvasHeight;
      redrawJournalContent(canvas);
    }
  }, [screen, journalData, journalDate, journalCanvasHeight, classicMode]);

  function getJournalCanvasCoordinates(e, canvas) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches && e.touches[0] ? e.touches[0].clientY : e.clientY;
    
    const scaleX = rect.width > 0 ? 900 / rect.width : 1;
    const scaleY = rect.height > 0 ? journalCanvasHeight / rect.height : 1;
    
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY
    };
  }

  function startJournalDrawing(e) {
    if (journalMode === "text") {
      const canvas = journalCanvasRef.current;
      const coords = getJournalCanvasCoordinates(e, canvas);
      commitJournalText();
      setJournalTextPos(coords);
      setJournalTextBuf("");
      setTimeout(() => {
        journalTextInputRef.current?.focus();
      }, 50);
      return;
    }
    
    journalDrawingRef.current.isDrawing = true;
    const canvas = journalCanvasRef.current;
    const coords = getJournalCanvasCoordinates(e, canvas);
    journalDrawingRef.current.lastX = coords.x;
    journalDrawingRef.current.lastY = coords.y;
    
    if (journalMode === "pen") {
      journalDrawingRef.current.currentStrokePoints = [[coords.x, coords.y]];
    } else if (journalMode === "eraser") {
      eraseStrokesAt(coords.x, coords.y);
    }
  }

  function drawJournal(e) {
    if (!journalDrawingRef.current.isDrawing) return;
    const canvas = journalCanvasRef.current;
    const coords = getJournalCanvasCoordinates(e, canvas);
    
    if (journalMode === "pen") {
      const ctx = canvas.getContext("2d");
      ctx.strokeStyle = JOURNAL_COLORS[journalColorIdx];
      ctx.lineWidth = 2.0;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(journalDrawingRef.current.lastX, journalDrawingRef.current.lastY);
      ctx.lineTo(coords.x, coords.y);
      ctx.stroke();
      
      journalDrawingRef.current.currentStrokePoints.push([coords.x, coords.y]);
      journalDrawingRef.current.lastX = coords.x;
      journalDrawingRef.current.lastY = coords.y;
      
      maybeExpandJournalCanvas(coords.y);
    } else if (journalMode === "eraser") {
      eraseStrokesAt(coords.x, coords.y);
    }
  }

  function stopJournalDrawing() {
    if (!journalDrawingRef.current.isDrawing) return;
    journalDrawingRef.current.isDrawing = false;
    
    if (journalMode === "pen" && journalDrawingRef.current.currentStrokePoints.length > 0) {
      const newStroke = {
        color: JOURNAL_COLORS[journalColorIdx],
        pts: journalDrawingRef.current.currentStrokePoints
      };
      
      const dateEntry = journalData[journalDate] || { strokes: [], texts: [] };
      const updatedEntry = {
        ...dateEntry,
        strokes: [...(dateEntry.strokes || []), newStroke]
      };
      
      const updatedData = {
        ...journalData,
        [journalDate]: updatedEntry
      };
      
      setJournalData(updatedData);
      saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    }
    
    journalDrawingRef.current.currentStrokePoints = [];
  }

  function eraseStrokesAt(x, y) {
    const radius = 11;
    const dateEntry = journalData[journalDate] || { strokes: [], texts: [] };
    const strokes = dateEntry.strokes || [];
    let changed = false;
    
    const keptStrokes = strokes.filter(stroke => {
      const hit = stroke.pts.some(pt => {
        const dx = pt[0] - x;
        const dy = pt[1] - y;
        return dx * dx + dy * dy <= radius * radius;
      });
      if (hit) {
        changed = true;
        return false;
      }
      return true;
    });
    
    if (changed) {
      const updatedEntry = {
        ...dateEntry,
        strokes: keptStrokes
      };
      const updatedData = {
        ...journalData,
        [journalDate]: updatedEntry
      };
      setJournalData(updatedData);
      saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    }
  }

  function commitJournalText() {
    if (journalTextBuf.trim() && journalTextPos) {
      const dateEntry = journalData[journalDate] || { strokes: [], texts: [] };
      const newText = {
        x: journalTextPos.x,
        y: journalTextPos.y,
        text: journalTextBuf,
        color: JOURNAL_COLORS[journalColorIdx],
        size: journalTextSize
      };
      
      const updatedEntry = {
        ...dateEntry,
        texts: [...(dateEntry.texts || []), newText]
      };
      const updatedData = {
        ...journalData,
        [journalDate]: updatedEntry
      };
      
      setJournalData(updatedData);
      saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    }
    setJournalTextBuf("");
    setJournalTextPos(null);
  }

  function handleJournalTextKeyDown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitJournalText();
      const nextY = journalTextPos.y + journalTextSize + 8;
      setJournalTextPos({ x: journalTextPos.x, y: nextY });
      setJournalTextBuf("");
      maybeExpandJournalCanvas(nextY);
      setTimeout(() => {
        journalTextInputRef.current?.focus();
      }, 50);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setJournalTextBuf("");
      setJournalTextPos(null);
    }
  }

  function handlePrevDay() {
    commitJournalText();
    const current = new Date(journalDate);
    current.setDate(current.getDate() - 1);
    const prevDateStr = current.toISOString().slice(0, 10);
    setJournalDate(prevDateStr);
  }

  function handleNextDay() {
    commitJournalText();
    const current = new Date(journalDate);
    current.setDate(current.getDate() + 1);
    const nextDateStr = current.toISOString().slice(0, 10);
    setJournalDate(nextDateStr);
  }

  function formatJournalDate(dateStr) {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-US", { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }).toUpperCase();
    } catch {
      return dateStr;
    }
  }

  function getJournalDatesList() {
    return Object.keys(journalData)
      .filter(d => {
        const entry = journalData[d];
        return (entry.strokes && entry.strokes.length > 0) || (entry.texts && entry.texts.length > 0);
      })
      .sort((a, b) => b.localeCompare(a));
  }

  function maybeExpandJournalCanvas(y) {
    if (y > journalCanvasHeight - 120) {
      setJournalCanvasHeight(h => h + 400);
    }
  }

  function handleClearJournal() {
    const updatedData = {
      ...journalData,
      [journalDate]: { strokes: [], texts: [] }
    };
    setJournalData(updatedData);
    setJournalCanvasHeight(1200);
    saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    recordAction("Journal cleared for today.");
  }

  function handleUndoJournal() {
    const dateEntry = journalData[journalDate] || { strokes: [], texts: [] };
    const strokes = dateEntry.strokes || [];
    const texts = dateEntry.texts || [];
    
    if (texts.length > 0) {
      const updatedEntry = {
        ...dateEntry,
        texts: texts.slice(0, -1)
      };
      const updatedData = {
        ...journalData,
        [journalDate]: updatedEntry
      };
      setJournalData(updatedData);
      saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    } else if (strokes.length > 0) {
      const updatedEntry = {
        ...dateEntry,
        strokes: strokes.slice(0, -1)
      };
      const updatedData = {
        ...journalData,
        [journalDate]: updatedEntry
      };
      setJournalData(updatedData);
      saveJournal(updatedData).catch(err => console.error("Failed to save journal", err));
    }
  }

  function handleExportJournalPng() {
    if (journalCanvasRef.current) {
      const link = document.createElement("a");
      link.download = `journal_${journalDate}.png`;
      link.href = journalCanvasRef.current.toDataURL("image/png");
      link.click();
      recordAction("Journal page exported as PNG.");
    }
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
    setMathCorrectCount(0);
    setMathWrongCount(0);
    setMathStreak(0);
    setMathRevealTable(false);
    
    if (mathModelStatus === "loaded") {
      setMathStage("discipline");
    } else {
      setMathStage("loading");
    }
    
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
          {mathStage === "loading" && (
            <div className="math-loading-container">
              <div className="math-hex-logo spinner">∑</div>
              <h3>Warming up local AI models...</h3>
              <p>Initializing client-side digit classifier (MNIST ONNX Core)...</p>
              <div className="math-loading-bar-container">
                <div className="math-loading-bar-fill" />
              </div>
              <button className="secondary-button font-pixel" onClick={() => setMathStage("discipline")} style={{ marginTop: '20px' }}>
                Skip Loading →
              </button>
            </div>
          )}

          {mathStage === "discipline" && (
            <div className="math-trainer-container">
              <div className="math-header">
                <div>
                  <span className="mode-kicker">✦ MATH PRACTISE • SELECT DISCIPLINE</span>
                  <h3 className="font-pixel">Choose Your Training Dojo</h3>
                </div>
                <button className="ghost-button font-pixel" onClick={() => setScreen("home")}>Exit</button>
              </div>
              <div className="math-discipline-cards">
                <button className="discipline-card tables" onClick={() => { setMathMode("tables"); setMathStage("configure"); }}>
                  <span className="discipline-icon">⚔</span>
                  <div>
                    <h4 className="font-pixel">TABLES (पहाड़े)</h4>
                    <p>Master multiplication tables 1–45</p>
                  </div>
                </button>
                <button className="discipline-card squares" onClick={() => { setMathMode("squares"); setMathStage("configure"); }}>
                  <span className="discipline-icon">🛡</span>
                  <div>
                    <h4 className="font-pixel">SQUARES (वर्ग)</h4>
                    <p>Practice perfect squares up to 50²</p>
                  </div>
                </button>
                <button className="discipline-card cubes" onClick={() => { setMathMode("cubes"); setMathStage("configure"); }}>
                  <span className="discipline-icon">🌀</span>
                  <div>
                    <h4 className="font-pixel">CUBES (घन)</h4>
                    <p>Practice perfect cubes up to 30³</p>
                  </div>
                </button>
              </div>
            </div>
          )}

          {mathStage === "configure" && (
            <div className="math-trainer-container">
              <div className="math-header">
                <div>
                  <span className="mode-kicker">✦ MATH PRACTISE • CONFIGURE MISSION</span>
                  <h3 className="font-pixel">Setup Your Challenge</h3>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button className="ghost-button font-pixel" onClick={() => setMathStage("discipline")}>◀ Back</button>
                  <button className="ghost-button font-pixel" onClick={() => setScreen("home")}>Exit</button>
                </div>
              </div>

              {mathMode === "tables" ? (
                <div className="configure-section">
                  <div className="section-header">
                    <h4 className="font-pixel">SELECT TABLES (1–45)</h4>
                    <div className="helper-buttons">
                      <button className="tiny-button" onClick={() => {
                        const all = {};
                        for (let i = 1; i <= 45; i++) all[i] = true;
                        setMathTablesConfig(all);
                        localStorage.setItem("anki_math_tables", JSON.stringify(all));
                      }}>Select All</button>
                      <button className="tiny-button" onClick={() => {
                        setMathTablesConfig({});
                        localStorage.setItem("anki_math_tables", JSON.stringify({}));
                      }}>Clear All</button>
                    </div>
                  </div>
                  <div className="tables-grid">
                    {Array.from({ length: 45 }, (_, i) => i + 1).map((n) => (
                      <button
                        key={n}
                        className={`grid-cb ${mathTablesConfig[n] ? "checked" : ""}`}
                        onClick={() => {
                          const next = { ...mathTablesConfig, [n]: !mathTablesConfig[n] };
                          setMathTablesConfig(next);
                          localStorage.setItem("anki_math_tables", JSON.stringify(next));
                        }}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="configure-section">
                  <div className="section-header">
                    <h4 className="font-pixel">SELECT RANGE</h4>
                    <div className="helper-buttons">
                      <button className="tiny-button" onClick={() => {
                        const maxVal = mathMode === "squares" ? 50 : 30;
                        const all = {};
                        for (let s = 1; s <= maxVal; s += 5) {
                          const e = Math.min(s + 4, maxVal);
                          all[`${s}-${e}`] = true;
                        }
                        const key = mathMode === "squares" ? "anki_math_squares" : "anki_math_cubes";
                        if (mathMode === "squares") setMathSquaresConfig(all);
                        else setMathCubesConfig(all);
                        localStorage.setItem(key, JSON.stringify(all));
                      }}>Select All</button>
                      <button className="tiny-button" onClick={() => {
                        const key = mathMode === "squares" ? "anki_math_squares" : "anki_math_cubes";
                        if (mathMode === "squares") setMathSquaresConfig({});
                        else setMathCubesConfig({});
                        localStorage.setItem(key, JSON.stringify({}));
                      }}>Clear All</button>
                    </div>
                  </div>
                  <div className="ranges-grid">
                    {(() => {
                      const maxVal = mathMode === "squares" ? 50 : 30;
                      const ranges = [];
                      for (let s = 1; s <= maxVal; s += 5) {
                        const e = Math.min(s + 4, maxVal);
                        ranges.push(`${s}-${e}`);
                      }
                      const activeConfig = mathMode === "squares" ? mathSquaresConfig : mathCubesConfig;
                      return ranges.map((r) => (
                        <button
                          key={r}
                          className={`grid-cb range-cb ${activeConfig[r] ? "checked" : ""}`}
                          onClick={() => {
                            const next = { ...activeConfig, [r]: !activeConfig[r] };
                            const key = mathMode === "squares" ? "anki_math_squares" : "anki_math_cubes";
                            if (mathMode === "squares") setMathSquaresConfig(next);
                            else setMathCubesConfig(next);
                            localStorage.setItem(key, JSON.stringify(next));
                          }}
                        >
                          {r}
                        </button>
                      ));
                    })()}
                  </div>
                </div>
              )}

              <div className="configure-section timer-section">
                <h4 className="font-pixel">SELECT TIMER</h4>
                <div className="timer-options-row">
                  {[
                    { value: 0, label: "NONE" },
                    { value: 1, label: "1 MIN" },
                    { value: 3, label: "3 MIN" },
                    { value: 5, label: "5 MIN" }
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      className={`timer-cb ${mathTimerConfig === opt.value ? "checked" : ""}`}
                      onClick={() => {
                        setMathTimerConfig(opt.value);
                        localStorage.setItem("anki_math_timer", String(opt.value));
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <button
                className="start-mission-btn font-pixel"
                onClick={() => {
                  const config = mathMode === "tables" ? mathTablesConfig : (mathMode === "squares" ? mathSquaresConfig : mathCubesConfig);
                  const hasSelected = Object.keys(config).some(k => config[k]);
                  if (!hasSelected) {
                    setMathResult("SELECT AT LEAST ONE TARGET, NINJA!");
                    return;
                  }
                  setMathResult("");
                  setMathCorrectCount(0);
                  setMathWrongCount(0);
                  setMathStreak(0);
                  setMathQAttempted(false);
                  setMathRevealTable(false);
                  setMathAnswer("");
                  
                  const problem = generateNextMathProblem(mathMode, mathTablesConfig, mathSquaresConfig, mathCubesConfig);
                  if (problem) {
                    setMathProblem(problem);
                    setMathStage("practice");
                    if (mathTimerConfig > 0) {
                      setMathTimeLeft(mathTimerConfig * 60);
                    }
                    setTimeout(() => {
                      handleClearMathCanvas();
                    }, 50);
                  } else {
                    setMathResult("GENERATE PROBLEM FAILED");
                  }
                }}
              >
                ▶ START MISSION
              </button>

              {mathResult && <div className="config-error-message">{mathResult}</div>}
            </div>
          )}

          {mathStage === "practice" && (
            <div className="math-practice-container">
              <div className="math-header">
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button className="ghost-button font-pixel" onClick={() => setMathStage("configure")}>◀ Back</button>
                  <div className="math-mode-badge uppercase font-pixel">{mathMode} MODE</div>
                </div>
                <div className="practice-meta">
                  <span className="practice-timer-display font-pixel">
                    {mathTimerConfig > 0
                      ? `TIME: ${Math.floor(mathTimeLeft / 60)}:${String(mathTimeLeft % 60).padStart(2, "0")}`
                      : `MISSION ${mathCorrectCount + mathWrongCount + 1}`}
                  </span>
                  <span className="practice-streak-display font-pixel">
                    🔥 {mathStreak}
                  </span>
                </div>
              </div>

              <div className="math-split-workspace">
                {/* Left Panel (60%) */}
                <div className="math-workspace-left">
                  <div className="math-problem-display-card">
                    <div className="math-problem-text-giant font-pixel">{mathProblem.prompt}</div>
                  </div>

                  <div className="math-giant-input-wrapper">
                    <input
                      ref={(el) => el && el.focus()}
                      type="text"
                      pattern="[0-9]*"
                      inputMode="numeric"
                      className={`math-large-input ${mathResult.includes("Correct") || mathResult.includes("COWABUNGA") || mathResult.includes("LETHAL") || mathResult.includes("PERFECT") || mathResult.includes("NAILED") || mathResult.includes("KAME-HA") ? "correct-border" : (mathResult.includes("WRONG") ? "wrong-border" : "")}`}
                      placeholder="?"
                      value={mathAnswer}
                      onChange={(e) => {
                        const val = e.target.value;
                        if (/^\d*$/.test(val)) {
                          setMathAnswer(val);
                        }
                      }}
                    />
                    {mathResult && (
                      <div className={`math-feedback-text font-pixel ${mathResult.includes("Correct") || mathResult.includes("COWABUNGA") || mathResult.includes("LETHAL") || mathResult.includes("PERFECT") || mathResult.includes("NAILED") || mathResult.includes("KAME-HA") ? "green-text" : "red-text"}`}>
                        {mathResult}
                      </div>
                    )}
                  </div>

                  <div className="math-drawing-wrapper">
                    <div className="math-canvas-label-row">
                      <span>✏ Write answer below:</span>
                      {mathRecognised && <span className="ocr-recognised-badge">Recognised: {mathRecognised}</span>}
                    </div>
                    <canvas
                      ref={mathCanvasRef}
                      width={512}
                      height={200}
                      className="math-drawing-scratchpad"
                      onMouseDown={(e) => startMathDrawing(e, mathCanvasRef.current)}
                      onMouseMove={(e) => drawMath(e, mathCanvasRef.current)}
                      onMouseUp={() => stopMathDrawing(mathCanvasRef.current)}
                      onMouseLeave={() => stopMathDrawing(mathCanvasRef.current)}
                      onTouchStart={(e) => startMathDrawing(e, mathCanvasRef.current)}
                      onTouchMove={(e) => drawMath(e, mathCanvasRef.current)}
                      onTouchEnd={() => stopMathDrawing(mathCanvasRef.current)}
                    />
                  </div>

                  <div className="math-buttons-bar">
                    <button className="secondary-button" onClick={() => handleCheckMathAnswer()}>✓ Check</button>
                    <button className="ghost-button" onClick={handleClearMathCanvas}>Clear</button>
                    <button className="ghost-button" onClick={handleNextMathProblem}>Skip →</button>
                    {mathQAttempted && (
                      <button className="reveal-answer-btn font-pixel" onClick={() => setMathRevealTable(true)}>REVEAL ANSWER 👁</button>
                    )}
                  </div>
                </div>

                {/* Right Panel (40%) */}
                <div className="math-workspace-right">
                  <div className="reference-header font-pixel">▣ REFERENCE</div>
                  <div className="reference-content">
                    {!mathRevealTable ? (
                      <div className="reference-hint">
                        Draw your answer on the scratchpad or type it in.
                        <br /><br />
                        Wrong answer? Click <strong>REVEAL ANSWER</strong> to view hint helper table here.
                      </div>
                    ) : (
                      <div className="reference-reveal-details">
                        {mathMode === "tables" ? (
                          <div className="table-hint-rows">
                            {(() => {
                              const base = mathProblem.n1;
                              const asked = mathProblem.n2;
                              const rows = [];
                              for (let i = 1; i <= 20; i++) {
                                rows.push(
                                  <div key={i} className={`table-row-line ${i === asked ? "highlight-row" : ""}`}>
                                    <span>{i === asked ? "▶" : "·"}</span>
                                    <span>{base} × {String(i).padStart(2, " ")} = {base * i}</span>
                                  </div>
                                );
                              }
                              return rows;
                            })()}
                          </div>
                        ) : (
                          <div className="square-cube-reveal-hint">
                            <div className="giant-answer-badge font-pixel">
                              {mathProblem.prompt.replace("= ?", "").replace("?", "").trim()} = {mathProblem.answer}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {mathStage === "report" && (
            <div className="math-trainer-container">
              <div className="math-header">
                <div>
                  <span className="mode-kicker">✦ MISSION COMPLETED</span>
                  <h3 className="font-pixel">Training Report</h3>
                </div>
              </div>
              
              <div className="report-summary-stats">
                <div className="report-badge green">
                  <span className="report-badge-val font-pixel">{mathCorrectCount}</span>
                  <span className="report-badge-lbl">CORRECT ANSWERS</span>
                </div>
                
                <div className="report-badge purple">
                  <span className="report-badge-val font-pixel">
                    {mathCorrectCount + mathWrongCount > 0
                      ? Math.round((mathCorrectCount / (mathCorrectCount + mathWrongCount)) * 100)
                      : 0}%
                  </span>
                  <span className="report-badge-lbl">ACCURACY</span>
                </div>

                <div className="report-badge orange">
                  <span className="report-badge-val font-pixel">
                    {mathTimerConfig > 0
                      ? (mathCorrectCount / mathTimerConfig).toFixed(1)
                      : "—"}
                  </span>
                  <span className="report-badge-lbl">SPEED (Q/MIN)</span>
                </div>
              </div>

              <button className="finish-mission-btn font-pixel" onClick={() => setMathStage("discipline")}>
                FINISH MISSION
              </button>
            </div>
          )}
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
                    onClick={() => setEditorPdfPageZero(0)}
                    title="First Page"
                  >
                    «
                  </button>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={editorPdfPageZero <= 0}
                    onClick={() => setEditorPdfPageZero((prev) => Math.max(0, prev - 1))}
                    title="Previous Page (ArrowLeft)"
                  >
                    ‹ Prev
                  </button>
                  <div className="jump-page-input-wrapper" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>Page </span>
                    <input
                      type="number"
                      min="1"
                      max={editorPdfDoc.numPages}
                      value={editorPdfPageZero + 1}
                      onChange={(e) => {
                        const p = parseInt(e.target.value, 10);
                        if (!isNaN(p) && p >= 1 && p <= editorPdfDoc.numPages) {
                          setEditorPdfPageZero(p - 1);
                        }
                      }}
                      style={{
                        width: '50px',
                        textAlign: 'center',
                        padding: '2px',
                        background: 'var(--panel-3)',
                        color: 'var(--text)',
                        border: '1px solid var(--border)',
                        borderRadius: '4px'
                      }}
                    />
                    <span> of {editorPdfDoc.numPages}</span>
                  </div>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={editorPdfPageZero >= editorPdfDoc.numPages - 1}
                    onClick={() => setEditorPdfPageZero((prev) => Math.min(editorPdfDoc.numPages - 1, prev + 1))}
                    title="Next Page (ArrowRight)"
                  >
                    Next ›
                  </button>
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={editorPdfPageZero >= editorPdfDoc.numPages - 1}
                    onClick={() => setEditorPdfPageZero(editorPdfDoc.numPages - 1)}
                    title="Last Page"
                  >
                    »
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
                      <>
                        <img alt="" draggable="false" src={editorImage.src} style={{ maxHeight: '600px', margin: '0 auto' }} />
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
                      </>
                    ) : (
                      <div
                        className="pdf-canvas-wrapper"
                        style={{
                          position: 'relative',
                          display: 'block',
                          margin: '0 auto',
                          width: 'fit-content',
                          maxWidth: '100%',
                          height: 'fit-content'
                        }}
                      >
                        <canvas ref={editorCanvasRef} style={{ maxWidth: '100%', maxHeight: '600px', display: 'block', margin: '0 auto' }} />
                        {editorPreviewMasks.map((mask) => {
                          const isSelected = editorSelectedMaskIds.has(mask.id);
                          const pageWidth = editorPdfPageDims.width || 1;
                          const pageHeight = editorPdfPageDims.height || 1;
                          const style = {
                            left: `${(mask.x / pageWidth) * 100}%`,
                            top: `${(mask.y / pageHeight) * 100}%`,
                            width: `${(mask.width / pageWidth) * 100}%`,
                            height: `${(mask.height / pageHeight) * 100}%`,
                          };
                          return (
                            <span
                              className={
                                mask.id === "editor-mask-preview"
                                  ? "draft-mask mask-box"
                                  : `mask-box ${isSelected ? "selected" : ""}`
                              }
                              key={mask.id}
                              style={style}
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
                    )}
                  </div>
                ) : (
                  <div
                    className={`mask-empty ${isDragOver ? "dragover" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setIsDragOver(true);
                    }}
                    onDragLeave={() => setIsDragOver(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setIsDragOver(false);
                      const file = e.dataTransfer.files?.[0];
                      processLoadedFile(file);
                    }}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--muted)',
                      gap: '8px',
                      border: isDragOver ? '2px dashed var(--accent)' : '2px dashed transparent',
                      background: isDragOver ? 'rgba(167, 125, 255, 0.05)' : 'transparent',
                      transition: 'all 0.2s ease',
                      borderRadius: '4px',
                      height: '100%'
                    }}
                  >
                    <span style={{ fontSize: '24px' }}>📂</span>
                    <p style={{ margin: 0, fontSize: '13px', fontWeight: 'bold' }}>
                      Drag & Drop a PDF or Image here
                    </p>
                    <p style={{ margin: 0, fontSize: '11px' }}>
                      or use the sidebar buttons
                    </p>
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
      const datesWithEntries = getJournalDatesList();
      return (
        <section className="journal-panel">
          {/* Header */}
          <div className="journal-header">
            <div className="journal-header-left">
              <span className="journal-kicker">SHINOBI LOGBOOK</span>
              <h2>Daily Journal</h2>
            </div>
            
            {/* Interactive Date Selector */}
            <div className="journal-date-navigator">
              <button 
                className="journal-date-arrow" 
                onClick={handlePrevDay}
                title="Previous Day"
                type="button"
              >
                ◀
              </button>
              <input 
                type="date" 
                className="journal-date-input"
                value={journalDate} 
                onChange={(e) => {
                  commitJournalText();
                  setJournalDate(e.target.value);
                }} 
              />
              <span className="journal-date-display">
                {formatJournalDate(journalDate)}
              </span>
              <button 
                className="journal-date-arrow" 
                onClick={handleNextDay}
                title="Next Day"
                type="button"
              >
                ▶
              </button>
            </div>
            
            <button
              className="ghost-button journal-back-btn"
              onClick={() => {
                commitJournalText();
                setScreen("home");
                recordAction("Journal closed.");
              }}
              type="button"
            >
              Back [ESC]
            </button>
          </div>

          <div className="journal-split-workspace">
            {/* Sidebar with log list */}
            <aside className="journal-sidebar">
              <div className="journal-sidebar-title">PAST ENTRIES</div>
              <div className="journal-sidebar-list">
                {datesWithEntries.length > 0 ? (
                  datesWithEntries.map((d) => (
                    <button
                      key={d}
                      className={`journal-sidebar-item ${d === journalDate ? "active" : ""}`}
                      onClick={() => {
                        commitJournalText();
                        setJournalDate(d);
                      }}
                      type="button"
                    >
                      <span className="sidebar-item-dot">◈</span>
                      <span className="sidebar-item-date">{d}</span>
                    </button>
                  ))
                ) : (
                  <div className="sidebar-empty">No entries yet. Start writing!</div>
                )}
              </div>
            </aside>

            {/* Main Canvas Workspace */}
            <div className="journal-canvas-container">
              <div 
                className="journal-canvas-wrapper"
                style={{ 
                  position: "relative", 
                  width: "900px", 
                  height: `${journalCanvasHeight}px`,
                  margin: "0 auto" 
                }}
              >
                <canvas
                  ref={journalCanvasRef}
                  onMouseDown={startJournalDrawing}
                  onMouseMove={drawJournal}
                  onMouseUp={stopJournalDrawing}
                  onMouseLeave={stopJournalDrawing}
                  onTouchStart={startJournalDrawing}
                  onTouchMove={drawJournal}
                  onTouchEnd={stopJournalDrawing}
                  style={{
                    display: "block",
                    width: "900px",
                    height: `${journalCanvasHeight}px`,
                    cursor: journalMode === "pen" ? "crosshair" : journalMode === "eraser" ? "cell" : "text"
                  }}
                />
                {/* Active Text Input overlay */}
                {journalTextPos && (
                  <input
                    ref={journalTextInputRef}
                    type="text"
                    value={journalTextBuf}
                    onChange={(e) => setJournalTextBuf(e.target.value)}
                    onKeyDown={handleJournalTextKeyDown}
                    onBlur={commitJournalText}
                    style={{
                      position: "absolute",
                      left: `${(journalTextPos.x / 900) * 100}%`,
                      top: `${(journalTextPos.y / journalCanvasHeight) * 100}%`,
                      transform: "translateY(-80%)",
                      font: `${journalTextSize}px Segoe UI, sans-serif`,
                      color: JOURNAL_COLORS[journalColorIdx],
                      background: "transparent",
                      border: "none",
                      outline: "none",
                      borderBottom: `1px dashed ${JOURNAL_COLORS[journalColorIdx]}`,
                      caretColor: JOURNAL_COLORS[journalColorIdx],
                      zIndex: 10,
                      minWidth: "150px",
                      padding: "0 2px"
                    }}
                  />
                )}
              </div>
            </div>
          </div>

          {/* Floating Toolbar Controls */}
          <div className="journal-toolbar">
            <div className="journal-toolbar-group">
              <span className="toolbar-label">MODE:</span>
              <button 
                className={`toolbar-btn ${journalMode === "pen" ? "active" : ""}`}
                onClick={() => { commitJournalText(); setJournalMode("pen"); }}
                title="Pen Tool"
                type="button"
              >
                ✏️ PEN
              </button>
              <button 
                className={`toolbar-btn ${journalMode === "eraser" ? "active" : ""}`}
                onClick={() => { commitJournalText(); setJournalMode("eraser"); }}
                title="Eraser Tool"
                type="button"
              >
                🧽 ERASER
              </button>
              <button 
                className={`toolbar-btn ${journalMode === "text" ? "active" : ""}`}
                onClick={() => setJournalMode("text")}
                title="Text Block Tool"
                type="button"
              >
                ⌨️ TEXT
              </button>
            </div>

            {journalMode !== "eraser" && (
              <div className="journal-toolbar-group">
                <span className="toolbar-label">COLOR:</span>
                <div className="journal-colors-list">
                  {JOURNAL_COLORS.map((color, idx) => (
                    <button
                      key={color}
                      className={`journal-color-dot ${journalColorIdx === idx ? "active" : ""}`}
                      style={{ backgroundColor: color }}
                      onClick={() => setJournalColorIdx(idx)}
                      title={`Select Color ${idx + 1}`}
                      type="button"
                    />
                  ))}
                </div>
              </div>
            )}

            {journalMode === "text" && (
              <div className="journal-toolbar-group">
                <span className="toolbar-label">SIZE:</span>
                <select 
                  className="journal-size-select"
                  value={journalTextSize}
                  onChange={(e) => setJournalTextSize(Number(e.target.value))}
                >
                  <option value={12}>12px</option>
                  <option value={14}>14px</option>
                  <option value={16}>16px</option>
                  <option value={18}>18px</option>
                  <option value={24}>24px</option>
                  <option value={32}>32px</option>
                </select>
              </div>
            )}

            <div className="journal-toolbar-separator" />

            <div className="journal-toolbar-group">
              <button 
                className="toolbar-btn action-btn" 
                onClick={handleUndoJournal}
                title="Undo last stroke or text"
                type="button"
              >
                ↩️ UNDO
              </button>
              <button 
                className="toolbar-btn action-btn danger-btn" 
                onClick={handleClearJournal}
                title="Clear current day's sheet"
                type="button"
              >
                🗑️ CLEAR
              </button>
              <button 
                className="toolbar-btn action-btn success-btn" 
                onClick={handleExportJournalPng}
                title="Export as PNG image"
                type="button"
              >
                💾 EXPORT
              </button>
            </div>
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
            <button
              className="toggle-row"
              onClick={handleForceResetFromBackend}
              type="button"
              style={{
                color: (!isOnline || !isApiReachable) ? "#888888" : "#FF4444",
                cursor: (!isOnline || !isApiReachable) ? "not-allowed" : "pointer"
              }}
              disabled={!isOnline || !isApiReachable}
            >
              <span>Reset Local Cache</span>
              <strong>{(!isOnline || !isApiReachable) ? "DISABLED (OFFLINE)" : "RELOAD FROM SERVER"}</strong>
            </button>
          </div>

          <div style={{ marginTop: "2rem", borderTop: "1px solid var(--border)", paddingTop: "1.5rem" }}>
            <span className="mode-kicker" style={{ color: "var(--purple)", display: "block", marginBottom: "0.5rem" }}>Keybinds</span>
            <h4 style={{ marginBottom: "1rem", color: "var(--text)" }}>Keyboard Shortcuts</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "10px", maxHeight: "280px", overflowY: "auto", paddingRight: "8px" }}>
              {Object.entries(shortcuts).map(([actionId, sequence]) => (
                <div key={actionId} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  background: "rgba(22, 27, 37, 0.6)",
                  padding: "10px 14px",
                  borderRadius: "4px",
                  border: "1px solid var(--border)"
                }}>
                  <span style={{ fontSize: "11px", color: "var(--muted)" }}>{shortcutLabels[actionId] || actionId}</span>
                  <button
                    className="ghost-button"
                    style={{
                      minWidth: "120px",
                      minHeight: "32px",
                      padding: "4px 8px",
                      fontSize: "10px",
                      borderColor: activeRecordingId === actionId ? "var(--neon)" : "var(--border)",
                      color: activeRecordingId === actionId ? "var(--neon)" : "var(--text)"
                    }}
                    onClick={() => setActiveRecordingId(actionId)}
                  >
                    {activeRecordingId === actionId ? "Press keys..." : sequence || "None"}
                  </button>
                </div>
              ))}
            </div>
            {Object.keys(shortcuts).length > 0 && (
              <button 
                className="ghost-button"
                onClick={() => {
                  setShortcuts(defaultShortcuts);
                  localStorage.removeItem("anki_shortcuts");
                  recordAction("All keyboard shortcuts reset to defaults.");
                }}
                style={{ marginTop: "1rem", color: "var(--red)", borderColor: "var(--red)" }}
              >
                Reset to Defaults
              </button>
            )}
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
                if (!isOnline || !isApiReachable) {
                  alert("Sync is not available while offline.");
                  return;
                }
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
              disabled={!isOnline || !isApiReachable}
              type="button"
              style={{
                background: (!isOnline || !isApiReachable) ? "rgba(120, 120, 120, 0.1)" : "rgba(106, 88, 224, 0.1)",
                border: (!isOnline || !isApiReachable) ? "1px dashed #888888" : "1px dashed #6A58E0",
                borderRadius: "8px",
                cursor: (!isOnline || !isApiReachable) ? "not-allowed" : "pointer",
                display: "flex",
                flexDirection: "column",
                padding: "12px",
                alignItems: "center",
                justifyContent: "center",
                color: (!isOnline || !isApiReachable) ? "#888888" : "inherit"
              }}
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
  const isMathScreen = screen === "math";
  const isJournalScreen = screen === "journal";

  return (
    <div
      className={`app-shell ${classicMode ? "classic-mode" : ""} ${
        isReviewScreen ? "review-fullscreen" : ""
      } ${isEditorScreen ? "editor-fullscreen review-fullscreen" : ""} ${
        isMathScreen ? "math-fullscreen review-fullscreen" : ""
      } ${isJournalScreen ? "journal-fullscreen review-fullscreen" : ""}`}
    >
      <div className="scanlines" />
      <header className="topbar local-topbar">
        <div className="brand">
          <h1 data-text="ANKI OCCLUSION">ANKI OCCLUSION</h1>
        </div>
        <nav className="nav-links local-nav">
          <button onClick={handleMathNav} type="button">
            🧮 Math Trainer
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
          {!(isOnline && isApiReachable) ? (
            <div className="sync-badge offline" style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(235, 94, 40, 0.15)", border: "1px solid #EB5E28", color: "#EB5E28", padding: "6px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "bold" }} title="Working locally out of IndexedDB">
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#EB5E28", display: "inline-block" }}></span>
              Offline
            </div>
          ) : pendingCount > 0 ? (
            <button
              className="sync-badge pending"
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
              style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(244, 208, 111, 0.15)", border: "1px solid #F4D06F", color: "#F4D06F", padding: "6px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "bold", cursor: "pointer" }}
              title="Click to sync local changes"
            >
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#F4D06F", display: "inline-block" }}></span>
              Sync Pending ({pendingCount})
            </button>
          ) : (
            <div className="sync-badge synced" style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(60, 186, 126, 0.15)", border: "1px solid #3CBA7E", color: "#3CBA7E", padding: "6px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "bold" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#3CBA7E", display: "inline-block" }}></span>
              Online & Synced
            </div>
          )}
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
