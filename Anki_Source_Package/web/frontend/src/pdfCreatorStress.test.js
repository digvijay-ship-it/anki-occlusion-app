import assert from "node:assert/strict";
import test from "node:test";

// ============================================================================
// STRESS TESTS: PDF CREATOR & DRAG-AND-DROP FILE LOADING
// ============================================================================

// A mock of the state and actions inside the React App component
class MockApp {
  constructor() {
    this.editorImage = null;
    this.editorPdfDoc = null;
    this.editorPdfBlob = null;
    this.editorPdfName = "";
    this.editorPdfPageZero = 0;
    this.editorMasks = [];
    this.editorSelectedMaskIds = new Set();
    this.actionsLog = [];
  }

  setEditorImage(img) {
    this.editorImage = img;
  }

  setEditorPdfDoc(doc) {
    this.editorPdfDoc = doc;
  }

  setEditorPdfBlob(blob) {
    this.editorPdfBlob = blob;
  }

  setEditorPdfName(name) {
    this.editorPdfName = name;
  }

  setEditorPdfPageZero(pageOrFn) {
    if (typeof pageOrFn === "function") {
      this.editorPdfPageZero = pageOrFn(this.editorPdfPageZero);
    } else {
      this.editorPdfPageZero = pageOrFn;
    }
  }

  updateEditorMasksWithHistory(masks) {
    this.editorMasks = masks;
  }

  setEditorSelectedMaskIds(set) {
    this.editorSelectedMaskIds = set;
  }

  recordAction(msg) {
    this.actionsLog.push(msg);
  }

  // Implementation of processLoadedFile ported from App.jsx for testing
  async processLoadedFile(file, mockFileReaderResult = null, mockPdfDoc = null, shouldPdfFail = false) {
    if (!file) return;
    if (file.type === "application/pdf") {
      this.setEditorImage(null);
      // Simulate FileReader async behavior
      try {
        if (shouldPdfFail) {
          throw new Error("Invalid PDF signature");
        }
        this.setEditorPdfDoc(mockPdfDoc);
        this.setEditorPdfPageZero(0);
        this.setEditorPdfBlob(file);
        this.setEditorPdfName(file.name);
        this.updateEditorMasksWithHistory([]);
        this.setEditorSelectedMaskIds(new Set());
        this.recordAction(`${file.name} (PDF, ${mockPdfDoc.numPages} pages) loaded in editor.`);
      } catch (e) {
        this.recordAction(`Failed to load PDF in editor: ${e.message}`);
      }
    } else if (file.type.startsWith("image/")) {
      this.setEditorPdfDoc(null);
      this.setEditorPdfBlob(null);
      this.setEditorImage({
        name: file.name,
        src: String(mockFileReaderResult || ""),
        blob: file,
      });
      this.updateEditorMasksWithHistory([]);
      this.setEditorSelectedMaskIds(new Set());
      this.recordAction(`${file.name} loaded in editor.`);
    } else {
      this.recordAction("Unsupported file type. Choose an image or PDF.");
    }
  }

  // Page navigation simulator
  handleGoToPage(pageZero) {
    if (!this.editorPdfDoc) return;
    const total = this.editorPdfDoc.numPages;
    if (pageZero >= 0 && pageZero < total) {
      this.setEditorPdfPageZero(pageZero);
    }
  }

  handlePrevPage() {
    if (!this.editorPdfDoc) return;
    this.setEditorPdfPageZero((prev) => Math.max(0, prev - 1));
  }

  handleNextPage() {
    if (!this.editorPdfDoc) return;
    const total = this.editorPdfDoc.numPages;
    this.setEditorPdfPageZero((prev) => Math.min(total - 1, prev + 1));
  }

  handleJumpInput(val) {
    if (!this.editorPdfDoc) return;
    const p = parseInt(val, 10);
    if (!isNaN(p) && p >= 1 && p <= this.editorPdfDoc.numPages) {
      this.setEditorPdfPageZero(p - 1);
    }
  }

  handleArrowKey(key, activeElementTag = "DIV") {
    if (activeElementTag === "INPUT") return; // Should not change page when typing in input
    if (!this.editorPdfDoc) return;
    const total = this.editorPdfDoc.numPages;
    if (key === "arrowleft") {
      if (this.editorPdfPageZero > 0) {
        this.setEditorPdfPageZero((prev) => Math.max(0, prev - 1));
      }
    } else if (key === "arrowright") {
      if (this.editorPdfPageZero < total - 1) {
        this.setEditorPdfPageZero((prev) => Math.min(total - 1, prev + 1));
      }
    }
  }
}

// ============================================================================
// TESTS: DRAG-AND-DROP FILE LOADING
// ============================================================================

