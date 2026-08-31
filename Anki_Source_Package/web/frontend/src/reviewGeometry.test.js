import assert from "node:assert/strict";
import test from "node:test";

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
} from "./reviewGeometry.js";

test("review geometry identifies grouped review targets", () => {
  const item = {
    deck_id: 1,
    card_id: "card-1",
    group_id: "g1",
    target_kind: "group",
    target_box_ids: ["b1", "b2"],
    target_box_indexes: [0, 1],
  };

  assert.equal(reviewItemKey(item), "1:card-1:group:g1");
  assert.equal(itemTargetLabel(item), "2 Grouped Occlusions");
  assert.equal(isTargetReviewBox({ box_id: "b2", group_id: "g1" }, item, 1), true);
  assert.equal(isTargetReviewBox({ box_id: "b3", group_id: "" }, item, 2), false);
});

test("review geometry converts desktop page rects into current-page rects", () => {
  const dims = [
    { width: 600, height: 800 },
    { width: 600, height: 900 },
  ];
  const tops = pageTopsFromDims(dims);
  const box = { rect: [40, tops[1] + 120, 200, 60] };

  assert.equal(inferBoxPage(box, tops, dims), 1);
  assert.deepEqual(maskRectForPage(box, tops[1]), {
    x: 40,
    y: 120,
    width: 200,
    height: 60,
  });
});

test("review fit scale matches desktop fit-width behavior", () => {
  assert.equal(fitWidthScale({ width: 1032 }, { width: 500 }), 2);
  assert.equal(fitWidthScale({ width: 1000 }, { width: 500 }, 0), 2);
  assert.equal(fitWidthScale({ width: 10 }, { width: 500 }), 0.05);
  assert.equal(fitWidthScale({ width: 10000 }, { width: 100 }), 8);
});

test("review zoom and center mirror desktop canvas math", () => {
  assert.equal(Number(zoomReviewScale(1, 1).toFixed(2)), 1.1);
  assert.equal(Number(zoomReviewScale(1.1, -1).toFixed(2)), 1);
  assert.deepEqual(
    centerScrollForRect(
      { width: 500, height: 400 },
      { width: 1000, height: 1200 },
      { x: 700, y: 800, width: 100, height: 100 },
      1,
    ),
    { left: 500, top: 650 },
  );
});

test("review queue labels use desktop page and target labels", () => {
  assert.equal(reviewQueueLabel({ page_num: 4, box_index: 2 }), "p.5 · #3");
  assert.equal(
    reviewQueueLabel({ page_num: 1, group_id: "g1", target_box_indexes: [5] }),
    "p.2 · #6 [grp]",
  );
});

test("review mask state reveals only the active target", () => {
  const item = { box_id: "b1", target_box_ids: ["b1"], target_box_indexes: [0] };

  assert.equal(reviewMaskState({ box_id: "b1" }, item, 0, false, "hide_all"), "target");
  assert.equal(reviewMaskState({ box_id: "b1" }, item, 0, true, "hide_all"), "revealed");
  assert.equal(reviewMaskState({ box_id: "b2" }, item, 1, false, "hide_one"), "context");
});

test("review target rect and hit testing support center and ctrl reveal", () => {
  const boxes = [
    { box_id: "a", box_index: 0, rect: [10, 20, 100, 40] },
    { box_id: "b", box_index: 1, group_id: "g1", rect: [200, 20, 60, 60], page_num: 1 },
    { box_id: "c", box_index: 2, group_id: "g1", rect: [280, 40, 60, 80], page_num: 1 },
  ];

  assert.deepEqual(targetRectForItem(boxes, { group_id: "g1" }, [0, 800]), {
    x: 200,
    y: 820,
    width: 140,
    height: 100,
  });
  assert.equal(boxAtPoint(boxes, { x: 290, y: 50 }).box.box_id, "c");
  assert.equal(boxAtPoint(boxes, { x: 5, y: 5 }), null);
});

test("review reveal overlay floats inside the visible scroll viewport", () => {
  assert.deepEqual(
    floatingOverlayPosition(
      { clientWidth: 800, clientHeight: 600, scrollLeft: 40, scrollTop: 120 },
      { height: 54 },
    ),
    { left: 440, top: 648 },
  );
  assert.deepEqual(
    floatingOverlayPosition(
      { clientWidth: 800, clientHeight: 600, scrollLeft: 40, scrollTop: 300 },
      { height: 54 },
    ),
    { left: 440, top: 828 },
  );
  assert.equal(floatingOverlayPosition({ clientWidth: 0, clientHeight: 600 }), null);
});

test("review rating previews mirror desktop learning button labels", () => {
  assert.deepEqual(
    reviewRatingPreviews(
      { sched_state: "new", sm2_last_quality: -1 },
      new Date("2026-05-27T10:00:00"),
    ),
    {
      1: "1m",
      3: "5m",
      4: "10m",
      5: "4d",
      6: "7d",
    },
  );
  assert.deepEqual(
    reviewRatingPreviews({ rating_previews: { 1: "10m", 3: "12d" } }),
    {
      1: "10m",
      3: "12d",
      4: "10m",
      5: "4d",
      6: "7d",
    },
  );
});
