"use client";

import React, { useEffect } from "react";

export default function Error({ error, reset }) {
  useEffect(() => {
    // Regista o erro para diagnóstico
    console.error("Erro capturado por app/error.js:", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-1 flex-col items-center justify-center p-6 text-center">
      <div className="max-w-md w-full rounded-card border border-border bg-surface p-6 shadow-menu text-text">
        <h2 className="text-lg font-semibold mb-2">Ocorreu um erro</h2>
        <p className="text-xs text-text-secondary mb-4">
          {error?.message || "Ocorreu um problema ao carregar a página."}
        </p>
        <button
          type="button"
          onClick={() => reset()}
          className="rounded-item bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent-hover transition-ui"
        >
          Tentar novamente
        </button>
      </div>
    </div>
  );
}
