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
    appConfig,
  } = useApp();

  const isApiMode = appConfig?.modo === "api";

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

  const isSignup = !isApiMode && authModalMode === "signup";

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
      if (err?.status === 429) {
        setErro(err?.message || t.error429);
      } else if (err?.status === 503) {
        setErro(err?.message || t.error503);
      } else {
        setErro(err?.message || "Erro ao autenticar. Verifique os dados ou o servidor.");
      }
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
      if (err?.status === 429) {
        setErro(err?.message || t.error429);
      } else if (err?.status === 503) {
        setErro(err?.message || t.error503);
      } else {
        setErro(err?.message || "Erro ao entrar com conta de demonstração. Verifique a ligação ao servidor.");
      }
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

        {/* Aviso de demonstração visível em PT, FR e EN */}
        <div className="mb-4 space-y-2 rounded-item border border-accent/25 bg-accent/5 p-3 text-xs leading-relaxed text-text">
          <p className="font-medium text-text">
            <strong className="text-accent">PT:</strong> Demonstração do hackathon. Não envie dados pessoais reais. Textos, vozes e fotos são processados por modelos da Meta. Os dados de convidados são apagados após 24 horas.
          </p>
          <p className="text-text-secondary text-[11.5px]">
            <strong>FR:</strong> Démonstration du hackathon. N&apos;envoyez pas de données personnelles réelles. Les textes, voix et photos sont traités par des modèles de Meta. Les données des invités sont supprimées après 24 heures.
          </p>
          <p className="text-text-secondary text-[11.5px]">
            <strong>EN:</strong> Hackathon demo. Do not send real personal data. Texts, voices, and photos are processed by Meta models. Guest data is deleted after 24 hours.
          </p>
        </div>

        {/* Mode Tabs: Login vs Sign in / Registar em agrilink.store */}
        <div className="mb-5">
          <div className="grid grid-cols-2 gap-1 rounded-item bg-sidebar p-1">
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
            {isApiMode ? (
              <a
                href={appConfig?.registo_url || "https://agrilink.store/registar"}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center rounded-item py-2 text-xs font-semibold text-accent hover:text-accent-hover transition-ui"
              >
                Criar conta ↗
              </a>
            ) : (
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
            )}
          </div>
          {isApiMode && (
            <p className="mt-2 text-center text-xs text-text-secondary">
              Depois de criar a conta, volte aqui e entre.
            </p>
          )}
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
              {isApiMode ? "Email ou Telefone" : t.authEmailLabel}
            </label>
            <input
              type={isApiMode ? "text" : "email"}
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={isApiMode ? "ex: 923456789 ou agricultor@exemplo.com" : t.authEmailPlaceholder}
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
            <p className="text-xs text-text-secondary">
              {isApiMode ? "Utilize a sua conta do NongLink para aceder às suas parcelas e vendas." : t.authDemoHint}
            </p>
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

        {!isApiMode && (
          <>
            <div className="my-4 border-t border-border" />
            <button
              type="button"
              onClick={handleDemo}
              disabled={submitting}
              className="w-full rounded-item border border-border bg-bg px-4 py-2 text-xs font-medium text-text hover:bg-sidebar-hover transition-ui"
            >
              {t.useDemoAccount}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
