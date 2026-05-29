export const PDF_PAGE_GAP = 12;
export const REVIEW_MIN_SCALE = 0.05;
export const REVIEW_MAX_SCALE = 8;
export const REVIEW_ZOOM_FACTOR = 1.1;
export const REVIEW_RATING_QUALITIES = [1, 3, 4, 5, 6];

const LEARNING_STEPS = [1, 10];
const RELEARN_STEPS = [10];
const GRADUATING_INTERVAL = 1;
const EASY_INTERVAL = 4;
const PERFECT_INTERVAL = 7;
const EASY_BONUS = 1.3;
const PERFECT_BONUS = 1.6;
const MAX_INTERVAL = 365;
const EF_DELTA = {
  1: -0.2,
  3: -0.15,
  4: 0,
  5: 0.15,
  6: 0.3,
};

export function clampReviewScale(value) {
  const scale = Number(value || 1);
  return Math.max(REVIEW_MIN_SCALE, Math.min(REVIEW_MAX_SCALE, scale));
}

export function zoomReviewScale(current, direction) {
  const factor = direction > 0 ? REVIEW_ZOOM_FACTOR : 1 / REVIEW_ZOOM_FACTOR;
  return clampReviewScale(Number(current || 1) * factor);
}

function addMinutes(date, minutes) {
  return new Date(date.getTime() + Number(minutes || 0) * 60 * 1000);
}

function dueInDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + Number(days || 0));
}

function updateEase(ease, quality) {
  return Math.max(1.3, Math.min(2.5, Number(ease || 2.5) + Number(EF_DELTA[quality] || 0)));
}

function initSchedule(item, now = new Date()) {
  return {
    sched_state: item?.sched_state || "new",
    sched_step: Number(item?.sched_step || 0),
    sm2_interval: Number(item?.sm2_interval || 1),
    sm2_ease: Number(item?.sm2_ease || 2.5),
    sm2_due: item?.sm2_due ? new Date(item.sm2_due) : now,
    sm2_repetitions: Number(item?.sm2_repetitions || 0),
  };
}

function formatLearningDue(dueDate, now) {
  const minutes = Math.max(1, Math.round((dueDate.getTime() - now.getTime()) / 60000));
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h`;
}

function updateSchedulePreview(item, quality, now = new Date()) {
  const current = initSchedule(item, now);
  let state = current.sched_state === "new" ? "learning" : current.sched_state;
  let step = current.sched_step;
  let ease = current.sm2_ease;
  let interval = current.sm2_interval;
  let due = current.sm2_due;
  const goodIntervalRaw =
    state === "review"
      ? current.sm2_repetitions === 0
        ? 1
        : current.sm2_repetitions === 1
          ? 6
          : Math.min(MAX_INTERVAL, Math.max(1, Math.round(interval * ease)))
      : GRADUATING_INTERVAL;

  if (quality <= 1) {
    if (state === "review") ease = updateEase(ease, 1);
    const steps = state === "review" ? RELEARN_STEPS : LEARNING_STEPS;
    state = state === "review" ? "relearn" : "learning";
    step = 0;
    due = addMinutes(now, steps[0]);
  } else if (quality === 3) {
    if (state === "learning" || state === "relearn") {
      const steps = state === "relearn" ? RELEARN_STEPS : LEARNING_STEPS;
      const hardMinutes = step === 0 && steps.length > 1 ? Math.floor((steps[0] + steps[1]) / 2) : steps[Math.min(step, steps.length - 1)];
      due = addMinutes(now, hardMinutes);
    } else {
      ease = updateEase(ease, 3);
      state = "review";
      step = 0;
      interval = Math.min(Math.min(MAX_INTERVAL, Math.max(1, Math.round(interval * 1.2))), goodIntervalRaw);
      due = dueInDays(now, interval);
    }
  } else if (quality === 5) {
    if (state === "review") ease = updateEase(ease, 5);
    state = "review";
    step = 0;
    interval =
      current.sched_state === "review"
        ? Math.max(Math.min(MAX_INTERVAL, Math.max(EASY_INTERVAL, Math.round(interval * ease * EASY_BONUS))), goodIntervalRaw + 1)
        : EASY_INTERVAL;
    due = dueInDays(now, interval);
  } else if (quality >= 6) {
    if (state === "review") ease = updateEase(ease, 6);
    state = "review";
    step = 0;
    if (current.sched_state === "review") {
      const easyRaw = Math.max(Math.min(MAX_INTERVAL, Math.max(EASY_INTERVAL, Math.round(interval * ease * EASY_BONUS))), goodIntervalRaw + 1);
      interval = Math.max(Math.min(MAX_INTERVAL, Math.max(PERFECT_INTERVAL, Math.round(interval * ease * PERFECT_BONUS))), easyRaw + 1);
    } else {
      interval = PERFECT_INTERVAL;
    }
    due = dueInDays(now, interval);
  } else if (state === "learning" || state === "relearn") {
    const steps = state === "relearn" ? RELEARN_STEPS : LEARNING_STEPS;
    const nextStep = step + 1;
    if (nextStep >= steps.length) {
      state = "review";
      step = 0;
      interval = GRADUATING_INTERVAL;
      due = dueInDays(now, interval);
    } else {
      step = nextStep;
      due = addMinutes(now, steps[nextStep]);
    }
  } else {
    state = "review";
    step = 0;
    interval = goodIntervalRaw;
    due = dueInDays(now, interval);
  }

  return state === "learning" || state === "relearn"
    ? formatLearningDue(due, now)
    : `${Math.max(1, Math.round(interval))}d`;
}

export function reviewRatingPreviews(item, now = new Date()) {
  const previews = item?.rating_previews || {};
  return Object.fromEntries(
    REVIEW_RATING_QUALITIES.map((quality) => [
      quality,
      previews[String(quality)] || previews[quality] || updateSchedulePreview(item, quality, now),
    ]),
  );
}

export function boxIdentity(box, index = 0) {
  return String(box?.box_id || `idx:${box?.box_index ?? index}`);
}

export function reviewItemKey(item) {
  const target =
    item?.group_id
      ? `group:${item.group_id}`
      : item?.box_id || (item?.box_index ?? "card");
  return `${item?.deck_id}:${item?.card_id}:${target}`;
}

export function itemTargetLabel(item) {
  const localMaskCount = item?.local_masks?.length || 0;
  if (localMaskCount) {
    return `${localMaskCount} Mask${localMaskCount === 1 ? "" : "s"}`;
  }
  if (item?.target_kind === "group" || item?.group_id) {
    const count = item?.target_box_indexes?.length || item?.target_box_ids?.length || 1;
    return `${count} Grouped Occlusion${count === 1 ? "" : "s"}`;
  }
  const hasBox =
    Boolean(item?.box_id) || (item?.box_index !== null && item?.box_index !== undefined);
  if (hasBox) {
    const n = Number.isFinite(Number(item.box_index)) ? Number(item.box_index) + 1 : "?";
    return `Occlusion ${n}`;
  }
  return "Whole card";
}

export function reviewQueueLabel(item) {
  const pagePart = Number.isFinite(Number(item?.page_num))
    ? `p.${Number(item.page_num) + 1} · `
    : "";
  if (item?.target_kind === "group" || item?.group_id) {
    const firstIndex = item?.target_box_indexes?.[0];
    const n = Number.isFinite(Number(firstIndex)) ? Number(firstIndex) + 1 : "?";
    return `${pagePart}#${n} [grp]`;
  }
  if (item?.box_index === null || item?.box_index === undefined) {
    return `${pagePart}card`;
  }
  return `${pagePart}#${Number(item.box_index) + 1}`;
}

