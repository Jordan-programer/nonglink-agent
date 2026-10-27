"""FastAPI application entry point (backend/app/main.py) for the NongLink Field Agent.

Exposes the REST API for text, voice ASR (muse-voice-transcribe-1.0), vision
segmentation (sam-3.1), two-step confirmation (/confirmar), and SQLite persistence
for listings, irrigations, conversations, and messages.
"""

import json
from pathlib import Path
import secrets
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import APIStatusError, AuthenticationError, NotFoundError
from pydantic import BaseModel, Field

from app.agent import (
    BASE_URL,
    MAX_TURNS,
    MODEL_NAME,
    SYSTEM_INSTRUCTIONS,
    TOOLS,
    analyze_photo,
    build_action_description,
    create_listing,
    create_meta_client,
    detect_language,
    get_crop_price,
    log_action,
    schedule_irrigation,
)
from app.config import FRONTEND_DIR, ROOT_INDEX_HTML, UPLOADS_DIR
from app.db import (
    _verify_password,
    authenticate_user,
    create_conversation,
    create_guest_user,
    create_session_token,
    create_user,
    delete_all_user_conversations,
    delete_conversation,
    delete_session_token,
    delete_user_account_and_all_data,
    ensure_conversation,
    format_photo_attachment,
    get_conversation,
    get_photo,
    get_user_by_id,
    get_user_by_token,
    get_user_session_expiry,
    init_db,
    insert_message,
    insert_photo,
    invalidate_all_user_sessions,
    invalidate_other_sessions,
    list_conversations,
    list_irrigations,
    list_listings,
    list_messages,
    update_conversation_title,
    update_message_action,
    update_user_name,
    update_user_password,
)
from app.visao import VisionSegmentationError, resolve_photo_path
from app.voz import VoiceTranscriptionError, transcrever
from scripts.seed import seed_database

init_db()
seed_database()

app = FastAPI(
    title="NongLink Field Agent API",
    description=(
        "Multilingual agricultural field agent API (PT, FR, EN) with Voice ASR "
        "(muse-voice-transcribe-1.0), Vision Segmentation (sam-3.1), SQLite conversation "
        "persistence, and two-step confirmation."
    ),
    version="4.0.0",
)

