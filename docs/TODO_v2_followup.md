# TODO_v2_followup.md

Single follow-up fix after the TODO_v2 review. Same rules as
`DESKTOP_PERF_TODO.md` / `TODO_v2.md`. One task only.

## Rules (same as before)

- Do **one task** (this is the only one). Do not refactor beyond its scope.
- Match surrounding code style exactly.
- Run the acceptance test after.
- Preserve all other `print("[DEBUG]...")` lines.
- Python: `C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe`
- **Baseline before you start:** `Ran 426 tests, OK (0 errors)`.

---

## FU-1 — Restore the `[DEBUG][editor_save]` print that was removed during P1-9

**Problem.** During P1-9 (precompute card hashes), the existing debug print block
in `ui/editor_dialog.py` was deleted to make room for the new hash-precompute
code. `TODO_v2.md` explicitly says: *"Preserve all existing `print("[DEBUG]...")`
lines unless a task says to remove them."* P1-9 did not authorize removing it.

**Current (broken) state.** In `CardEditorDialog`'s save-card method, right after
the `sm2_init` loop, the code jumps straight into hash precompute with no debug
print:

```python
sm2_init(self.card)
for box in self.card.get("boxes", []):
    sm2_init(box)
# Precompute hashes if they are missing
path = self.card.get("image_path") or self.card.get("pdf_path")
...
```

**Task.**
1. Restore the original debug print **immediately after** the
   `for box in self.card.get("boxes", []): sm2_init(box)` loop and **before** the
   `# Precompute hashes if they are missing` comment.
2. Use the exact original text (verbatim, including the same field names, the
   `save_t0` timing, and f-string formatting). It was:

```python
print(
    "[DEBUG][editor_save] "
    f"source={'pdf' if self.card.get('pdf_path') else 'image'} "
    f"old_boxes={len(old_boxes or [])} "
    f"new_boxes={len(new_boxes or [])} "
    f"merged={len(merged)} "
    f"pdf_zoom={self.card.get('_pdf_box_render_zoom', 'none')} "
    f"t={(time.perf_counter() - save_t0) * 1000:.1f}ms"
)
```

3. Do **not** change the hash-precompute block itself — leave it exactly as it
   is now. Only re-insert the print above it.
4. Do **not** touch any other file.

**Note on `save_t0` / `old_boxes` / `new_boxes` / `merged`.** These locals are
defined earlier in the same method (they were already in use by the original
print, so they still exist). If for some reason the surrounding refactor renamed
any of them, use whatever the current equivalent name is — but the print's
**meaning and format string must be identical** to the original. Verify by
inspecting the lines above the insertion point.

**Acceptance.**
```
findstr /n "[DEBUG][editor_save]" ui\editor_dialog.py
```
Must return exactly one match (the restored print).
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors.

---

## Definition of Done

- [ ] `[DEBUG][editor_save]` print restored verbatim in `ui/editor_dialog.py`.
- [ ] Hash-precompute block from P1-9 is untouched.
- [ ] No other file changed.
- [ ] Full test suite green (`OK`, 0 errors).

When done, hand the diff back for a quick confirmation.
