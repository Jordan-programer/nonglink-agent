const RAW_BASE_URL =
  (typeof process !== "undefined" &&
    (process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL)) ||
  "http://127.0.0.1:8000";

export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, "");

const SESSION_TOKEN_KEY = "nonglink_token";

let currentAuthToken = null;
let unauthorizedHandler = null;

export function setOnUnauthorized(handler) {
  unauthorizedHandler = typeof handler === "function" ? handler : null;
}

export function setApiAuthToken(token) {
  const clean = token ? String(token) : null;
  currentAuthToken = clean;
  if (typeof window !== "undefined" && window.sessionStorage) {
    try {
      if (clean) {
        window.sessionStorage.setItem(SESSION_TOKEN_KEY, clean);
      } else {
        window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
      }
    } catch {
      // ignore storage errors
    }
  }
}

export function getApiAuthToken() {
  if (currentAuthToken) {
    return currentAuthToken;
  }
  if (typeof window !== "undefined" && window.sessionStorage) {
    try {
      const saved = window.sessionStorage.getItem(SESSION_TOKEN_KEY);
      if (saved) {
        currentAuthToken = saved;
        return saved;
      }
    } catch {
      // ignore storage errors
    }
  }
  return null;
}

function handleUnauthorizedResponse(path) {
  setApiAuthToken(null);
  if (unauthorizedHandler && path !== "/auth/login") {
    unauthorizedHandler();
  }
}

async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const headers = {
    ...(options.headers || {}),
  };
  const token = getApiAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    handleUnauthorizedResponse(path);
  }

  if (!response.ok) {
    let errorDetail = "";
    try {
      const data = await response.json();
      errorDetail = data?.detail || data?.erro || data?.message || "";
    } catch {
      // ignore JSON parse error on error response
    }
    const err = new Error(errorDetail || `HTTP ${response.status}`);
    err.status = response.status;
    throw err;
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { texto: text };
  }
}

function safeParseJson(val) {
  if (!val) return null;
  if (typeof val === "object") return val;
  if (typeof val === "string") {
    try {
      return JSON.parse(val);
    } catch {
      return { descricao: val };
    }
  }
  return null;
}

export function normalizeMessage(raw, index = 0) {
  if (!raw || typeof raw !== "object") {
    return {
      id: `msg-${index}`,
      papel: "agente",
      texto: String(raw || ""),
      criado_em: null,
      accao_json: null,
      estado_accao: null,
      resultado_id: null,
      anexo_json: null,
    };
  }

  const papelRaw = String(raw.papel || raw.role || "agente").toLowerCase();
  const papel =
    papelRaw === "utilizador" || papelRaw === "user" || papelRaw === "humano"
      ? "utilizador"
      : "agente";

  const texto =
    raw.texto ??
    raw.mensagem ??
    raw.resposta ??
    raw.content ??
    raw.transcricao ??
    "";

  const accao_json = safeParseJson(raw.accao_json ?? raw.accao ?? raw.acao_json ?? raw.acao);
  const anexo_json = safeParseJson(raw.anexo_json ?? raw.anexo ?? raw.foto_json ?? raw.foto);

  return {
    id: raw.id ?? `msg-${index}-${raw.criado_em || ""}`,
    papel,
    texto: String(texto ?? ""),
    criado_em: raw.criado_em ?? raw.created_at ?? null,
    accao_json,
    estado_accao: raw.estado_accao ?? raw.estado_acao ?? (accao_json ? "pendente" : null),
    resultado_id:
      raw.resultado_id ??
      raw.numero ??
      accao_json?.resultado_id ??
      accao_json?.numero ??
      null,
    anexo_json,
  };
}

export function normalizeConversation(raw, fallbackId = "") {
  if (!raw || typeof raw !== "object") {
    return { id: fallbackId, titulo: "", mensagens: [] };
  }
  const mensagensRaw = Array.isArray(raw.mensagens)
    ? raw.mensagens
    : Array.isArray(raw.messages)
    ? raw.messages
    : [];

  return {
    id: raw.id || raw.sessao || fallbackId,
    titulo: raw.titulo || raw.title || "",
    atualizada_em: raw.atualizada_em || raw.updated_at || raw.criado_em || null,
    mensagens: mensagensRaw.map((m, idx) => normalizeMessage(m, idx)),
  };
}

