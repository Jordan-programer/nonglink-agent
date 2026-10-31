"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/context/AppContext";
import {
  obterConversa,
  enviarMensagemAgente,
  enviarFoto,
  enviarVoz,
  confirmarAccao,
  normalizeMessage,
  normalizeConversation,
} from "@/api";
import Cabecalho from "./Cabecalho";
import EstadoVazio from "./EstadoVazio";
import Mensagem from "./Mensagem";
import CaixaTexto from "./CaixaTexto";

function generateUUID() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function appendOrReplaceMessages(prevMessages, apiResponse) {
  if (!apiResponse) return prevMessages;

  // If the API returns a full conversation object with `mensagens`
  if (Array.isArray(apiResponse.mensagens) || Array.isArray(apiResponse.messages)) {
    const conv = normalizeConversation(apiResponse);
    return conv.mensagens;
  }

  // If the API returns an array of messages
  if (Array.isArray(apiResponse)) {
    return apiResponse.map((m, idx) => normalizeMessage(m, idx));
  }

  // If the API returns `{ utilizador: ..., agente: ... }`
  if (apiResponse.agente && typeof apiResponse.agente === "object") {
    const next = [...prevMessages];
    const agentMsg = normalizeMessage(
      { ...apiResponse.agente, papel: "agente" },
      next.length
    );
    next.push(agentMsg);
    return next;
  }

  // Otherwise treat apiResponse itself as an agent message
  const agentMsg = normalizeMessage(
    { ...apiResponse, papel: "agente" },
    prevMessages.length
  );
  if (
    agentMsg.texto ||
    agentMsg.accao_json ||
    agentMsg.anexo_json ||
    agentMsg.estado_accao
  ) {
    return [...prevMessages, agentMsg];
  }
  return prevMessages;
}

