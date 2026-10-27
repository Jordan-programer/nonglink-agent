"use client";

import React, { useState } from "react";
import { useApp } from "@/context/AppContext";

function formatNumberAO(val) {
  if (val === null || val === undefined || val === "") return "";
  const num = Number(val);
  if (isNaN(num)) return String(val);
  return num.toLocaleString("pt-PT");
}

function detectActionType(accao) {
  if (!accao || typeof accao !== "object") return "venda";
  const tipo = String(
    accao.tipo || accao.accao || accao.acao || accao.type || ""
  ).toLowerCase();
  if (
    tipo.includes("rega") ||
    tipo.includes("water") ||
    tipo.includes("arros") ||
    accao.parcela !== undefined ||
    accao.hora !== undefined
  ) {
    return "rega";
  }
  return "venda";
}

function buildRows(accao, tipo, t) {
  if (!accao || typeof accao !== "object") {
    return [];
  }

  const rows = [];

  if (tipo === "rega") {
    const parcela = accao.parcela ?? accao.plot ?? accao.local;
    const hora = accao.hora ?? accao.horario ?? accao.time;

    if (parcela !== undefined && parcela !== null && parcela !== "") {
      rows.push({ label: t.fieldPlot, value: String(parcela), highlight: false });
    }
    if (hora !== undefined && hora !== null && hora !== "") {
      rows.push({ label: t.fieldTime, value: String(hora), highlight: true });
    }
  } else {
    const cultura = accao.cultura ?? accao.produto ?? accao.crop;
    const quantidade =
      accao.quantidade_kg ?? accao.quantidade ?? accao.peso ?? accao.qty;
    const preco =
      accao.preco_kg ??
      accao.preco_por_kg ??
      accao.preco ??
      accao.valor_kg ??
      accao.price;
    const total =
      accao.total ??
      accao.valor_total ??
      (quantidade && preco && !isNaN(Number(quantidade)) && !isNaN(Number(preco))
        ? Number(quantidade) * Number(preco)
        : undefined);

    if (cultura !== undefined && cultura !== null && cultura !== "") {
      rows.push({ label: t.fieldCrop, value: String(cultura), highlight: false });
    }
    if (quantidade !== undefined && quantidade !== null && quantidade !== "") {
      const qStr = String(quantidade).toLowerCase().includes("kg")
        ? String(quantidade)
        : `${formatNumberAO(quantidade)} kg`;
      rows.push({ label: t.fieldQuantity, value: qStr, highlight: false });
    }
    if (preco !== undefined && preco !== null && preco !== "") {
      const pStr = String(preco).toLowerCase().includes("kz")
        ? String(preco)
        : `${formatNumberAO(preco)} Kz`;
      rows.push({ label: t.fieldPricePerKg, value: pStr, highlight: false });
    }
    if (total !== undefined && total !== null && total !== "") {
      const tStr = String(total).toLowerCase().includes("kz")
        ? String(total)
        : `${formatNumberAO(total)} Kz`;
      rows.push({ label: t.fieldTotal, value: tStr, highlight: true });
    }
  }

  // Fallback for unrecognized fields or `descricao`
  if (rows.length === 0) {
    if (accao.descricao) {
      const lines = String(accao.descricao)
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean);
      lines.forEach((line, idx) => {
        if (line.includes(":")) {
          const [k, ...rest] = line.split(":");
          rows.push({
            label: k.trim(),
            value: rest.join(":").trim(),
            highlight: idx === lines.length - 1,
          });
        } else {
          rows.push({
            label: idx === 0 ? t.fieldDescription : `•`,
            value: line,
            highlight: false,
          });
        }
      });
    } else {
      const ignoredKeys = new Set([
        "tipo",
        "accao",
        "acao",
        "type",
        "estado",
        "estado_accao",
        "resultado_id",
        "numero",
        "id",
      ]);
      Object.entries(accao).forEach(([k, v]) => {
        if (!ignoredKeys.has(k) && v !== null && v !== undefined && typeof v !== "object") {
          rows.push({
            label: k,
            value: String(v),
            highlight: false,
          });
        }
      });
    }
  }

  return rows;
}

