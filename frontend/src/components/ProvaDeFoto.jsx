"use client";

import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useApp } from "@/context/AppContext";
import { obterFoto } from "@/api";

function extractBoxes(anexo) {
  if (!anexo || typeof anexo !== "object") return [];
  const rawList =
    anexo.caixas ||
    anexo.boxes ||
    anexo.bboxes ||
    anexo.deteccoes ||
    anexo.detections ||
    anexo.contornos ||
    [];
  if (!Array.isArray(rawList)) return [];

  return rawList
    .map((item) => {
      if (Array.isArray(item) && item.length >= 4) {
        return {
          vals: item.slice(0, 4).map(Number),
          format: anexo.formato_caixas || anexo.box_format || null,
        };
      }
      if (item && typeof item === "object") {
        if (Array.isArray(item.caixa || item.box || item.bbox)) {
          const arr = item.caixa || item.box || item.bbox;
          return {
            vals: arr.slice(0, 4).map(Number),
            format: item.formato || anexo.formato_caixas || null,
          };
        }
        if (
          item.x !== undefined &&
          item.y !== undefined &&
          (item.largura !== undefined || item.w !== undefined || item.width !== undefined)
        ) {
          return {
            vals: [
              Number(item.x),
              Number(item.y),
              Number(item.largura ?? item.w ?? item.width),
              Number(item.altura ?? item.h ?? item.height),
            ],
            format: "xywh",
          };
        }
        if (
          item.x1 !== undefined &&
          item.y1 !== undefined &&
          item.x2 !== undefined &&
          item.y2 !== undefined
        ) {
          return {
            vals: [
              Number(item.x1),
              Number(item.y1),
              Number(item.x2),
              Number(item.y2),
            ],
            format: "xyxy",
          };
        }
      }
      return null;
    })
    .filter((b) => b && b.vals.every((n) => !isNaN(n)));
}

function drawBoxesOnCanvas(canvas, img, boxes) {
  if (!canvas || !img) return;
  const natW = img.naturalWidth || img.width || 1;
  const natH = img.naturalHeight || img.height || 1;
  canvas.width = natW;
  canvas.height = natH;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  ctx.clearRect(0, 0, natW, natH);
  ctx.drawImage(img, 0, 0, natW, natH);

  if (!boxes || boxes.length === 0) return;

  const rootStyles =
    typeof window !== "undefined"
      ? getComputedStyle(document.documentElement)
      : null;
  const accentColor =
    rootStyles?.getPropertyValue("--color-accent")?.trim() || "#C2603C";

  // Scale 2px relative to display size so line stays a crisp 2px on screen
  const displayW = canvas.clientWidth || 320;
  const scaleFactor = natW / Math.max(1, displayW);
  ctx.strokeStyle = accentColor;
  ctx.lineWidth = Math.max(2, 2 * scaleFactor);

  boxes.forEach(({ vals, format }) => {
    let [a, b, c, d] = vals;
    const isNormalized =
      a >= 0 && a <= 1 && b >= 0 && b <= 1 && c >= 0 && c <= 1 && d >= 0 && d <= 1;

    if (isNormalized) {
      a *= natW;
      b *= natH;
      c *= natW;
      d *= natH;
    }

    let x, y, w, h;
    if (format === "xywh") {
      x = a;
      y = b;
      w = c;
      h = d;
    } else if (format === "xyxy") {
      x = a;
      y = b;
      w = c - a;
      h = d - b;
    } else {
      // Auto-detect: if c > a and d > b and (a + c > natW * 1.02 or b + d > natH * 1.02), it's [x1, y1, x2, y2].
      // Also if c > a and d > b, check whether [x1,y1,x2,y2] or [x,y,w,h] is more plausible.
      if (a + c > natW * 1.01 || b + d > natH * 1.01) {
        x = a;
        y = b;
        w = c - a;
        h = d - b;
      } else if (c > a && d > b && (c - a) < natW * 0.9 && (d - b) < natH * 0.9 && (a > c * 0.25 || b > d * 0.25)) {
        // Commonly [x1, y1, x2, y2] in object detection APIs
        x = a;
        y = b;
        w = c - a;
        h = d - b;
      } else {
        x = a;
        y = b;
        w = c;
        h = d;
      }
    }

    if (w > 0 && h > 0) {
      ctx.strokeRect(x, y, w, h);
    }
  });
}