test("Drag-and-drop: successfully loads a valid PDF file", async () => {
  const app = new MockApp();
  const file = { name: "anatomy.pdf", type: "application/pdf" };
  const mockPdfDoc = { numPages: 15 };

  await app.processLoadedFile(file, null, mockPdfDoc);

  assert.equal(app.editorImage, null);
  assert.equal(app.editorPdfDoc, mockPdfDoc);
  assert.equal(app.editorPdfName, "anatomy.pdf");
  assert.equal(app.editorPdfPageZero, 0);
  assert.equal(app.editorMasks.length, 0);
  assert.equal(app.actionsLog[0], "anatomy.pdf (PDF, 15 pages) loaded in editor.");
});

test("Drag-and-drop: successfully loads a valid image file", async () => {
  const app = new MockApp();
  const file = { name: "brain.png", type: "image/png" };
  const mockResult = "data:image/png;base64,mockdata";

  await app.processLoadedFile(file, mockResult);

  assert.equal(app.editorPdfDoc, null);
  assert.equal(app.editorPdfBlob, null);
  assert.ok(app.editorImage);
  assert.equal(app.editorImage.name, "brain.png");
  assert.equal(app.editorImage.src, mockResult);
  assert.equal(app.editorMasks.length, 0);
  assert.equal(app.actionsLog[0], "brain.png loaded in editor.");
});

test("Drag-and-drop: rejects unsupported file types", async () => {
  const app = new MockApp();
  const file = { name: "notes.txt", type: "text/plain" };

  await app.processLoadedFile(file);

  assert.equal(app.editorImage, null);
  assert.equal(app.editorPdfDoc, null);
  assert.equal(app.actionsLog[0], "Unsupported file type. Choose an image or PDF.");
});

test("Drag-and-drop: handles null or undefined file gracefully", async () => {
  const app = new MockApp();
  await app.processLoadedFile(null);
  assert.equal(app.editorImage, null);
  assert.equal(app.editorPdfDoc, null);
  assert.equal(app.actionsLog.length, 0);
});

test("Drag-and-drop: handles PDF loading errors gracefully", async () => {
  const app = new MockApp();
  const file = { name: "corrupted.pdf", type: "application/pdf" };

  await app.processLoadedFile(file, null, null, true);

  assert.equal(app.editorPdfDoc, null);
  assert.equal(app.actionsLog[0], "Failed to load PDF in editor: Invalid PDF signature");
});

// ============================================================================
// TESTS: PAGE NAVIGATION CONTROLS
// ============================================================================

test("Page navigation: First, Last, Prev, Next controls", () => {
  const app = new MockApp();
  app.editorPdfDoc = { numPages: 5 };
  app.editorPdfPageZero = 2; // Start on page 3

  // Test Prev
  app.handlePrevPage();
  assert.equal(app.editorPdfPageZero, 1); // Page 2

  // Test Next
  app.handleNextPage();
  app.handleNextPage();
  assert.equal(app.editorPdfPageZero, 3); // Page 4

  // Test First
  app.handleGoToPage(0);
  assert.equal(app.editorPdfPageZero, 0); // Page 1

  // Test Last
  app.handleGoToPage(4);
  assert.equal(app.editorPdfPageZero, 4); // Page 5
});

test("Page navigation: boundary conditions for Prev/Next", () => {
  const app = new MockApp();
  app.editorPdfDoc = { numPages: 3 };

  // Prev on first page should stay on first page
  app.editorPdfPageZero = 0;
  app.handlePrevPage();
  assert.equal(app.editorPdfPageZero, 0);

  // Next on last page should stay on last page
  app.editorPdfPageZero = 2;
  app.handleNextPage();
  assert.equal(app.editorPdfPageZero, 2);
});

test("Page navigation: Jump to page input with valid, invalid, and out-of-bounds inputs", () => {
  const app = new MockApp();
  app.editorPdfDoc = { numPages: 10 };
  app.editorPdfPageZero = 0;

  // Valid jump
  app.handleJumpInput("5");
  assert.equal(app.editorPdfPageZero, 4);

  // Out of bounds (too large)
  app.handleJumpInput("12");
  assert.equal(app.editorPdfPageZero, 4); // Should ignore and remain on 4

  // Out of bounds (too small / negative)
  app.handleJumpInput("0");
  assert.equal(app.editorPdfPageZero, 4);

  // Invalid non-numeric input
  app.handleJumpInput("abc");
  assert.equal(app.editorPdfPageZero, 4);
});

test("Page navigation: Arrow keys navigation and input focus behavior", () => {
  const app = new MockApp();
  app.editorPdfDoc = { numPages: 5 };
  app.editorPdfPageZero = 1;

  // ArrowLeft should go prev
  app.handleArrowKey("arrowleft");
  assert.equal(app.editorPdfPageZero, 0);

  // ArrowRight should go next
  app.handleArrowKey("arrowright");
  assert.equal(app.editorPdfPageZero, 1);

  // Arrow keys should be ignored when typing in an INPUT element
  app.handleArrowKey("arrowright", "INPUT");
  assert.equal(app.editorPdfPageZero, 1); // Remains 1
});