ALLOWED_CORS_ORIGINS: List[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
ALLOWED_CORS_HEADERS: List[str] = [
    "Authorization",
    "Content-Type",
    "Accept",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=ALLOWED_CORS_HEADERS,
)

PENDING_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_LAST_PHOTO: Dict[str, str] = {}

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
GENERIC_LOGIN_ERROR = "Email ou palavra-passe incorrectos"
LOGIN_FAILURES_BY_EMAIL: Dict[str, List[float]] = {}
LOGIN_FAILURES_BY_IP: Dict[str, List[float]] = {}


def reset_login_rate_limits() -> None:
    """Clear in-memory login failure counters."""
    LOGIN_FAILURES_BY_EMAIL.clear()
    LOGIN_FAILURES_BY_IP.clear()


def _prune_attempts(timestamps: List[float], now: float) -> List[float]:
    cutoff = now - LOGIN_WINDOW_SECONDS
    return [t for t in timestamps if t > cutoff]


def _is_login_blocked(email_lower: str, client_ip: str, now: float) -> bool:
    if email_lower:
        email_list = _prune_attempts(LOGIN_FAILURES_BY_EMAIL.get(email_lower, []), now)
        LOGIN_FAILURES_BY_EMAIL[email_lower] = email_list
        if len(email_list) >= LOGIN_MAX_FAILURES:
            return True
    if client_ip:
        ip_list = _prune_attempts(LOGIN_FAILURES_BY_IP.get(client_ip, []), now)
        LOGIN_FAILURES_BY_IP[client_ip] = ip_list
        if len(ip_list) >= LOGIN_MAX_FAILURES:
            return True
    return False


def _record_login_failure(email_lower: str, client_ip: str, now: float) -> None:
    if email_lower:
        email_list = _prune_attempts(LOGIN_FAILURES_BY_EMAIL.get(email_lower, []), now)
        email_list.append(now)
        LOGIN_FAILURES_BY_EMAIL[email_lower] = email_list
    if client_ip:
        ip_list = _prune_attempts(LOGIN_FAILURES_BY_IP.get(client_ip, []), now)
        ip_list.append(now)
        LOGIN_FAILURES_BY_IP[client_ip] = ip_list


class RegisterUserRequest(BaseModel):
    """Request payload for POST /auth/registar (Sign up / Sign in)."""

    nome: str = Field(description="User full name or farm name.")
    email: str = Field(description="User email address.")
    senha: str = Field(description="User password (minimum 8 characters).")


class LoginUserRequest(BaseModel):
    """Request payload for POST /auth/login."""

    email: str = Field(description="User email address.")
    senha: str = Field(description="User password.")


class UpdateProfileRequest(BaseModel):
    """Request payload for PATCH /auth/eu."""

    nome: str = Field(description="New user name (1-60 characters).")


class ChangePasswordRequest(BaseModel):
    """Request payload for POST /auth/senha."""

    senha_actual: str = Field(description="Current password.")
    senha_nova: str = Field(description="New password (minimum 8 characters).")


class DeleteAccountRequest(BaseModel):
    """Request payload for DELETE /auth/eu."""

    senha: Optional[str] = Field(default=None, description="Password for registered accounts.")
    confirmacao: Optional[str] = Field(default=None, description="Confirmation keyword ('APAGAR') for guest accounts.")


class LogoutUserRequest(BaseModel):
    """Optional request payload for POST /auth/logout."""

    token: Optional[str] = Field(default=None, description="Session token to invalidate.")


class CreateConversationRequest(BaseModel):
    """Request payload for POST /conversas."""

    id: Optional[str] = Field(
        default=None,
        description="Optional UUID string for the conversation.",
    )
    titulo: str = Field(
        default="Nova conversa",
        description="Conversation title.",
    )


class RenameConversationRequest(BaseModel):
    """Request payload for PATCH /conversas/{conversa_id}."""

    titulo: str = Field(
        description="New conversation title.",
    )


class AgentMessageRequest(BaseModel):
    """Request payload for POST /agente."""

    sessao: str = Field(
        default="default",
        description="Session / conversation identifier used to track state and persist messages.",
    )
    conversa_id: Optional[str] = Field(
        default=None,
        description="Optional explicit conversation UUID alias for sessao.",
    )
    mensagem: Optional[str] = Field(
        default=None,
        description="Farmer's message in Portuguese, French, or English.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional English alias for 'mensagem'.",
    )
    idioma: Optional[str] = Field(
        default=None,
        description="Optional language override ('pt', 'fr', 'en').",
    )
    foto_id: Optional[str] = Field(
        default=None,
        description="Optional photo ID previously uploaded via POST /foto.",
    )


class ConfirmActionRequest(BaseModel):
    """Request payload for POST /confirmar."""

    sessao: str = Field(
        default="default",
        description="Session / conversation identifier whose pending action is being confirmed or cancelled.",
    )
    conversa_id: Optional[str] = Field(
        default=None,
        description="Optional explicit conversation UUID alias for sessao.",
    )
    confirmar: bool = Field(
        description="True to confirm and execute the pending action, False to cancel it."
    )


def _extract_latest_photo_analysis(
    executed_actions: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Return the latest analisar_foto result from executed_actions, if any."""
    for action in reversed(executed_actions):
        if action.get("ferramenta") == "analisar_foto":
            res = action.get("resultado")
            if isinstance(res, dict) and res.get("status") == "executed":
                return res
    return None


def _auto_title_from_text(text: str) -> str:
    """Create a short conversation title from the first user message."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return "Nova conversa"
    return cleaned[:48] + ("…" if len(cleaned) > 48 else "")


def utilizador_atual(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Require a valid Authorization: Bearer token and return the authenticated user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Autenticação obrigatória (Authorization: Bearer).",
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token de autenticação inválido.",
        )
    user = get_user_by_token(token)
    if not user or not user.get("id"):
        raise HTTPException(
            status_code=401,
            detail="Sessão inválida ou expirada. Inicie sessão novamente.",
        )
    return user


def _record_user_message_in_db(
    conversa_id: str,
    user_text: str,
    foto_id: Optional[str] = None,
    utilizador_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure the conversation exists for utilizador_id, auto-title if new, and insert user message."""
    try:
        conv = ensure_conversation(
            conversa_id,
            titulo=_auto_title_from_text(user_text),
            utilizador_id=utilizador_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.") from exc

    if conv.get("titulo") in ("Nova conversa", "Conversa") and user_text.strip():
        update_conversation_title(
            conversa_id,
            _auto_title_from_text(user_text),
            utilizador_id=utilizador_id,
        )

    anexo = (
        {"foto_id": foto_id, "contagem": 0, "cobertura": 0.0, "caixas": []}
        if foto_id
        else None
    )
    return insert_message(
        conversa_id=conversa_id,
        papel="utilizador",
        texto=user_text,
        anexo_json=anexo,
        utilizador_id=utilizador_id,
    )


def _continue_agent_turns(
    session_id: str,
    history: List[Any],
    lang: str,
    start_turn: int,
    executed_actions: List[Dict[str, Any]],
    utilizador_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run or resume the agent loop up to MAX_TURNS, pausing on side-effecting tools."""
    client = create_meta_client()
    final_text = ""

    for turn in range(start_turn, MAX_TURNS + 1):
        response = client.responses.create(
            model=MODEL_NAME,
            input=history,
            tools=TOOLS,
            include=["reasoning.encrypted_content"],
        )

        # Preserve encrypted reasoning tokens across turns
        history.extend(response.output)

        function_calls = [
            item
            for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]

        if not function_calls:
            final_text = response.output_text or ""
            photo_analysis = _extract_latest_photo_analysis(executed_actions)
            anexo_payload = (
                format_photo_attachment(photo_analysis) if photo_analysis else None
            )
            saved_msg = insert_message(
                conversa_id=session_id,
                papel="agente",
                texto=final_text,
                anexo_json=anexo_payload,
                utilizador_id=utilizador_id,
            )
            return {
                "estado": "concluido",
                "sessao": session_id,
                "conversa_id": session_id,
                "mensagem_id": saved_msg["id"],
                "resposta": final_text,
                "idioma": lang,
                "voltas": turn,
                "accoes": executed_actions,
                "analise_foto": photo_analysis,
                "anexo_json": anexo_payload,
            }

        for idx, call in enumerate(function_calls):
            try:
                parsed_args = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                parsed_args = {}

            if call.name == "obter_preco":
                cultura = str(parsed_args.get("cultura", ""))
                tool_output = get_crop_price(cultura=cultura)
                executed_actions.append(
                    {
                        "ferramenta": "obter_preco",
                        "argumentos": {"cultura": cultura},
                        "estado": "executada",
                        "resultado": tool_output,
                    }
                )
                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(tool_output, ensure_ascii=False),
                    }
                )
                continue

            if call.name == "analisar_foto":
                foto_id = str(
                    parsed_args.get("foto_id")
                    or SESSION_LAST_PHOTO.get(session_id)
                    or ""
                )
                objecto = str(parsed_args.get("objecto", "tomato"))
                try:
                    tool_output = analyze_photo(
                        foto_id=foto_id,
                        objecto=objecto,
                        utilizador_id=utilizador_id,
                    )
                    estado_foto = "executada"
                except Exception as exc:
                    tool_output = {"status": "error", "message": str(exc)}
                    estado_foto = "erro"

                executed_actions.append(
                    {
                        "ferramenta": "analisar_foto",
                        "argumentos": {"foto_id": foto_id, "objecto": objecto},
                        "estado": estado_foto,
                        "resultado": tool_output,
                    }
                )
                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(tool_output, ensure_ascii=False),
                    }
                )
                continue

            if call.name in ("criar_anuncio", "agendar_rega"):
                description = build_action_description(call.name, parsed_args, lang=lang)
                action_payload: Dict[str, Any] = {
                    "ferramenta": call.name,
                    "tipo": "rega" if call.name == "agendar_rega" else "venda",
                    "argumentos": parsed_args,
                    "descricao": description,
                    **parsed_args,
                }
                if call.name == "criar_anuncio":
                    qty = float(parsed_args.get("quantidade_kg", 0))
                    price_kz = float(parsed_args.get("preco_kz_kg", 0))
                    action_payload["preco_kg"] = price_kz
                    action_payload["total"] = round(qty * price_kz, 2)
                log_action(
                    call.name,
                    parsed_args,
                    "PENDING_WEB_CONFIRMATION",
                    {"sessao": session_id, "descricao": description},
                )

                photo_analysis = _extract_latest_photo_analysis(executed_actions)
                anexo_payload = (
                    format_photo_attachment(photo_analysis) if photo_analysis else None
                )
                pending_msg = insert_message(
                    conversa_id=session_id,
                    papel="agente",
                    texto=description,
                    accao_json=action_payload,
                    estado_accao="pendente",
                    anexo_json=anexo_payload,
                    utilizador_id=utilizador_id,
                )

                PENDING_SESSIONS[session_id] = {
                    "utilizador_id": utilizador_id,
                    "history": history,
                    "pending_message_id": pending_msg["id"],
                    "pending_call": {
                        "call_id": call.call_id,
                        "ferramenta": call.name,
                        "argumentos": parsed_args,
                    },
                    "remaining_calls": [
                        {
                            "call_id": rem.call_id,
                            "ferramenta": rem.name,
                            "argumentos": (
                                json.loads(rem.arguments) if rem.arguments else {}
                            ),
                        }
                        for rem in function_calls[idx + 1 :]
                    ],
                    "turn": turn,
                    "lang": lang,
                    "executed_actions": executed_actions,
                    "descricao": description,
                }

                return {
                    "estado": "pendente",
                    "sessao": session_id,
                    "conversa_id": session_id,
                    "mensagem_id": pending_msg["id"],
                    "accao": action_payload,
                    "accao_json": action_payload,
                    "estado_accao": "pendente",
                    "descricao": description,
                    "resposta": description,
                    "idioma": lang,
                    "accoes": executed_actions,
                    "analise_foto": photo_analysis,
                    "anexo_json": anexo_payload,
                }

            unknown_output = {"status": "error", "message": f"Unknown tool: {call.name}"}
            history.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(unknown_output, ensure_ascii=False),
                }
            )

        final_text = response.output_text or ""

    photo_analysis = _extract_latest_photo_analysis(executed_actions)
    anexo_payload = format_photo_attachment(photo_analysis) if photo_analysis else None
    saved_msg = insert_message(
        conversa_id=session_id,
        papel="agente",
        texto=final_text,
        anexo_json=anexo_payload,
        utilizador_id=utilizador_id,
    )
    return {
        "estado": "concluido",
        "sessao": session_id,
        "conversa_id": session_id,
        "mensagem_id": saved_msg["id"],
        "resposta": final_text,
        "idioma": lang,
        "voltas": MAX_TURNS,
        "accoes": executed_actions,
        "analise_foto": photo_analysis,
        "anexo_json": anexo_payload,
    }


