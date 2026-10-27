"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import { listarRegas } from "@/api";

export default function TabelaRegas() {
  const { t, triggerNewChat } = useApp();
  const router = useRouter();

  const [regas, setRegas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await listarRegas();
      setRegas(Array.isArray(data) ? data : []);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  // Sorted by time (ordenado pela hora)
  const sortedRegas = useMemo(() => {
    return [...regas].sort((a, b) => {
      const hA = String(a?.hora ?? a?.horario ?? "");
      const hB = String(b?.hora ?? b?.horario ?? "");
      return hA.localeCompare(hB);
    });
  }, [regas]);

  const handleGoToChat = () => {
    triggerNewChat();
    router.push("/");
  };

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="font-serif text-[28px] font-medium text-text">
          {t.wateringTitle}
        </h1>
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
      ) : sortedRegas.length === 0 ? (
        <div className="py-10 text-left">
          <p className="mb-4 text-base text-text-secondary">
            {t.wateringEmpty}
          </p>
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
            <thead className="border-b border-border text-text-secondary">
              <tr>
                <th className="py-2.5 pr-4 text-left font-medium">
                  {t.wateringColPlot}
                </th>
                <th className="px-3 py-2.5 text-right font-medium">
                  {t.wateringColTime}
                </th>
                <th className="pl-3 py-2.5 text-right font-medium">
                  {t.wateringColNumber}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sortedRegas.map((item, idx) => {
                const parcela = item.parcela ?? item.plot ?? item.local ?? "—";
                const hora = item.hora ?? item.horario ?? item.time ?? "—";
                const numero =
                  item.numero ?? item.resultado_id ?? item.id ?? "—";

                return (
                  <tr
                    key={item.id || item.numero || idx}
                    className="hover:bg-sidebar-hover/50 transition-ui"
                  >
                    <td className="py-3 pr-4 font-medium text-text">
                      {parcela}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-text">
                      {hora}
                    </td>
                    <td className="pl-3 py-3 text-right tabular-nums text-text-secondary">
                      {numero}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
