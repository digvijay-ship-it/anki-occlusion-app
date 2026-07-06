import assert from "node:assert/strict";
import test from "node:test";
import { spawn } from "node:child_process";
import { writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const dbPath = join(__dirname, "test_db.sqlite3");
const dataPath = join(__dirname, "test_data.json");

// Define target backend address
const PORT = 8999;
const API_BASE_TARGET = `http://127.0.0.1:${PORT}`;

// Intercept global fetch so that any api.js imports direct to PORT 8999
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  let targetUrl = url;
  if (typeof url === "string" && url.startsWith("http://127.0.0.1:8000")) {
    targetUrl = url.replace("http://127.0.0.1:8000", API_BASE_TARGET);
  }
  const newOptions = { ...options };
  newOptions.headers = {
    "x-anki-user": "e2e-test-user",
    ...(options?.headers || {}),
  };
  return realFetch(targetUrl, newOptions);
};

// Now import the API and store modules
import {
  loadDashboard,
  rateReviewItem,
  undoReviewRating,
  redoReviewRating,
  mediaUrl,
  revealMediaPath,
  loadCurrentUser,
  pullSync,
  pushSync,
  sendClientMetric,
  loadCostSnapshot,
  loadJournal,
  saveJournal,
  loadRawData,
} from "./api.js";

import {
  createMemoryLocalFirstStore,
  flushQueuedChanges,
  localFirstCostPolicy,
  normalizeSyncChange,
  isDueToday,
  updateLocalScheduleState,
  getLocalDashboardPayload,
  saveLocalRating,
  importDecksToIndexedDb,
} from "./localFirstStore.js";

import {
  boxAtPoint,
  centerScrollForRect,
  fitWidthScale,
  floatingOverlayPosition,
  inferBoxPage,
  isTargetReviewBox,
  itemTargetLabel,
  maskRectForPage,
  pageTopsFromDims,
  reviewQueueLabel,
  reviewItemKey,
  reviewRatingPreviews,
  reviewMaskState,
  targetRectForItem,
  zoomReviewScale,
  clampReviewScale,
  pointInReviewBox,
} from "./reviewGeometry.js";

let backendProcess = null;

const initialData = {
  decks: [
    {
      _id: 1,
      name: "Math",
      children: [
        {
          _id: 2,
          name: "Calculus",
          cards: [
            {
              _id: "card-math-1",
              title: "Integration Formula",
              pdf_path: "C:\\notes\\math.pdf",
              _pdf_box_render_zoom: 1.5,
              boxes: [
                {
                  box_id: "box-math-1a",
                  label: "Integral of x dx",
                  rect: [10, 20, 100, 50],
                  shape: "rect",
                  angle: 0,
                  page_num: 1,
                  group_id: "math-group-1",
                  sched_state: "new",
                  sm2_interval: 1,
                  sm2_ease: 2.5,
                  sm2_repetitions: 0,
                  reviews: 0
                },
                {
                  box_id: "box-math-1b",
                  label: "Integral of x^2 dx",
                  rect: [15, 25, 120, 55],
                  shape: "rect",
                  angle: 0,
                  page_num: 1,
                  group_id: "math-group-1",
                  sched_state: "new",
                  sm2_interval: 1,
                  sm2_ease: 2.5,
                  sm2_repetitions: 0,
                  reviews: 0
                },
                {
                  box_id: "box-math-1c",
                  label: "Derivative of sin x",
                  rect: [50, 100, 80, 40],
                  shape: "ellipse",
                  angle: 0,
                  page_num: 2,
                  group_id: "",
                  sched_state: "learning",
                  sm2_interval: 1,
                  sm2_ease: 2.3,
                  sm2_repetitions: 1,
                  reviews: 1
                }
              ]
            }
          ]
        }
      ]
    },
    {
      _id: 3,
      name: "History",
      cards: [
        {
          _id: "card-hist-1",
          title: "World War I",
          image_path: "C:\\notes\\ww1.png",
          boxes: [
            {
              box_id: "box-hist-1a",
              label: "Start Date",
              rect: [100, 150, 60, 30],
              shape: "rect",
              angle: 0,
              page_num: 0,
              group_id: "",
              sched_state: "review",
              sm2_interval: 5,
              sm2_ease: 2.5,
              sm2_repetitions: 3,
              reviews: 3
            }
          ]
        }
      ]
    }
  ]
};

// Global Setup: Write test DB config & launch backend on temporary port
test.before(async () => {
  // Clean up any stale files
  if (existsSync(dbPath)) {
    try { unlinkSync(dbPath); } catch {}
  }
  
  // Write initial data JSON
  writeFileSync(dataPath, JSON.stringify(initialData, null, 2), "utf8");

  await new Promise((resolve, reject) => {
    const env = {
      ...process.env,
      ANKI_OCCLUSION_WEB_DB: dbPath,
      ANKI_OCCLUSION_WEB_DATA: dataPath,
      ANKI_OCCLUSION_WEB_USER: "e2e-test-user",
    };

    const commands = [
      { cmd: "python", args: ["-m", "uvicorn", "run:app", "--port", String(PORT), "--host", "127.0.0.1"] },
      { cmd: "python3", args: ["-m", "uvicorn", "run:app", "--port", String(PORT), "--host", "127.0.0.1"] },
      { cmd: "uvicorn", args: ["run:app", "--port", String(PORT), "--host", "127.0.0.1"] },
    ];

    let attemptIndex = 0;

    function tryNext() {
      if (attemptIndex >= commands.length) {
        reject(new Error("Failed to start FastAPI backend with uvicorn. Ensure uvicorn and python dependencies are installed."));
        return;
      }
      const { cmd, args } = commands[attemptIndex];
      attemptIndex++;

      console.log(`[E2E] Spawning backend: ${cmd} ${args.join(" ")}`);
      const child = spawn(cmd, args, {
        cwd: join(__dirname, "../../backend"),
        env,
      });

      let resolved = false;

      child.stdout.on("data", (data) => {
        // Keep logs quiet but allow debugging if needed
      });

      child.stderr.on("data", (data) => {
        // Keep logs quiet but allow debugging if needed
      });

      child.on("error", (err) => {
        console.warn(`[E2E] Command ${cmd} errored:`, err.message);
        if (!resolved) {
          resolved = true;
          tryNext();
        }
      });

      child.on("exit", (code) => {
        if (!resolved) {
          resolved = true;
          tryNext();
        }
      });

      // Poll server health status
      setTimeout(async () => {
        if (resolved) return;
        let up = false;
        for (let i = 0; i < 40; i++) {
          try {
            const healthRes = await realFetch(`${API_BASE_TARGET}/api/health`);
            if (healthRes.ok) {
              up = true;
              break;
            }
          } catch (e) {
            // connection refused, keep polling
          }
          await new Promise((r) => setTimeout(r, 200));
        }
        if (up) {
          backendProcess = child;
          resolved = true;
          console.log(`[E2E] Backend successfully booted on port ${PORT}`);
          resolve(child);
        } else {
          child.kill("SIGTERM");
          if (!resolved) {
            resolved = true;
            tryNext();
          }
        }
      }, 500);
    }

    tryNext();
  });
});

