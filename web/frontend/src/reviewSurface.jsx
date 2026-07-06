import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import { mediaUrl } from "./api.js";
import {
  boxAtPoint,
  boxIdentity,
  centerScrollForRect,
  fitWidthScale,
  floatingOverlayPosition,
  maskRectForPage,
  maskStyleFromRect,
  normalizeReviewBoxes,
  pageTopsFromDims,
  reviewMaskState,
  targetRectForItem,
} from "./reviewGeometry.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

function pointFromPointer(event, element, surfaceSize) {
  const rect = element.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * Number(surfaceSize?.width || 100),
    y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * Number(surfaceSize?.height || 100),
  };
}

function strokePath(points) {
  if (!points?.length) return "";
  return points
    .map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(3)} ${point.y.toFixed(3)}`)
    .join(" ");
}

function InkLayer({ active, color, width, strokes, onChange, onPointAction, surfaceSize }) {
  const svgRef = useRef(null);
  const draftIdRef = useRef("");

  function updateDraft(event, create = false) {
    if (!active || !svgRef.current) return;
    const point = pointFromPointer(event, svgRef.current, surfaceSize);
    if (create) {
      const id = `stroke-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      draftIdRef.current = id;
      onChange((prevStrokes) => [...(prevStrokes || []), { id, color, width, points: [point] }]);
      return;
    }
    const currentDraftId = draftIdRef.current;
    if (!currentDraftId) return;
    onChange((prevStrokes) =>
      (prevStrokes || []).map((stroke) =>
        stroke.id === currentDraftId
          ? { ...stroke, points: [...stroke.points, point] }
          : stroke,
      ),
    );
  }

  return (
    <svg
      className={`review-ink-layer ${active ? "active" : ""}`}
      onPointerDown={(event) => {
        if (!active) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        if (event.ctrlKey || event.metaKey) {
          draftIdRef.current = "";
          onPointAction?.(pointFromPointer(event, event.currentTarget, surfaceSize));
          return;
        }
        updateDraft(event, true);
      }}
      onPointerMove={(event) => {
        if (!active || !draftIdRef.current) return;
        updateDraft(event);
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
          event.currentTarget.releasePointerCapture?.(event.pointerId);
        }
        draftIdRef.current = "";
      }}
      onPointerCancel={(event) => {
        if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
          event.currentTarget.releasePointerCapture?.(event.pointerId);
        }
        draftIdRef.current = "";
      }}
      onLostPointerCapture={() => {
        draftIdRef.current = "";
      }}
      preserveAspectRatio="none"
      ref={svgRef}
      viewBox={`0 0 ${Math.max(1, Number(surfaceSize?.width || 100))} ${Math.max(
        1,
        Number(surfaceSize?.height || 100),
      )}`}
    >
      {(strokes || []).map((stroke) => (
        <path
          d={strokePath(stroke.points)}
          fill="none"
          key={stroke.id}
          stroke={stroke.color}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={stroke.width}
        />
      ))}
    </svg>
  );
}

function ReviewMask({
  box,
  item,
  index,
  pageTop,
  surfaceSize,
  revealed,
  revealedBoxes,
  reviewStyle,
  onToggleReveal,
}) {
  const rect = maskRectForPage(box, pageTop);
  const style = maskStyleFromRect(rect, surfaceSize);
  if (!rect || !style.width) return null;
  const revealedByClick = revealedBoxes?.has?.(boxIdentity(box, index));
  const state = reviewMaskState(box, item, index, revealed || revealedByClick, reviewStyle);
  return (
    <span
      className={`review-mask desktop-mask ${state} ${
        box.shape === "ellipse" ? "ellipse" : ""
      }`}
      onPointerDown={(event) => {
        if (!onToggleReveal) return;
        event.preventDefault();
        event.stopPropagation();
        onToggleReveal(box, index);
      }}
      style={{
        ...style,
        transform: `rotate(${Number(box.angle || 0)}deg)`,
      }}
    />
  );
}