def _execute_or_cancel_pending_call(
    tool_name: str,
    arguments: Dict[str, Any],
    confirmed: bool,
    utilizador_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute or cancel a pending criar_anuncio or agendar_rega call."""
    status_label = "EXECUTED" if confirmed else "CANCELLED_BY_USER"
    if tool_name == "criar_anuncio":
        return create_listing(
            cultura=str(arguments.get("cultura", "")),
            quantidade_kg=float(arguments.get("quantidade_kg", 0)),
            preco_kz_kg=float(arguments.get("preco_kz_kg", 0)),
            confirmed=confirmed,
            status_label=status_label,
            utilizador_id=utilizador_id,
        )
    if tool_name == "agendar_rega":
        return schedule_irrigation(
            parcela=str(arguments.get("parcela", "")),
            hora=str(arguments.get("hora", "")),
            confirmed=confirmed,
            status_label=status_label,
            utilizador_id=utilizador_id,
        )
    return {"status": "error", "message": f"Unsupported tool: {tool_name}"}


def _build_initial_history(
    session_id: str, user_text: str, explicit_foto_id: Optional[str] = None
) -> List[Any]:
    """Build the conversation history including recent SQLite messages and active foto_id context."""
    prior_messages = list_messages(session_id)
    history: List[Any] = [{"role": "system", "content": SYSTEM_INSTRUCTIONS}]

    if len(prior_messages) > 1:
        for msg in prior_messages[-7:-1]:
            role = "user" if msg.get("papel") == "utilizador" else "assistant"
            text_content = str(msg.get("texto", "")).strip()
            if text_content:
                history.append({"role": role, "content": text_content})

    active_photo = explicit_foto_id or SESSION_LAST_PHOTO.get(session_id)
    if active_photo:
        enriched_user_text = (
            f"{user_text}\n\n[Contexto da sessão: o agricultor anexou a foto "
            f"com foto_id='{active_photo}'. Se o pedido envolver analisar/contar o lote na foto, "
            f"use a ferramenta analisar_foto com foto_id='{active_photo}'.]"
        )
    else:
        enriched_user_text = user_text

    history.append({"role": "user", "content": enriched_user_text})
    return history


@app.get("/", response_class=HTMLResponse)
def serve_index(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> HTMLResponse:
    """Serve the frontend web interface (protected)."""
    _ = user
    if ROOT_INDEX_HTML.exists():
        return HTMLResponse(content=ROOT_INDEX_HTML.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>NongLink Agent API (Dados de demonstração)</h1>"
    )


@app.get("/health")
def health_check(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, str]:
    """Protected health check endpoint."""
    _ = user
    return {"status": "ok", "service": "nonglink-agent", "model": MODEL_NAME}


@app.post("/auth/registar")
def post_auth_register(payload: RegisterUserRequest) -> Dict[str, Any]:
    """Register a new user account in SQLite and return an active session token."""
    try:
        user = create_user(
            nome=payload.nome,
            email=payload.email,
            senha=payload.senha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = create_session_token(user["id"])
    return {
        "status": "ok",
        "utilizador": {**user, "is_demo": False},
        "token": token,
    }


@app.post("/auth/login")
def post_auth_login(
    payload: LoginUserRequest,
    request: Request = None,  # type: ignore[assignment]
) -> Dict[str, Any]:
    """Authenticate an existing user with email and password, enforcing 5 failures / 15 min per email and IP."""
    clean_email = (payload.email or "").strip().lower()
    client_ip = (
        request.client.host
        if request is not None and getattr(request, "client", None) is not None
        else "127.0.0.1"
    ) or "127.0.0.1"
    now = time.time()

    if _is_login_blocked(clean_email, client_ip, now):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas tentativas falhadas. Aguarde 15 minutos antes de tentar novamente.",
        )

    user = authenticate_user(email=clean_email, senha=payload.senha)
    if user is None:
        _record_login_failure(clean_email, client_ip, now)
        raise HTTPException(
            status_code=401,
            detail=GENERIC_LOGIN_ERROR,
        )

    LOGIN_FAILURES_BY_EMAIL.pop(clean_email, None)
    LOGIN_FAILURES_BY_IP.pop(client_ip, None)
    token = create_session_token(user["id"])
    is_guest = str(user.get("email", "")).endswith("@convidado.nonglink")
    return {
        "status": "ok",
        "utilizador": {**user, "is_demo": is_guest},
        "token": token,
    }


@app.post("/auth/demo")
def post_auth_demo() -> Dict[str, Any]:
    """Create a new isolated temporary guest account (24h session, no password) and return its session."""
    user = create_guest_user()
    token = create_session_token(user["id"], is_guest=True)
    return {
        "status": "ok",
        "utilizador": {**user, "is_demo": True, "convidado": True},
        "token": token,
    }


@app.post("/auth/logout")
@app.post("/auth/sair")
def post_auth_logout(
    payload: Optional[LogoutUserRequest] = None,
    authorization: Optional[str] = Header(default=None),
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, str]:
    """Invalidate the current session token and log out the user."""
    _ = user
    token = payload.token if payload and payload.token else None
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        delete_session_token(token)
    return {"status": "ok"}


@app.post("/auth/sair-todas", status_code=204)
def post_auth_logout_all(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Response:
    """Invalidate all sessions of the user, returning 204."""
    invalidate_all_user_sessions(str(user["id"]))
    return Response(status_code=204)


@app.get("/auth/eu")
@app.get("/auth/me")
def get_auth_me(
    authorization: Optional[str] = Header(default=None),
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Return the authenticated user profile with criado_em, convidado and expira_em for guests."""
    is_guest = str(user.get("email", "")).endswith("@convidado.nonglink")
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    expira_em = get_user_session_expiry(token) if (is_guest and token) else None

    profile_data = {
        **user,
        "is_demo": is_guest,
        "convidado": is_guest,
    }
    if is_guest and expira_em:
        profile_data["expira_em"] = expira_em

    return {
        "autenticado": True,
        "utilizador": profile_data,
    }


@app.patch("/auth/eu")
def patch_auth_me(
    payload: UpdateProfileRequest,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Update authenticated user's name (1-60 characters, no control chars)."""
    try:
        updated = update_user_name(str(user["id"]), payload.nome)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado.")

    is_guest = str(updated.get("email", "")).endswith("@convidado.nonglink")
    return {
        "status": "ok",
        "utilizador": {
            **updated,
            "is_demo": is_guest,
            "convidado": is_guest,
        },
    }


@app.post("/auth/senha")
def post_auth_change_password(
    payload: ChangePasswordRequest,
    request: Request = None,  # type: ignore[assignment]
    authorization: Optional[str] = Header(default=None),
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, str]:
    """Change user password, verifying current password and revoking all other sessions."""
    is_guest = str(user.get("email", "")).endswith("@convidado.nonglink")
    if is_guest:
        raise HTTPException(
            status_code=400,
            detail="Contas de convidado não têm palavra-passe.",
        )

    clean_email = str(user.get("email", "")).strip().lower()
    client_ip = (
        request.client.host
        if request is not None and getattr(request, "client", None) is not None
        else "127.0.0.1"
    ) or "127.0.0.1"
    now = time.time()

    if _is_login_blocked(clean_email, client_ip, now):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas tentativas falhadas. Aguarde 15 minutos antes de tentar novamente.",
        )

    current_token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""

    try:
        update_user_password(
            user_id=str(user["id"]),
            senha_actual=payload.senha_actual,
            senha_nova=payload.senha_nova,
        )
    except ValueError as exc:
        msg = str(exc)
        if "actual incorrecta" in msg or "Palavra-passe actual" in msg:
            _record_login_failure(clean_email, client_ip, now)
            raise HTTPException(
                status_code=401,
                detail=GENERIC_LOGIN_ERROR,
            ) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    # Password changed successfully -> clear failed rate limit counters and invalidate all other sessions
    LOGIN_FAILURES_BY_EMAIL.pop(clean_email, None)
    LOGIN_FAILURES_BY_IP.pop(client_ip, None)
    if current_token:
        invalidate_other_sessions(str(user["id"]), current_token)

    return {"status": "ok", "mensagem": "Palavra-passe actualizada com sucesso."}


@app.delete("/auth/eu", status_code=204)
def delete_auth_me(
    payload: Optional[DeleteAccountRequest] = None,
    request: Request = None,  # type: ignore[assignment]
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Response:
    """Delete user account and all data (conversations, messages, listings, irrigations, photos, files)."""
    user_id = str(user["id"])
    clean_email = str(user.get("email", "")).strip().lower()
    is_guest = clean_email.endswith("@convidado.nonglink")
    client_ip = (
        request.client.host
        if request is not None and getattr(request, "client", None) is not None
        else "127.0.0.1"
    ) or "127.0.0.1"
    now = time.time()

    if _is_login_blocked(clean_email, client_ip, now):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas tentativas falhadas. Aguarde 15 minutos antes de tentar novamente.",
        )

    if is_guest:
        confirmation = payload.confirmacao if payload else None
        if confirmation != "APAGAR":
            raise HTTPException(
                status_code=400,
                detail="Para apagar a conta de convidado, confirme enviando 'APAGAR'.",
            )
    else:
        password_attempt = payload.senha if payload else None
        if not password_attempt:
            _record_login_failure(clean_email, client_ip, now)
            raise HTTPException(
                status_code=401,
                detail=GENERIC_LOGIN_ERROR,
            )
        # Verify password
        full_user = get_user_by_id(user_id)
        authenticated = authenticate_user(email=clean_email, senha=password_attempt)
        if authenticated is None:
            _record_login_failure(clean_email, client_ip, now)
            raise HTTPException(
                status_code=401,
                detail=GENERIC_LOGIN_ERROR,
            )

    # Password/confirmation verified -> clear failures and delete account
    LOGIN_FAILURES_BY_EMAIL.pop(clean_email, None)
    LOGIN_FAILURES_BY_IP.pop(client_ip, None)

    photo_files = delete_user_account_and_all_data(user_id)
    for pf in photo_files:
        try:
            Path(pf).unlink(missing_ok=True)
        except Exception:
            pass

    return Response(status_code=204)


@app.get("/conversas")
def get_conversations(
    q: Optional[str] = None,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> List[Dict[str, Any]]:
    """Return conversations belonging exclusively to the authenticated user."""
    query_str = q if isinstance(q, str) else None
    return list_conversations(q=query_str, utilizador_id=str(user["id"]))


@app.delete("/conversas")
def delete_all_conversations(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Delete all conversations of the current user, along with messages and attached photo files, keeping listings and irrigations."""
    user_id = str(user["id"])
    count, photo_files = delete_all_user_conversations(user_id)
    for pf in photo_files:
        try:
            Path(pf).unlink(missing_ok=True)
        except Exception:
            pass

    # Clear memory sessions belonging to this user
    to_remove_pending = [
        sid for sid, p in PENDING_SESSIONS.items() if p.get("utilizador_id") == user_id
    ]
    for sid in to_remove_pending:
        PENDING_SESSIONS.pop(sid, None)
        SESSION_LAST_PHOTO.pop(sid, None)

    return {"status": "ok", "apagadas": count}


@app.post("/conversas")
def post_conversation(
    payload: CreateConversationRequest,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Create a new conversation in SQLite scoped to the authenticated user."""
    try:
        return create_conversation(
            titulo=payload.titulo,
            conversation_id=payload.id,
            utilizador_id=str(user["id"]),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.") from exc


@app.get("/conversas/{conversa_id}")
def get_conversation_detail(
    conversa_id: str,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Return a conversation along with all of its messages if owned by the current user."""
    user_id = str(user["id"])
    conv = get_conversation(conversa_id, utilizador_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    messages = list_messages(conversa_id)
    return {
        "id": conv["id"],
        "utilizador_id": conv.get("utilizador_id", user_id),
        "titulo": conv["titulo"],
        "criada_em": conv["criada_em"],
        "atualizada_em": conv["atualizada_em"],
        "conversa": conv,
        "mensagens": messages,
    }


@app.patch("/conversas/{conversa_id}")
def patch_conversation(
    conversa_id: str,
    payload: RenameConversationRequest,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Rename an existing conversation owned by the current user."""
    updated = update_conversation_title(
        conversa_id, payload.titulo, utilizador_id=str(user["id"])
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return updated


@app.delete("/conversas/{conversa_id}", status_code=204)
def remove_conversation(
    conversa_id: str,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Response:
    """Delete a conversation and its messages if owned by the current user."""
    deleted = delete_conversation(conversa_id, utilizador_id=str(user["id"]))
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    PENDING_SESSIONS.pop(conversa_id, None)
    SESSION_LAST_PHOTO.pop(conversa_id, None)
    return Response(status_code=204)


@app.get("/conversas/{conversa_id}/mensagens")
def get_conversation_messages(
    conversa_id: str,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> List[Dict[str, Any]]:
    """Return all messages for a conversation in chronological order."""
    conv = get_conversation(conversa_id, utilizador_id=str(user["id"]))
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return list_messages(conversa_id)


@app.get("/anuncios")
def get_listings(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> List[Dict[str, Any]]:
    """Return marketplace listings belonging exclusively to the authenticated user."""
    return list_listings(utilizador_id=str(user["id"]))


@app.get("/regas")
def get_irrigations(
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> List[Dict[str, Any]]:
    """Return scheduled irrigations belonging exclusively to the authenticated user."""
    return list_irrigations(utilizador_id=str(user["id"]))


@app.get("/foto/{foto_id}")
@app.get("/fotos/{foto_id}")
def get_uploaded_photo(
    foto_id: str,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Response:
    """Serve an uploaded photo by foto_id only to its owner (404 otherwise)."""
    try:
        path = resolve_photo_path(foto_id, utilizador_id=str(user["id"]))
    except VisionSegmentationError as exc:
        raise HTTPException(status_code=404, detail="Foto não encontrada.") from exc
    ext = path.suffix.lower()
    media_type = (
        "image/png"
        if ext == ".png"
        else "image/webp"
        if ext == ".webp"
        else "image/jpeg"
    )
    return Response(content=path.read_bytes(), media_type=media_type)


@app.post("/foto")
async def post_photo(
    sessao: str = Form(default="default"),
    imagem: Optional[UploadFile] = File(default=None),
    foto: Optional[UploadFile] = File(default=None),
    ficheiro: Optional[UploadFile] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Receive a photo via multipart/form-data, save it with a random ID, and record ownership."""
    user_id = str(user["id"])
    upload = imagem or foto or ficheiro or file
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Nenhum ficheiro de imagem enviado (use o campo 'imagem' ou 'ficheiro').",
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="O ficheiro de imagem está vazio.")

    session_id = sessao.strip() or "default"
    try:
        ensure_conversation(session_id, utilizador_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.") from exc

    ext = Path(upload.filename or "foto.jpg").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"

    foto_id = secrets.token_urlsafe(12)
    dest_path = UPLOADS_DIR / f"{foto_id}{ext}"
    dest_path.write_bytes(raw_bytes)

    insert_photo(utilizador_id=user_id, caminho=str(dest_path), foto_id=foto_id)
    SESSION_LAST_PHOTO[session_id] = foto_id

    log_action(
        "upload_foto",
        {"sessao": session_id, "foto_id": foto_id},
        "SAVED",
        {"caminho": str(dest_path), "tamanho_bytes": len(raw_bytes)},
    )

    return {
        "foto_id": foto_id,
        "sessao": session_id,
        "conversa_id": session_id,
        "caminho": str(dest_path),
        "url_imagem": f"/foto/{foto_id}",
    }


@app.post("/voz")
async def post_voice(
    sessao: str = Form(default="default"),
    idioma: str = Form(default="pt"),
    foto_id: Optional[str] = Form(default=None),
    audio: Optional[UploadFile] = File(default=None),
    ficheiro: Optional[UploadFile] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Receive an audio recording, transcribe it, persist messages, and run the agent loop."""
    user_id = str(user["id"])
    upload = audio or ficheiro or file
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Nenhum ficheiro de áudio enviado (use o campo 'audio' ou 'ficheiro').",
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="O ficheiro de áudio está vazio.")

    session_id = sessao.strip() or "default"
    if foto_id:
        if get_photo(foto_id.strip(), utilizador_id=user_id) is None:
            raise HTTPException(status_code=404, detail="Foto não encontrada.")

    ext = Path(upload.filename or "voz.wav").suffix.lower() or ".wav"
    temp_audio_name = f"voz_{uuid.uuid4().hex[:8]}{ext}"
    temp_audio_path = UPLOADS_DIR / temp_audio_name
    temp_audio_path.write_bytes(raw_bytes)

    lang_hint = idioma.strip().lower() if idioma else "pt"

    try:
        transcript_text = transcrever(str(temp_audio_path), idioma_dica=lang_hint)
    except VoiceTranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not transcript_text.strip():
        fallback_user_text = "🎤 Mensagem de voz (sem fala audível detectada)"
        fallback_agent_text = (
            "Não foi possível detectar fala audível na gravação. "
            "Por favor fale um pouco mais perto do microfone ou escreva a sua mensagem."
        )
        _record_user_message_in_db(
            conversa_id=session_id,
            user_text=fallback_user_text,
            foto_id=foto_id or SESSION_LAST_PHOTO.get(session_id),
            utilizador_id=user_id,
        )
        saved_msg = insert_message(
            conversa_id=session_id,
            papel="agente",
            texto=fallback_agent_text,
            utilizador_id=user_id,
        )
        return {
            "estado": "concluido",
            "sessao": session_id,
            "conversa_id": session_id,
            "mensagem_id": saved_msg["id"],
            "transcricao": "",
            "resposta": fallback_agent_text,
            "idioma": lang_hint,
            "accoes": [],
        }

    if foto_id:
        SESSION_LAST_PHOTO[session_id] = foto_id.strip()

    _record_user_message_in_db(
        conversa_id=session_id,
        user_text=transcript_text,
        foto_id=foto_id or SESSION_LAST_PHOTO.get(session_id),
        utilizador_id=user_id,
    )

    detected_lang = (
        lang_hint
        if lang_hint in ("pt", "fr", "en")
        else detect_language(transcript_text)
    )
    history = _build_initial_history(
        session_id=session_id,
        user_text=transcript_text,
        explicit_foto_id=foto_id,
    )

    try:
        agent_result = _continue_agent_turns(
            session_id=session_id,
            history=history,
            lang=detected_lang,
            start_turn=1,
            executed_actions=[],
            utilizador_id=user_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Erro 401: Invalid MODEL_API_KEY.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Erro 404: Endpoint '{BASE_URL}' or model '{MODEL_NAME}' not found.",
        ) from exc
    except APIStatusError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=exc.message
        ) from exc

    agent_result["transcricao"] = transcript_text
    return agent_result


@app.post("/agente")
@app.post("/agent")
def post_agent(
    payload: AgentMessageRequest,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Run the agent loop, persist messages in SQLite, and pause on any action requiring confirmation."""
    user_id = str(user["id"])
    user_text = (payload.mensagem or payload.message or "").strip()
    if not user_text:
        raise HTTPException(
            status_code=422,
            detail={
                "pt": "O campo 'mensagem' é obrigatório e não pode estar vazio.",
                "fr": "Le champ 'mensagem' est obligatoire et ne peut pas être vide.",
                "en": "The 'mensagem' field is required and cannot be empty.",
            },
        )

    session_id = (payload.conversa_id or payload.sessao or "default").strip() or "default"
    if payload.foto_id:
        if get_photo(payload.foto_id.strip(), utilizador_id=user_id) is None:
            raise HTTPException(status_code=404, detail="Foto não encontrada.")
        SESSION_LAST_PHOTO[session_id] = payload.foto_id.strip()

    active_photo_id = payload.foto_id or SESSION_LAST_PHOTO.get(session_id)
    _record_user_message_in_db(
        conversa_id=session_id,
        user_text=user_text,
        foto_id=active_photo_id,
        utilizador_id=user_id,
    )

    lang = (
        payload.idioma
        if payload.idioma in ("pt", "fr", "en")
        else detect_language(user_text)
    )

    history = _build_initial_history(
        session_id=session_id,
        user_text=user_text,
        explicit_foto_id=payload.foto_id,
    )

    try:
        return _continue_agent_turns(
            session_id=session_id,
            history=history,
            lang=lang,
            start_turn=1,
            executed_actions=[],
            utilizador_id=user_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Erro 401 / Erreur 401 / Error 401: Invalid MODEL_API_KEY.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Erro 404: Endpoint '{BASE_URL}' or model '{MODEL_NAME}' not found.",
        ) from exc
    except APIStatusError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=exc.message
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/confirmar")
def post_confirm(
    payload: ConfirmActionRequest,
    user: Dict[str, Any] = Depends(utilizador_atual),
) -> Dict[str, Any]:
    """Execute or cancel a pending action owned by the current user, and continue the agent loop."""
    user_id = str(user["id"])
    session_id = (payload.conversa_id or payload.sessao or "default").strip() or "default"
    conv = get_conversation(session_id, utilizador_id=user_id)
    pending_peek = PENDING_SESSIONS.get(session_id)
    if (
        conv is None
        or pending_peek is None
        or pending_peek.get("utilizador_id") != user_id
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "pt": f"Nenhuma acção pendente encontrada para a sessão '{session_id}'.",
                "fr": f"Aucune action en attente trouvée pour la session '{session_id}'.",
                "en": f"No pending action found for session '{session_id}'.",
            },
        )

    pending_state = PENDING_SESSIONS.pop(session_id)
    history: List[Any] = pending_state["history"]
    pending_message_id: Optional[int] = pending_state.get("pending_message_id")
    pending_call: Dict[str, Any] = pending_state["pending_call"]
    remaining_calls: List[Dict[str, Any]] = pending_state.get("remaining_calls", [])
    turn: int = int(pending_state["turn"])
    lang: str = str(pending_state["lang"])
    executed_actions: List[Dict[str, Any]] = pending_state["executed_actions"]

    tool_output = _execute_or_cancel_pending_call(
        tool_name=pending_call["ferramenta"],
        arguments=pending_call["argumentos"],
        confirmed=payload.confirmar,
        utilizador_id=user_id,
    )

    db_action_state = "confirmada" if payload.confirmar else "cancelada"
    generated_result_id = (
        str(tool_output.get("id")) if tool_output.get("id") else None
    )
    if pending_message_id is not None:
        update_message_action(
            message_id=pending_message_id,
            estado_accao=db_action_state,
            resultado_id=generated_result_id,
        )

    action_status = (
        "confirmada_e_executada" if payload.confirmar else "cancelada_pelo_utilizador"
    )
    executed_actions.append(
        {
            "ferramenta": pending_call["ferramenta"],
            "argumentos": pending_call["argumentos"],
            "estado": action_status,
            "resultado": tool_output,
        }
    )

    history.append(
        {
            "type": "function_call_output",
            "call_id": pending_call["call_id"],
            "output": json.dumps(tool_output, ensure_ascii=False),
        }
    )

    for extra_call in remaining_calls:
        if extra_call["ferramenta"] == "obter_preco":
            cultura = str(extra_call["argumentos"].get("cultura", ""))
            extra_out = get_crop_price(cultura=cultura)
            executed_actions.append(
                {
                    "ferramenta": "obter_preco",
                    "argumentos": {"cultura": cultura},
                    "estado": "executada",
                    "resultado": extra_out,
                }
            )
        elif extra_call["ferramenta"] == "analisar_foto":
            f_id = str(
                extra_call["argumentos"].get("foto_id")
                or SESSION_LAST_PHOTO.get(session_id)
                or ""
            )
            obj = str(extra_call["argumentos"].get("objecto", "tomato"))
            extra_out = analyze_photo(
                foto_id=f_id,
                objecto=obj,
                utilizador_id=user_id,
            )
            executed_actions.append(
                {
                    "ferramenta": "analisar_foto",
                    "argumentos": {"foto_id": f_id, "objecto": obj},
                    "estado": "executada",
                    "resultado": extra_out,
                }
            )
        else:
            extra_out = _execute_or_cancel_pending_call(
                tool_name=extra_call["ferramenta"],
                arguments=extra_call["argumentos"],
                confirmed=payload.confirmar,
                utilizador_id=user_id,
            )
            executed_actions.append(
                {
                    "ferramenta": extra_call["ferramenta"],
                    "argumentos": extra_call["argumentos"],
                    "estado": action_status,
                    "resultado": extra_out,
                }
            )
        history.append(
            {
                "type": "function_call_output",
                "call_id": extra_call["call_id"],
                "output": json.dumps(extra_out, ensure_ascii=False),
            }
        )

    try:
        continuation = _continue_agent_turns(
            session_id=session_id,
            history=history,
            lang=lang,
            start_turn=turn + 1,
            executed_actions=executed_actions,
            utilizador_id=user_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Erro 401 / Erreur 401 / Error 401: Invalid MODEL_API_KEY.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Erro 404: Endpoint '{BASE_URL}' or model '{MODEL_NAME}' not found.",
        ) from exc
    except APIStatusError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=exc.message
        ) from exc

    if continuation.get("estado") == "pendente":
        return continuation

    return {
        "estado": "confirmado" if payload.confirmar else "cancelado",
        "estado_accao": db_action_state,
        "sessao": session_id,
        "conversa_id": session_id,
        "confirmar": payload.confirmar,
        "accao": {
            "ferramenta": pending_call["ferramenta"],
            "argumentos": pending_call["argumentos"],
        },
        "resultado_accao": tool_output,
        "resultado_id": generated_result_id,
        "resposta": continuation.get("resposta", ""),
        "idioma": lang,
        "accoes": executed_actions,
        "analise_foto": _extract_latest_photo_analysis(executed_actions),
    }