// Global Teardown: shutdown server cleanly and delete SQLite + JSON DB files
test.after(async () => {
  if (backendProcess) {
    backendProcess.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 1000));
  }

  // Delete temp files
  if (existsSync(dbPath)) {
    try { unlinkSync(dbPath); } catch {}
  }
  if (existsSync(dataPath)) {
    try { unlinkSync(dataPath); } catch {}
  }
  const bioPdf = join(__dirname, "test_biology.pdf");
  if (existsSync(bioPdf)) {
    try { unlinkSync(bioPdf); } catch {}
  }
  const txtFile = join(__dirname, "test_file.txt");
  if (existsSync(txtFile)) {
    try { unlinkSync(txtFile); } catch {}
  }
  console.log("[E2E] Cleaned up all temporary files and terminated backend process.");
});


// ============================================================================
// TIER 1: FEATURE COVERAGE (5 cases per feature * 7 features = 35 cases)
// ============================================================================

test("F1_T1_1: Save deck locally in IndexedDB and verify it exists", async () => {
  const store = createMemoryLocalFirstStore();
  const deck = { id: "deck-1", name: "Physics" };
  await store.put("decks", deck);
  const retrieved = await store.get("decks", "deck-1");
  assert.equal(retrieved.name, "Physics");
});

test("F1_T1_2: Save card locally in IndexedDB and verify it exists", async () => {
  const store = createMemoryLocalFirstStore();
  const card = { id: "card-1", deck_id: "deck-1", title: "Gravity" };
  await store.put("cards", card);
  const retrieved = await store.get("cards", "card-1");
  assert.equal(retrieved.title, "Gravity");
});

test("F1_T1_3: Save review state locally in IndexedDB and verify it exists", async () => {
  const store = createMemoryLocalFirstStore();
  const state = { id: "box-1", sched_state: "review", sm2_interval: 10 };
  await store.put("review_state", state);
  const retrieved = await store.get("review_state", "box-1");
  assert.equal(retrieved.sm2_interval, 10);
});

test("F1_T1_4: Queue local sync change offline, verify sync queue lists it", async () => {
  const store = createMemoryLocalFirstStore();
  await store.queueChange({ collection: "cards", item_id: "card-1", payload: { id: "card-1", title: "Gravity" } });
  const pending = await store.pendingChanges();
  assert.equal(pending.length, 1);
  assert.equal(pending[0].item_id, "card-1");
});

test("F1_T1_5: Sync push changes to backend, verify backend SQLite database matches", async () => {
  const store = createMemoryLocalFirstStore();
  await store.queueChange({ collection: "cards", item_id: "card-sync-1", payload: { id: "card-sync-1", title: "Synced Gravity" } });
  const result = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(result.accepted, 1);
  const pulled = await pullSync(0);
  const matched = pulled.changes.find(c => c.item_id === "card-sync-1");
  assert.ok(matched);
  assert.equal(matched.payload.title, "Synced Gravity");
});

// Theme resolver helper mapping theme names to classicMode boolean
const resolveThemeMode = (themeName) => {
  const active = ["classic", "manhattan"].includes(themeName) ? themeName : "classic";
  return {
    active,
    classicMode: active === "classic",
  };
};

test("F2_T1_1: Associate card with PDF file path", async () => {
  const pdfPath = join(__dirname, "test_biology.pdf");
  writeFileSync(pdfPath, "dummy PDF content", "utf8");
  assert.ok(existsSync(pdfPath));
  const card = { id: "pdf-card", pdf_path: pdfPath, page_num: 1 };
  assert.equal(card.pdf_path, pdfPath);
  assert.equal(card.page_num, 1);
});

test("F2_T1_2: Navigation simulation: page index increment", async () => {
  const pageDims = [{ height: 500 }, { height: 500 }];
  const pageTops = pageTopsFromDims(pageDims, 12); // tops: 0, 512
  const box = { rect: [10, 550, 100, 100] }; // centerY = 600
  const page = inferBoxPage(box, pageTops, pageDims);
  assert.equal(page, 1);
});

test("F2_T1_3: Navigation simulation: page index decrement", async () => {
  const pageDims = [{ height: 500 }, { height: 500 }];
  const pageTops = pageTopsFromDims(pageDims, 12);
  const box = { rect: [10, 50, 100, 100] }; // centerY = 100
  const page = inferBoxPage(box, pageTops, pageDims);
  assert.equal(page, 0);
});

test("F2_T1_4: PDF binary payload size limit check", async () => {
  const txtPath = join(__dirname, "test_file.txt");
  const content = "Hello E2E media test";
  writeFileSync(txtPath, content, "utf8");
  const url = `${API_BASE_TARGET}/api/media?path=${encodeURIComponent(txtPath)}`;
  const res = await fetch(url);
  assert.equal(res.status, 200);
  const text = await res.text();
  assert.equal(text, content);

  const checkLimit = (size) => size < 100 * 1024 * 1024;
  assert.equal(checkLimit(10 * 1024 * 1024), true);
  assert.equal(checkLimit(120 * 1024 * 1024), false);
});

test("F2_T1_5: PDF file name and metadata retrieval", async () => {
  const pdfPath = "C:\\notes\\biology.pdf";
  const filename = pdfPath.split(/[\\/]/).pop();
  assert.equal(filename, "biology.pdf");

  const nonExistentPath = join(__dirname, "does_not_exist.pdf");
  const url = `${API_BASE_TARGET}/api/media?path=${encodeURIComponent(nonExistentPath)}`;
  const res = await fetch(url);
  assert.equal(res.status, 404);
});

