"use client";

import React, { useState, useEffect } from "react";
import { useApp } from "@/context/AppContext";

export default function ModalAuth() {
  const {
    t,
    lang,
    setLang,
    user,
    authModalOpen,
    authModalMode,
    setAuthModalMode,
    closeAuthModal,
    login,
    register,
    loginWithDemo,
  } = useApp();

  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setErro("");
  }, [authModalMode]);

  // Se já há utilizador autenticado, o ecrã de entrada não é apresentado
  if (user) return null;

  const isSignup = authModalMode === "signup";

  const languages = [
    { code: "pt", label: "PT" },
    { code: "fr", label: "FR" },
    { code: "en", label: "EN" },
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErro("");
    const cleanEmail = email.trim();
    const cleanSenha = senha;
    if (!cleanEmail || !cleanSenha) {
      setErro("Preencha o email e a palavra-passe.");
      return;
    }
    setSubmitting(true);
    try {
      if (isSignup) {
        const cleanNome = nome.trim();
        if (!cleanNome) {
          setErro("Indique o seu nome ou cooperativa.");
          setSubmitting(false);
          return;
        }
        await register(cleanNome, cleanEmail, cleanSenha);
      } else {
        await login(cleanEmail, cleanSenha);
      }
      setNome("");
      setEmail("");
      setSenha("");
    } catch (err) {
      setSenha("");
      setErro(err?.message || "Erro ao autenticar. Verifique os dados ou o servidor.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDemo = async () => {
    setErro("");
    setSubmitting(true);
    try {
      await loginWithDemo();
    } catch (err) {
      setErro(err?.message || "Erro ao entrar com conta de demonstração. Verifique a ligação ao servidor.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={isSignup ? t.signIn : t.login}
    >
      <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 text-text shadow-menu">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text">
              {t.brand} · {t.accountSection}
            </h2>
            <p className="text-xs text-text-secondary">{t.demoData}</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Seletor compacto de idioma PT FR EN */}
            <div className="flex items-center rounded-item border border-border bg-sidebar p-0.5 text-[11px] font-semibold">
              {languages.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setLang(l.code)}
                  className={`rounded-[4px] px-2 py-0.5 transition-ui ${
                    lang === l.code
                      ? "bg-surface text-accent font-bold shadow-sm"
                      : "text-text-secondary hover:text-text"
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Mode Tabs: Login vs Sign in (Register) */}
        <div className="mb-5 grid grid-cols-2 gap-1 rounded-item bg-sidebar p-1">
          <button
            type="button"
            onClick={() => setAuthModalMode("login")}
            className={`rounded-item py-2 text-xs font-semibold transition-ui ${
              !isSignup
                ? "bg-surface text-text shadow-sm"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t.login}
          </button>
          <button
            type="button"
            onClick={() => setAuthModalMode("signup")}
            className={`rounded-item py-2 text-xs font-semibold transition-ui ${
              isSignup
                ? "bg-surface text-text shadow-sm"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t.signIn}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5">
          {isSignup && (
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                {t.authNameLabel}
              </label>
              <input
                type="text"
                required
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder={t.authNamePlaceholder}
                className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-secondary focus:border-accent focus:outline-none"
              />
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              {t.authEmailLabel}
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t.authEmailPlaceholder}
              className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-secondary focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              {t.authPasswordLabel}
            </label>
            <input
              type="password"
              required
              minLength={isSignup ? 8 : 1}
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              placeholder={t.authPasswordPlaceholder}
              className="w-full rounded-item border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-secondary focus:border-accent focus:outline-none"
            />
          </div>

          {!isSignup && (
            <p className="text-xs text-text-secondary">{t.authDemoHint}</p>
          )}

          {erro && (
            <div className="rounded-item border border-danger/30 bg-danger/10 px-3 py-2 text-xs font-medium text-danger">
              {erro}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-item bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50 transition-ui"
          >
            {submitting
              ? t.authSubmitting
              : isSignup
              ? t.authSubmitSignup
              : t.authSubmitLogin}
          </button>
        </form>

        <div className="my-4 border-t border-border" />

        <button
          type="button"
          onClick={handleDemo}
          disabled={submitting}
          className="w-full rounded-item border border-border bg-bg px-4 py-2 text-xs font-medium text-text hover:bg-sidebar-hover transition-ui"
        >
          {t.useDemoAccount}
        </button>
      </div>
    </div>
  );
}
