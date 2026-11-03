"use client";

import React, { useState, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import { getGreeting } from "@/i18n";
import CaixaTexto from "./CaixaTexto";

export default function EstadoVazio({
  inputValue,
  onInputChange,
  onSend,
  onSendVoice,
  disabled,
  autoFocusTrigger,
}) {
  const { lang, t } = useApp();
  const [greeting, setGreeting] = useState(() => getGreeting(lang));

  useEffect(() => {
    setGreeting(getGreeting(lang, new Date()));
  }, [lang]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-8">
      <div className="w-full max-w-[720px] flex flex-col items-center">
        {/* Sprout icon + Greeting in Newsreader 36px */}
        <div className="mb-2 flex items-center justify-center gap-3 text-center">
          <svg
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="shrink-0 text-accent"
          >
            <path d="M12 22v-9" />
            <path d="M12 13C12 8.5 8.5 5 3.5 5c0 5 3.5 8 8.5 8Z" />
            <path d="M12 15c0-4 3-7 7.5-7 0 4-3 7-7.5 7Z" />
          </svg>
          <h1 className="font-serif text-[32px] sm:text-[36px] font-medium leading-tight text-text">
            {greeting}
          </h1>
        </div>

        {/* Subtitle */}
        <p className="mb-4 text-center font-serif text-[18px] text-text-secondary">
          {t.emptyPrompt}
        </p>

        {/* Aviso de demonstração do hackathon em PT, FR e EN */}
        <div className="mb-5 w-full rounded-item border border-accent/25 bg-accent/5 p-3.5 text-xs leading-relaxed text-text space-y-1.5 shadow-soft">
          <div className="flex items-center gap-1.5 font-semibold text-accent text-[11px] uppercase tracking-wide">
            <span>⚠️ Demonstração do Hackathon</span>
          </div>
          <p className="font-medium text-text">
            <strong className="text-accent">PT:</strong> Demonstração do hackathon. Não envie dados pessoais reais. Textos, vozes e fotos são processados por modelos da Meta. Os dados de convidados são apagados após 24 horas.
          </p>
          <p className="text-text-secondary text-[11px]">
            <strong>FR:</strong> Démonstration du hackathon. N&apos;envoyez pas de données personnelles réelles. Les textes, voix et photos sont traités par des modèles de Meta. Les données des invités sont supprimées après 24 heures.
          </p>
          <p className="text-text-secondary text-[11px]">
            <strong>EN:</strong> Hackathon demo. Do not send real personal data. Texts, voices, and photos are processed by Meta models. Guest data is deleted after 24 hours.
          </p>
        </div>

        {/* Textbox */}
        <CaixaTexto
          value={inputValue}
          onChange={onInputChange}
          onSend={onSend}
          onSendVoice={onSendVoice}
          disabled={disabled}
          autoFocusTrigger={autoFocusTrigger}
        />

        {/* Three suggestion pills */}
        <div className="mt-5 flex w-full flex-col sm:flex-row flex-wrap items-stretch sm:items-center justify-center gap-2">
          {t.pills.map((pillText, idx) => (
            <button
              key={idx}
              type="button"
              disabled={disabled}
              onClick={() => {
                onInputChange?.(pillText);
                onSend?.({ text: pillText, photoFile: null });
              }}
              className="rounded-full border border-border bg-surface px-4 py-2 text-center text-sm text-text hover:bg-sidebar-hover disabled:opacity-50 transition-ui"
            >
              {pillText}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