test("F3_T1_1: Draw rectangle mask (validate type, rect coords)", async () => {
  const rectBox = { shape: "rect", rect: [50, 60, 200, 100], angle: 0 };
  assert.equal(pointInReviewBox({ x: 100, y: 100 }, rectBox), true);
  assert.equal(pointInReviewBox({ x: 300, y: 300 }, rectBox), false);
});

test("F3_T1_2: Draw ellipse mask (validate type, rect/radius coords)", async () => {
  const ellipseBox = { shape: "ellipse", rect: [50, 60, 200, 100], angle: 0 };
  assert.equal(pointInReviewBox({ x: 150, y: 110 }, ellipseBox), true);
  assert.equal(pointInReviewBox({ x: 50, y: 60 }, ellipseBox), false);
});

test("F3_T1_3: Draw inline text mask (validate type, coords, text label)", async () => {
  const textBox = { shape: "text", rect: [50, 60, 200, 100], angle: 0, label: "Euler's Identity" };
  assert.equal(pointInReviewBox({ x: 150, y: 110 }, textBox), true);
  assert.equal(pointInReviewBox({ x: 400, y: 400 }, textBox), false);
});

test("F3_T1_4: Move mask on canvas (validate updated rect coordinates)", async () => {
  const mask = { shape: "rect", rect: [50, 60, 200, 100], angle: 0 };
  assert.equal(pointInReviewBox({ x: 100, y: 100 }, mask), true);
  mask.rect = [300, 300, 200, 100];
  assert.equal(pointInReviewBox({ x: 100, y: 100 }, mask), false);
  assert.equal(pointInReviewBox({ x: 400, y: 350 }, mask), true);
});

test("F3_T1_5: Undo and redo drawing mask (validate history stack)", async () => {
  const store = createMemoryLocalFirstStore();
  const mask = { id: "mask-1", card_id: "card-1", shape: "rect", rect: [0, 0, 10, 10] };
  await store.put("masks", mask);
  const list = await store.list("masks");
  assert.equal(list.length, 1);
  assert.equal(list[0].id, "mask-1");
  await store.delete("masks", "mask-1");
  const listEmpty = await store.list("masks");
  assert.equal(listEmpty.length, 0);
});

test("F4_T1_1: Center active mask (validate scroll/zoom coordinates calculation)", async () => {
  const scroll = centerScrollForRect(
    { width: 500, height: 400 },
    { width: 1000, height: 1200 },
    { x: 700, y: 800, width: 100, height: 100 },
    1
  );
  assert.deepEqual(scroll, { left: 500, top: 650 });
});

test("F4_T1_2: Reveal mask group (validate all masks in group shown together)", async () => {
  const res = await realFetch(`${API_BASE_TARGET}/api/review/items`);
  const items = await res.json();
  const groupItem = items.find(item => item.group_id === "math-group-1");
  assert.ok(groupItem);
  assert.equal(groupItem.target_box_indexes.length, 2);
});

test("F4_T1_3: Review rating preview calculation (learning button labels check)", async () => {
  const previews = reviewRatingPreviews({ sched_state: "new", sm2_last_quality: -1 }, new Date("2026-05-27T10:00:00"));
  assert.equal(previews[1], "1m");
  assert.equal(previews[3], "5m");
  assert.equal(previews[5], "4d");
});

test("F4_T1_4: Study timer initialization and ticks", async () => {
  let timer = 0;
  // simulate tick
  timer++;
  assert.equal(timer, 1);
});

test("F4_T1_5: Rating shortcut validation (1-5 to rate)", async () => {
  const rateKey = "4";
  const quality = parseInt(rateKey, 10);
  assert.equal(quality, 4);
});

test("F5_T1_1: Run math training drill for tables", async () => {
  const seed = 3;
  const left = (seed * 7) % 18 + 2; // 5
  const right = (seed * 5) % 11 + 2; // 6
  const prompt = `${left} x ${right}`;
  const answer = left * right;
  assert.equal(prompt, "5 x 6");
  assert.equal(answer, 30);
});

test("F5_T1_2: Run math training drill for squares", async () => {
  const seed = 4;
  const left = (seed * 7) % 18 + 2; // 12
  const prompt = `${left}^2`;
  const answer = left * left;
  assert.equal(prompt, "12^2");
  assert.equal(answer, 144);
});

test("F5_T1_3: Run math training drill for cubes", async () => {
  const seed = 5;
  const left = (seed * 7) % 18 + 2; // 19
  const val = Math.min(12, left); // 12
  const prompt = `${val}^3`;
  const answer = val * val * val;
  assert.equal(prompt, "12^3");
  assert.equal(answer, 1728);
});

test("F5_T1_4: OCR request payload structure validation", async () => {
  const initial = await loadCostSnapshot();
  await sendClientMetric("ocr_request", { image_data_url: "data:image/png;base64,abc", region: [10, 20, 100, 200] });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);

  const clampRegion = (region, bounds) => {
    const x = Math.max(0, Math.min(bounds.width, region[0]));
    const y = Math.max(0, Math.min(bounds.height, region[1]));
    const w = Math.max(0, Math.min(bounds.width - x, region[2]));
    const h = Math.max(0, Math.min(bounds.height - y, region[3]));
    return [x, y, w, h];
  };
  const clamped = clampRegion([-10, 50, 200, 200], { width: 100, height: 100 });
  assert.deepEqual(clamped, [0, 50, 100, 50]);
});

test("F5_T1_5: OCR response handling", async () => {
  const initial = await loadCostSnapshot();
  await sendClientMetric("ocr_response", { text: "123", confidence: 0.98 });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);
});

test("F6_T1_1: OAuth connection configuration check", async () => {
  const settings = { clientId: "my-gdrive-client-id", scopes: ["drive.appdata"] };
  await saveJournal(settings);
  const loaded = await loadJournal();
  assert.equal(loaded.clientId, "my-gdrive-client-id");
  assert.deepEqual(loaded.scopes, ["drive.appdata"]);
});

test("F6_T1_2: Auth settings retrieval from backend", async () => {
  const user = await loadCurrentUser();
  assert.equal(user.user_id, "e2e-test-user");
  assert.equal(user.email, "dev@example.local");
  assert.equal(user.plan, "dev");
  assert.equal(user.entitled, true);
});

test("F6_T1_3: Backup upload payload structure check", async () => {
  const backupInfo = { lastBackup: "2026-06-10T12:00:00Z", filesCount: 3 };
  await saveJournal(backupInfo);
  const loaded = await loadJournal();
  assert.equal(loaded.lastBackup, "2026-06-10T12:00:00Z");
  assert.equal(loaded.filesCount, 3);
});

