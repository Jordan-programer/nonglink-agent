"use client";

import React, { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import { renomearConversa, apagarConversa } from "@/api";

export default function Cabecalho({ title }) {
  const {
    t,
    setMobileDrawerOpen,
    activeConversationId,
    activeConversationTitle,
    setActiveConversationTitle,
    carregarConversas,
    triggerNewChat,
  } = useApp();

  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [busy, setBusy] = useState(false);

  const menuContainerRef = useRef(null);
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const renameInputRef = useRef(null);

  const displayTitle =
    title || activeConversationTitle || t.newChatTitle;
  const hasConversationActions = Boolean(activeConversationId);

  useEffect(() => {
    setRenameValue(activeConversationTitle || "");
  }, [activeConversationTitle]);

  useEffect(() => {
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [isRenaming]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleOutside(e) {
      if (
        menuContainerRef.current &&
        !menuContainerRef.current.contains(e.target)
      ) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [menuOpen]);

  useEffect(() => {
    if (menuOpen && menuRef.current) {
      const first = menuRef.current.querySelector('[role="menuitem"]');
      first?.focus();
    }
  }, [menuOpen]);

  const handleKeyDown = (e) => {
    if (!menuOpen) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setMenuOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = menuRef.current?.querySelectorAll('[role="menuitem"]');
      if (!items || items.length === 0) return;
      const arr = Array.from(items);
      const idx = arr.indexOf(document.activeElement);
      const next =
        e.key === "ArrowDown"
          ? (idx + 1) % arr.length
          : (idx - 1 + arr.length) % arr.length;
      arr[next]?.focus();
    }
  };

  const handleRenameSubmit = async () => {
    const trimmed = renameValue.trim();
    if (!trimmed || !activeConversationId || trimmed === activeConversationTitle) {
      setIsRenaming(false);
      return;
    }
    setBusy(true);
    try {
      await renomearConversa(activeConversationId, trimmed);
      setActiveConversationTitle(trimmed);
      await carregarConversas();
    } catch {
      // keep previous title on error
    } finally {
      setBusy(false);
      setIsRenaming(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!activeConversationId) return;
    setBusy(true);
    try {
      await apagarConversa(activeConversationId);
      await carregarConversas();
      setIsConfirmingDelete(false);
      triggerNewChat();
      router.push("/");
    } catch {
      setIsConfirmingDelete(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="flex h-[56px] shrink-0 items-center justify-between border-b border-border bg-bg px-3 md:px-5">
      {/* Left: mobile menu button (spacer on desktop) */}
      <div className="flex w-28 items-center">
        <button
          type="button"
          aria-label={t.openSidebar}
          onClick={() => setMobileDrawerOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-item text-text-secondary hover:bg-sidebar-hover hover:text-text md:hidden transition-ui"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>

      {/* Center: Conversation title with arrow & dropdown */}
      <div
        ref={menuContainerRef}
        onKeyDown={handleKeyDown}
        className="relative flex min-w-0 flex-1 items-center justify-center px-2"
      >
        {isRenaming ? (
          <input
            ref={renameInputRef}
            type="text"
            value={renameValue}
            disabled={busy}
            aria-label={t.rename}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleRenameSubmit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setIsRenaming(false);
              }
            }}
            onBlur={handleRenameSubmit}
            className="w-full max-w-xs rounded-item border border-accent bg-surface px-2.5 py-1 text-center text-sm font-medium text-text focus:outline-none"
          />
        ) : isConfirmingDelete ? (
          <div className="flex items-center gap-2 rounded-item border border-border bg-surface px-3 py-1 text-xs shadow-soft">
            <span className="font-medium text-text">
              {t.deleteConfirmQuestion}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={handleDeleteConfirm}
              className="rounded-btn bg-error px-2 py-0.5 font-medium text-white hover:opacity-90 transition-ui"
            >
              {t.delete}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setIsConfirmingDelete(false)}
              className="rounded-btn border border-border px-2 py-0.5 font-medium text-text hover:bg-sidebar-hover transition-ui"
            >
              {t.cancel}
            </button>
          </div>
        ) : hasConversationActions ? (
          <button
            ref={triggerRef}
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((prev) => !prev)}
            className="flex max-w-xs items-center gap-1.5 rounded-item px-2.5 py-1.5 text-sm font-medium text-text hover:bg-sidebar-hover transition-ui"
          >
            <span className="truncate">{displayTitle}</span>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="shrink-0 text-text-secondary"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        ) : (
          <div className="truncate px-2.5 py-1.5 text-sm font-medium text-text">
            {displayTitle}
          </div>
        )}

        {menuOpen && hasConversationActions && (
          <div
            ref={menuRef}
            role="menu"
            aria-label={t.options}
            className="absolute top-full mt-1 w-40 rounded-item border border-border bg-surface p-1 shadow-menu z-50"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setRenameValue(activeConversationTitle || displayTitle);
                setIsRenaming(true);
              }}
              className="flex w-full items-center rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
            >
              {t.rename}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setIsConfirmingDelete(true);
              }}
              className="flex w-full items-center rounded-item px-2.5 py-1.5 text-left text-sm text-error hover:bg-sidebar-hover transition-ui"
            >
              {t.delete}
            </button>
          </div>
        )}
      </div>

      {/* Right: "Dados de demonstração" badge */}
      <div className="flex items-center justify-end gap-2">
        <span className="rounded-item border border-border bg-sidebar px-2.5 py-1 text-xs font-medium text-text-secondary whitespace-nowrap">
          {t.demoData}
        </span>
      </div>
    </header>
  );
}
