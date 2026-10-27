"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import ItemConversa from "./ItemConversa";
import MenuConta from "./MenuConta";

function groupConversationsByDate(conversas, t) {
  const groups = {
    today: [],
    yesterday: [],
    last7Days: [],
    older: [],
  };

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOf7DaysAgo = new Date(startOfToday);
  startOf7DaysAgo.setDate(startOf7DaysAgo.getDate() - 7);

  conversas.forEach((c) => {
    const d = c.atualizada_em ? new Date(c.atualizada_em) : new Date(0);
    if (isNaN(d.getTime()) || d >= startOfToday) {
      groups.today.push(c);
    } else if (d >= startOfYesterday) {
      groups.yesterday.push(c);
    } else if (d >= startOf7DaysAgo) {
      groups.last7Days.push(c);
    } else {
      groups.older.push(c);
    }
  });

  return [
    { key: "today", label: t.groupToday, items: groups.today },
    { key: "yesterday", label: t.groupYesterday, items: groups.yesterday },
    { key: "last7Days", label: t.groupLast7Days, items: groups.last7Days },
    { key: "older", label: t.groupOlder, items: groups.older },
  ].filter((g) => g.items.length > 0);
}

export default function BarraLateral() {
  const {
    t,
    user,
    openAuthModal,
    sidebarCollapsed,
    setSidebarCollapsed,
    mobileDrawerOpen,
    setMobileDrawerOpen,
    conversas,
    searchQuery,
    setSearchQuery,
    activeConversationId,
    triggerNewChat,
  } = useApp();

  const pathname = usePathname();
  const router = useRouter();

  const grouped = useMemo(
    () => groupConversationsByDate(conversas, t),
    [conversas, t]
  );

  const handleNewChat = () => {
    if (!user) {
      openAuthModal("login");
      return;
    }
    triggerNewChat();
    router.push("/");
  };

  const closeMobile = () => {
    setMobileDrawerOpen(false);
  };

  const isSalesActive = pathname === "/vendas";
  const isWateringActive = pathname === "/regas";

  const renderSidebarContent = (isCollapsedView) => (
    <div className="flex h-full flex-col justify-between bg-sidebar text-text select-none">
      {/* Top & Scrollable Middle */}
      <div className="flex min-h-0 flex-1 flex-col">
        {/* 1. Brand & Toggle Button */}
        <div
          className={`flex h-14 shrink-0 items-center px-3 ${
            isCollapsedView ? "justify-center" : "justify-between"
          }`}
        >
          {!isCollapsedView && (
            <Link
              href="/"
              onClick={handleNewChat}
              className="px-1 font-serif text-[22px] font-medium tracking-tight text-text"
            >
              {t.brand}
            </Link>
          )}

          {/* Desktop collapse/expand or Mobile close */}
          <button
            type="button"
            aria-label={isCollapsedView ? t.openSidebar : t.closeSidebar}
            title={isCollapsedView ? t.openSidebar : t.closeSidebar}
            onClick={() => {
              if (mobileDrawerOpen) {
                setMobileDrawerOpen(false);
              } else {
                setSidebarCollapsed((prev) => !prev);
              }
            }}
            className="flex h-9 w-9 items-center justify-center rounded-item text-text-secondary hover:bg-sidebar-hover hover:text-text transition-ui"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="3" y="3" width="18" height="18" rx="3" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        </div>

        {/* 2. Botão "Novo chat" */}
        <div className="shrink-0 px-2.5 pb-2">
          <button
            type="button"
            onClick={handleNewChat}
            aria-label={t.newChat}
            title={isCollapsedView ? t.newChat : undefined}
            className={`flex w-full items-center rounded-item p-2 text-left hover:bg-sidebar-hover transition-ui ${
              isCollapsedView ? "justify-center" : "gap-2.5"
            }`}
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-white hover:bg-accent-hover transition-ui"
              aria-hidden="true"
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </span>
            {!isCollapsedView && (
              <span className="truncate text-sm font-semibold text-text">
                {t.newChat}
              </span>
            )}
          </button>
        </div>

        {/* 3. Campo "Procurar conversas" */}
        {!isCollapsedView && (
          <div className="shrink-0 px-3 pb-2">
            <div className="relative flex items-center">
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 text-text-secondary"
              >
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t.searchPlaceholder}
                aria-label={t.searchPlaceholder}
                className="w-full rounded-item border border-border bg-surface py-1.5 pl-8 pr-2.5 text-sm text-text placeholder:text-text-secondary focus:border-accent focus:outline-none transition-ui"
              />
            </div>
          </div>
        )}

        {/* 4. Ligações "Vendas" e "Regas" */}
        <nav
          aria-label="Navegação principal"
          className="shrink-0 space-y-0.5 px-2.5 pb-3"
        >
          <Link
            href="/vendas"
            onClick={closeMobile}
            aria-label={t.navSales}
            title={isCollapsedView ? t.navSales : undefined}
            className={`flex items-center rounded-item px-2.5 py-2 text-sm transition-ui ${
              isCollapsedView ? "justify-center" : "gap-2.5"
            } ${
              isSalesActive
                ? "bg-sidebar-active font-medium text-accent"
                : "text-text hover:bg-sidebar-hover"
            }`}
          >
            <svg
              width="17"
              height="17"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="shrink-0"
            >
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
              <line x1="7" y1="7" x2="7.01" y2="7" />
            </svg>
            {!isCollapsedView && <span>{t.navSales}</span>}
          </Link>

          <Link
            href="/regas"
            onClick={closeMobile}
            aria-label={t.navWatering}
            title={isCollapsedView ? t.navWatering : undefined}
            className={`flex items-center rounded-item px-2.5 py-2 text-sm transition-ui ${
              isCollapsedView ? "justify-center" : "gap-2.5"
            } ${
              isWateringActive
                ? "bg-sidebar-active font-medium text-accent"
                : "text-text hover:bg-sidebar-hover"
            }`}
          >
            <svg
              width="17"
              height="17"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="shrink-0"
            >
              <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />
            </svg>
            {!isCollapsedView && <span>{t.navWatering}</span>}
          </Link>
        </nav>

        {/* 5. Etiqueta "Recentes" e lista de conversas agrupada */}
        {!isCollapsedView && (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="shrink-0 px-4 pb-1.5 text-xs text-text-secondary">
              {t.recents}
            </div>

            <div className="flex-1 overflow-y-auto px-2.5 pb-3 space-y-3">
              {!user ? (
                <p className="px-2 py-2 text-xs text-text-secondary">
                  {t.loginToSeeHistory}
                </p>
              ) : conversas.length === 0 ? (
                <p className="px-2 py-2 text-xs text-text-secondary">
                  {t.noConversationsFound}
                </p>
              ) : (
                grouped.map((group) => (
                  <div key={group.key} className="space-y-0.5">
                    <div className="px-2 py-1 text-[11px] font-medium text-text-secondary">
                      {group.label}
                    </div>
                    {group.items.map((conv) => {
                      const isActive =
                        pathname === `/c/${conv.id}` ||
                        activeConversationId === conv.id;
                      return (
                        <ItemConversa
                          key={conv.id}
                          conversa={conv}
                          isActive={isActive}
                          onNavigate={closeMobile}
                        />
                      );
                    })}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* 6. Rodapé: Conta de demonstração */}
      <div className="shrink-0 border-t border-border p-2">
        <MenuConta collapsed={isCollapsedView} onNavigate={closeMobile} />
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        aria-label="Barra lateral"
        className={`hidden md:block shrink-0 border-r border-border h-full transition-ui ${
          sidebarCollapsed ? "w-[56px]" : "w-[288px]"
        }`}
      >
        {renderSidebarContent(sidebarCollapsed)}
      </aside>

      {/* Mobile drawer (< 768px) */}
      {mobileDrawerOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="fixed inset-0 bg-black/50 transition-opacity"
            aria-hidden="true"
            onClick={closeMobile}
          />
          <aside
            aria-label="Barra lateral"
            className="relative z-10 h-full w-[288px] max-w-[85vw] border-r border-border shadow-menu transition-ui"
          >
            {renderSidebarContent(false)}
          </aside>
        </div>
      )}
    </>
  );
}