export default function ChatVista({ conversationId = null }) {
  const {
    t,
    user,
    openAuthModal,
    loginWithDemo,
    setActiveConversationId,
    setActiveConversationTitle,
    carregarConversas,
    newChatTrigger,
    sessionStoreRef,
  } = useApp();

  const router = useRouter();

  const [sessionId, setSessionId] = useState(
    () => conversationId || generateUUID()
  );
  const [mensagens, setMensagens] = useState(() => {
    if (conversationId && sessionStoreRef.current[conversationId]?.mensagens) {
      return sessionStoreRef.current[conversationId].mensagens;
    }
    return [];
  });
  const [inputValue, setInputValue] = useState("");
  const [isCalculating, setIsCalculating] = useState(() => {
    if (conversationId && sessionStoreRef.current[conversationId]?.isCalculating) {
      return true;
    }
    return false;
  });
  const [errorState, setErrorState] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [retryAction, setRetryAction] = useState(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  const scrollContainerRef = useRef(null);
  const userScrolledUpRef = useRef(false);

  // Sync session store
  const updateSessionStore = useCallback(
    (id, patch) => {
      sessionStoreRef.current[id] = {
        ...(sessionStoreRef.current[id] || {}),
        ...patch,
      };
    },
    [sessionStoreRef]
  );

  // Reset when clicking "Novo chat" on "/" or when user session changes / logs out
  useEffect(() => {
    if (!user) {
      setSessionId(generateUUID());
      setMensagens([]);
      setInputValue("");
      setIsCalculating(false);
      setErrorState(false);
      setRetryAction(null);
      setActiveConversationId(null);
      setActiveConversationTitle("");
      if (conversationId) {
        router.replace("/");
      }
      return;
    }
    if (!conversationId) {
      const freshId = generateUUID();
      setSessionId(freshId);
      setMensagens([]);
      setInputValue("");
      setIsCalculating(false);
      setErrorState(false);
      setRetryAction(null);
      setActiveConversationId(null);
      setActiveConversationTitle("");
    }
  }, [
    user,
    conversationId,
    newChatTrigger,
    router,
    setActiveConversationId,
    setActiveConversationTitle,
  ]);

  // Load existing conversation when on /c/:id
  const fetchConversation = useCallback(
    async (idToLoad, isRetry = false) => {
      if (!idToLoad) return;

      // If this session was just created on "/" and is still in-flight, subscribe to its completion
      const cached = sessionStoreRef.current[idToLoad];
      if (cached && cached.isCalculating && !isRetry) {
        setMensagens(cached.mensagens || []);
        setIsCalculating(true);
        if (cached.promise) {
          try {
            const finalMsgs = await cached.promise;
            if (Array.isArray(finalMsgs)) {
              setMensagens(finalMsgs);
            }
          } catch {
            setErrorState(true);
          } finally {
            setIsCalculating(false);
          }
        }
        return;
      }

      setErrorState(false);
      try {
        const conv = await obterConversa(idToLoad);
        setMensagens(conv.mensagens || []);
        setActiveConversationId(idToLoad);
        setActiveConversationTitle(conv.titulo || t.newChatTitle);
        updateSessionStore(idToLoad, {
          mensagens: conv.mensagens || [],
          titulo: conv.titulo,
          isCalculating: false,
        });
      } catch (err) {
        // If 404 on a brand new session that already has local messages, keep local messages
        if (cached?.mensagens?.length > 0 && err?.status === 404) {
          setMensagens(cached.mensagens);
        } else {
          setErrorState(true);
          setRetryAction(() => () => fetchConversation(idToLoad, true));
        }
      }
    },
    [sessionStoreRef, setActiveConversationId, setActiveConversationTitle, t.newChatTitle, updateSessionStore]
  );

  useEffect(() => {
    if (conversationId && user) {
      setSessionId(conversationId);
      setActiveConversationId(conversationId);
      fetchConversation(conversationId);
    }
  }, [conversationId, user, fetchConversation, setActiveConversationId]);

  // Scroll handling: auto-scroll unless user scrolled up
  const scrollToBottom = useCallback((behavior = "smooth") => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    userScrolledUpRef.current = false;
    setShowScrollBottom(false);
  }, []);

  useEffect(() => {
    if (!userScrolledUpRef.current) {
      scrollToBottom("smooth");
    }
  }, [mensagens, isCalculating, scrollToBottom]);

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 80) {
      userScrolledUpRef.current = true;
      setShowScrollBottom(true);
    } else {
      userScrolledUpRef.current = false;
      setShowScrollBottom(false);
    }
  };

  // Sync conversation from server after any mutation, tolerantly falling back to current messages
  const syncAfterResponse = async (targetSessionId, fallbackMessages, fallbackTitle) => {
    let finalMessages = fallbackMessages;
    try {
      const serverConv = await obterConversa(targetSessionId);
      if (serverConv && Array.isArray(serverConv.mensagens) && serverConv.mensagens.length > 0) {
        finalMessages = serverConv.mensagens;
      }
      if (serverConv?.titulo) {
        setActiveConversationTitle(serverConv.titulo);
      } else if (fallbackTitle) {
        setActiveConversationTitle(fallbackTitle);
      }
    } catch {
      if (fallbackTitle) {
        setActiveConversationTitle(fallbackTitle);
      }
    }
    setMensagens(finalMessages);
    updateSessionStore(targetSessionId, {
      mensagens: finalMessages,
      isCalculating: false,
      promise: null,
    });
    await carregarConversas();
    return finalMessages;
  };

  // Send text and/or photo
  const executeSend = async ({ text, photoFile, targetId, baseMessages }) => {
    setErrorState(false);
    setRetryAction(null);
    setIsCalculating(true);

    const requestPromise = (async () => {
      let currentMsgs = [...baseMessages];

      if (photoFile) {
        const resFoto = await enviarFoto(targetId, photoFile);
        currentMsgs = appendOrReplaceMessages(currentMsgs, resFoto);
        setMensagens(currentMsgs);
      }

      if (text) {
        const resAgente = await enviarMensagemAgente(targetId, text);
        currentMsgs = appendOrReplaceMessages(currentMsgs, resAgente);
        setMensagens(currentMsgs);
      }

      const fallbackTitle = text || t.photoAttached;
      return syncAfterResponse(targetId, currentMsgs, fallbackTitle);
    })();

    updateSessionStore(targetId, {
      mensagens: baseMessages,
      isCalculating: true,
      promise: requestPromise,
    });

    try {
      await requestPromise;
    } catch (err) {
      updateSessionStore(targetId, { isCalculating: false, promise: null });
      setErrorState(true);
      if (err?.status === 429) {
        setErrorMessage(err?.message || t.error429);
      } else if (err?.status === 503) {
        setErrorMessage(err?.message || t.error503);
      } else if (err?.status === 413 || err?.status === 415) {
        setErrorMessage(err?.message);
      } else {
        setErrorMessage(err?.message || t.connectionError);
      }
      setRetryAction(() => () =>
        executeSend({ text, photoFile, targetId, baseMessages })
      );
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSend = ({ text, photoFile }) => {
    if (!user) {
      openAuthModal("login");
      return;
    }
    const isFirstMessage = mensagens.length === 0 && !conversationId;
    const targetId = sessionId;

    const optimisticUserMsg = {
      id: `user-${Date.now()}`,
      papel: "utilizador",
      texto: text || "",
      criado_em: new Date().toISOString(),
      accao_json: null,
      estado_accao: null,
      resultado_id: null,
      anexo_json: photoFile
        ? { url: URL.createObjectURL(photoFile) }
        : null,
    };

    const nextMessages = [...mensagens, optimisticUserMsg];
    setMensagens(nextMessages);
    setInputValue("");
    userScrolledUpRef.current = false;

    updateSessionStore(targetId, {
      mensagens: nextMessages,
      isCalculating: true,
    });

    if (isFirstMessage) {
      setActiveConversationId(targetId);
      setActiveConversationTitle(text || t.photoAttached);
      router.replace(`/c/${encodeURIComponent(targetId)}`);
    }

    executeSend({
      text,
      photoFile,
      targetId,
      baseMessages: nextMessages,
    });
  };

  // Send voice recording
  const executeVoiceSend = async ({ audioFile, targetId, baseMessages }) => {
    setErrorState(false);
    setRetryAction(null);
    setIsCalculating(true);

    const requestPromise = (async () => {
      const resVoz = await enviarVoz(targetId, audioFile);
      const updated = appendOrReplaceMessages(baseMessages, resVoz);
      setMensagens(updated);
      return syncAfterResponse(targetId, updated, t.voiceMessage);
    })();

    updateSessionStore(targetId, {
      mensagens: baseMessages,
      isCalculating: true,
      promise: requestPromise,
    });

    try {
      await requestPromise;
    } catch (err) {
      updateSessionStore(targetId, { isCalculating: false, promise: null });
      setErrorState(true);
      if (err?.status === 429) {
        setErrorMessage(err?.message || t.error429);
      } else if (err?.status === 503) {
        setErrorMessage(err?.message || t.error503);
      } else if (err?.status === 413 || err?.status === 415) {
        setErrorMessage(err?.message);
      } else {
        setErrorMessage(err?.message || t.connectionError);
      }
      setRetryAction(() => () =>
        executeVoiceSend({ audioFile, targetId, baseMessages })
      );
    } finally {
      setIsCalculating(false);
    }
  };

  const handleSendVoice = (audioFile) => {
    if (!user) {
      openAuthModal("login");
      return;
    }
    if (!audioFile) return;
    const isFirstMessage = mensagens.length === 0 && !conversationId;
    const targetId = sessionId;

    const optimisticVoiceMsg = {
      id: `voice-${Date.now()}`,
      papel: "utilizador",
      texto: `🎤 ${t.voiceMessage}`,
      criado_em: new Date().toISOString(),
      accao_json: null,
      estado_accao: null,
      resultado_id: null,
      anexo_json: null,
    };

    const nextMessages = [...mensagens, optimisticVoiceMsg];
    setMensagens(nextMessages);
    userScrolledUpRef.current = false;

    updateSessionStore(targetId, {
      mensagens: nextMessages,
      isCalculating: true,
    });

    if (isFirstMessage) {
      setActiveConversationId(targetId);
      setActiveConversationTitle(t.voiceMessage);
      router.replace(`/c/${encodeURIComponent(targetId)}`);
    }

    executeVoiceSend({
      audioFile,
      targetId,
      baseMessages: nextMessages,
    });
  };

  // Confirm or cancel Talão action (POST /confirmar)
  const handleConfirmAction = async (confirmar, msgId) => {
    setErrorState(false);
    setRetryAction(null);
    try {
      const res = await confirmarAccao(sessionId, confirmar);
      const returnedNumero =
        res?.resultado_id ||
        res?.numero ||
        res?.id ||
        res?.accao_json?.resultado_id ||
        null;

      const updatedMsgs = mensagens.map((m) => {
        if (m.id === msgId || m.estado_accao === "pendente") {
          return {
            ...m,
            estado_accao: confirmar ? "confirmada" : "cancelada",
            resultado_id: returnedNumero || m.resultado_id,
          };
        }
        return m;
      });

      const synced = appendOrReplaceMessages(updatedMsgs, res);
      await syncAfterResponse(sessionId, synced);
      return res;
    } catch (err) {
      setErrorState(true);
      setRetryAction(() => () => handleConfirmAction(confirmar, msgId));
      throw err;
    }
  };

  const isEmpty = mensagens.length === 0 && !isCalculating && !errorState && !conversationId;

  if (!user) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-bg">
        <Cabecalho />
        <div className="flex flex-1 flex-col items-center justify-center px-4 py-8">
          <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 text-center shadow-soft">
            <h1 className="font-serif text-2xl font-medium text-text mb-2">
              {t.authRequiredTitle}
            </h1>
            <p className="text-sm text-text-secondary">
              {t.authRequiredSubtitle}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-bg">
      <Cabecalho />

      {isEmpty ? (
        <EstadoVazio
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSend={handleSend}
          onSendVoice={handleSendVoice}
          disabled={isCalculating}
          autoFocusTrigger={newChatTrigger}
        />
      ) : (
        <div className="relative flex min-h-0 flex-1 flex-col items-center">
          {/* Scrollable conversation area */}
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="w-full flex-1 overflow-y-auto px-4 pt-6 pb-4"
          >
            <div className="mx-auto flex w-full max-w-[760px] flex-col gap-6">
              {mensagens.map((msg) => (
                <Mensagem
                  key={msg.id}
                  mensagem={msg}
                  onConfirmAction={(confirmar) =>
                    handleConfirmAction(confirmar, msg.id)
                  }
                />
              ))}

              {/* Agent loading indicator: three pulsing dots + "A calcular…" */}
              {isCalculating && (
                <div
                  role="status"
                  aria-live="polite"
                  className="flex items-center gap-2.5 py-2 text-sm text-text-secondary font-serif"
                >
                  <span className="flex items-center gap-1" aria-hidden="true">
                    <span className="h-2 w-2 rounded-full bg-accent dot-pulse-1" />
                    <span className="h-2 w-2 rounded-full bg-accent dot-pulse-2" />
                    <span className="h-2 w-2 rounded-full bg-accent dot-pulse-3" />
                  </span>
                  <span>{t.calculating}</span>
                </div>
              )}

              {/* Connection or Quota/Maintenance error notice with "Tentar outra vez" */}
              {errorState && (
                <div
                  role="alert"
                  className="rounded-item border border-error/40 bg-surface p-4 text-sm text-text"
                >
                  <p className="mb-3">{errorMessage || t.connectionError}</p>
                  {retryAction && (
                    <button
                      type="button"
                      onClick={() => retryAction()}
                      className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-ui"
                    >
                      {t.retry}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* "Ir para o fim" floating button when user scrolled up */}
          {showScrollBottom && (
            <button
              type="button"
              onClick={() => scrollToBottom("smooth")}
              className="absolute bottom-32 z-20 flex items-center gap-1.5 rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-text shadow-menu hover:bg-sidebar-hover transition-ui"
            >
              <span>{t.scrollToBottom}</span>
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
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <polyline points="19 12 12 19 5 12" />
              </svg>
            </button>
          )}

          {/* Fixed bottom textbox */}
          <div className="w-full shrink-0 bg-bg px-4 pb-3 pt-1">
            <div className="mx-auto w-full max-w-[760px]">
              <CaixaTexto
                value={inputValue}
                onChange={setInputValue}
                onSend={handleSend}
                onSendVoice={handleSendVoice}
                disabled={isCalculating}
                autoFocusTrigger={newChatTrigger}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
