"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useApp } from "@/context/AppContext";

export default function MenuConta({ collapsed = false, onNavigate }) {
  const {
    lang,
    setLang,
    theme,
    setTheme,
    t,
    user,
    openAuthModal,
    loginWithDemo,
    logout,
  } = useApp();
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const handleKeyDown = (e) => {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = menuRef.current?.querySelectorAll(
        '[role="menuitem"], [role="menuitemradio"]'
      );
      if (!items || items.length === 0) return;
      const arr = Array.from(items);
      const currentIndex = arr.indexOf(document.activeElement);
      let nextIndex = 0;
      if (e.key === "ArrowDown") {
        nextIndex = currentIndex < arr.length - 1 ? currentIndex + 1 : 0;
      } else {
        nextIndex = currentIndex > 0 ? currentIndex - 1 : arr.length - 1;
      }
      arr[nextIndex]?.focus();
    }
  };

  useEffect(() => {
    if (open && menuRef.current) {
      const first = menuRef.current.querySelector(
        '[role="menuitem"], [role="menuitemradio"]'
      );
      first?.focus();
    }
  }, [open]);

  const languages = [
    { code: "pt", label: "Português" },
    { code: "fr", label: "Français" },
    { code: "en", label: "English" },
  ];

  const themes = [
    { code: "system", label: t.themeSystem },
    { code: "light", label: t.themeLight },
    { code: "dark", label: t.themeDark },
  ];

  const displayName = user
    ? user.is_demo
      ? t.demoAccount
      : user.nome
    : t.loggedOutLabel;

  const displayEmail = user?.email || "";
  const avatarInitial = user
    ? (user.is_demo ? "D" : (user.nome || "U").trim().charAt(0).toUpperCase())
    : "?";

  return (
    <div ref={containerRef} className="relative" onKeyDown={handleKeyDown}>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={displayName}
          className="absolute bottom-full left-0 mb-2 w-64 rounded-item border border-border bg-surface p-2 shadow-menu z-50 transition-ui"
        >
          {/* Secção de Conta: Login, Sign in, Logout */}
          <div className="px-2 py-1 text-xs font-medium text-text-secondary">
            {t.accountSection}
          </div>
          {user && (
            <div className="mb-1.5 rounded-item bg-sidebar px-2.5 py-1.5">
              <div className="truncate text-xs font-semibold text-text">
                {displayName}
              </div>
              {displayEmail && (
                <div className="truncate text-xs text-text-secondary">
                  {displayEmail}
                </div>
              )}
            </div>
          )}

          <div className="mb-2 space-y-0.5">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                openAuthModal("login");
              }}
              className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
            >
              <span>{t.login}</span>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                openAuthModal("signup");
              }}
              className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
            >
              <span>{t.signIn}</span>
            </button>

            {user ? (
              <button
                type="button"
                role="menuitem"
                onClick={async () => {
                  setOpen(false);
                  await logout();
                }}
                className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm font-medium text-danger hover:bg-sidebar-hover transition-ui"
              >
                <span>{t.logout}</span>
              </button>
            ) : (
              <button
                type="button"
                role="menuitem"
                onClick={async () => {
                  setOpen(false);
                  await loginWithDemo();
                }}
                className="flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-xs font-medium text-accent hover:bg-sidebar-hover transition-ui"
              >
                <span>{t.useDemoAccount}</span>
              </button>
            )}
          </div>

          <div className="my-1.5 border-t border-border" />

          {/* Idioma */}
          <div className="px-2 py-1 text-xs font-medium text-text-secondary">
            {t.language}
          </div>
          <div className="mb-2 space-y-0.5">
            {languages.map((item) => {
              const active = lang === item.code;
              return (
                <button
                  key={item.code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  onClick={() => {
                    setLang(item.code);
                  }}
                  className={`flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm transition-ui ${
                    active
                      ? "bg-sidebar-active font-medium text-text"
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

          <div className="my-1.5 border-t border-border" />

          {/* Tema */}
          <div className="px-2 py-1 text-xs font-medium text-text-secondary">
            {t.theme}
          </div>
          <div className="mb-2 space-y-0.5">
            {themes.map((item) => {
              const active = theme === item.code;
              return (
                <button
                  key={item.code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  onClick={() => {
                    setTheme(item.code);
                  }}
                  className={`flex w-full items-center justify-between rounded-item px-2.5 py-1.5 text-left text-sm transition-ui ${
                    active
                      ? "bg-sidebar-active font-medium text-text"
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

          <div className="my-1.5 border-t border-border" />

          {/* Sobre */}
          <Link
            href="/sobre"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
            }}
            className="flex w-full items-center rounded-item px-2.5 py-1.5 text-sm text-text hover:bg-sidebar-hover transition-ui"
          >
            {t.navAbout}
          </Link>
        </div>
      )}

      {!collapsed && !user && (
        <div className="mb-2 grid grid-cols-2 gap-1.5">
          <button
            type="button"
            onClick={() => openAuthModal("login")}
            className="rounded-item bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover transition-ui"
          >
            {t.authSubmitLogin}
          </button>
          <button
            type="button"
            onClick={() => openAuthModal("signup")}
            className="rounded-item border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold text-text hover:bg-sidebar-hover transition-ui"
          >
            {t.authSubmitSignup}
          </button>
        </div>
      )}

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
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ${
            user ? "bg-accent" : "bg-text-secondary"
          }`}
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
