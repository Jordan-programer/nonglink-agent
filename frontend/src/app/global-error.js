"use client";

import React, { useEffect } from "react";

export default function GlobalError({ error, reset }) {
  useEffect(() => {
    console.error("Erro capturado por app/global-error.js:", error);
  }, [error]);

  return (
    <html lang="pt">
      <body className="flex min-h-screen flex-col items-center justify-center p-4 bg-[#fbf9f4] text-[#1b1917]">
        <div className="max-w-md w-full border border-[#e7e2d7] bg-white p-6 text-center rounded-2xl shadow-lg">
          <h2 className="text-lg font-semibold mb-2">Erro na aplicação</h2>
          <p className="text-xs text-[#78716c] mb-4">
            {error?.message || "Ocorreu um erro ao inicializar a aplicação."}
          </p>
          <button
            type="button"
            onClick={() => reset()}
            className="px-4 py-2 bg-[#2d5a3c] text-white text-xs font-semibold rounded-lg hover:opacity-90"
          >
            Tentar novamente
          </button>
        </div>
      </body>
    </html>
  );
}
