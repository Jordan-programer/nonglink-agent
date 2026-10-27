"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import { translations } from "@/i18n";
import {
  listarConversas,
  loginUtilizador,
  registarUtilizador,
  loginDemo,
  logoutUtilizador,
  setApiAuthToken,
  getApiAuthToken,
  setOnUnauthorized,
  obterUtilizadorAtual,
} from "@/api";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  // Language: 'pt' (default), 'fr', 'en' — kept in memory only (no persistent storage)
  const [lang, setLang] = useState("pt");
  // Theme: 'system' (default), 'light', 'dark' — kept in memory only (no persistent storage)
  const [theme, setTheme] = useState("system");

  // User authentication state: starts unauthenticated (null) so no chat is possible without login
  const [user, setUser] = useState(null);
  const [authToken, setAuthToken] = useState(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authModalMode, setAuthModalMode] = useState("login"); // 'login' | 'signup'

  // Sidebar desktop collapsed state & mobile drawer open state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // Conversations list and search query (strictly scoped to the logged-in user)
  const [conversas, setConversas] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loadingConversas, setLoadingConversas] = useState(false);

  // Current active conversation ID and title (for Cabecalho & BarraLateral)
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [activeConversationTitle, setActiveConversationTitle] = useState("");

  // Trigger counter to focus/reset input on "Novo chat" or user switch
  const [newChatTrigger, setNewChatTrigger] = useState(0);

  // In-memory store for active conversation transitions from "/" -> "/c/:id"
  const sessionStoreRef = useRef({});

  // Apply theme attribute to documentElement
  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    if (theme === "light") {
      root.setAttribute("data-theme", "light");
    } else if (theme === "dark") {
      root.setAttribute("data-theme", "dark");
    } else {
      root.removeAttribute("data-theme");
    }
  }, [theme]);

  // Apply lang attribute to documentElement
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = lang;
  }, [lang]);

  const carregarConversas = useCallback(
    async (q = searchQuery) => {
      if (!user || !authToken) {
        setConversas([]);
        return;
      }
      setLoadingConversas(true);
      try {
        const lista = await listarConversas(q);
        setConversas(lista);
      } catch {
        setConversas([]);
      } finally {
        setLoadingConversas(false);
      }
    },
    [searchQuery, user, authToken]
  );

  // Load conversations for the active user and 300ms debounced search
  useEffect(() => {
    if (!user || !authToken) {
      setConversas([]);
      return;
    }
    const timer = setTimeout(() => {
      carregarConversas(searchQuery);
    }, 150);
    return () => clearTimeout(timer);
  }, [searchQuery, user, authToken, carregarConversas]);

  const t = translations[lang] || translations.pt;

  const triggerNewChat = useCallback(() => {
    setActiveConversationId(null);
    setActiveConversationTitle("");
    setNewChatTrigger((prev) => prev + 1);
    setMobileDrawerOpen(false);
  }, []);

  const openAuthModal = useCallback((mode = "login") => {
    setAuthModalMode(mode === "signup" ? "signup" : "login");
    setAuthModalOpen(true);
  }, []);

  const closeAuthModal = useCallback(() => {
    setAuthModalOpen(false);
  }, []);

  const _applyAuthenticatedSession = useCallback((utilizador, token) => {
    setApiAuthToken(token);
    sessionStoreRef.current = {};
    setConversas([]);
    setActiveConversationId(null);
    setActiveConversationTitle("");
    setUser(utilizador);
    setAuthToken(token);
    setNewChatTrigger((prev) => prev + 1);
    setAuthModalOpen(false);
  }, []);

  const login = useCallback(
    async (email, senha) => {
      const res = await loginUtilizador(email, senha);
      if (res?.utilizador && res?.token) {
        _applyAuthenticatedSession(res.utilizador, res.token);
      }
      return res;
    },
    [_applyAuthenticatedSession]
  );

  const register = useCallback(
    async (nome, email, senha) => {
      const res = await registarUtilizador(nome, email, senha);
      if (res?.utilizador && res?.token) {
        _applyAuthenticatedSession(res.utilizador, res.token);
      }
      return res;
    },
    [_applyAuthenticatedSession]
  );

  const loginWithDemo = useCallback(async () => {
    const res = await loginDemo();
    if (res?.utilizador && res?.token) {
      _applyAuthenticatedSession(res.utilizador, res.token);
    }
    return res;
  }, [_applyAuthenticatedSession]);

  const logout = useCallback(async () => {
    try {
      await logoutUtilizador();
    } catch {
      // ignore network error on logout
    }
    setApiAuthToken(null);
    sessionStoreRef.current = {};
    setUser(null);
    setAuthToken(null);
    setConversas([]);
    setActiveConversationId(null);
    setActiveConversationTitle("");
    setNewChatTrigger((prev) => prev + 1);
  }, []);

  // Clear all session state (conversations, messages, photos) and show the sign-in screen
  const handleUnauthorized = useCallback(() => {
    setApiAuthToken(null);
    sessionStoreRef.current = {};
    setUser(null);
    setAuthToken(null);
    setConversas([]);
    setActiveConversationId(null);
    setActiveConversationTitle("");
    setNewChatTrigger((prev) => prev + 1);
    setAuthModalMode("login");
    setAuthModalOpen(true);
  }, []);

  // Register the global 401 handler used by every API call
  useEffect(() => {
    setOnUnauthorized(handleUnauthorized);
    return () => setOnUnauthorized(null);
  }, [handleUnauthorized]);

  // Restore an existing tab session (token kept only in sessionStorage) and validate it with /auth/me
  useEffect(() => {
    const savedToken = getApiAuthToken();
    if (!savedToken) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await obterUtilizadorAtual();
        if (!cancelled && res?.utilizador) {
          setUser(res.utilizador);
          setAuthToken(savedToken);
        }
      } catch {
        // 401 is handled globally by handleUnauthorized
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppContext.Provider
      value={{
        lang,
        setLang,
        theme,
        setTheme,
        t,
        user,
        setUser,
        authToken,
        authModalOpen,
        authModalMode,
        setAuthModalMode,
        openAuthModal,
        closeAuthModal,
        login,
        register,
        loginWithDemo,
        logout,
        sidebarCollapsed,
        setSidebarCollapsed,
        mobileDrawerOpen,
        setMobileDrawerOpen,
        conversas,
        setConversas,
        searchQuery,
        setSearchQuery,
        loadingConversas,
        carregarConversas,
        activeConversationId,
        setActiveConversationId,
        activeConversationTitle,
        setActiveConversationTitle,
        newChatTrigger,
        triggerNewChat,
        sessionStoreRef,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useApp must be used within AppProvider");
  }
  return ctx;
}