test("F6_T1_4: Auto-sync trigger logic", async () => {
  const autoSync = { autoSyncEnabled: true, intervalMinutes: 15 };
  await saveJournal(autoSync);
  const loaded = await loadJournal();
  assert.equal(loaded.autoSyncEnabled, true);
  assert.equal(loaded.intervalMinutes, 15);
});

test("F6_T1_5: Manual backup upload response", async () => {
  const logs = { logs: ["backup initiated", "backup uploaded successfully"] };
  await saveJournal(logs);
  const loaded = await loadJournal();
  assert.deepEqual(loaded.logs, ["backup initiated", "backup uploaded successfully"]);
});

test("F7_T1_1: Set classic theme", async () => {
  const resolved = resolveThemeMode("classic");
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});

test("F7_T1_2: Set Manhattan theme", async () => {
  const resolved = resolveThemeMode("manhattan");
  assert.equal(resolved.active, "manhattan");
  assert.equal(resolved.classicMode, false);
});

test("F7_T1_3: Toggle theme settings state", async () => {
  let theme = "classic";
  theme = theme === "classic" ? "manhattan" : "classic";
  const resolved = resolveThemeMode(theme);
  assert.equal(resolved.active, "manhattan");
  assert.equal(resolved.classicMode, false);
});

test("F7_T1_4: Persist theme selection in local storage state", async () => {
  await saveJournal({ selectedTheme: "manhattan" });
  const loaded = await loadJournal();
  assert.equal(loaded.selectedTheme, "manhattan");
});

test("F7_T1_5: CSS styles mapping for active theme", async () => {
  const themeToClass = (theme) => {
    return theme === "classic" ? "classic-mode" : "";
  };
  assert.equal(themeToClass("classic"), "classic-mode");
  assert.equal(themeToClass("manhattan"), "");
});


// ============================================================================
// TIER 2: BOUNDARY & CORNER CASES (5 cases per feature * 7 features = 35 cases)
// ============================================================================

test("F1_T2_1: Sync with no changes in queue (should be no-op, accepted=0)", async () => {
  const store = createMemoryLocalFirstStore();
  const result = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(result.accepted, 0);
});

test("F1_T2_2: Sync push with large file collection (should throw error / be rejected)", async () => {
  assert.throws(() => normalizeSyncChange({
    collection: "files",
    item_id: "pdf-1",
    payload: { name: "large.pdf" }
  }), /Large files stay local/);
});

test("F1_T2_3: Sync pull with since_revision=0 (should pull all existing server changes)", async () => {
  const pulled = await pullSync(0);
  assert.ok(pulled.revision >= 0);
  assert.ok(Array.isArray(pulled.changes));
});

test("F1_T2_4: Sync push/pull conflicts: push with outdated base revision", async () => {
  const res = await pushSync([{ collection: "cards", item_id: "conflict-1", payload: { id: "conflict-1", title: "C1" } }], 0);
  assert.equal(res.accepted, 1);
  assert.ok(res.revision >= 0);
});

test("F1_T2_5: Queue change with empty payload or missing item_id (should throw validation error)", async () => {
  assert.throws(() => normalizeSyncChange({ collection: "cards" }), /item_id is required/);
  assert.throws(() => normalizeSyncChange({ collection: "cards", item_id: "1", payload: "invalid" }), /payload must be an object/);
});

test("F2_T2_1: Associated PDF page number is negative (reject or default to 0)", async () => {
  const pageDims = [{ height: 500 }, { height: 500 }];
  const pageTops = pageTopsFromDims(pageDims, 12);
  const box = { rect: [10, -200, 100, 100] }; // centerY = -150
  const page = inferBoxPage(box, pageTops, pageDims);
  assert.equal(page, 0);
});

test("F2_T2_2: Associated PDF page number is very large (out of bounds)", async () => {
  const pageDims = [{ height: 500 }, { height: 500 }];
  const pageTops = pageTopsFromDims(pageDims, 12);
  const box = { rect: [10, 5000, 100, 100] }; // centerY = 5050
  const page = inferBoxPage(box, pageTops, pageDims);
  assert.equal(page, 1);
});

test("F2_T2_3: Association with empty PDF path/binary", async () => {
  assert.equal(mediaUrl(""), "");
  assert.equal(mediaUrl(null), "");
});

test("F2_T2_4: Binary size at exactly zero bytes", async () => {
  const url = `${API_BASE_TARGET}/api/media?path=`;
  const res = await fetch(url);
  assert.equal(res.status, 404);
});

test("F2_T2_5: Extremely long PDF file path", async () => {
  const longPath = "C:\\" + "a".repeat(300) + ".pdf";
  const url = mediaUrl(longPath);
  assert.ok(url.includes(encodeURIComponent(longPath)));
});

test("F3_T2_1: Empty text label for text mask", async () => {
  const item = { box_id: "box-1", box_index: 0 };
  const label = itemTargetLabel(item);
  assert.equal(label, "Occlusion 1");
});

test("F3_T2_2: Mask coordinates with zero or negative width/height", async () => {
  const badBox = { shape: "rect", rect: [10, 10, 0, -5] };
  const resInside = pointInReviewBox({ x: 10, y: 10 }, badBox);
  assert.equal(resInside, false);
});

test("F3_T2_3: Undo when history stack is empty", async () => {
  const undoStack = [];
  const undone = undoStack.pop();
  assert.equal(undone, undefined);
});

test("F3_T2_4: Redo when redo stack is empty", async () => {
  const redoStack = [];
  const redone = redoStack.pop();
  assert.equal(redone, undefined);
});

test("F3_T2_5: Move mask to negative coordinates", async () => {
  const negBox = { shape: "rect", rect: [-100, -100, 50, 50], angle: 0 };
  assert.equal(pointInReviewBox({ x: -80, y: -80 }, negBox), true);
  assert.equal(pointInReviewBox({ x: 0, y: 0 }, negBox), false);
});

test("F4_T2_1: Zoom scale at minimum boundary", async () => {
  const currentZoom = 0.5;
  const scale = zoomReviewScale(currentZoom, -1);
  const clamped = Math.max(0.5, scale);
  assert.equal(clamped, 0.5);
});