function overlayStyle(position) {
  return position
    ? {
        left: `${position.left}px`,
        top: `${position.top}px`,
      }
    : {
        left: "50%",
        top: "50%",
      };
}

function useFloatingRevealPosition(frameRef, overlayRef, deps = []) {
  const [position, setPosition] = useState(null);

  const updatePosition = useCallback(() => {
    const frame = frameRef.current;
    if (!frame) return;
    setPosition(
      floatingOverlayPosition(
        {
          clientHeight: frame.clientHeight,
          clientWidth: frame.clientWidth,
          scrollLeft: frame.scrollLeft,
          scrollTop: frame.scrollTop,
        },
        {
          height: overlayRef.current?.offsetHeight || 54,
        },
      ),
    );
  }, [frameRef, overlayRef]);

  useEffect(() => {
    updatePosition();
  }, [updatePosition, ...deps]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(updatePosition);
    observer.observe(frame);
    if (overlayRef.current) observer.observe(overlayRef.current);
    return () => observer.disconnect();
  }, [frameRef, overlayRef, updatePosition]);

  return [position, updatePosition];
}

function RevealOverlay({ item, overlayRef, ratingOverlay, revealed, onReveal, position }) {
  const style = overlayStyle(position);
  if (revealed) {
    return ratingOverlay ? (
      <div className="review-rating-float" ref={overlayRef} style={style}>
        {ratingOverlay}
      </div>
    ) : (
      <div className="answer-chip" ref={overlayRef} style={style}>
        <strong>Answer revealed</strong>
        <span>{item?.target_kind === "group" ? "Grouped masks" : "Target mask"}</span>
      </div>
    );
  }
  return (
    <button
      className="reveal-button image-reveal"
      disabled={!item}
      onClick={(event) => {
        onReveal?.(event);
      }}
      ref={overlayRef}
      style={style}
      type="button"
    >
      Show Answer <span>[Space]</span>
    </button>
  );
}

