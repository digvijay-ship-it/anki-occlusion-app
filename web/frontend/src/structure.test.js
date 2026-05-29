import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const reviewSurfaceSource = readFileSync(
  new URL("./reviewSurface.jsx", import.meta.url),
  "utf8",
);

test("dashboard maps to the desktop dojo home structure", () => {
  assert.match(appSource, /<div className="workspace local-workspace">/);
  assert.match(appSource, /<aside className="left-rail dojo-rail">/);
  assert.match(appSource, /<section className="mission-card training-mission">/);
  assert.match(appSource, /<section className="scroll-stage">/);
  assert.match(appSource, /<section className="main-actions">/);
  assert.doesNotMatch(appSource, /<aside className="right-rail"/);
  assert.doesNotMatch(appSource, /<section className="review-console"/);
  assert.doesNotMatch(appSource, /<footer className="statusbar"/);
  assert.doesNotMatch(cssSource, /\.statusbar/);
  assert.doesNotMatch(appSource, /ReviewStage|review-stage-card/);
});

test("review rating buttons stay available for the review screen", () => {
  assert.match(appSource, /export function ReviewQualityButtons/);
  assert.match(
    appSource,
    /<div className="quality-grid review-quality-buttons">[\s\S]*className=\{`quality-button/,
  );
  assert.match(cssSource, /\.quality-grid/);
  assert.match(cssSource, /\.quality-button::after/);
  assert.match(reviewSurfaceSource, /className="reveal-button/);
  assert.match(cssSource, /\.reveal-button/);
});

test("local desktop styling is wired to the mapped structure", () => {
  assert.match(cssSource, /@keyframes panel-scan/);
  assert.match(cssSource, /@keyframes quiet-pulse/);
  assert.match(cssSource, /@keyframes active-row/);
  assert.match(cssSource, /\.local-workspace/);
  assert.match(cssSource, /\.dojo-rail/);
  assert.match(cssSource, /\.mission-card/);
  assert.match(cssSource, /\.scroll-stage/);
  assert.doesNotMatch(cssSource, /\.right-rail|\.review-stage-card/);
});

test("visible dashboard controls are wired to handlers", () => {
  assert.match(appSource, /onClick=\{handleMathNav\}/);
  assert.match(appSource, /onClick=\{handleJournalNav\}/);
  assert.match(appSource, /onClick=\{handleClassicToggle\}/);
  assert.match(appSource, /onClick=\{handleMoreNav\}/);
  assert.match(appSource, /onClick=\{handleRefresh\}/);
  assert.match(appSource, /onClick=\{handleSettingsNav\}/);
  assert.match(appSource, /onClick=\{handleBgmToggle\}/);
  assert.match(appSource, /onClick=\{\(\) => openActionPanel\("new-dojo"\)\}/);
  assert.match(appSource, /onClick=\{\(\) => openActionPanel\("sub-dojo"\)\}/);
  assert.match(appSource, /onClick=\{handleDeleteDojo\}/);
  assert.match(appSource, /onClick=\{\(\) => openActionPanel\("forge-scroll"\)\}/);
  assert.match(appSource, /onClick=\{\(\) => openReviewScreen\("due"\)\}/);
  assert.match(appSource, /onClick=\{\(\) => openReviewScreen\("selected"\)\}/);
  assert.match(appSource, /onClick=\{\(\) => openEditorMode\("home"\)\}/);
  assert.match(appSource, /onClick=\{handleDeleteSelected\}/);
});

test("math nav opens the trainer instead of selecting a math deck", () => {
  assert.match(appSource, /function handleMathNav\(\) \{[\s\S]*setScreen\("math"\)/);
  assert.match(appSource, /screen === "math"/);
  assert.match(appSource, /className="mode-panel math-panel"/);
  assert.doesNotMatch(appSource, /handleSelectDeck\(mathDeck|setSelectedDeckId\(mathDeck/);
});

test("review screen follows the desktop session controls", () => {
  assert.match(appSource, /function openReviewScreen\(mode = "due"\)/);
  assert.match(appSource, /mode === "selected" && activeItem \? \[activeItem\]/);
  assert.match(appSource, /setReviewSessionKeys\(queueKeys\)/);
  assert.match(appSource, /setReviewSessionSnapshot\(queue\)/);
  assert.match(appSource, /setReviewDoneKeys\(new Set\(\)\)/);
  assert.match(appSource, /className="review-toolbar"/);
  assert.match(appSource, /className="review-progress-block"/);
  assert.match(appSource, /className="review-queue-panel open"/);
  assert.match(appSource, /function hideReviewQueue\(\)/);
  assert.match(appSource, /function showReviewQueue\(\)/);
  assert.match(appSource, /setQueueLocked\(false\)/);
  assert.match(appSource, /className=\{`review-workbench \$\{queueVisible \? "" : "queue-hidden"\}`\}/);
  assert.match(appSource, /onClick=\{hideReviewQueue\}[\s\S]*Hide/);
  assert.match(appSource, /onClick=\{showReviewQueue\}[\s\S]*Show Queue/);
  assert.doesNotMatch(appSource, /disabled=\{queueLocked\}/);
  assert.match(cssSource, /\.review-workbench\.queue-hidden[\s\S]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(cssSource, /\.review-queue-restore/);
  assert.match(appSource, /reviewQueueLabel\(item\)/);
  assert.match(appSource, /className=\{rowState\}/);
  assert.match(appSource, /onClick=\{\(\) => openEditorMode\("review"\)\}/);
  assert.match(appSource, /className="review-tool mode-toggle"/);
  assert.match(appSource, /ReviewDocumentSurface/);
  assert.match(appSource, /reviewRatingPreviews\(activeItem\)/);
  assert.match(appSource, /ratingOverlay=\{/);
  assert.match(appSource, /previews=\{activeRatingPreviews\}/);
  assert.match(appSource, /reviewPenActive/);
  assert.match(appSource, /reviewFocusMode/);
  assert.match(appSource, /function toggleReviewFocusMode\(source = "toolbar"\)/);
  assert.match(appSource, /reviewFocusMode \? "review-focus-mode" : ""/);
  assert.match(appSource, /onClick=\{\(\) => toggleReviewFocusMode\(\)\}[\s\S]*Focus/);
  assert.match(appSource, /className="review-focus-exit"/);
  assert.match(appSource, /Clear Pen/);
  assert.match(appSource, /function fitReviewSurface\(source = "toolbar"\)/);
  assert.match(appSource, /setReviewFitRequest\(\(current\) => current \+ 1\)/);
  assert.match(appSource, /fitRequest=\{reviewFitRequest\}/);
  assert.match(appSource, /onFitScale=\{setReviewZoom\}/);
  assert.match(appSource, /centerRequest=\{reviewCenterRequest\}/);
  assert.match(appSource, /pageCommand=\{reviewPageCommand\}/);
  assert.match(appSource, /function handleReviewUndo\(\)/);
  assert.match(appSource, /function handleReviewRedo\(\)/);
  assert.match(appSource, /undoReviewRating\(\)/);
  assert.match(appSource, /redoReviewRating\(\)/);
  assert.match(appSource, /reviewUndoStack/);
  assert.match(appSource, /reviewRedoStack/);
  assert.match(appSource, /event\.key\.toLowerCase\(\) === "f"[\s\S]*toggleReviewFocusMode\("shortcut"\)/);
  assert.match(appSource, /if \(reviewFocusMode\) \{[\s\S]*setReviewFocusMode\(false\)/);
  assert.match(appSource, /event\.key\.toLowerCase\(\) === "c"[\s\S]*fitAndCenterReviewSurface\("shortcut"\)/);
  assert.match(appSource, /event\.key\.toLowerCase\(\) === "z"[\s\S]*handleReviewUndo\(\)/);
  assert.match(appSource, /event\.key\.toLowerCase\(\) === "y"[\s\S]*handleReviewRedo\(\)/);
  assert.match(appSource, /event\.key\.toLowerCase\(\) === "l"[\s\S]*revealCurrentPdfFolder\(\)/);
  assert.match(appSource, /sendReviewPageCommand\("prev"\)/);
  assert.match(appSource, /sendReviewPageCommand\("next"\)/);
  assert.match(appSource, /onClick=\{handleReviewUndo\}[\s\S]*Undo/);
  assert.match(appSource, /onClick=\{handleReviewRedo\}[\s\S]*Redo/);
  assert.match(appSource, /onClick=\{revealCurrentPdfFolder\}[\s\S]*Folder/);
  assert.match(appSource, /onClick=\{\(\) => fitReviewSurface\(\)\}[\s\S]*Fit/);
  assert.match(appSource, /screen === "review-summary"/);
  assert.match(cssSource, /\.review-fullscreen \.desktop-review-mode\.review-focus-mode[\s\S]*grid-template-rows: minmax\(0, 1fr\)/);
  assert.doesNotMatch(appSource, /review-shortcut-hint/);
  assert.doesNotMatch(cssSource, /review-shortcut-hint/);
  assert.match(cssSource, /\.review-focus-mode \.review-workbench[\s\S]*height: 100%/);
  assert.match(cssSource, /\.review-focus-mode \.review-document-frame[\s\S]*height: 100%/);
  assert.match(cssSource, /\.review-rating-float/);
});

test("web pdf review uses the desktop continuous canvas model", () => {
  assert.match(reviewSurfaceSource, /function PdfReviewSurface/);
  assert.match(reviewSurfaceSource, /const frameRef = useRef\(null\)/);
  assert.match(reviewSurfaceSource, /function scrollToPage\(nextPage\)/);
  assert.match(reviewSurfaceSource, /function handleScroll\(event\) \{[\s\S]*setPageZero\(pageFromScroll/);
  assert.match(reviewSurfaceSource, /className="pdf-page-stack"/);
  assert.match(reviewSurfaceSource, /docState\.pageDims\.map/);
  assert.match(reviewSurfaceSource, /function ensurePagesAround\(pageIndex\)/);
  assert.match(reviewSurfaceSource, /renderedPagesRef/);
  assert.match(reviewSurfaceSource, /pageTop=\{0\}/);
  assert.match(reviewSurfaceSource, /useFloatingRevealPosition/);
  assert.match(reviewSurfaceSource, /floatingOverlayPosition/);
  assert.match(reviewSurfaceSource, /onScroll=\{handleScroll\}/);
  assert.match(reviewSurfaceSource, /overlayRef=\{overlayRef\}/);
  assert.match(reviewSurfaceSource, /review-rating-float/);
  assert.match(reviewSurfaceSource, /position=\{revealPosition\}/);
  assert.doesNotMatch(cssSource, /\.image-reveal \{[^}]*bottom:/);
  assert.match(cssSource, /\.review-mask\.hidden \{[\s\S]*rgba\(255, 77, 90, 0\.96\)/);
  assert.doesNotMatch(reviewSurfaceSource, /const pageBoxes = useMemo/);
  assert.doesNotMatch(reviewSurfaceSource, /ref=\{canvasRef\}/);
  assert.match(cssSource, /\.pdf-page-stack/);
  assert.match(cssSource, /\.pdf-page-shell/);
  assert.match(cssSource, /\.review-pdf-nav \{[\s\S]*position: sticky/);
});

test("review heading only shows the active card title", () => {
  const reviewStart = appSource.indexOf('if (screen === "review")');
  const summaryStart = appSource.indexOf('if (screen === "review-summary")');
  const reviewBlock = appSource.slice(reviewStart, summaryStart);

  assert.match(reviewBlock, /<h3>\{activeItem\?\.card_title \|\| "No Due Scroll"\}<\/h3>/);
  assert.doesNotMatch(reviewBlock, /<span className="mode-kicker">Active Review<\/span>/);
  assert.doesNotMatch(reviewBlock, /activeItem\.deck_name/);
});

test("review mode takes over the full browser workspace", () => {
  assert.match(appSource, /const isReviewScreen = screen === "review"/);
  assert.match(appSource, /isReviewScreen \? "review-fullscreen" : ""/);
  assert.match(cssSource, /\.review-fullscreen \.topbar,[\s\S]*\.review-fullscreen \.left-rail,[\s\S]*\.review-fullscreen \.deck-hero/);
  assert.match(cssSource, /\.review-fullscreen \.local-workspace[\s\S]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(cssSource, /\.review-fullscreen \.desktop-review-mode[\s\S]*height: 100%/);
  assert.match(cssSource, /\.review-fullscreen \.main-panel[\s\S]*overflow: hidden/);
});

test("editor mode is a real browser-local mask editor", () => {
  assert.match(appSource, /function openEditorMode\(returnScreen = "home"\)/);
  assert.match(appSource, /screen === "editor"/);
  assert.match(appSource, /className="mode-panel editor-mode"/);
  assert.match(appSource, /function handleSaveEditor/);
  assert.match(appSource, /editor_masks|local_masks: editorMasks/);
  assert.match(cssSource, /\.editor-form/);
  assert.match(cssSource, /\.editor-mask-editor/);
});

test("review shortcut effect is declared after active item is available", () => {
  const activeItemIndex = appSource.indexOf("const activeItem =");
  const shortcutEffectIndex = appSource.indexOf("function handleReviewShortcut");

  assert.notEqual(activeItemIndex, -1);
  assert.notEqual(shortcutEffectIndex, -1);
  assert.ok(
    activeItemIndex < shortcutEffectIndex,
    "shortcut dependencies must not read activeItem before it is initialized",
  );
});

test("forge image masks stay browser local", () => {
  assert.match(appSource, /accept="image\/\*"/);
  assert.match(appSource, /function handleImageFileChange/);
  assert.match(appSource, /function handleMaskPointerDown/);
  assert.match(appSource, /image_data_url: draftImage\?\.src \|\| null/);
  assert.match(appSource, /local_masks: draftMasks/);
  assert.match(appSource, /className="mask-stage"/);
  assert.match(appSource, /className=\{`review-image-frame/);
  assert.match(cssSource, /\.mask-box/);
  assert.match(cssSource, /\.review-mask/);
  assert.doesNotMatch(appSource, /new FormData|uploadImage|\/api\/files|\/api\/upload/);
});
