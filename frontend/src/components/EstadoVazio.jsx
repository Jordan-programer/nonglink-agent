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
        <p className="mb-6 text-center font-serif text-[18px] text-text-secondary">
          {t.emptyPrompt}
        </p>

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
