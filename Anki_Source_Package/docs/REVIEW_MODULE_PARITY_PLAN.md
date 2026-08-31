# Review Module Parity Plan

Desktop source of truth:
- `ui/review_screen.py`
- `services/review_manager.py`
- `services/shortcut_manager.py`
- `ui/canvas/state.py`
- `ui/canvas/renderer.py`
- `ui/canvas/interaction.py`
- `ui/pdf_viewer_controller.py`

Web review files:
- `web/frontend/src/App.jsx`
- `web/frontend/src/reviewSurface.jsx`
- `web/frontend/src/reviewGeometry.js`
- `web/backend/anki_web/store.py`

## Keep And Match

- Session queue is a fixed review run, not a shrinking list. Rated rows stay visible as done, progress moves forward, and the final summary opens after the last pending item.
- Review PDF is one continuous scroll surface with page offsets, sticky page controls, and page-aware mask positions.
- PDF rendering should be current/visible-page first. The desktop uses skeletons, priority pages, and on-demand rendering; the web uses PDF.js with lazy current/nearby page rendering.
- Fit is measured fit-width against the review viewport. Center scrolls to the active mask. `C` fits-and-centers; `F` toggles focus mode; `Ctrl+0` is fit only.
- Reveal controls float inside the visible canvas scroll area, matching the desktop `_reveal_bar`; they recalc from the frame scroll offset instead of being glued to PDF/image coordinates.
- Non-revealed PDF/image masks must be opaque enough to hide the answer; revealed/context masks can remain transparent.
- Toolbar `Prev` and `Next` are PDF page navigation, not card navigation.
- Pen is active by default in review. Plain pen drag draws ink; `X` cycles color; `+/-` adjusts width; `Delete` clears marks; Ctrl-click/tap on a mask toggles that mask reveal.
- Rating shortcuts remain gated behind reveal: `Space`, then `1/2/3/4/5`.
- Web should support safe browser equivalents for desktop review shortcuts: `Esc`, `E`, `L`, `Ctrl+E`, `Ctrl+L`, `Ctrl+Z`, `Ctrl+Y`, `Left`, `Right`, zoom, fit, center, pen controls.

## Drop Or Defer For Web

- Browser-hosted folder reveal uses the local backend to ask the OS file manager to select the PDF. This remains local-app-only and should not be exposed from a hosted web deployment.
- Review rating undo/redo uses local backend JSON snapshots plus frontend session-state snapshots. It is session-scoped like the desktop review manager stacks.
- Native annotation dialog/window management is desktop-only. Web review keeps pen annotation and routes durable mask editing through `Edit Card`.
- PyQt/QPixmap RAM cache panels are desktop internals. Web review keeps browser-local rendering and PDF.js lazy page work instead.

## Current Web Gap Status

- Implemented: continuous PDF surface, review pen, measured fit, page toolbar navigation, center requests, focus mode, queue hide/show, session queue snapshots/done rows, lazy PDF page rendering, floating reveal control, stronger hidden masks, safe shortcut coverage, rating undo/redo, local folder reveal.
- Deferred: native annotation dialog.
