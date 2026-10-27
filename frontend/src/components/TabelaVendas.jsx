"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import { listarAnuncios } from "@/api";

function formatNumber(val) {
  if (val === null || val === undefined || val === "") return "—";
  const num = Number(val);
  if (isNaN(num)) return String(val);
  return num.toLocaleString("pt-PT");
}

function formatDate(val) {
  if (!val) return "—";
  const d = new Date(val);
  if (isNaN(d.getTime())) return String(val);
  return d.toLocaleDateString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default function TabelaVendas() {
  const { t, triggerNewChat } = useApp();
  const router = useRouter();

  const [anuncios, setAnuncios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedCrop, setSelectedCrop] = useState("");

  const carregar = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await listarAnuncios();
      setAnuncios(Array.isArray(data) ? data : []);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const crops = useMemo(() => {
    const set = new Set();
    anuncios.forEach((a) => {
      const c = a?.cultura || a?.produto || a?.crop;
      if (c) set.add(String(c));
    });
    return Array.from(set);
  }, [anuncios]);

  const filtered = useMemo(() => {
    if (!selectedCrop) return anuncios;
    return anuncios.filter(
      (a) => String(a?.cultura || a?.produto || a?.crop || "") === selectedCrop
    );
  }, [anuncios, selectedCrop]);

  const handleGoToChat = () => {
    triggerNewChat();
    router.push("/");
  };

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-serif text-[28px] font-medium text-text">
          {t.salesTitle}
        </h1>

        {crops.length > 0 && (
          <div className="flex items-center gap-2">
            <select
              value={selectedCrop}
              onChange={(e) => setSelectedCrop(e.target.value)}
              aria-label={t.salesFilterLabel}
              className="rounded-btn border border-border bg-surface px-3 py-1.5 text-sm text-text focus:border-accent focus:outline-none transition-ui"
            >
              <option value="">{t.salesFilterAll}</option>
              {crops.map((crop) => (
                <option key={crop} value={crop}>
                  {crop}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-item border border-border bg-surface p-4 text-sm text-text"
        >
          <p className="mb-3">{t.connectionError}</p>
          <button
            type="button"
            onClick={carregar}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-ui"
          >
            {t.retry}
          </button>
        </div>
      ) : loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-text-secondary">
          <span className="h-2 w-2 rounded-full bg-accent dot-pulse-1" />
          <span className="h-2 w-2 rounded-full bg-accent dot-pulse-2" />
          <span className="h-2 w-2 rounded-full bg-accent dot-pulse-3" />
          <span>{t.calculating}</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-10 text-left">
          <p className="mb-4 text-base text-text-secondary">{t.salesEmpty}</p>
          <button
            type="button"
            onClick={handleGoToChat}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-ui"
          >
            {t.talkToAgent}
          </button>
        </div>
      ) : (
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="hidden sm:table-header-group border-b border-border text-text-secondary">
              <tr>
                <th className="py-2.5 pr-4 text-left font-medium">
                  {t.salesColCrop}
                </th>
                <th className="px-3 py-2.5 text-right font-medium">
                  {t.salesColQty}
                </th>
                <th className="px-3 py-2.5 text-right font-medium">
                  {t.salesColPrice}
                </th>
                <th className="px-3 py-2.5 text-right font-medium">
                  {t.salesColTotal}
                </th>
                <th className="px-3 py-2.5 text-right font-medium">
                  {t.salesColDate}
                </th>
                <th className="pl-3 py-2.5 text-right font-medium">
                  {t.salesColNumber}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((item, idx) => {
                const cultura = item.cultura ?? item.produto ?? "—";
                const qtd = item.quantidade_kg ?? item.quantidade ?? item.peso;
                const preco =
                  item.preco_kg ?? item.preco_por_kg ?? item.preco ?? item.valor_kg;
                const total =
                  item.total ??
                  item.valor_total ??
                  (qtd && preco && !isNaN(Number(qtd)) && !isNaN(Number(preco))
                    ? Number(qtd) * Number(preco)
                    : null);
                const data =
                  item.criado_em ?? item.data ?? item.created_at ?? null;
                const numero =
                  item.numero ?? item.resultado_id ?? item.id ?? "—";

                return (
                  <React.Fragment key={item.id || item.numero || idx}>
                    {/* Desktop row */}
                    <tr className="hidden sm:table-row hover:bg-sidebar-hover/50 transition-ui">
                      <td className="py-3 pr-4 font-medium text-text">
                        {cultura}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-text">
                        {formatNumber(qtd)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-text">
                        {formatNumber(preco)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums font-semibold text-text">
                        {formatNumber(total)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-text-secondary">
                        {formatDate(data)}
                      </td>
                      <td className="pl-3 py-3 text-right tabular-nums text-text-secondary">
                        {numero}
                      </td>
                    </tr>

                    {/* Mobile row: two lines of text inside the table */}
                    <tr className="sm:hidden">
                      <td colSpan={6} className="py-2.5">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-medium text-text">
                            {cultura} ·{" "}
                            <span className="tabular-nums">
                              {formatNumber(qtd)} kg × {formatNumber(preco)} Kz
                            </span>
                          </span>
                          <span className="tabular-nums font-semibold text-text">
                            {formatNumber(total)} Kz
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-baseline justify-between gap-2 text-xs text-text-secondary">
                          <span className="tabular-nums">{formatDate(data)}</span>
                          <span className="tabular-nums">{numero}</span>
                        </div>
                      </td>
                    </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
