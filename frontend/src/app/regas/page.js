"use client";

import React, { useEffect } from "react";
import { useApp } from "@/context/AppContext";
import Cabecalho from "@/components/Cabecalho";
import TabelaRegas from "@/components/TabelaRegas";

export default function RegasPage() {
  const { t, setActiveConversationId, setActiveConversationTitle } = useApp();

  useEffect(() => {
    setActiveConversationId(null);
    setActiveConversationTitle(t.wateringTitle);
  }, [t.wateringTitle, setActiveConversationId, setActiveConversationTitle]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-bg">
      <Cabecalho title={t.wateringTitle} />
      <div className="flex-1 overflow-y-auto">
        <TabelaRegas />
      </div>
    </div>
  );
}