function ImageReviewSurface(props) {
  const {
    item,
    revealed,
    onReveal,
    reviewStyle,
    zoom,
    penActive,
    penColor,
    penWidth,
    inkStrokes,
    onInkChange,
    fitRequest,
    onFitScale,
    centerRequest,
    onCenterComplete,
    revealedBoxes,
    onToggleBoxReveal,
    onPageStateChange,
    ratingOverlay,
    localDb,
  } = props;
  const frameRef = useRef(null);
  const overlayRef = useRef(null);
  const [imageSize, setImageSize] = useState(null);
  const [source, setSource] = useState("");

  const blobUrlRef = useRef(null);

  useEffect(() => {
    let active = true;
    async function resolveSource() {
      if (localDb && item?.image_path) {
        try {
          const fileRecord = await localDb.get("files", item.image_path);
          if (fileRecord && fileRecord.blob) {
            if (blobUrlRef.current) {
              URL.revokeObjectURL(blobUrlRef.current);
            }
            const url = URL.createObjectURL(fileRecord.blob);
            blobUrlRef.current = url;
            if (active) {
              setSource(url);
              return;
            }
          }
        } catch (e) {
          console.warn("Failed to retrieve image from IndexedDB", e);
        }
      }
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
      if (active) {
        setSource(item?.image_data_url || mediaUrl(item?.image_path));
      }
    }
    resolveSource();
    return () => {
      active = false;
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [item?.image_path, item?.image_data_url, localDb]);
  const boxes = normalizeReviewBoxes(item);
  const localMasks = item?.local_masks || [];
  const [revealPosition, updateRevealPosition] = useFloatingRevealPosition(
    frameRef,
    overlayRef,
    [revealed, imageSize, zoom, item?.card_id, item?.box_id, item?.group_id],
  );

  function centerOnTarget() {
    if (!frameRef.current || !imageSize) return;
    const targetRect = targetRectForItem(boxes, item);
    const scroll = centerScrollForRect(
      { width: frameRef.current.clientWidth, height: frameRef.current.clientHeight },
      imageSize,
      targetRect,
      zoom,
    );
    if (!scroll) return;
    frameRef.current.scrollTo({ left: scroll.left, top: scroll.top, behavior: "auto" });
  }

  function toggleBoxRevealAtPoint(point) {
    const hit = boxAtPoint(boxes, point);
    if (hit) onToggleBoxReveal?.(hit.box, hit.index);
  }

  useEffect(() => {
    if (!fitRequest || !imageSize || !frameRef.current) return;
    onFitScale?.(
      fitWidthScale(
        { width: frameRef.current.clientWidth, height: frameRef.current.clientHeight },
        imageSize,
        0,
      ),
    );
  }, [fitRequest, imageSize, onFitScale]);

  useEffect(() => {
    onPageStateChange?.({ pageZero: 0, pageCount: 0, hasPages: false });
  }, [item?.card_id, item?.box_id, item?.group_id, onPageStateChange]);

  useEffect(() => {
    if (!centerRequest) return;
    centerOnTarget();
    onCenterComplete?.();
  }, [centerRequest, imageSize, zoom]);

  return (
    <div
      className={`review-image-frame review-document-frame ${revealed ? "revealed" : ""}`}
      onScroll={updateRevealPosition}
      ref={frameRef}
    >
      <div
        className="review-document-scale-box"
        style={{
          width: imageSize ? `${imageSize.width * zoom}px` : undefined,
          height: imageSize ? `${imageSize.height * zoom}px` : undefined,
        }}
      >
        <div
          className="review-image-zoom-layer review-document-layer"
          style={{
            "--review-zoom": zoom,
            width: imageSize ? `${imageSize.width}px` : undefined,
            height: imageSize ? `${imageSize.height}px` : undefined,
          }}
        >
          {source ? (
            <img
              alt=""
              draggable="false"
              onLoad={(event) =>
                setImageSize({
                  width: event.currentTarget.naturalWidth || event.currentTarget.clientWidth,
                  height: event.currentTarget.naturalHeight || event.currentTarget.clientHeight,
                })
              }
              src={source}
            />
          ) : (
            <div className="review-document-empty">No image source</div>
          )}
          {imageSize
            ? boxes.map((box, index) => (
                <ReviewMask
                  box={box}
                  index={index}
                  item={item}
                  key={`${box.box_id || index}`}
                  onToggleReveal={onToggleBoxReveal}
                  pageTop={0}
                  revealed={revealed}
                  revealedBoxes={revealedBoxes}
                  reviewStyle={reviewStyle}
                  surfaceSize={imageSize}
                />
              ))
            : null}
          {localMasks.map((mask) => (
            <span
              className={`review-mask local-review-mask ${revealed ? "revealed" : "target"}`}
              key={mask.id}
              style={{
                left: `${mask.x}%`,
                top: `${mask.y}%`,
                width: `${mask.width}%`,
                height: `${mask.height}%`,
              }}
            />
          ))}
          {imageSize ? (
            <InkLayer
              active={penActive}
              color={penColor}
              onChange={onInkChange}
              onPointAction={toggleBoxRevealAtPoint}
              strokes={inkStrokes}
              surfaceSize={imageSize}
              width={penWidth}
            />
          ) : null}
        </div>
      </div>
      <RevealOverlay
        item={item}
        onReveal={onReveal}
        overlayRef={overlayRef}
        position={revealPosition}
        ratingOverlay={ratingOverlay}
        revealed={revealed}
      />
    </div>
  );
}

function PdfReviewSurface(props) {
  const {
    item,
    revealed,
    onReveal,
    reviewStyle,
    zoom,
    penActive,
    penColor,
    penWidth,
    inkStrokes,
    onInkChange,
    fitRequest,
    onFitScale,
    centerRequest,
    onCenterComplete,
    revealedBoxes,
    onToggleBoxReveal,
    pageCommand,
    onPageStateChange,
    ratingOverlay,
    localDb,
  } = props;
  const frameRef = useRef(null);
  const overlayRef = useRef(null);
  const canvasRefs = useRef(new Map());
  const renderTasksRef = useRef(new Map());
  const renderedPagesRef = useRef(new Set());
  const blobUrlRef = useRef(null);
  const renderingPagesRef = useRef(new Set());
  const [docState, setDocState] = useState({
    doc: null,
    pageCount: 0,
    pageDims: [],
    pageTops: [],
    loading: false,
    error: "",
  });
  const [pageZero, setPageZero] = useState(Number(item?.page_num || 0));
  const scale = Number(item?.pdf_box_render_zoom || 1.5);
  const boxes = normalizeReviewBoxes(item);
  const documentSize = useMemo(() => {
    const width = Math.max(0, ...docState.pageDims.map((dim) => Number(dim.width || 0)));
    const lastTop = docState.pageTops[docState.pageTops.length - 1] || 0;
    const lastHeight = docState.pageDims[docState.pageDims.length - 1]?.height || 0;
    return {
      width,
      height: lastTop + lastHeight,
    };
  }, [docState.pageDims, docState.pageTops]);
  const [revealPosition, updateRevealPosition] = useFloatingRevealPosition(
    frameRef,
    overlayRef,
    [revealed, documentSize, zoom, item?.card_id, item?.box_id, item?.group_id],
  );

  function cancelRenderTasks() {
    for (const task of renderTasksRef.current.values()) {
      task?.cancel?.();
    }
    renderTasksRef.current.clear();
    renderingPagesRef.current.clear();
  }

  function pageFromScroll(scrollTop) {
    if (!docState.pageTops.length) return 0;
    const imageScrollTop = Number(scrollTop || 0) / Math.max(Number(zoom || 1), 0.01);
    let nextPage = 0;
    for (let index = 0; index < docState.pageTops.length; index += 1) {
      if (imageScrollTop + 1 >= docState.pageTops[index]) {
        nextPage = index;
      } else {
        break;
      }
    }
    return Math.max(0, Math.min(nextPage, Math.max(0, docState.pageCount - 1)));
  }

  function currentScrollPage() {
    return pageFromScroll(frameRef.current?.scrollTop || 0);
  }

  function scrollToPage(nextPage) {
    if (!frameRef.current || !docState.pageTops.length) return;
    const clamped = Math.max(0, Math.min(Number(nextPage || 0), docState.pageCount - 1));
    frameRef.current.scrollTo({
      top: (docState.pageTops[clamped] || 0) * Math.max(Number(zoom || 1), 0.01),
      left: 0,
      behavior: "auto",
    });
    setPageZero(clamped);
  }

  async function renderPage(pageIndex) {
    if (
      !docState.doc ||
      !docState.pageDims[pageIndex] ||
      renderedPagesRef.current.has(pageIndex) ||
      renderingPagesRef.current.has(pageIndex)
    ) {
      return;
    }
    const canvas = canvasRefs.current.get(pageIndex);
    if (!canvas) return;
    renderingPagesRef.current.add(pageIndex);
    try {
      const page = await docState.doc.getPage(pageIndex + 1);
      const viewport = page.getViewport({ scale });
      const ctx = canvas.getContext("2d");
      const outputScale = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      canvas.dataset.rendered = "true";
      ctx.setTransform(outputScale, 0, 0, outputScale, 0, 0);
      const task = page.render({ canvasContext: ctx, viewport });
      renderTasksRef.current.set(pageIndex, task);
      await task.promise;
      renderedPagesRef.current.add(pageIndex);
    } catch (error) {
      if (error?.name !== "RenderingCancelledException") {
        // Keep review usable if one page render fails; the loading chip/error
        // path belongs to the document load itself.
        console.warn("PDF page render failed", error);
      }
    } finally {
      renderingPagesRef.current.delete(pageIndex);
      renderTasksRef.current.delete(pageIndex);
    }
  }

  function ensurePagesAround(pageIndex) {
    if (!docState.doc || !docState.pageCount) return;
    const clamped = Math.max(0, Math.min(Number(pageIndex || 0), docState.pageCount - 1));
    [clamped - 1, clamped, clamped + 1]
      .filter((index) => index >= 0 && index < docState.pageCount)
      .forEach((index) => {
        renderPage(index);
      });
  }

  function centerOnTarget() {
    if (!frameRef.current || !documentSize.width) return;
    const targetRect = targetRectForItem(boxes, item, docState.pageTops);
    const scroll = centerScrollForRect(
      { width: frameRef.current.clientWidth, height: frameRef.current.clientHeight },
      documentSize,
      targetRect,
      zoom,
    );
    if (!scroll) return;
    frameRef.current.scrollTo({ left: scroll.left, top: scroll.top, behavior: "auto" });
    setPageZero(pageFromScroll(scroll.top));
  }

  function toggleBoxRevealAtPoint(point) {
    const hit = boxAtPoint(boxes, point);
    if (hit) onToggleBoxReveal?.(hit.box, hit.index);
  }

  useEffect(() => {
    setPageZero(Number(item?.page_num || 0));
  }, [item?.card_id, item?.box_id, item?.group_id, item?.page_num]);

  useEffect(() => {
    let cancelled = false;
    async function loadPdf() {
      if (!item?.pdf_path) return;
      setDocState((current) => ({ ...current, loading: true, error: "" }));
      try {
        let pdfSource = mediaUrl(item.pdf_path);
        if (localDb) {
          try {
            const fileRecord = await localDb.get("files", item.pdf_path);
            if (fileRecord && fileRecord.blob) {
              if (blobUrlRef.current) {
                URL.revokeObjectURL(blobUrlRef.current);
              }
              const url = URL.createObjectURL(fileRecord.blob);
              pdfSource = url;
              blobUrlRef.current = url;
            }
          } catch (e) {
            console.warn("Failed to retrieve PDF from IndexedDB", e);
          }
        }
        const loadingTask = pdfjsLib.getDocument(pdfSource);
        const doc = await loadingTask.promise;
        const pageDims = [];
        for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
          const page = await doc.getPage(pageNumber);
          const viewport = page.getViewport({ scale });
          pageDims.push({ width: viewport.width, height: viewport.height });
        }
        if (!cancelled) {
          renderedPagesRef.current = new Set();
          renderingPagesRef.current = new Set();
          setDocState({
            doc,
            pageCount: doc.numPages,
            pageDims,
            pageTops: pageTopsFromDims(pageDims),
            loading: false,
            error: "",
          });
        }
      } catch (error) {
        if (!cancelled) {
          setDocState({
            doc: null,
            pageCount: 0,
            pageDims: [],
            pageTops: [],
            loading: false,
            error: error.message || "Could not load PDF.",
          });
        }
      }
    }
    loadPdf();
    return () => {
      cancelled = true;
      cancelRenderTasks();
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [item?.pdf_path, scale]);

  useEffect(() => {
    ensurePagesAround(pageZero);
  }, [docState.doc, docState.pageDims, pageZero, scale]);

  useEffect(() => {
    if (!docState.pageTops.length) return;
    const targetPage = Number(item?.page_num || 0);
    scrollToPage(targetPage);
    ensurePagesAround(targetPage);
  }, [docState.pageTops, item?.card_id, item?.box_id, item?.group_id, item?.page_num]);

  useEffect(() => {
    if (!fitRequest || !documentSize.width || !frameRef.current) return;
    onFitScale?.(
      fitWidthScale(
        { width: frameRef.current.clientWidth, height: frameRef.current.clientHeight },
        documentSize,
        0,
      ),
    );
  }, [documentSize, fitRequest, onFitScale]);

  useEffect(() => {
    onPageStateChange?.({
      pageZero,
      pageCount: docState.pageCount,
      hasPages: docState.pageCount > 0,
    });
  }, [docState.pageCount, onPageStateChange, pageZero]);

  useEffect(() => {
    if (!centerRequest) return;
    centerOnTarget();
    onCenterComplete?.();
  }, [centerRequest, documentSize, zoom]);

  useEffect(() => {
    if (!pageCommand?.id) return;
    if (pageCommand.action === "prev") {
      scrollToPage(currentScrollPage() - 1);
    } else if (pageCommand.action === "next") {
      scrollToPage(currentScrollPage() + 1);
    }
  }, [pageCommand?.id]);

  function handleScroll(event) {
    setPageZero(pageFromScroll(event.currentTarget.scrollTop));
    updateRevealPosition();
  }

  return (
    <div
      className={`review-image-frame review-document-frame ${revealed ? "revealed" : ""}`}
      onScroll={handleScroll}
      ref={frameRef}
    >
      <div className="review-pdf-nav">
        <button disabled={pageZero <= 0} onClick={() => scrollToPage(currentScrollPage() - 1)} type="button">
          Prev Page
        </button>
        <span>
          Page {Math.min(pageZero + 1, docState.pageCount || 1)} / {docState.pageCount || 1}
        </span>
        <button
          disabled={!docState.pageCount || pageZero >= docState.pageCount - 1}
          onClick={() => scrollToPage(currentScrollPage() + 1)}
          type="button"
        >
          Next Page
        </button>
      </div>
      <div
        className="review-document-scale-box"
        style={{
          width: documentSize.width ? `${documentSize.width * zoom}px` : undefined,
          height: documentSize.height ? `${documentSize.height * zoom}px` : undefined,
        }}
      >
        <div
          className="review-image-zoom-layer review-document-layer pdf-layer"
          style={{
            "--review-zoom": zoom,
            width: documentSize.width ? `${documentSize.width}px` : undefined,
            height: documentSize.height ? `${documentSize.height}px` : undefined,
          }}
        >
          {docState.error ? (
            <div className="review-document-empty">{docState.error}</div>
          ) : (
            <div className="pdf-page-stack">
              {docState.pageDims.map((dim, index) => {
                const pageMasks = boxes.filter(box => {
                  const p = box.page_num !== undefined && box.page_num !== null
                    ? box.page_num
                    : inferBoxPage(box, docState.pageTops, docState.pageDims);
                  return p === index;
                });
                return (
                  <div
                    className="pdf-page-shell"
                    key={index}
                    style={{
                      height: `${dim.height}px`,
                      top: `${docState.pageTops[index] || 0}px`,
                      width: `${dim.width}px`,
                      position: 'relative',
                    }}
                  >
                    <canvas
                      height="0"
                      ref={(node) => {
                        if (node) {
                          canvasRefs.current.set(index, node);
                        } else {
                          canvasRefs.current.delete(index);
                        }
                      }}
                      width="0"
                    />
                    {pageMasks.map((box, bIdx) => {
                      const hasPageNum = box.page_num !== undefined && box.page_num !== null;
                      const pageTop = hasPageNum ? 0 : (docState.pageTops[index] || 0);
                      return (
                        <ReviewMask
                          box={box}
                          index={box.box_index ?? bIdx}
                          item={item}
                          key={`${box.box_id || bIdx}`}
                          onToggleReveal={onToggleBoxReveal}
                          pageTop={pageTop}
                          revealed={revealed}
                          revealedBoxes={revealedBoxes}
                          reviewStyle={reviewStyle}
                          surfaceSize={dim}
                        />
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}
          {documentSize.width && documentSize.height ? (
            <InkLayer
              active={penActive}
              color={penColor}
              onChange={onInkChange}
              onPointAction={toggleBoxRevealAtPoint}
              strokes={inkStrokes}
              surfaceSize={documentSize}
              width={penWidth}
            />
          ) : null}
        </div>
      </div>
      {docState.loading ? <div className="review-loading-chip">Loading PDF...</div> : null}
      <RevealOverlay
        item={item}
        onReveal={onReveal}
        overlayRef={overlayRef}
        position={revealPosition}
        ratingOverlay={ratingOverlay}
        revealed={revealed}
      />
    </div>
  );
}

export function ReviewDocumentSurface(props) {
  if (props.item?.pdf_path) {
    return <PdfReviewSurface {...props} />;
  }
  return <ImageReviewSurface {...props} />;
}