export default function ProvaDeFoto({ anexoJson }) {
  const { t } = useApp();
  const [modalOpen, setModalOpen] = useState(false);
  const [loadedImg, setLoadedImg] = useState(null);
  const [loadError, setLoadError] = useState(false);

  const inlineCanvasRef = useRef(null);
  const modalCanvasRef = useRef(null);

  const anexo = anexoJson && typeof anexoJson === "object" ? anexoJson : null;

  const fotoId = anexo
    ? anexo.foto_id ?? anexo.id ?? anexo.url ?? anexo.caminho ?? null
    : null;

  const boxes = useMemo(() => extractBoxes(anexo), [anexo]);

  // Load the photo with fetch (Authorization: Bearer) -> local blob URL -> Image.
  // The blob URL is revoked when the component unmounts or the photo changes.
  useEffect(() => {
    setLoadedImg(null);
    setLoadError(false);
    if (!fotoId) return undefined;

    let cancelled = false;
    let objectUrl = null;

    (async () => {
      try {
        const blob = await obterFoto(fotoId);
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        const img = new Image();
        img.onload = () => {
          if (!cancelled) setLoadedImg(img);
        };
        img.onerror = () => {
          if (!cancelled) setLoadError(true);
        };
        img.src = objectUrl;
      } catch {
        if (!cancelled) setLoadError(true);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [fotoId]);

  const renderCanvases = useCallback(
    (imgEl) => {
      if (!imgEl) return;
      if (inlineCanvasRef.current) {
        drawBoxesOnCanvas(inlineCanvasRef.current, imgEl, boxes);
      }
      if (modalCanvasRef.current) {
        drawBoxesOnCanvas(modalCanvasRef.current, imgEl, boxes);
      }
    },
    [boxes]
  );

  useEffect(() => {
    if (loadedImg) {
      renderCanvases(loadedImg);
    }
  }, [loadedImg, modalOpen, renderCanvases]);

  useEffect(() => {
    if (!modalOpen) return undefined;
    const handleKey = (e) => {
      if (e.key === "Escape") {
        setModalOpen(false);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [modalOpen]);

  if (!anexo || !fotoId) return null;

  const count =
    anexo.contagem ??
    anexo.detetados ??
    anexo.total_detetados ??
    anexo.total ??
    (boxes.length > 0 ? boxes.length : null);

  const itemLabel =
    anexo.cultura_plural ||
    anexo.objeto ||
    anexo.cultura ||
    anexo.classe ||
    "itens";

  const rawCoverage =
    anexo.cobertura_pct ?? anexo.cobertura ?? anexo.cobertura_imagem ?? null;

  const coveragePct =
    rawCoverage !== null && rawCoverage !== undefined
      ? Math.round(
          Number(rawCoverage) <= 1 && Number(rawCoverage) > 0
            ? Number(rawCoverage) * 100
            : Number(rawCoverage)
        )
      : null;

  const detectedCaption =
    anexo.legenda_detetados ||
    (count !== null ? `${t.photoDetected}: ${count} ${itemLabel}` : null);

  const coverageCaption =
    anexo.legenda_cobertura ||
    (coveragePct !== null && !isNaN(coveragePct)
      ? `${t.photoCoverage}: ${coveragePct}%`
      : null);

  const placeholder = (
    <div
      role="img"
      aria-label={detectedCaption || t.photoAttached}
      className="flex h-40 w-64 items-center justify-center text-xs text-text-secondary"
    >
      {loadError ? t.photoAttached : "…"}
    </div>
  );

  return (
    <div className="my-2.5 max-w-sm font-sans">
      <button
        type="button"
        onClick={() => loadedImg && setModalOpen(true)}
        aria-label={t.photoAttached}
        className="group relative block overflow-hidden rounded-item border border-border bg-surface text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {loadedImg ? (
          <canvas
            ref={inlineCanvasRef}
            aria-label={detectedCaption || t.photoAttached}
            className="block max-h-64 w-auto max-w-full object-contain"
          />
        ) : (
          placeholder
        )}
      </button>

      {/* Two-line caption below photo (never showing diagnostics/diseases/quality) */}
      {(detectedCaption || coverageCaption) && (
        <div className="mt-1.5 text-xs leading-relaxed text-text-secondary">
          {detectedCaption && <div>{detectedCaption}</div>}
          {coverageCaption && <div>{coverageCaption}</div>}
        </div>
      )}

      {/* Lightbox modal on tap */}
      {modalOpen && loadedImg && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t.photoAttached}
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/80 p-4"
          onClick={() => setModalOpen(false)}
        >
          <div
            className="relative flex max-h-[90dvh] max-w-[92vw] flex-col items-end gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="rounded-btn bg-surface px-3.5 py-1.5 text-sm font-medium text-text shadow-menu hover:bg-sidebar-hover transition-ui"
            >
              {t.close}
            </button>
            <div className="overflow-auto rounded-item border border-border bg-surface p-1">
              <canvas
                ref={modalCanvasRef}
                aria-label={detectedCaption || t.photoAttached}
                className="block max-h-[78dvh] w-auto max-w-full object-contain"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