export default function Talao({
  accaoJson,
  estadoAccao = "pendente",
  resultadoId = null,
  onConfirm,
}) {
  const { t } = useApp();
  const [submitting, setSubmitting] = useState(false);
  const [justStamped, setJustStamped] = useState(false);
  const [localEstado, setLocalEstado] = useState(null);
  const [localResultadoId, setLocalResultadoId] = useState(null);

  const effectiveEstado = localEstado || estadoAccao || "pendente";
  const effectiveNumero =
    localResultadoId ||
    resultadoId ||
    accaoJson?.resultado_id ||
    accaoJson?.numero ||
    null;

  const tipo = detectActionType(accaoJson);
  const isRega = tipo === "rega";
  const rows = buildRows(accaoJson, tipo, t);

  const isPending = effectiveEstado === "pendente";
  const isConfirmed =
    effectiveEstado === "confirmada" ||
    effectiveEstado === "confirmado" ||
    effectiveEstado === "publicado" ||
    effectiveEstado === "agendado";
  const isCancelled =
    effectiveEstado === "cancelada" || effectiveEstado === "cancelado";

  const handleAction = async (confirmar) => {
    if (submitting || !isPending) return;
    setSubmitting(true);
    try {
      const res = await onConfirm?.(confirmar);
      setJustStamped(true);
      setLocalEstado(confirmar ? "confirmada" : "cancelada");
      const returnedId =
        res?.resultado_id ||
        res?.numero ||
        res?.id ||
        res?.accao_json?.resultado_id ||
        null;
      if (returnedId) {
        setLocalResultadoId(returnedId);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const headerTitle = isRega ? t.talaoWateringHeader : t.talaoSaleHeader;
  const confirmButtonLabel = isRega ? t.btnScheduleWatering : t.btnPublishSale;
  const cancelButtonLabel = isRega ? t.btnCancelWatering : t.btnCancelSale;

  const stampWord = isCancelled
    ? t.stampCancelled
    : isRega
    ? t.stampScheduled
    : t.stampPublished;

  const finalStatusLabel = isCancelled
    ? isRega
      ? t.statusCancelledWatering
      : t.statusCancelledSale
    : isRega
    ? t.statusScheduled
    : t.statusPublished;

  return (
    <div className="my-3 w-full max-w-sm font-sans">
      {/* Talão card */}
      <div className="talao-perforated relative rounded-talao border border-border bg-surface p-4 text-text">
        {/* Header in Stencil font */}
        <div className="mb-3 border-b border-border pb-2 flex items-baseline justify-between gap-2">
          <h3 className="font-stencil text-xl font-bold uppercase tracking-wider text-text">
            {headerTitle}
          </h3>
          {effectiveNumero && (
            <span className="tabular-nums text-xs font-semibold text-text-secondary">
              {String(effectiveNumero).startsWith("N.")
                ? effectiveNumero
                : `${t.fieldNumber} ${effectiveNumero}`}
            </span>
          )}
        </div>

        {/* Rows with leader dots and tabular numerals */}
        <div className="space-y-2 text-sm">
          {rows.map((row, idx) => (
            <div key={idx} className="flex items-baseline justify-between">
              <span className="text-text-secondary">{row.label}</span>
              <span className="talao-dots" aria-hidden="true" />
              <span
                className={`tabular-nums ${
                  row.highlight
                    ? "text-base font-semibold text-text"
                    : "font-medium text-text"
                }`}
              >
                {row.value}
              </span>
            </div>
          ))}
        </div>

        {/* Footer inside Talão */}
        <div className="mt-4 pt-2 border-t border-border flex items-center justify-between text-[11px] text-text-secondary">
          <span>{t.demoData}</span>
          {(isConfirmed || isCancelled) && (
            <span className="font-medium">{finalStatusLabel}</span>
          )}
        </div>

        {/* Stamp overlay when confirmed or cancelled */}
        {(isConfirmed || isCancelled) && (
          <div
            aria-label={stampWord}
            className={`pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 select-none rounded-[4px] border-4 border-double px-3 py-1 font-stencil text-2xl font-extrabold uppercase tracking-widest ${
              justStamped ? "stamp-animate" : "stamp-static"
            } ${
              isCancelled
                ? "border-error text-error bg-surface/85"
                : "border-success text-success bg-surface/85"
            }`}
          >
            {stampWord}
          </div>
        )}
      </div>

      {/* Action buttons only when pending */}
      {isPending && (
        <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            disabled={submitting}
            onClick={() => handleAction(true)}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 transition-ui"
          >
            {confirmButtonLabel}
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => handleAction(false)}
            className="rounded-btn border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-sidebar-hover disabled:opacity-50 transition-ui"
          >
            {cancelButtonLabel}
          </button>
        </div>
      )}
    </div>
  );
}