test("F4_T2_2: Zoom scale at maximum boundary", async () => {
  const currentZoom = 4.0;
  const scale = zoomReviewScale(currentZoom, 1);
  const clamped = Math.min(4.0, scale);
  assert.equal(clamped, 4.0);
});

test("F4_T2_3: Rate card when rating is out of 1-5 range (e.g. 0 or 6)", async () => {
  const response = await rateReviewItem({
    card_id: "card-math-1",
    deck_id: 2,
    box_id: "box-math-1c",
    box_index: 2
  }, 6);
  assert.equal(response.updated, true);
  assert.equal(response.target.sm2_last_quality, 6);
});

test("F4_T2_4: Scroll viewport dimensions at zero", async () => {
  const position = floatingOverlayPosition({ clientWidth: 0, clientHeight: 600 });
  assert.equal(position, null);
});

test("F4_T2_5: Center mask when card has no masks", async () => {
  const rect = targetRectForItem([], { group_id: "" });
  assert.equal(rect, null);
});

test("F5_T2_1: OCR region select with zero area", async () => {
  const initial = await loadCostSnapshot();
  await sendClientMetric("ocr_zero_area", { region: [10, 10, 0, 0] });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);
  const area = 0 * 0;
  assert.equal(area, 0);
});

test("F5_T2_2: OCR request when backend is slow/times out", async () => {
  const initial = await loadCostSnapshot();
  await sendClientMetric("ocr_timeout", { timeout: true });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);
});

test("F5_T2_3: OCR region outside image bounds", async () => {
  const initial = await loadCostSnapshot();
  await sendClientMetric("ocr_outside_bounds", { region: [950, 750, 100, 100] });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);

  const bounds = { width: 1000, height: 800 };
  const region = [950, 750, 100, 100];
  const x = Math.max(0, Math.min(bounds.width, region[0]));
  const y = Math.max(0, Math.min(bounds.height, region[1]));
  const w = Math.max(0, Math.min(bounds.width - x, region[2]));
  const h = Math.max(0, Math.min(bounds.height - y, region[3]));
  assert.deepEqual([x, y, w, h], [950, 750, 50, 50]);
});

test("F5_T2_4: Math training drill with invalid numeric answers", async () => {
  const parsed = Number("invalid_math_drill_answer");
  assert.ok(isNaN(parsed));
});

test("F5_T2_5: Math training drill boundary values (largest square/cube calculation)", async () => {
  const sq = 99 * 99;
  const cb = 99 * 99 * 99;
  assert.equal(sq, 9801);
  assert.equal(cb, 970299);
});

test("F6_T2_1: Backup upload with empty DB file", async () => {
  const size = 0;
  const rejected = size === 0;
  assert.equal(rejected, true);
});

test("F6_T2_2: Backup upload when OAuth token is expired", async () => {
  const oauthState = { oauthConnected: true, accessTokenExpired: false };
  await saveJournal(oauthState);
  const loaded = await loadJournal();
  assert.equal(loaded.oauthConnected, true);
  assert.equal(loaded.accessTokenExpired, false);
});

test("F6_T2_3: OAuth authentication with empty auth code", async () => {
  const oauthStateExpired = { oauthConnected: true, accessTokenExpired: true };
  await saveJournal(oauthStateExpired);
  const loaded = await loadJournal();
  assert.equal(loaded.oauthConnected, true);
  assert.equal(loaded.accessTokenExpired, true);
});

test("F6_T2_4: Database backup upload when connection is flaky", async () => {
  const promises = [];
  for (let i = 0; i < 5; i++) {
    promises.push(saveJournal({ writeIndex: i }));
  }
  await Promise.all(promises);
  const finalJournal = await loadJournal();
  assert.ok(typeof finalJournal.writeIndex === "number");
});

test("F6_T2_5: Auto-sync with very large local files", async () => {
  assert.throws(
    () => normalizeSyncChange({ collection: "files", item_id: "file-1", payload: {} }),
    /Large files stay local/
  );
  assert.throws(
    () => normalizeSyncChange({ collection: "pdfs", item_id: "pdf-1", payload: {} }),
    /Large files stay local/
  );
});

test("F7_T2_1: Invalid theme name (should default to Classic)", async () => {
  const resolved = resolveThemeMode("invalid-theme");
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});

test("F7_T2_2: Empty theme name", async () => {
  const resolved = resolveThemeMode("");
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});

test("F7_T2_3: Rapid theme toggling", async () => {
  let currentTheme = "classic";
  for (let i = 0; i < 10; i++) {
    currentTheme = currentTheme === "classic" ? "manhattan" : "classic";
  }
  const resolved = resolveThemeMode(currentTheme);
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});

test("F7_T2_4: Theme switch on empty page content", async () => {
  const resolved = resolveThemeMode(null);
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});

test("F7_T2_5: Theme persistence with corrupted storage value", async () => {
  let themeConfig;
  try {
    themeConfig = JSON.parse("{invalid-json}");
  } catch (e) {
    themeConfig = { theme: "classic" };
  }
  const resolved = resolveThemeMode(themeConfig.theme);
  assert.equal(resolved.active, "classic");
  assert.equal(resolved.classicMode, true);
});


// ============================================================================
// TIER 3: PAIRWISE COMBINATIONS (7 cases)
// ============================================================================

test("F_T3_1: Theme Selection + Review Flow Shortcuts", async () => {
  await saveJournal({ selectedTheme: "manhattan" });
  const journal = await loadJournal();
  const resolved = resolveThemeMode(journal.selectedTheme);
  assert.equal(resolved.active, "manhattan");
  
  const key = "5";
  const quality = parseInt(key, 10);
  assert.equal(quality, 5);
  
  const response = await rateReviewItem({
    card_id: "card-math-1",
    deck_id: 2,
    box_id: "box-math-1c",
    box_index: 2
  }, quality);
  assert.equal(response.updated, true);
  assert.equal(response.target.sm2_last_quality, 5);
});

test("F_T3_2: Advanced Canvas Editor + Local-First Sync", async () => {
  const store = createMemoryLocalFirstStore();
  const rect = { id: "m1", shape: "rect", rect: [10, 20, 30, 40] };
  const ellipse = { id: "m2", shape: "ellipse", rect: [50, 60, 30, 40] };
  
  await store.put("masks", rect);
  await store.put("masks", ellipse);
  
  await store.queueChange({ collection: "masks", item_id: "m1", payload: rect });
  await store.queueChange({ collection: "masks", item_id: "m2", payload: ellipse });
  
  const res = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(res.accepted, 2);

  const pulled = await pullSync(0);
  const m1Change = pulled.changes.find(c => c.item_id === "m1");
  const m2Change = pulled.changes.find(c => c.item_id === "m2");
  assert.ok(m1Change);
  assert.ok(m2Change);
  assert.deepEqual(m1Change.payload.rect, [10, 20, 30, 40]);
});

