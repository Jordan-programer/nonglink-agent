"""FastAPI application entry point (backend/app/main.py) for the NongLink Field Agent.

Exposes the REST API for text, voice ASR (muse-voice-transcribe-1.0), vision
segmentation (sam-3.1), two-step confirmation (/confirmar), and SQLite persistence
for listings, irrigations, conversations, and messages.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
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
    create_conversation,
    delete_conversation,
    ensure_conversation,
    format_photo_attachment,
    get_conversation,
    init_db,
    insert_message,
    list_conversations,
    list_irrigations,
    list_listings,
    list_messages,
    update_conversation_title,
    update_message_action,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

PENDING_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_LAST_PHOTO: Dict[str, str] = {}
PHOTO_COUNTER = 0


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


def _record_user_message_in_db(
    conversa_id: str,
    user_text: str,
    foto_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure the conversation exists, auto-title if new, and insert the user message."""
    conv = ensure_conversation(conversa_id, titulo=_auto_title_from_text(user_text))
    if conv.get("titulo") in ("Nova conversa", "Conversa") and user_text.strip():
        update_conversation_title(conversa_id, _auto_title_from_text(user_text))

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
    )


def _continue_agent_turns(
    session_id: str,
    history: List[Any],
    lang: str,
    start_turn: int,
    executed_actions: List[Dict[str, Any]],
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
                    tool_output = analyze_photo(foto_id=foto_id, objecto=objecto)
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
                action_payload = {
                    "ferramenta": call.name,
                    "argumentos": parsed_args,
                }
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
                )

                PENDING_SESSIONS[session_id] = {
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
    tool_name: str, arguments: Dict[str, Any], confirmed: bool
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
        )
    if tool_name == "agendar_rega":
        return schedule_irrigation(
            parcela=str(arguments.get("parcela", "")),
            hora=str(arguments.get("hora", "")),
            confirmed=confirmed,
            status_label=status_label,
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
def serve_index() -> HTMLResponse:
    """Serve the frontend web interface."""
    frontend_index = FRONTEND_DIR / "index.html"
    if frontend_index.exists():
        return HTMLResponse(content=frontend_index.read_text(encoding="utf-8"))
    if ROOT_INDEX_HTML.exists():
        return HTMLResponse(content=ROOT_INDEX_HTML.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>NongLink Agent API (Dados de demonstração)</h1>"
    )


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok", "service": "nonglink-agent", "model": MODEL_NAME}


@app.get("/conversas")
def get_conversations(q: Optional[str] = Query(default=None)) -> List[Dict[str, Any]]:
    """Return all conversations ordered from most recently updated to oldest."""
    return list_conversations(q=q)


@app.post("/conversas")
def post_conversation(payload: CreateConversationRequest) -> Dict[str, Any]:
    """Create a new conversation in SQLite with a UUID text ID."""
    return create_conversation(titulo=payload.titulo, conversation_id=payload.id)


@app.get("/conversas/{conversa_id}")
def get_conversation_detail(conversa_id: str) -> Dict[str, Any]:
    """Return a conversation along with all of its messages."""
    conv = get_conversation(conversa_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    messages = list_messages(conversa_id)
    return {
        "id": conv["id"],
        "titulo": conv["titulo"],
        "criada_em": conv["criada_em"],
        "atualizada_em": conv["atualizada_em"],
        "conversa": conv,
        "mensagens": messages,
    }


@app.patch("/conversas/{conversa_id}")
def patch_conversation(
    conversa_id: str, payload: RenameConversationRequest
) -> Dict[str, Any]:
    """Rename an existing conversation."""
    updated = update_conversation_title(conversa_id, payload.titulo)
    if updated is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return updated


@app.delete("/conversas/{conversa_id}", status_code=204)
def remove_conversation(conversa_id: str) -> Response:
    """Delete a conversation and its messages."""
    delete_conversation(conversa_id)
    PENDING_SESSIONS.pop(conversa_id, None)
    SESSION_LAST_PHOTO.pop(conversa_id, None)
    return Response(status_code=204)


@app.get("/conversas/{conversa_id}/mensagens")
def get_conversation_messages(conversa_id: str) -> List[Dict[str, Any]]:
    """Return all messages for a conversation in chronological order."""
    return list_messages(conversa_id)


@app.get("/anuncios")
def get_listings() -> List[Dict[str, Any]]:
    """Return all marketplace listings from the SQLite database (nonglink.db)."""
    return list_listings()


@app.get("/regas")
def get_irrigations() -> List[Dict[str, Any]]:
    """Return all scheduled irrigations from the SQLite database (nonglink.db)."""
    return list_irrigations()


@app.get("/foto/{foto_id}")
@app.get("/fotos/{foto_id}")
def get_uploaded_photo(foto_id: str) -> FileResponse:
    """Serve an uploaded or sample photo by foto_id (supports /foto/{id} and /fotos/{id})."""
    try:
        path = resolve_photo_path(foto_id)
    except VisionSegmentationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@app.post("/foto")
async def post_photo(
    sessao: str = Form(default="default"),
    imagem: Optional[UploadFile] = File(default=None),
    foto: Optional[UploadFile] = File(default=None),
    ficheiro: Optional[UploadFile] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> Dict[str, Any]:
    """Receive a photo via multipart/form-data, save it in UPLOADS_DIR, and return foto_id."""
    global PHOTO_COUNTER
    upload = imagem or foto or ficheiro or file
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Nenhum ficheiro de imagem enviado (use o campo 'imagem' ou 'ficheiro').",
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="O ficheiro de imagem está vazio.")

    ext = Path(upload.filename or "foto.jpg").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"

    PHOTO_COUNTER += 1
    foto_id = f"FOTO-{PHOTO_COUNTER:04d}{ext}"
    dest_path = UPLOADS_DIR / foto_id
    dest_path.write_bytes(raw_bytes)

    session_id = sessao.strip() or "default"
    SESSION_LAST_PHOTO[session_id] = foto_id
    ensure_conversation(session_id)

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
) -> Dict[str, Any]:
    """Receive an audio recording, transcribe it, persist messages, and run the agent loop."""
    upload = audio or ficheiro or file
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Nenhum ficheiro de áudio enviado (use o campo 'audio' ou 'ficheiro').",
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="O ficheiro de áudio está vazio.")

    ext = Path(upload.filename or "voz.wav").suffix.lower() or ".wav"
    temp_audio_name = f"voz_{uuid.uuid4().hex[:8]}{ext}"
    temp_audio_path = UPLOADS_DIR / temp_audio_name
    temp_audio_path.write_bytes(raw_bytes)

    session_id = sessao.strip() or "default"
    lang_hint = idioma.strip().lower() if idioma else "pt"

    try:
        transcript_text = transcrever(str(temp_audio_path), idioma_dica=lang_hint)
    except VoiceTranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not transcript_text.strip():
        return {
            "estado": "concluido",
            "sessao": session_id,
            "conversa_id": session_id,
            "transcricao": "",
            "resposta": "Não foi possível detectar fala audível na gravação.",
            "idioma": lang_hint,
            "accoes": [],
        }

    if foto_id:
        SESSION_LAST_PHOTO[session_id] = foto_id.strip()

    _record_user_message_in_db(
        conversa_id=session_id,
        user_text=transcript_text,
        foto_id=foto_id or SESSION_LAST_PHOTO.get(session_id),
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
def post_agent(payload: AgentMessageRequest) -> Dict[str, Any]:
    """Run the agent loop, persist messages in SQLite, and pause on any action requiring confirmation."""
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
        SESSION_LAST_PHOTO[session_id] = payload.foto_id.strip()

    _record_user_message_in_db(
        conversa_id=session_id,
        user_text=user_text,
        foto_id=payload.foto_id,
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
def post_confirm(payload: ConfirmActionRequest) -> Dict[str, Any]:
    """Execute or cancel a pending action, update SQLite message state, and continue the agent loop."""
    session_id = (payload.conversa_id or payload.sessao or "default").strip() or "default"
    pending_state = PENDING_SESSIONS.pop(session_id, None)
    if pending_state is None:
        raise HTTPException(
            status_code=404,
            detail={
                "pt": f"Nenhuma acção pendente encontrada para a sessão '{session_id}'.",
                "fr": f"Aucune action en attente trouvée pour la session '{session_id}'.",
                "en": f"No pending action found for session '{session_id}'.",
            },
        )

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
            extra_out = analyze_photo(foto_id=f_id, objecto=obj)
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
