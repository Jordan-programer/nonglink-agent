"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useApp } from "@/context/AppContext";
import {
  atualizarNomeUtilizador,
  alterarPalavraPasse,
  sairTodasSessoes,
  apagarTodasConversas,
  apagarConta,
} from "@/api";

export default function DefinicoesDialog() {
  const {
    t,
    lang,
    setLang,
    theme,
    setTheme,
    user,
    setUser,
    definicoesOpen,
    setDefinicoesOpen,
    carregarConversas,
    triggerNewChat,
    handleUnauthorized,
  } = useApp();

  const [activeTab, setActiveTab] = useState("profile"); // profile | preferences | security | data

  // Profile form state
  const [nome, setNome] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState(null); // { type: 'success' | 'error', text }

  // Security: Change password state
  const [senhaActual, setSenhaActual] = useState("");
  const [senhaNova, setSenhaNova] = useState("");
  const [senhaConfirma, setSenhaConfirma] = useState("");
  const [passSaving, setPassSaving] = useState(false);
  const [passMsg, setPassMsg] = useState(null);

  // Security: Logout all state
  const [loggingOutAll, setLoggingOutAll] = useState(false);

  // Data: Delete conversations state
  const [confirmDeleteConvs, setConfirmDeleteConvs] = useState(false);
  const [deletingConvs, setDeletingConvs] = useState(false);
  const [convsMsg, setConvsMsg] = useState(null);

  // Data: Delete account state
  const [deleteAccountInput, setDeleteAccountInput] = useState("");
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [accountMsg, setAccountMsg] = useState(null);

  const dialogRef = useRef(null);
  const previousFocusRef = useRef(null);

  // Sync initial name when user changes or dialog opens
  useEffect(() => {
    if (user?.nome) {
      setNome(user.nome);
    }
  }, [user?.nome, definicoesOpen]);

  // Focus trap and Esc key listener
  useEffect(() => {
    if (!definicoesOpen) return;
    previousFocusRef.current = document.activeElement;

    function handleKeyDown(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        setDefinicoesOpen(false);
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable || focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (previousFocusRef.current?.focus) {
        previousFocusRef.current.focus();
      }
    };
  }, [definicoesOpen, setDefinicoesOpen]);

  // Close helper
  const handleClose = useCallback(() => {
    setDefinicoesOpen(false);
    setProfileMsg(null);
    setPassMsg(null);
    setConvsMsg(null);
    setAccountMsg(null);
    setConfirmDeleteConvs(false);
    setDeleteAccountInput("");
  }, [setDefinicoesOpen]);

  if (!definicoesOpen || !user) return null;

  const isGuest = Boolean(user.convidado || user.is_demo);
  const displayName = user.is_demo ? t.demoAccount : user.nome || "Utilizador";
  const avatarInitial = (user.is_demo ? "D" : (user.nome || "U")).trim().charAt(0).toUpperCase();

  // Format date helper
  const formatDate = (isoString) => {
    if (!isoString) return "";
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString(lang === "en" ? "en-GB" : lang === "fr" ? "fr-FR" : "pt-PT", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  };

  // Submit Profile Name Change
  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setProfileMsg(null);
    const trimmed = nome.trim();
    if (!trimmed) return;
    setProfileSaving(true);
    try {
      const res = await atualizarNomeUtilizador(trimmed);
      if (res?.utilizador) {
        setUser((prev) => ({
          ...prev,
          nome: res.utilizador.nome,
        }));
        setProfileMsg({ type: "success", text: t.nameUpdatedSuccess });
      }
    } catch (err) {
      setProfileMsg({ type: "error", text: err?.message || "Erro ao actualizar nome." });
    } finally {
      setProfileSaving(false);
    }
  };

  // Submit Password Change
  const handleSavePassword = async (e) => {
    e.preventDefault();
    setPassMsg(null);
    if (senhaNova !== senhaConfirma) {
      setPassMsg({ type: "error", text: t.passwordMismatch });
      return;
    }
    setPassSaving(true);
    try {
      await alterarPalavraPasse(senhaActual, senhaNova);
      setPassMsg({ type: "success", text: t.passwordUpdatedSuccess });
      setSenhaActual("");
      setSenhaNova("");
      setSenhaConfirma("");
    } catch (err) {
      setSenhaActual("");
      setSenhaNova("");
      setSenhaConfirma("");
      setPassMsg({ type: "error", text: err?.message || "Erro ao alterar palavra-passe." });
    } finally {
      setPassSaving(false);
    }
  };

  // Logout on all devices
  const handleLogoutAllDevices = async () => {
    setLoggingOutAll(true);
    try {
      await sairTodasSessoes();
    } catch {
      // ignore
    } finally {
      setLoggingOutAll(false);
      handleClose();
      handleUnauthorized();
    }
  };

  // Delete all conversations
  const handleDeleteAllConversations = async () => {
    setDeletingConvs(true);
    setConvsMsg(null);
    try {
      await apagarTodasConversas();
      await carregarConversas();
      triggerNewChat();
      setConfirmDeleteConvs(false);
      setConvsMsg({ type: "success", text: t.conversationsDeletedSuccess });
    } catch (err) {
      setConvsMsg({ type: "error", text: err?.message || "Erro ao apagar conversas." });
    } finally {
      setDeletingConvs(false);
    }
  };

  // Delete account completely
  const handleDeleteAccount = async (e) => {
    e.preventDefault();
    setAccountMsg(null);
    setDeletingAccount(true);
    try {
      if (isGuest) {
        if (deleteAccountInput.trim() !== "APAGAR") {
          setAccountMsg({ type: "error", text: "Escreva APAGAR para confirmar." });
          setDeletingAccount(false);
          return;
        }
        await apagarConta({ confirmacao: "APAGAR" });
      } else {
        if (!deleteAccountInput) {
          setAccountMsg({ type: "error", text: "Introduza a sua palavra-passe." });
          setDeletingAccount(false);
          return;
        }
        await apagarConta({ senha: deleteAccountInput });
      }
      handleClose();
      handleUnauthorized();
    } catch (err) {
      setAccountMsg({ type: "error", text: err?.message || "Erro ao apagar conta." });
    } finally {
      setDeletingAccount(false);
    }
  };

  const tabs = [
    { id: "profile", label: t.tabProfile },
    { id: "preferences", label: t.tabPreferences },
    { id: "security", label: t.tabSecurity },
    { id: "data", label: t.tabDataPrivacy },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 sm:p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={t.settingsTitle}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          handleClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        className="flex h-[90vh] max-h-[640px] w-full max-w-3xl flex-col overflow-hidden rounded-card border border-border bg-surface text-text shadow-menu md:flex-row"
      >
        {/* Navigation Sidebar (Desktop: left column; Mobile: top bar) */}
        <aside className="flex shrink-0 flex-row overflow-x-auto border-b border-border bg-sidebar p-2 md:w-56 md:flex-col md:border-b-0 md:border-r md:p-3">
          <div className="hidden pb-3 text-xs font-semibold tracking-wider uppercase text-text-secondary md:block px-2">
            {t.settingsTitle}
          </div>
          <nav className="flex flex-row gap-1 md:flex-col" aria-label={t.settingsTitle}>
            {tabs.map((tab) => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center whitespace-nowrap rounded-item px-3 py-2 text-xs md:text-sm font-medium transition-ui ${
                    active
                      ? "bg-surface font-semibold text-accent shadow-sm"
                      : "text-text-secondary hover:bg-sidebar-hover hover:text-text"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Content Area */}
        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          {/* Header */}
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-5">
            <h2 className="text-base font-semibold text-text">
              {tabs.find((tab) => tab.id === activeTab)?.label}
            </h2>
            <button
              type="button"
              onClick={handleClose}
              aria-label={t.close}
              className="flex h-8 w-8 items-center justify-center rounded-item text-text-secondary hover:bg-sidebar-hover hover:text-text transition-ui"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 p-5 md:p-6 space-y-6">
            {/* 1. PERFIL */}
            {activeTab === "profile" && (
              <div className="space-y-6 max-w-lg">
                {/* Avatar & Identidade */}
                <div className="flex items-center gap-4">
                  <span
                    className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent text-2xl font-bold text-white shadow"
                    aria-hidden="true"
                  >
                    {avatarInitial}
                  </span>
                  <div>
                    <div className="text-base font-semibold text-text">
                      {user.nome || displayName}
                    </div>
                    <div className="text-xs text-text-secondary">
                      {user.email || ""}
                    </div>
                  </div>
                </div>

                {/* Form Nome */}
                <form onSubmit={handleSaveProfile} className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-text-secondary">
                      {t.profileNameLabel}
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        required
                        maxLength={60}
                        value={nome}
                        onChange={(e) => setNome(e.target.value)}
                        className="flex-1 rounded-item border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                      />
                      <button
                        type="submit"
                        disabled={profileSaving || !nome.trim() || nome.trim() === user.nome}
                        className="rounded-item bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-40 transition-ui"
                      >
                        {profileSaving ? t.btnSavingName : t.btnSaveName}
                      </button>
                    </div>
                  </div>
                  {profileMsg && (
                    <div
                      className={`rounded-item px-3 py-2 text-xs font-medium ${
                        profileMsg.type === "success"
                          ? "border border-accent/30 bg-accent/10 text-accent"
                          : "border border-danger/30 bg-danger/10 text-danger"
                      }`}
                    >
                      {profileMsg.text}
                    </div>
                  )}
                </form>

                <div className="border-t border-border pt-4 space-y-3 text-xs">
                  {/* Email só de leitura */}
                  <div>
                    <span className="block font-medium text-text-secondary">
                      {t.profileEmailLabel}
                    </span>
                    <span className="text-sm text-text font-mono">
                      {user.email || "—"}
                    </span>
                  </div>

                  {/* Tipo de conta */}
                  <div>
                    <span className="block font-medium text-text-secondary">
                      {t.profileAccountTypeLabel}
                    </span>
                    <span className="inline-block rounded-item bg-sidebar px-2.5 py-1 text-xs font-medium text-text mt-0.5">
                      {isGuest ? t.profileGuestAccount : t.profileRegisteredAccount}
                    </span>
                    {isGuest && user.expira_em && (
                      <p className="mt-1 text-[11px] text-text-secondary">
                        {t.profileGuestExpires}: {formatDate(user.expira_em)}
                      </p>
                    )}
                  </div>

                  {/* Conta criada em */}
                  {user.criado_em && (
                    <div>
                      <span className="block font-medium text-text-secondary">
                        {t.profileCreatedLabel}
                      </span>
                      <span className="text-text mt-0.5 block">
                        {formatDate(user.criado_em)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 2. PREFERÊNCIAS */}
            {activeTab === "preferences" && (
              <div className="space-y-6 max-w-lg">
                {/* Idioma */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-text">
                    {t.prefLanguage}
                  </h3>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { code: "pt", label: "Português" },
                      { code: "fr", label: "Français" },
                      { code: "en", label: "English" },
                    ].map((item) => {
                      const active = lang === item.code;
                      return (
                        <button
                          key={item.code}
                          type="button"
                          onClick={() => setLang(item.code)}
                          className={`flex items-center justify-center gap-1 rounded-item border px-3 py-2 text-xs font-semibold transition-ui ${
                            active
                              ? "border-accent bg-accent/10 text-accent"
                              : "border-border bg-bg text-text hover:bg-sidebar-hover"
                          }`}
                        >
                          <span>{item.label}</span>
                          {active && <span>✓</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Tema */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-text">
                    {t.prefTheme}
                  </h3>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { code: "system", label: t.themeSystem },
                      { code: "light", label: t.themeLight },
                      { code: "dark", label: t.themeDark },
                    ].map((item) => {
                      const active = theme === item.code;
                      return (
                        <button
                          key={item.code}
                          type="button"
                          onClick={() => setTheme(item.code)}
                          className={`flex items-center justify-center gap-1 rounded-item border px-3 py-2 text-xs font-semibold transition-ui ${
                            active
                              ? "border-accent bg-accent/10 text-accent"
                              : "border-border bg-bg text-text hover:bg-sidebar-hover"
                          }`}
                        >
                          <span>{item.label}</span>
                          {active && <span>✓</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* 3. SEGURANÇA */}
            {activeTab === "security" && (
              <div className="space-y-6 max-w-lg">
                {isGuest ? (
                  <div className="rounded-item border border-border bg-sidebar p-4 text-xs text-text-secondary leading-relaxed">
                    {t.securityGuestNotice}
                  </div>
                ) : (
                  <>
                    {/* Formulário Alterar Palavra-passe */}
                    <form onSubmit={handleSavePassword} className="space-y-3">
                      <h3 className="text-sm font-semibold text-text">
                        {t.securityChangePassword}
                      </h3>
                      <div>
                        <label className="mb-1 block text-xs font-medium text-text-secondary">
                          {t.securityCurrentPassword}
                        </label>
                        <input
                          type="password"
                          required
                          autoComplete="current-password"
                          value={senhaActual}
                          onChange={(e) => setSenhaActual(e.target.value)}
                          className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-medium text-text-secondary">
                          {t.securityNewPassword}
                        </label>
                        <input
                          type="password"
                          required
                          minLength={8}
                          autoComplete="new-password"
                          value={senhaNova}
                          onChange={(e) => setSenhaNova(e.target.value)}
                          className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-medium text-text-secondary">
                          {t.securityConfirmPassword}
                        </label>
                        <input
                          type="password"
                          required
                          minLength={8}
                          autoComplete="new-password"
                          value={senhaConfirma}
                          onChange={(e) => setSenhaConfirma(e.target.value)}
                          className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                        />
                      </div>

                      {passMsg && (
                        <div
                          className={`rounded-item px-3 py-2 text-xs font-medium ${
                            passMsg.type === "success"
                              ? "border border-accent/30 bg-accent/10 text-accent"
                              : "border border-danger/30 bg-danger/10 text-danger"
                          }`}
                        >
                          {passMsg.text}
                        </div>
                      )}

                      <button
                        type="submit"
                        disabled={passSaving || !senhaActual || !senhaNova || !senhaConfirma}
                        className="rounded-item bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-40 transition-ui"
                      >
                        {passSaving ? t.authSubmitting : t.btnChangePassword}
                      </button>
                    </form>

                    <div className="border-t border-border pt-4 space-y-2">
                      <h3 className="text-sm font-semibold text-text">
                        {t.securityLogoutAll}
                      </h3>
                      <p className="text-xs text-text-secondary">
                        {t.securityLogoutAllDesc}
                      </p>
                      <button
                        type="button"
                        onClick={handleLogoutAllDevices}
                        disabled={loggingOutAll}
                        className="rounded-item border border-border bg-bg px-3 py-2 text-xs font-medium text-text hover:bg-sidebar-hover disabled:opacity-40 transition-ui"
                      >
                        {loggingOutAll ? t.authSubmitting : t.btnLogoutAllDevices}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* 4. DADOS E PRIVACIDADE */}
            {activeTab === "data" && (
              <div className="space-y-6 max-w-lg">
                {/* Apagar todas as conversas */}
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-text">
                    {t.dataDeleteConversations}
                  </h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    {t.dataDeleteConversationsDesc}
                  </p>

                  {convsMsg && (
                    <div
                      className={`rounded-item px-3 py-2 text-xs font-medium ${
                        convsMsg.type === "success"
                          ? "border border-accent/30 bg-accent/10 text-accent"
                          : "border border-danger/30 bg-danger/10 text-danger"
                      }`}
                    >
                      {convsMsg.text}
                    </div>
                  )}

                  {!confirmDeleteConvs ? (
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteConvs(true)}
                      className="rounded-item border border-danger/30 bg-danger/10 px-3 py-2 text-xs font-semibold text-danger hover:bg-danger/20 transition-ui"
                    >
                      {t.btnDeleteAllConversations}
                    </button>
                  ) : (
                    <div className="flex items-center gap-2 pt-1">
                      <button
                        type="button"
                        onClick={handleDeleteAllConversations}
                        disabled={deletingConvs}
                        className="rounded-item bg-danger px-3 py-2 text-xs font-semibold text-white hover:bg-danger/90 disabled:opacity-40 transition-ui"
                      >
                        {deletingConvs ? t.authSubmitting : t.btnConfirmDeleteAllConversations}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteConvs(false)}
                        className="rounded-item border border-border bg-bg px-3 py-2 text-xs font-medium text-text hover:bg-sidebar-hover transition-ui"
                      >
                        {t.cancel}
                      </button>
                    </div>
                  )}
                </div>

                {/* Zona de Perigo */}
                <div className="rounded-card border border-danger/30 bg-danger/5 p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-danger">
                    {t.dangerZone}
                  </h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    {t.dangerZoneDesc}
                  </p>

                  <form onSubmit={handleDeleteAccount} className="space-y-3 pt-2">
                    <label className="block text-xs font-medium text-text">
                      {isGuest ? t.deleteAccountGuestPrompt : t.deleteAccountConfirmPrompt}
                    </label>
                    <input
                      type={isGuest ? "text" : "password"}
                      required
                      placeholder={isGuest ? "APAGAR" : ""}
                      value={deleteAccountInput}
                      onChange={(e) => setDeleteAccountInput(e.target.value)}
                      className="w-full rounded-item border border-danger/40 bg-bg px-3 py-2 text-sm text-text focus:border-danger focus:outline-none"
                    />

                    {accountMsg && (
                      <div className="rounded-item border border-danger/40 bg-danger/10 px-3 py-2 text-xs font-medium text-danger">
                        {accountMsg.text}
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={deletingAccount || !deleteAccountInput}
                      className="rounded-item bg-danger px-4 py-2 text-xs font-semibold text-white hover:bg-danger/90 disabled:opacity-40 transition-ui"
                    >
                      {deletingAccount ? t.authSubmitting : t.btnConfirmDeleteAccount}
                    </button>
                  </form>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