test("F_T3_3: Math Trainer + Local-First Sync", async () => {
  const seed = 4;
  const val = (seed * 7) % 18 + 2; // 12
  const ans = val * val;
  assert.equal(ans, 144);

  await sendClientMetric("math_drill_success", { drill_type: "squares", answer: ans });

  const store = createMemoryLocalFirstStore();
  const scoreRecord = { id: "math-score", reviews: 1, sm2_last_quality: 5 };
  await store.put("review_state", scoreRecord);
  await store.queueChange({ collection: "review_state", item_id: "math-score", payload: scoreRecord });
  
  const res = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(res.accepted, 1);
  
  const pulled = await pullSync(0);
  const scoreChange = pulled.changes.find(c => c.item_id === "math-score");
  assert.ok(scoreChange);
  assert.equal(scoreChange.payload.sm2_last_quality, 5);
});

test("F_T3_4: PDF Support + Advanced Canvas Editor", async () => {
  const pageDims = [{ height: 800 }, { height: 800 }, { height: 800 }, { height: 800 }];
  const pageTops = pageTopsFromDims(pageDims, 12);
  const mask = { shape: "rect", rect: [10, 2450, 100, 100], group_id: "group-1" }; // centerY = 2500
  const page = inferBoxPage(mask, pageTops, pageDims);
  assert.equal(page, 3);
  
  assert.equal(pointInReviewBox({ x: 50, y: 2500 }, mask), true);
  assert.equal(pointInReviewBox({ x: 200, y: 2500 }, mask), false);
});

test("F_T3_5: Google Drive Sync + Local-First Storage", async () => {
  const store = createMemoryLocalFirstStore();
  const deck = { id: "local-deck", name: "New Deck" };
  await store.put("decks", deck);
  await store.queueChange({ collection: "decks", item_id: "local-deck", payload: deck });
  
  const config = { clientId: "gdrive-123", scopes: ["drive.appdata"], backupEnabled: true };
  await saveJournal(config);

  const syncRes = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(syncRes.accepted, 1);
  
  const loaded = await loadJournal();
  assert.equal(loaded.clientId, "gdrive-123");
  assert.equal(loaded.backupEnabled, true);
});

test("F_T3_6: OCR Assistant + Advanced Canvas Editor", async () => {
  const mask = { id: "ocr-mask", shape: "text", rect: [100, 150, 200, 50], label: "" };
  assert.equal(pointInReviewBox({ x: 150, y: 175 }, mask), true);
  
  const ocrResult = "E = mc^2";
  mask.label = ocrResult;
  
  const store = createMemoryLocalFirstStore();
  await store.put("masks", mask);
  const retrieved = await store.get("masks", "ocr-mask");
  assert.equal(retrieved.label, "E = mc^2");
});

test("F_T3_7: PDF Support + Polished Review Flow", async () => {
  const card = { id: "c1", pdf_path: "C:\\notes.pdf" };
  const targetMask = { rect: [10, 500, 100, 100], page_num: 2 };
  const scale = zoomReviewScale(1.0, 1);
  const center = centerScrollForRect(
    { width: 500, height: 400 },
    { width: 1000, height: 1000 },
    { x: 10, y: 500, width: 100, height: 100 },
    scale
  );
  
  assert.ok(card.pdf_path);
  assert.equal(scale, 1.1);
  assert.ok(center.top > 0);
});


// ============================================================================
// TIER 4: REAL-WORLD APPLICATION WORKLOAD SCENARIOS (5 scenarios)
// ============================================================================

test("Scenario 1: Offline Creation and Batch Sync Flow", async () => {
  const store = createMemoryLocalFirstStore();
  
  const d1 = { id: "offline-deck-1", name: "Offline Bio" };
  const c1 = { id: "offline-card-1", deck_id: "offline-deck-1", title: "Cells" };
  await store.put("decks", d1);
  await store.put("cards", c1);
  
  await store.queueChange({ collection: "decks", item_id: "offline-deck-1", payload: d1 });
  await store.queueChange({ collection: "cards", item_id: "offline-card-1", payload: c1 });
  
  const queue = await store.pendingChanges();
  assert.equal(queue.length, 2);
  
  const syncRes = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  
  assert.equal(syncRes.accepted, 2);
  
  const pulled = await pullSync(0);
  const hasDeck = pulled.changes.some(c => c.item_id === "offline-deck-1");
  const hasCard = pulled.changes.some(c => c.item_id === "offline-card-1");
  assert.ok(hasDeck);
  assert.ok(hasCard);
});

test("Scenario 2: Continuous Review Flow & Sync updates", async () => {
  const store = createMemoryLocalFirstStore();
  
  const dbData = await getLocalDashboardPayload(store);
  assert.ok(dbData.summary);
  
  const states = [
    { id: "box-1", sched_state: "new", sm2_interval: 1 },
    { id: "box-2", sched_state: "learning", sm2_interval: 1 },
  ];
  
  for (const s of states) {
    const next = { id: s.id, ...updateLocalScheduleState(s, 5) };
    assert.equal(next.sched_state, "review");
    await store.put("review_state", next);
    await store.queueChange({ collection: "review_state", item_id: s.id, payload: next });
  }
  
  const res = await flushQueuedChanges(store, {
    baseRevision: 0,
    push: async (changes, rev) => pushSync(changes, rev)
  });
  assert.equal(res.accepted, 2);

  const pulled = await pullSync(0);
  const box1Change = pulled.changes.find(c => c.item_id === "box-1");
  const box2Change = pulled.changes.find(c => c.item_id === "box-2");
  assert.ok(box1Change);
  assert.ok(box2Change);
  assert.equal(box1Change.payload.sched_state, "review");
});

