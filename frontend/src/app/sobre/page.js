"use client";

import React, { useEffect } from "react";
import { useApp } from "@/context/AppContext";
import Cabecalho from "@/components/Cabecalho";

export default function SobrePage() {
  const { t, setActiveConversationId, setActiveConversationTitle } = useApp();

  useEffect(() => {
    setActiveConversationId(null);
    setActiveConversationTitle(t.aboutTitle);
  }, [t.aboutTitle, setActiveConversationId, setActiveConversationTitle]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-bg">
      <Cabecalho title={t.aboutTitle} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[720px] px-4 py-8 md:px-8 md:py-12">
          <h1 className="mb-6 font-serif text-[28px] font-medium text-text">
            {t.aboutTitle}
          </h1>
          <div className="agent-prose space-y-4">
            <p>{t.aboutParagraph1}</p>
            <p>{t.aboutParagraph2}</p>
            <p className="pt-2 text-text-secondary">{t.aboutHackathon}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
