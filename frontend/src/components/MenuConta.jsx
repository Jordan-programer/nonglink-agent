"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { useApp } from "@/context/AppContext";

export default function MenuConta({ collapsed = false, onNavigate }) {
  const {
    lang,
    setLang,
    t,
    user,
    logout,
    setDefinicoesOpen,
  } = useApp();

  const [open, setOpen] = useState(false);
  const [submenuOpen, setSubmenuOpen] = useState(false);

  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const idiomaTriggerRef = useRef(null);
  const submenuRef = useRef(null);

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setSubmenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Focus management when menu opens
  useEffect(() => {
    if (open && menuRef.current) {
      const first = menuRef.current.querySelector('[role="menuitem"]');
      first?.focus();
    }
  }, [open]);

  // Keyboard navigation on main menu
  const handleKeyDown = (e) => {
    if (!open) return;

    if (e.key === "Escape") {
      e.preventDefault();
      if (submenuOpen) {
        setSubmenuOpen(false);
        idiomaTriggerRef.current?.focus();
      } else {
        setOpen(false);
        triggerRef.current?.focus();
      }
      return;
    }

    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const currentParent = submenuOpen && submenuRef.current?.contains(document.activeElement)
        ? submenuRef.current
        : menuRef.current;
      if (!currentParent) return;

      const items = Array.from(
        currentParent.querySelectorAll('[role="menuitem"]')
      );
      if (items.length === 0) return;

      const idx = items.indexOf(document.activeElement);
      let nextIdx = 0;
      if (e.key === "ArrowDown") {
        nextIdx = idx < items.length - 1 ? idx + 1 : 0;
      } else {
        nextIdx = idx > 0 ? idx - 1 : items.length - 1;
      }
      items[nextIdx]?.focus();
    }
  };

  const handleIdiomaKeyDown = (e) => {
    if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setSubmenuOpen(true);
      setTimeout(() => {
        const first = submenuRef.current?.querySelector('[role="menuitem"]');
        first?.focus();
      }, 30);
    }
  };

  const handleSubmenuKeyDown = (e) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setSubmenuOpen(false);
      idiomaTriggerRef.current?.focus();
    }
  };

  // Only render when authenticated
  if (!user) {
    return null;
  }

  const languages = [
    { code: "pt", label: "Português" },
    { code: "fr", label: "Français" },
    { code: "en", label: "English" },
  ];

  const displayName = user.is_demo ? t.demoAccount : user.nome || "Utilizador";
  const displayEmail = user.email || "";
  const avatarInitial = (user.is_demo ? "D" : (user.nome || "U")).trim().charAt(0).toUpperCase();

  return (
    <div ref={containerRef} className="relative" onKeyDown={handleKeyDown}>
      {/* Upward floating menu */}
      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={displayName}
          className="absolute bottom-full left-0 mb-2 w-60 rounded-item border border-border bg-surface p-1.5 shadow-menu z-50 transition-ui"
        >
          {/* Informative Header (Name & Email, non-clickable) */}
          <div className="rounded-item bg-sidebar px-3 py-2 select-none mb-1">
            <div className="truncate text-xs font-semibold text-text">
              {displayName}
            </div>
            {displayEmail && (
              <div className="truncate text-[11px] text-text-secondary">
                {displayEmail}
              </div>
            )}
          </div>

          <div className="space-y-0.5">
            {/* Definições */}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                setSubmenuOpen(false);
                setDefinicoesOpen(true);
              }}
              className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
            >
              <span>{t.settings}</span>
            </button>

            {/* Idioma com submenu à direita */}
            <div
              className="relative"
              onMouseEnter={() => setSubmenuOpen(true)}
              onMouseLeave={() => setSubmenuOpen(false)}
            >
              <button
                ref={idiomaTriggerRef}
                type="button"
                role="menuitem"
                aria-haspopup="menu"
                aria-expanded={submenuOpen}
                onClick={() => setSubmenuOpen((prev) => !prev)}
                onKeyDown={handleIdiomaKeyDown}
                className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
              >
                <span>{t.language}</span>
                <span className="text-xs text-text-secondary" aria-hidden="true">
                  ▸
                </span>
              </button>

              {submenuOpen && (
                <div
                  ref={submenuRef}
                  role="menu"
                  aria-label={t.language}
                  onKeyDown={handleSubmenuKeyDown}
                  className="absolute left-full bottom-0 ml-1.5 w-36 rounded-item border border-border bg-surface p-1 shadow-menu z-50"
                >
                  {languages.map((item) => {
                    const active = lang === item.code;
                    return (
                      <button
                        key={item.code}
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setLang(item.code);
                          setSubmenuOpen(false);
                          setOpen(false);
                        }}
                        className={`flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-xs transition-ui ${
                          active
                            ? "bg-sidebar-active font-semibold text-text"
                            : "text-text hover:bg-sidebar-hover"
                        }`}
                      >
                        <span>{item.label}</span>
                        {active && (
                          <span
                            className="text-accent text-xs font-semibold"
                            aria-hidden="true"
                          >
                            ✓
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Sobre */}
            <Link
              href="/sobre"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                setSubmenuOpen(false);
                onNavigate?.();
              }}
              className="flex w-full items-center rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
            >
              {t.navAbout}
            </Link>
          </div>

          <div className="my-1 border-t border-border" />

          {/* Terminar sessão (a cor de erro) */}
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              setSubmenuOpen(false);
              await logout();
            }}
            className="flex w-full items-center rounded-item px-2.5 py-1.5 text-left text-sm font-medium text-danger hover:bg-sidebar-hover transition-ui"
          >
            <span>{t.logout}</span>
          </button>
        </div>
      )}

      {/* Botão de Perfil na barra lateral */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={displayName}
        title={collapsed ? displayName : undefined}
        className={`flex w-full items-center rounded-item p-2 text-left hover:bg-sidebar-hover transition-ui ${
          collapsed ? "justify-center" : "gap-3"
        }`}
      >
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-white shadow-sm"
          aria-hidden="true"
        >
          {avatarInitial}
        </span>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-text">
              {displayName}
            </div>
            {displayEmail && (
              <div className="truncate text-xs text-text-secondary">
                {displayEmail}
              </div>
            )}
          </div>
        )}
      </button>
    </div>
  );
}