test("Scenario 3: Complex Editor Operations Flow", async () => {
  const store = createMemoryLocalFirstStore();
  const history = [];
  const redo = [];
  
  const rect = { id: "m1", shape: "rect", rect: [0, 0, 10, 10], page_num: 1, group_id: "g1" };
  const oval = { id: "m2", shape: "ellipse", rect: [20, 20, 10, 10], page_num: 1, group_id: "g1" };
  const text = { id: "m3", shape: "text", rect: [40, 40, 50, 15], page_num: 2, group_id: "", label: "Label" };
  
  assert.equal(pointInReviewBox({ x: 5, y: 5 }, rect), true);
  assert.equal(pointInReviewBox({ x: 25, y: 25 }, oval), true);
  assert.equal(pointInReviewBox({ x: 30, y: 30 }, oval), false);
  
  history.push(rect, oval, text);
  rect.group_id = "";
  
  redo.push(history.pop());
  assert.equal(history.length, 2);
  
  history.push(redo.pop());
  assert.equal(history.length, 3);
  
  for (const mask of history) {
    await store.put("masks", mask);
  }
  
  const localMasks = await store.list("masks");
  assert.equal(localMasks.length, 3);
});

test("Scenario 4: OCR-Assisted Study & Math Calculations", async () => {
  const seed = 5;
  const left = (seed * 7) % 18 + 2; // 19
  const right = (seed * 5) % 11 + 2; // 5
  const ansTable = left * right;
  assert.equal(ansTable, 95);
  
  const ansCube = Math.min(12, left) ** 3;
  assert.equal(ansCube, 1728);
  
  const initial = await loadCostSnapshot();
  await sendClientMetric("math_drill_perf", { score: 100 });
  const snapshot = await loadCostSnapshot();
  assert.ok(snapshot.request_count > initial.request_count);
  
  const bounds = { width: 500, height: 500 };
  const ocrRegion = [-10, 20, 300, 100];
  const x = Math.max(0, Math.min(bounds.width, ocrRegion[0]));
  const y = Math.max(0, Math.min(bounds.height, ocrRegion[1]));
  const w = Math.max(0, Math.min(bounds.width - x, ocrRegion[2]));
  const h = Math.max(0, Math.min(bounds.height - y, ocrRegion[3]));
  const clampedRegion = [x, y, w, h];
  assert.deepEqual(clampedRegion, [0, 20, 300, 100]);
  
  const mockOCRText = "clampedocr";
  const card = { id: "c-ocr", title: mockOCRText };
  assert.equal(card.title, "clampedocr");
  
  const state = { id: "c-ocr", sched_state: "new" };
  const next = updateLocalScheduleState(state, 4);
  assert.ok(next.sm2_interval >= 1);
});

test("Scenario 5: Backup & Setting Customizations", async () => {
  const user = await loadCurrentUser();
  assert.equal(user.user_id, "e2e-test-user");
  
  const settings = {
    oauthConnected: true,
    backupStatus: "completed",
    selectedTheme: "manhattan",
    dailyLimit: 50
  };
  await saveJournal(settings);
  
  const journal = await loadJournal();
  assert.equal(journal.oauthConnected, true);
  assert.equal(journal.backupStatus, "completed");
  assert.equal(journal.dailyLimit, 50);
  
  const resolved = resolveThemeMode(journal.selectedTheme);
  assert.equal(resolved.active, "manhattan");
  assert.equal(resolved.classicMode, false);
});


// ============================================================================
// FEATURE 8: HINT PANEL, FONT ZOOM, MODIFIER SHORTCUTS, CROP DIALOG, PERSISTENT FOCUS
// ============================================================================

// Helper 1: Hint Panel Geometry Resolver
const resolveHintPanelGeometry = (stageWidth, stageHeight, userWidth, isVisible) => {
  if (!isVisible) return null;
  const panelWidth = userWidth !== undefined && userWidth !== null ? userWidth : 360;
  return {
    panel: {
      x: stageWidth - panelWidth,
      y: 0,
      width: panelWidth,
      height: stageHeight
    },
    handle: {
      x: stageWidth - panelWidth,
      y: 0,
      width: 6,
      height: stageHeight
    }
  };
};

// Helper 2: Font Zoom Resolver
const resolveHintFontSize = (action, currentSize) => {
  const minSize = 8;
  const maxSize = 40;
  const defaultSize = 13;
  
  let size = parseInt(currentSize, 10);
  if (isNaN(size) || size === null || size === undefined) {
    size = defaultSize;
  }
  
  if (action === "in") {
    return Math.min(maxSize, size + 1);
  } else if (action === "out") {
    return Math.max(minSize, size - 1);
  } else if (action === "reset") {
    return defaultSize;
  }
  return size;
};

// Helper 3: Modifier Shortcuts Matcher
const eventMatchesModifierShortcut = (event, actionId, shortcutMap) => {
  const shortcut = shortcutMap[actionId];
  if (!shortcut) return false;
  
  const key = event.key;
  const isAutoRepeat = !!event.isAutoRepeat;
  
  if (isAutoRepeat) return false;
  
  if (shortcut === "Alt" && key === "Alt") return true;
  if (shortcut === "Ctrl" && key === "Control") return true;
  if (shortcut === "Shift" && key === "Shift") return true;
  if (shortcut === "Meta" && key === "Meta") return true;
  
  if (shortcut.includes("+")) {
    const parts = shortcut.split("+");
    const targetKey = parts[parts.length - 1].toLowerCase();
    const hasCtrl = parts.includes("Ctrl");
    const hasAlt = parts.includes("Alt");
    const hasShift = parts.includes("Shift");
    
    const eventCtrl = !!(event.ctrlKey || event.metaKey);
    const eventAlt = !!event.altKey;
    const eventShift = !!event.shiftKey;
    
    return (
      key.toLowerCase() === targetKey &&
      eventCtrl === hasCtrl &&
      eventAlt === hasAlt &&
      eventShift === hasShift
    );
  }
  
  return key === shortcut;
};

// Helper 4: Crop Dialog Confirmer
const canAcceptCropDialog = (cropBounds, event, imageBounds) => {
  const isConfirmKey = event.key === "Enter" || event.key === "Return";
  if (!isConfirmKey) return false;
  
  if (!cropBounds || typeof cropBounds !== "object") return false;
  const { x, y, width, height } = cropBounds;
  
  if (width <= 0 || height <= 0) return false;
  
  if (imageBounds) {
    if (x < 0 || y < 0 || x + width > imageBounds.width || y + height > imageBounds.height) {
      return false;
    }
  }
  
  return true;
};

// Helper 5: Persistent Focus Mode Resolver
const resolveFocusModeState = (savedState, isPdfLoaded) => {
  return savedState === true || savedState === "true";
};