export async function listarConversas(q = "") {
  const query = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  const data = await request(`/conversas${query}`, {
    method: "GET",
  });
  const list = Array.isArray(data)
    ? data
    : Array.isArray(data?.conversas)
    ? data.conversas
    : Array.isArray(data?.items)
    ? data.items
    : [];
  return list.map((item, idx) => ({
    id: item?.id ?? item?.sessao ?? `conv-${idx}`,
    titulo: item?.titulo || item?.title || "Conversa",
    atualizada_em: item?.atualizada_em || item?.updated_at || item?.criado_em || new Date().toISOString(),
  }));
}

export async function obterConversa(id) {
  const data = await request(`/conversas/${encodeURIComponent(id)}`, {
    method: "GET",
  });
  return normalizeConversation(data, id);
}

export async function renomearConversa(id, titulo) {
  return request(`/conversas/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo }),
  });
}

export async function apagarConversa(id) {
  return request(`/conversas/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function enviarMensagemAgente(sessao, mensagem) {
  return request("/agente", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessao, mensagem }),
  });
}

export async function confirmarAccao(sessao, confirmar) {
  return request("/confirmar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessao, confirmar: Boolean(confirmar) }),
  });
}

export async function enviarVoz(sessao, ficheiro) {
  const formData = new FormData();
  formData.append("sessao", sessao);
  formData.append("ficheiro", ficheiro);
  return request("/voz", {
    method: "POST",
    body: formData,
  });
}

export async function enviarFoto(sessao, ficheiro) {
  const formData = new FormData();
  formData.append("sessao", sessao);
  formData.append("ficheiro", ficheiro);
  return request("/foto", {
    method: "POST",
    body: formData,
  });
}

export function obterUrlFoto(fotoId) {
  if (!fotoId) return "";
  if (typeof fotoId === "string" && (fotoId.startsWith("http://") || fotoId.startsWith("https://") || fotoId.startsWith("data:") || fotoId.startsWith("blob:"))) {
    return fotoId;
  }
  const cleanId = String(fotoId).replace(/^\/?fotos\//, "");
  return `${API_BASE_URL}/fotos/${encodeURIComponent(cleanId)}`;
}

export async function obterFoto(fotoId) {
  const url = obterUrlFoto(fotoId);
  if (!url) {
    throw new Error("URL de foto inválido.");
  }
  if (url.startsWith("blob:") || url.startsWith("data:")) {
    const resLocal = await fetch(url);
    return resLocal.blob();
  }
  const headers = {};
  const token = getApiAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const response = await fetch(url, {
    method: "GET",
    headers,
  });
  if (response.status === 401) {
    handleUnauthorizedResponse("/fotos");
  }
  if (!response.ok) {
    const err = new Error(`HTTP ${response.status}`);
    err.status = response.status;
    throw err;
  }
  return response.blob();
}

export async function obterUtilizadorAtual() {
  return request("/auth/eu", { method: "GET" });
}

export async function atualizarNomeUtilizador(nome) {
  return request("/auth/eu", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome }),
  });
}

export async function alterarPalavraPasse(senha_actual, senha_nova) {
  return request("/auth/senha", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha_actual, senha_nova }),
  });
}

export async function sairTodasSessoes() {
  return request("/auth/sair-todas", {
    method: "POST",
  });
}

export async function apagarTodasConversas() {
  return request("/conversas", {
    method: "DELETE",
  });
}

export async function apagarConta(payload) {
  return request("/auth/eu", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function listarAnuncios() {
  const data = await request("/anuncios", { method: "GET" });
  const list = Array.isArray(data)
    ? data
    : Array.isArray(data?.anuncios)
    ? data.anuncios
    : Array.isArray(data?.items)
    ? data.items
    : [];
  return list;
}

export async function listarRegas() {
  const data = await request("/regas", { method: "GET" });
  const list = Array.isArray(data)
    ? data
    : Array.isArray(data?.regas)
    ? data.regas
    : Array.isArray(data?.items)
    ? data.items
    : [];
  return list;
}

export async function registarUtilizador(nome, email, senha) {
  return request("/auth/registar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome, email, senha }),
  });
}

export async function loginUtilizador(email, senha) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, senha }),
  });
}

export async function loginDemo() {
  return request("/auth/demo", {
    method: "POST",
  });
}

export async function logoutUtilizador() {
  return request("/auth/sair", {
    method: "POST",
  });
}
