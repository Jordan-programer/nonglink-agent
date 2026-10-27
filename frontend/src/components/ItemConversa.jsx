"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import { renomearConversa, apagarConversa } from "@/api";

export default function ItemConversa({ conversa, isActive, onNavigate }) {
  const {
    t,
    carregarConversas,
    activeConversationId,
    setActiveConversationTitle,
    triggerNewChat,
  } = useApp();
  const router = useRouter();

  const [menuOpen, setMenuOpen] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [titleInput, setTitleInput] = useState(conversa.titulo || "");
  const [busy, setBusy] = useState(false);

  const itemRef = useRef(null);
  const inputRef = useRef(null);
  const menuRef = useRef(null);
  const menuButtonRef = useRef(null);

  useEffect(() => {
    setTitleInput(conversa.titulo || "");
  }, [conversa.titulo]);

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleOutside(e) {
      if (itemRef.current && !itemRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [menuOpen]);

  useEffect(() => {
    if (menuOpen && menuRef.current) {
      const firstBtn = menuRef.current.querySelector('[role="menuitem"]');
      firstBtn?.focus();
    }
  }, [menuOpen]);

  const handleMenuKeyDown = (e) => {
    if (!menuOpen) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setMenuOpen(false);
      menuButtonRef.current?.focus();
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

  const handleSaveRename = async () => {
    const trimmed = titleInput.trim();
    if (!trimmed || trimmed === conversa.titulo) {
      setIsRenaming(false);
      setTitleInput(conversa.titulo || "");
      return;
    }
    setBusy(true);
    try {
      await renomearConversa(conversa.id, trimmed);
      if (activeConversationId === conversa.id) {
        setActiveConversationTitle(trimmed);
      }
      await carregarConversas();
    } catch {
      // revert on error
      setTitleInput(conversa.titulo || "");
    } finally {
      setBusy(false);
      setIsRenaming(false);
    }
  };

  const handleConfirmDelete = async () => {
    setBusy(true);
    try {
      await apagarConversa(conversa.id);
      await carregarConversas();
      if (isActive || activeConversationId === conversa.id) {
        triggerNewChat();
        router.push("/");
      }
    } catch {
      setIsConfirmingDelete(false);
    } finally {
      setBusy(false);
    }
  };

  if (isConfirmingDelete) {
    return (
      <div
        ref={itemRef}
        className="rounded-item bg-sidebar-active px-2.5 py-2 text-sm transition-ui"
      >
        <p className="mb-2 font-medium text-text">{t.deleteConfirmQuestion}</p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={handleConfirmDelete}
            className="rounded-btn bg-error px-2.5 py-1 text-xs font-medium text-white hover:opacity-90 transition-ui"
          >
            {t.delete}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setIsConfirmingDelete(false)}
            className="rounded-btn border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text hover:bg-sidebar-hover transition-ui"
          >
            {t.cancel}
          </button>
        </div>
      </div>
    );
  }

  if (isRenaming) {
    return (
      <div ref={itemRef} className="rounded-item bg-sidebar-active px-2 py-1">
        <input
          ref={inputRef}
          type="text"
          value={titleInput}
          disabled={busy}
          aria-label={t.rename}
          onChange={(e) => setTitleInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSaveRename();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setIsRenaming(false);
              setTitleInput(conversa.titulo || "");
            }
          }}
          onBlur={handleSaveRename}
          className="w-full rounded-item border border-accent bg-surface px-2 py-1 text-sm text-text focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div
      ref={itemRef}
      onKeyDown={handleMenuKeyDown}
      className={`group relative flex items-center justify-between rounded-item transition-ui ${
        isActive ? "bg-sidebar-active font-medium" : "hover:bg-sidebar-hover"
      }`}
    >
      <Link
        href={`/c/${encodeURIComponent(conversa.id)}`}
        onClick={() => onNavigate?.()}
        className="flex-1 truncate py-2 pl-2.5 pr-8 text-sm text-text"
      >
        {conversa.titulo || t.newChatTitle}
      </Link>

      <button
        ref={menuButtonRef}
        type="button"
        aria-label={t.options}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setMenuOpen((prev) => !prev);
        }}
        className={`absolute right-1.5 flex h-7 w-7 items-center justify-center rounded-item text-text-secondary hover:bg-sidebar-active hover:text-text transition-ui ${
          menuOpen
            ? "opacity-100"
            : "opacity-100 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
        }`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          aria-hidden="true"
        >
          <circle cx="3.5" cy="8" r="1.25" />
          <circle cx="8" cy="8" r="1.25" />
          <circle cx="12.5" cy="8" r="1.25" />
        </svg>
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={t.options}
          className="absolute right-0 top-full mt-1 w-36 rounded-item border border-border bg-surface p-1 shadow-menu z-50"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
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
  );
}