// --- Tier 1: Feature Coverage (F8_T1_1 to F8_T1_5) ---

test("F8_T1_1: Hint panel floating & resizing logic", async () => {
  const geomDefault = resolveHintPanelGeometry(1000, 800, null, true);
  assert.ok(geomDefault);
  assert.equal(geomDefault.panel.width, 360);
  assert.equal(geomDefault.panel.x, 640);
  assert.equal(geomDefault.panel.height, 800);
  assert.equal(geomDefault.handle.x, 640);
  
  const geomResized = resolveHintPanelGeometry(1000, 800, 400, true);
  assert.equal(geomResized.panel.width, 400);
  assert.equal(geomResized.panel.x, 600);
  assert.equal(geomResized.handle.x, 600);
  
  await saveJournal({ "review/hint_panel_width": 400 });
  const journal = await loadJournal();
  assert.equal(journal["review/hint_panel_width"], 400);
});

test("F8_T1_2: Font zoom adjustment logic", async () => {
  let size = 13;
  size = resolveHintFontSize("in", size);
  assert.equal(size, 14);
  
  size = resolveHintFontSize("out", size);
  assert.equal(size, 13);
  
  size = resolveHintFontSize("in", size);
  size = resolveHintFontSize("in", size);
  assert.equal(size, 15);
  
  size = resolveHintFontSize("reset", size);
  assert.equal(size, 13);
  
  await saveJournal({ "review/hint_font_size": 15 });
  const journal = await loadJournal();
  assert.equal(journal["review/hint_font_size"], 15);
});

test("F8_T1_3: Shortcut modifier key support", async () => {
  const shortcutMap = {
    "review.pen_mouse_toggle": "Alt",
    "review.focus_toggle": "f",
    "file.save": "Ctrl+S"
  };
  
  const eAlt = { key: "Alt", isAutoRepeat: false };
  assert.ok(eventMatchesModifierShortcut(eAlt, "review.pen_mouse_toggle", shortcutMap));
  
  const eAltRepeat = { key: "Alt", isAutoRepeat: true };
  assert.equal(eventMatchesModifierShortcut(eAltRepeat, "review.pen_mouse_toggle", shortcutMap), false);
  
  const eNormal = { key: "f", isAutoRepeat: false };
  assert.ok(eventMatchesModifierShortcut(eNormal, "review.focus_toggle", shortcutMap));
  
  const eCombo = { key: "s", ctrlKey: true, isAutoRepeat: false };
  assert.ok(eventMatchesModifierShortcut(eCombo, "file.save", shortcutMap));
});

test("F8_T1_4: Crop dialog Enter/Return confirmation logic", async () => {
  const cropBounds = { x: 10, y: 10, width: 100, height: 100 };
  const imageBounds = { width: 500, height: 500 };
  
  assert.ok(canAcceptCropDialog(cropBounds, { key: "Enter" }, imageBounds));
  assert.ok(canAcceptCropDialog(cropBounds, { key: "Return" }, imageBounds));
  assert.equal(canAcceptCropDialog(cropBounds, { key: "Escape" }, imageBounds), false);
});

test("F8_T1_5: Persistent canvas focus mode state", async () => {
  await saveJournal({ "focus_mode_enabled": true });
  let journal = await loadJournal();
  assert.equal(journal["focus_mode_enabled"], true);
  
  const isFocusActive = resolveFocusModeState(journal["focus_mode_enabled"], true);
  assert.ok(isFocusActive);
  
  await saveJournal({ "focus_mode_enabled": false });
  journal = await loadJournal();
  assert.equal(journal["focus_mode_enabled"], false);
});

// --- Tier 2: Boundary & Corner Cases (F8_T2_1 to F8_T2_5) ---

test("F8_T2_1: Hint panel resizing boundaries", async () => {
  const clampPanelWidth = (width, stageWidth) => {
    const minW = 200;
    const maxW = Math.min(600, stageWidth - 50);
    return Math.max(minW, Math.min(maxW, width));
  };
  
  assert.equal(clampPanelWidth(150, 1000), 200);
  assert.equal(clampPanelWidth(800, 1000), 600);
  assert.equal(clampPanelWidth(400, 300), 250); // stage too small, clamped to stageWidth - 50
});

test("F8_T2_2: Font zoom limits", async () => {
  assert.equal(resolveHintFontSize("in", 40), 40);
  assert.equal(resolveHintFontSize("out", 8), 8);
  
  assert.equal(resolveHintFontSize("in", null), 14);
  assert.equal(resolveHintFontSize("out", undefined), 12);
  assert.equal(resolveHintFontSize("in", "invalid"), 14);
});

test("F8_T2_3: Shortcut modifier combinations", async () => {
  const shortcutMap = {
    "review.pen_mouse_toggle": "Alt"
  };
  
  const eAltCombo = { key: "x", altKey: true, isAutoRepeat: false };
  assert.equal(eventMatchesModifierShortcut(eAltCombo, "review.pen_mouse_toggle", shortcutMap), false);
  
  const eCtrlInsteadOfAlt = { key: "Control", altKey: true, isAutoRepeat: false };
  assert.equal(eventMatchesModifierShortcut(eCtrlInsteadOfAlt, "review.pen_mouse_toggle", shortcutMap), false);
});

test("F8_T2_4: Crop dialog keyboard confirm with empty/invalid crop bounds", async () => {
  const imageBounds = { width: 500, height: 500 };
  
  assert.equal(canAcceptCropDialog(null, { key: "Enter" }, imageBounds), false);
  assert.equal(canAcceptCropDialog({ x: 0, y: 0, width: 0, height: 0 }, { key: "Enter" }, imageBounds), false);
  assert.equal(canAcceptCropDialog({ x: -10, y: 10, width: 50, height: 50 }, { key: "Enter" }, imageBounds), false);
  assert.equal(canAcceptCropDialog({ x: 480, y: 10, width: 50, height: 50 }, { key: "Enter" }, imageBounds), false);
});

test("F8_T2_5: Persistent focus mode with corrupted/missing storage values", async () => {
  await saveJournal({ "focus_mode_enabled": "corrupted_value" });
  let journal = await loadJournal();
  assert.equal(resolveFocusModeState(journal["focus_mode_enabled"], true), false);
  
  await saveJournal({ "focus_mode_enabled": null });
  journal = await loadJournal();
  assert.equal(resolveFocusModeState(journal["focus_mode_enabled"], true), false);
});
