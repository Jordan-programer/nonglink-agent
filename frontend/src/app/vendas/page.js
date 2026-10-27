"use client";

import React, { useEffect } from "react";
import { useApp } from "@/context/AppContext";
import Cabecalho from "@/components/Cabecalho";
import TabelaVendas from "@/components/TabelaVendas";

export default function VendasPage() {
  const { t, setActiveConversationId, setActiveConversationTitle } = useApp();

  useEffect(() => {
    setActiveConversationId(null);
    setActiveConversationTitle(t.salesTitle);
  }, [t.salesTitle, setActiveConversationId, setActiveConversationTitle]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-bg">
      <Cabecalho title={t.salesTitle} />
      <div className="flex-1 overflow-y-auto">
        <TabelaVendas />
      </div>
    </div>
  );
}