export function normalizeReviewBoxes(item) {
  if (Array.isArray(item?.boxes) && item.boxes.length) {
    return item.boxes.map((box, index) => ({
      ...box,
      box_index: box.box_index ?? index,
      rect: Array.isArray(box.rect) ? box.rect : [],
    }));
  }
  if (Array.isArray(item?.rect) && item.rect.length >= 4) {
    return [
      {
        box_id: item.box_id || "",
        box_index: item.box_index ?? 0,
        rect: item.rect,
        shape: item.shape || "rect",
        angle: item.angle || 0,
        group_id: item.group_id || "",
        page_num: item.page_num || 0,
      },
    ];
  }
  return [];
}

export function pageTopsFromDims(dims, pageGap = PDF_PAGE_GAP) {
  const tops = [];
  let top = 0;
  for (const dim of dims || []) {
    tops.push(top);
    top += Number(dim?.height || 0) + pageGap;
  }
  return tops;
}

export function fitWidthScale(frameSize, documentSize, paddingX = 32) {
  const availableWidth = Math.max(1, Number(frameSize?.width || 0) - Number(paddingX || 0));
  const documentWidth = Number(documentSize?.width || 0);
  if (!documentWidth) return 1;
  return Math.max(0.05, Math.min(8, availableWidth / documentWidth));
}

export function targetRectForItem(boxes, item) {
  const rects = (boxes || [])
    .filter((box, index) => isTargetReviewBox(box, item, box.box_index ?? index))
    .map((box) => {
      const rect = Array.isArray(box?.rect) ? box.rect : [];
      if (rect.length < 4) return null;
      return {
        x: Number(rect[0] || 0),
        y: Number(rect[1] || 0),
        width: Number(rect[2] || 0),
        height: Number(rect[3] || 0),
      };
    })
    .filter(Boolean);
  if (!rects.length) return null;
  const left = Math.min(...rects.map((rect) => rect.x));
  const top = Math.min(...rects.map((rect) => rect.y));
  const right = Math.max(...rects.map((rect) => rect.x + rect.width));
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height));
  return {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
  };
}

