"use client";

import React from "react";
import { useApp } from "@/context/AppContext";

export default function ConfirmacaoMediaDialog() {
  const {
    mediaConsentModalOpen,
    confirmMediaConsent,
    cancelMediaConsent,
    t,
  } = useApp();

  if (!mediaConsentModalOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="media-notice-title"
    >
      <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 text-text shadow-menu">
        <div className="mb-4 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-accent font-bold text-sm">
            ⚠️
          </span>
          <div>
            <h2 id="media-notice-title" className="text-base font-semibold text-text">
              {t.mediaNoticeTitle || "Confirmação de Envio"}
            </h2>
            <p className="text-xs text-text-secondary">
              Apenas na primeira gravação ou foto desta sessão
            </p>
          </div>
        </div>

        {/* Aviso visível em PT, FR e EN */}
        <div className="mb-5 space-y-2 rounded-item border border-accent/25 bg-accent/5 p-3.5 text-xs leading-relaxed text-text">
          <p className="font-medium text-text">
            <strong className="text-accent">PT:</strong> Demonstração do hackathon. Não envie dados pessoais reais. Textos, vozes e fotos são processados por modelos da Meta. Os dados de convidados são apagados após 24 horas.
          </p>
          <p className="text-text-secondary text-[11.5px]">
            <strong>FR:</strong> Démonstration du hackathon. N&apos;envoyez pas de données personnelles réelles. Les textes, voix et photos sont traités par des modèles de Meta. Les données des invités sont supprimées après 24 heures.
          </p>
          <p className="text-text-secondary text-[11.5px]">
            <strong>EN:</strong> Hackathon demo. Do not send real personal data. Texts, voices, and photos are processed by Meta models. Guest data is deleted after 24 hours.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2.5">
          <button
            type="button"
            onClick={cancelMediaConsent}
            className="rounded-item border border-border bg-bg px-4 py-2 text-xs font-semibold text-text hover:bg-sidebar-hover transition-ui"
          >
            {t.cancel || "Cancelar"}
          </button>
          <button
            type="button"
            onClick={confirmMediaConsent}
            className="rounded-item bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent-hover transition-ui"
          >
            {t.mediaNoticeConfirm || "Compreendo e continuar"}
          </button>
        </div>
      </div>
    </div>
  );
}