export function centerScrollForRect(frameSize, documentSize, rect, scale = 1) {
  if (!rect || !frameSize?.width || !frameSize?.height || !documentSize?.width) return null;
  const zoom = clampReviewScale(scale);
  const contentWidth = Number(documentSize.width || 0) * zoom;
  const contentHeight = Number(documentSize.height || 0) * zoom;
  const centerX = (Number(rect.x || 0) + Number(rect.width || 0) / 2) * zoom;
  const centerY = (Number(rect.y || 0) + Number(rect.height || 0) / 2) * zoom;
  const maxLeft = Math.max(0, contentWidth - Number(frameSize.width || 0));
  const maxTop = Math.max(0, contentHeight - Number(frameSize.height || 0));
  return {
    left: Math.max(0, Math.min(centerX - Number(frameSize.width || 0) / 2, maxLeft)),
    top: Math.max(0, Math.min(centerY - Number(frameSize.height || 0) / 2, maxTop)),
  };
}

export function pointInReviewBox(point, box) {
  const rect = Array.isArray(box?.rect) ? box.rect : [];
  if (!point || rect.length < 4) return false;
  const x = Number(point.x || 0);
  const y = Number(point.y || 0);
  const left = Number(rect[0] || 0);
  const top = Number(rect[1] || 0);
  const width = Number(rect[2] || 0);
  const height = Number(rect[3] || 0);
  const cx = left + width / 2;
  const cy = top + height / 2;
  const angle = (-Number(box?.angle || 0) * Math.PI) / 180;
  const dx = x - cx;
  const dy = y - cy;
  const localX = dx * Math.cos(angle) - dy * Math.sin(angle);
  const localY = dx * Math.sin(angle) + dy * Math.cos(angle);
  if (box?.shape === "ellipse") {
    const rx = width / 2;
    const ry = height / 2;
    if (rx < 1 || ry < 1) return false;
    return (localX / rx) ** 2 + (localY / ry) ** 2 <= 1;
  }
  return Math.abs(localX) <= width / 2 && Math.abs(localY) <= height / 2;
}

export function boxAtPoint(boxes, point) {
  for (let index = (boxes || []).length - 1; index >= 0; index -= 1) {
    if (pointInReviewBox(point, boxes[index])) {
      return { box: boxes[index], index };
    }
  }
  return null;
}

export function inferBoxPage(box, pageTops, pageDims) {
  if (Number.isFinite(Number(box?.page_num))) {
    return Number(box.page_num);
  }
  const rect = Array.isArray(box?.rect) ? box.rect : [];
  if (rect.length < 4 || !pageTops?.length) return 0;
  const centerY = Number(rect[1] || 0) + Number(rect[3] || 0) / 2;
  let page = 0;
  for (let index = 0; index < pageTops.length; index += 1) {
    const top = pageTops[index];
    const height = Number(pageDims?.[index]?.height || 0);
    if (centerY >= top && centerY <= top + height) return index;
    if (centerY >= top) page = index;
  }
  return Math.max(0, Math.min(page, Math.max(0, pageTops.length - 1)));
}

export function isTargetReviewBox(box, item, index = 0) {
  const targetIndexes = new Set((item?.target_box_indexes || []).map(Number));
  const targetIds = new Set((item?.target_box_ids || []).map(String));
  if (item?.group_id && box?.group_id && String(box.group_id) === String(item.group_id)) {
    return true;
  }
  if (box?.box_id && targetIds.has(String(box.box_id))) return true;
  if (targetIndexes.has(Number(box?.box_index ?? index))) return true;
  if (item?.box_id && box?.box_id && String(item.box_id) === String(box.box_id)) return true;
  return Number(item?.box_index) === Number(box?.box_index ?? index);
}

export function reviewMaskState(box, item, index, revealed, reviewStyle) {
  const target = isTargetReviewBox(box, item, index);
  if (reviewStyle === "hide_one" && !target) {
    return "context";
  }
  if (revealed && target) {
    return "revealed";
  }
  return target ? "target" : "hidden";
}

export function maskRectForPage(box, pageTop = 0) {
  const rect = Array.isArray(box?.rect) ? box.rect : [];
  if (rect.length < 4) return null;
  return {
    x: Number(rect[0] || 0),
    y: Number(rect[1] || 0) - Number(pageTop || 0),
    width: Number(rect[2] || 0),
    height: Number(rect[3] || 0),
  };
}

export function floatingOverlayPosition(frameMetrics, overlayMetrics = {}) {
  const clientWidth = Number(frameMetrics?.clientWidth || 0);
  const clientHeight = Number(frameMetrics?.clientHeight || 0);
  if (!clientWidth || !clientHeight) return null;

  const scrollLeft = Number(frameMetrics?.scrollLeft || 0);
  const scrollTop = Number(frameMetrics?.scrollTop || 0);
  const overlayHeight = Number(overlayMetrics?.height || 54);
  const bottomGap = Number(overlayMetrics?.bottomGap || 18);

  return {
    left: scrollLeft + clientWidth / 2,
    top: scrollTop + Math.max(12, clientHeight - overlayHeight - bottomGap),
  };
}

export function maskStyleFromRect(rect, surfaceSize) {
  if (!rect || !surfaceSize?.width || !surfaceSize?.height) return {};
  return {
    left: `${(rect.x / surfaceSize.width) * 100}%`,
    top: `${(rect.y / surfaceSize.height) * 100}%`,
    width: `${(rect.width / surfaceSize.width) * 100}%`,
    height: `${(rect.height / surfaceSize.height) * 100}%`,
  };
}
