"""NongLink Field Agent core module (app/agent.py) for farmers in Angola, DRC, and Congo.

Runs the multi-turn agent loop using Meta's Responses API (muse-spark-1.3) with
tool calling (obter_preco, criar_anuncio, agendar_rega, analisar_foto),
encrypted reasoning preservation, human confirmation, and audit logging.
"""

from datetime import datetime, timezone
import json
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
from openai import APIStatusError, AuthenticationError, NotFoundError, OpenAI

from app.config import (
    LOG_FILE_PATH,
    MAX_AGENT_TURNS,
    META_BASE_URL,
    REASONING_MODEL,
    get_model_api_key,
)
from app.db import (
    get_crop_price_from_db,
    init_db,
    insert_irrigation,
    insert_listing,
)
from app.visao import resolve_photo_path, segmentar

BASE_URL = META_BASE_URL
MODEL_NAME = REASONING_MODEL
MAX_TURNS = MAX_AGENT_TURNS

FICTIONAL_CROP_PRICES_KZ: Dict[str, int] = {
    "tomate": 850,
    "tomates": 850,
    "tomato": 850,
    "tomatoes": 850,
    "mandioca": 450,
    "manioc": 450,
    "cassava": 450,
    "milho": 600,
    "mais": 600,
    "maïs": 600,
    "maize": 600,
    "corn": 600,
    "feijao": 1200,
    "feijão": 1200,
    "haricot": 1200,
    "haricots": 1200,
    "bean": 1200,
    "beans": 1200,
    "batata": 750,
    "batata-doce": 550,
    "pomme de terre": 750,
    "patate douce": 550,
    "potato": 750,
    "sweet potato": 550,
    "cebola": 950,
    "oignon": 950,
    "onion": 950,
    "banana": 500,
    "banane": 500,
    "plantain": 550,
    "cafe": 2100,
    "café": 2100,
    "coffee": 2100,
}

DEFAULT_CROP_PRICE_KZ = 700

SYSTEM_INSTRUCTIONS = """You are the NongLink Field Agent (Agente de Campo NongLink / Agent de Terrain NongLink), an agricultural assistant for smallholder farmers in Angola, DRC, and the Republic of the Congo.

Strict Mandatory Rules:
1. Language: ALWAYS reply in the exact same language used by the user: Portuguese (PT), French (FR), or English (EN). Default to Portuguese if unsure.
2. No Hallucinated Numbers: NEVER invent statistics, percentages, yields, or prices. Only state crop prices obtained directly from calling the `obter_preco` tool, and ALWAYS explicitly mention that these prices are demonstration values ("valores de demonstração" / "valeurs de démonstration" / "demonstration values").
3. Ask When Information Is Missing: If any required piece of information is missing to perform an action — such as crop (`cultura`), quantity in kg (`quantidade_kg`), plot (`parcela`), or time (`hora`) — DO NOT assume, guess, or invent default values. Ask the user clearly for the missing data instead of calling the tool.
4. Photo Analysis (`analisar_foto`) & Weight Estimation Rule:
   - When a photo (`foto_id`) is provided or mentioned, call `analisar_foto(foto_id, objecto)` to count and segment the crop using `sam-3.1`.
   - NEVER claim crop quality, freshness, ripeness, disease, pests, or phytosanitary diagnosis from the photo. ONLY report what the segmentation objectively measured: instance count (`contagem`), bounding boxes (`caixas`), and mask coverage percentage (`cobertura_percentagem`).
   - Do NOT convert the instance count into kilograms silently on your own: either ask the user for the average weight per unit (or crate) OR explicitly state that you are using a demonstration average weight estimate (e.g., 0.15 kg per tomato as a demonstration estimate) and show the full arithmetic calculation (`contagem × peso_medio_kg = quantidade_kg`) before proposing `criar_anuncio`.
5. Price Lookup Before Listing: When the user wants to publish an ad (`criar_anuncio`) and the crop and quantity in kg are known (or calculated via the shown demonstration estimate), call `obter_preco` first to get the demonstration price in Kz/kg, and then call `criar_anuncio(cultura, quantidade_kg, preco_kz_kg)`.
6. Mandatory User Confirmation via Tool Call: `criar_anuncio` and `agendar_rega` never execute without user confirmation because the NongLink runtime automatically intercepts your tool call and asks the user to confirm ("s" in terminal or Confirm button in web UI / `/confirmar`). Always call `criar_anuncio` or `agendar_rega` to propose the action and never claim it was executed until the tool output confirms `"status": "executed"`.
"""

UI_STRINGS: Dict[str, Dict[str, str]] = {
    "pt": {
        "confirm_ad": (
            "\n[CONFIRMAÇÃO] Deseja publicar o anúncio de {quantidade_kg} kg de "
            "'{cultura}' a {preco_kz_kg} Kz/kg (Total: {total_kz} Kz)? "
            "Digite 's' para confirmar (s/n): "
        ),
        "confirm_irrigation": (
            "\n[CONFIRMAÇÃO] Deseja agendar rega na parcela '{parcela}' às '{hora}'? "
            "Digite 's' para confirmar (s/n): "
        ),
        "action_cancelled": "Acção cancelada pelo utilizador no terminal.",
        "prompt_input": "Agricultor (PT/FR/EN): ",
    },
    "fr": {
        "confirm_ad": (
            "\n[CONFIRMATION] Voulez-vous publier l'annonce pour {quantidade_kg} kg de "
            "'{cultura}' à {preco_kz_kg} Kz/kg (Total : {total_kz} Kz) ? "
            "Tapez 's' ou 'o' pour confirmer (s/o/n) : "
        ),
        "confirm_irrigation": (
            "\n[CONFIRMATION] Voulez-vous planifier l'irrigation sur la parcelle '{parcela}' à '{hora}' ? "
            "Tapez 's' ou 'o' pour confirmer (s/o/n) : "
        ),
        "action_cancelled": "Action annulée par l'utilisateur dans le terminal.",
        "prompt_input": "Agriculteur (PT/FR/EN) : ",
    },
    "en": {
        "confirm_ad": (
            "\n[CONFIRMATION] Do you want to publish the listing for {quantidade_kg} kg of "
            "'{cultura}' at {preco_kz_kg} Kz/kg (Total: {total_kz} Kz)? "
            "Type 's' or 'y' to confirm (s/y/n): "
        ),
        "confirm_irrigation": (
            "\n[CONFIRMATION] Do you want to schedule irrigation on plot '{parcela}' at '{hora}'? "
            "Type 's' or 'y' to confirm (s/y/n): "
        ),
        "action_cancelled": "Action cancelled by the user in the terminal.",
        "prompt_input": "Farmer (PT/FR/EN): ",
    },
}

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "obter_preco",
        "description": (
            "PT: Obtém o preço fictício de mercado de uma cultura agrícola em Kz/kg. | "
            "FR: Obtient le prix fictif du marché d'une culture agricole en Kz/kg. | "
            "EN: Gets the fictional market price of an agricultural crop in Kz/kg."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cultura": {
                    "type": "string",
                    "description": "Crop name in PT, FR, or EN (e.g., 'tomate', 'manioc', 'maize').",
                }
            },
            "required": ["cultura"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "criar_anuncio",
        "description": (
            "PT: Publica um anúncio de venda de produção agrícola na plataforma NongLink. | "
            "FR: Publie une annonce de vente de récolte sur la plateforme NongLink. | "
            "EN: Publishes a crop sale listing on the NongLink marketplace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cultura": {
                    "type": "string",
                    "description": "Crop name (e.g., 'tomate', 'milho', 'manioc').",
                },
                "quantidade_kg": {
                    "type": "number",
                    "description": "Quantity in kilograms (kg).",
                },
                "preco_kz_kg": {
                    "type": "number",
                    "description": "Unit price in Kwanza per kilogram (Kz/kg).",
                },
            },
            "required": ["cultura", "quantidade_kg", "preco_kz_kg"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "agendar_rega",
        "description": (
            "PT: Agenda uma sessão de rega para uma parcela agrícola numa hora específica. | "
            "FR: Planifie une session d'irrigation pour une parcelle à une heure donnée. | "
            "EN: Schedules an irrigation session for a farm plot at a specific time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parcela": {
                    "type": "string",
                    "description": "Plot identifier or name (e.g., 'Parcela Norte', 'Parcelle A', 'Plot 1').",
                },
                "hora": {
                    "type": "string",
                    "description": "Scheduled time (e.g., '06:00', '18:30').",
                },
            },
            "required": ["parcela", "hora"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "analisar_foto",
        "description": (
            "PT: Analisa uma foto agrícola com o modelo sam-3.1 para contar instâncias, devolver caixas (boxes) e percentagem de cobertura. | "
            "FR: Analyse une photo agricole avec sam-3.1 pour compter les instances, renvoyer les boîtes et le pourcentage de couverture. | "
            "EN: Analyzes a farm photo using sam-3.1 to count instances, return bounding boxes, and mask coverage percentage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "foto_id": {
                    "type": "string",
                    "description": "Photo identifier or filename (e.g., 'FOTO-0001.jpg' or 'tomates.jpg').",
                },
                "objecto": {
                    "type": "string",
                    "description": "Target object/crop to segment (e.g., 'tomato', 'tomate', 'mandioca').",
                },
            },
            "required": ["foto_id", "objecto"],
            "additionalProperties": False,
        },
    },
]


def detect_language(text: str) -> str:
    """Detect whether the user message is in Portuguese, French, or English."""
    lowered = text.lower()
    fr_markers = ("j'ai", "combien", "annonce", "parcelle", "arroser", "irrigation", "prix", "bonjour")
    en_markers = ("i have", "how much", "publish", "schedule", "plot", "price", "tomato", "hello")
    if any(marker in lowered for marker in fr_markers):
        return "fr"
    if any(marker in lowered for marker in en_markers):
        return "en"
    return "pt"


def log_action(tool_name: str, args: Dict[str, Any], status: str, details: Dict[str, Any]) -> None:
    """Append an action record to LOG_FILE_PATH in JSON Lines format."""
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "timestamp": timestamp,
        "tool": tool_name,
        "arguments": args,
        "status": status,
        "details": details,
    }
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def get_crop_price(cultura: str) -> Dict[str, Any]:
    """Return fictional crop price in Kz/kg from SQLite or fallback dict and log the lookup."""
    init_db()
    db_row = get_crop_price_from_db(cultura)
    if db_row is not None:
        price_kz = int(db_row["preco_kz_kg"])
        note = str(db_row["observacao"])
    else:
        normalized = cultura.strip().lower()
        price_kz = FICTIONAL_CROP_PRICES_KZ.get(normalized, DEFAULT_CROP_PRICE_KZ)
        note = "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data"

    result = {
        "status": "executed",
        "cultura": cultura,
        "preco_kz_kg": price_kz,
        "moeda": "Kz/kg",
        "nota": note,
    }
    log_action("obter_preco", {"cultura": cultura}, "EXECUTED", result)
    return result


def create_listing(
    cultura: str,
    quantidade_kg: float,
    preco_kz_kg: float,
    confirmed: bool = True,
    status_label: str = "EXECUTED",
) -> Dict[str, Any]:
    """Save a marketplace listing to SQLite 'anuncios' if confirmed, and return the real ID."""
    total_kz = round(float(quantidade_kg) * float(preco_kz_kg), 2)
    args = {
        "cultura": cultura,
        "quantidade_kg": quantidade_kg,
        "preco_kz_kg": preco_kz_kg,
    }
    if not confirmed:
        result = {
            "status": status_label.lower(),
            "cultura": cultura,
            "quantidade_kg": quantidade_kg,
            "preco_kz_kg": preco_kz_kg,
            "valor_total_kz": total_kz,
            "mensagem": {
                "pt": "Anúncio não publicado (aguarda confirmação ou cancelado pelo utilizador).",
                "fr": "Annonce non publiée (en attente de confirmation ou annulée par l'utilisateur).",
                "en": "Listing not published (awaiting confirmation or cancelled by user).",
            },
        }
        log_action("criar_anuncio", args, status_label, result)
        return result

    db_record = insert_listing(
        cultura=cultura,
        quantidade_kg=float(quantidade_kg),
        preco_kz_kg=float(preco_kz_kg),
    )
    real_id = db_record["id"]
    result = {
        "status": "executed",
        "id": real_id,
        "anuncio_id": real_id,
        "cultura": cultura,
        "quantidade_kg": float(quantidade_kg),
        "preco_kz_kg": float(preco_kz_kg),
        "valor_total_kz": total_kz,
        "criado_em": db_record["criado_em"],
        "mensagem": {
            "pt": f"Anúncio {real_id} gravado na base de dados: {quantidade_kg} kg de {cultura} a {preco_kz_kg} Kz/kg (Total: {total_kz} Kz).",
            "fr": f"Annonce {real_id} enregistrée en base de données : {quantidade_kg} kg de {cultura} à {preco_kz_kg} Kz/kg (Total : {total_kz} Kz).",
            "en": f"Listing {real_id} saved to database: {quantidade_kg} kg of {cultura} at {preco_kz_kg} Kz/kg (Total: {total_kz} Kz).",
        },
    }
    log_action("criar_anuncio", args, "EXECUTED", result)
    return result


def schedule_irrigation(
    parcela: str,
    hora: str,
    confirmed: bool = True,
    status_label: str = "EXECUTED",
) -> Dict[str, Any]:
    """Save an irrigation schedule to SQLite 'regas' if confirmed, and return the real ID."""
    args = {"parcela": parcela, "hora": hora}
    if not confirmed:
        result = {
            "status": status_label.lower(),
            "parcela": parcela,
            "hora": hora,
            "mensagem": {
                "pt": "Rega não agendada (aguarda confirmação ou cancelada pelo utilizador).",
                "fr": "Irrigation non planifiée (en attente de confirmation ou annulée par l'utilisateur).",
                "en": "Irrigation not scheduled (awaiting confirmation or cancelled by user).",
            },
        }
        log_action("agendar_rega", args, status_label, result)
        return result

    db_record = insert_irrigation(parcela=parcela, hora=hora)
    real_id = db_record["id"]
    result = {
        "status": "executed",
        "id": real_id,
        "agendamento_id": real_id,
        "parcela": parcela,
        "hora": hora,
        "criado_em": db_record["criado_em"],
        "mensagem": {
            "pt": f"Rega {real_id} gravada na base de dados para a parcela '{parcela}' às {hora}.",
            "fr": f"Irrigation {real_id} enregistrée en base de données pour la parcelle '{parcela}' à {hora}.",
            "en": f"Irrigation {real_id} saved to database for plot '{parcela}' at {hora}.",
        },
    }
    log_action("agendar_rega", args, "EXECUTED", result)
    return result


def analyze_photo(foto_id: str, objecto: str) -> Dict[str, Any]:
    """Segment an image using visao.segmentar (sam-3.1) and return count, coverage, and boxes."""
    resolved_path = resolve_photo_path(foto_id)
    seg_result = segmentar(str(resolved_path), prompt_texto=objecto)

    demo_unit_weight_kg = 0.15
    estimated_total_kg = round(seg_result["contagem"] * demo_unit_weight_kg, 2)

    result = {
        "status": "executed",
        "foto_id": foto_id,
        "caminho_imagem": str(resolved_path),
        "objecto": objecto,
        "contagem": seg_result["contagem"],
        "cobertura": seg_result["cobertura_percentagem"],
        "cobertura_percentagem": seg_result["cobertura_percentagem"],
        "caixas": seg_result["caixas"],
        "largura_imagem": seg_result["largura_imagem"],
        "altura_imagem": seg_result["altura_imagem"],
        "imagem_saida": seg_result["imagem_saida"],
        "peso_unitario_demo_kg": demo_unit_weight_kg,
        "quantidade_estimada_demo_kg": estimated_total_kg,
        "conta_demonstracao": (
            f"{seg_result['contagem']} unidades × {demo_unit_weight_kg} kg/unidade (estimativa de demonstração) = {estimated_total_kg} kg"
        ),
        "observacao": seg_result["observacao"],
    }
    log_action(
        "analisar_foto",
        {"foto_id": foto_id, "objecto": objecto},
        "EXECUTED",
        result,
    )
    return result


obter_preco = get_crop_price
criar_anuncio = create_listing
agendar_rega = schedule_irrigation
analisar_foto = analyze_photo


def build_action_description(
    tool_name: str, arguments: Dict[str, Any], lang: str = "pt"
) -> str:
    """Build a human-readable multilingual description for a pending action."""
    if tool_name == "criar_anuncio":
        cultura = arguments.get("cultura", "")
        quantidade_kg = float(arguments.get("quantidade_kg", 0))
        preco_kz_kg = float(arguments.get("preco_kz_kg", 0))
        total_kz = round(quantidade_kg * preco_kz_kg, 2)
        descriptions = {
            "pt": (
                f"Publicar anúncio de {quantidade_kg:g} kg de '{cultura}' a "
                f"{preco_kz_kg:g} Kz/kg (Total: {total_kz:g} Kz — valor de demonstração)."
            ),
            "fr": (
                f"Publier l'annonce pour {quantidade_kg:g} kg de '{cultura}' à "
                f"{preco_kz_kg:g} Kz/kg (Total : {total_kz:g} Kz — valeur de démonstration)."
            ),
            "en": (
                f"Publish listing for {quantidade_kg:g} kg of '{cultura}' at "
                f"{preco_kz_kg:g} Kz/kg (Total: {total_kz:g} Kz — demonstration value)."
            ),
        }
        return descriptions.get(lang, descriptions["pt"])

    if tool_name == "agendar_rega":
        parcela = arguments.get("parcela", "")
        hora = arguments.get("hora", "")
        descriptions = {
            "pt": f"Agendar rega na parcela '{parcela}' às {hora} (dados de demonstração).",
            "fr": f"Planifier l'irrigation sur la parcelle '{parcela}' à {hora} (données de démonstration).",
            "en": f"Schedule irrigation on plot '{parcela}' at {hora} (demonstration data).",
        }
        return descriptions.get(lang, descriptions["pt"])

    return f"{tool_name}({json.dumps(arguments, ensure_ascii=False)})"


def ask_terminal_confirmation(prompt_text: str) -> bool:
    """Prompt the user in the terminal and return True if confirmed with 's' (or 'o'/'y')."""
    try:
        answer = input(prompt_text).strip().lower()
    except EOFError:
        return False
    return answer in ("s", "sim", "o", "oui", "y", "yes")


def create_meta_client() -> OpenAI:
    """Create and return an OpenAI client configured for the Meta Model API."""
    return OpenAI(
        base_url=META_BASE_URL,
        api_key=get_model_api_key(),
    )


def execute_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    lang: str = "pt",
    interactive: bool = True,
    confirm_callback: Optional[Callable[[str], bool]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Execute a tool call with human-in-the-loop confirmation for side-effecting tools."""
    confirmation_fn = confirm_callback or ask_terminal_confirmation
    strings = UI_STRINGS.get(lang, UI_STRINGS["pt"])

    if tool_name == "obter_preco":
        cultura = str(arguments.get("cultura", ""))
        result = get_crop_price(cultura=cultura)
        action_record = {
            "ferramenta": "obter_preco",
            "argumentos": {"cultura": cultura},
            "requer_confirmacao": False,
            "estado": "executada",
            "resultado": result,
        }
        return result, action_record

    if tool_name == "analisar_foto":
        foto_id = str(arguments.get("foto_id", ""))
        objecto = str(arguments.get("objecto", "tomato"))
        result = analyze_photo(foto_id=foto_id, objecto=objecto)
        action_record = {
            "ferramenta": "analisar_foto",
            "argumentos": {"foto_id": foto_id, "objecto": objecto},
            "requer_confirmacao": False,
            "estado": "executada",
            "resultado": result,
        }
        return result, action_record

    if tool_name == "criar_anuncio":
        cultura = str(arguments.get("cultura", ""))
        quantidade_kg = float(arguments.get("quantidade_kg", 0))
        preco_kz_kg = float(arguments.get("preco_kz_kg", 0))
        total_kz = round(quantidade_kg * preco_kz_kg, 2)

        if interactive:
            prompt_msg = strings["confirm_ad"].format(
                quantidade_kg=quantidade_kg,
                cultura=cultura,
                preco_kz_kg=preco_kz_kg,
                total_kz=total_kz,
            )
            is_confirmed = confirmation_fn(prompt_msg)
            status_label = "EXECUTED" if is_confirmed else "CANCELLED_BY_USER"
            result = create_listing(
                cultura=cultura,
                quantidade_kg=quantidade_kg,
                preco_kz_kg=preco_kz_kg,
                confirmed=is_confirmed,
                status_label=status_label,
            )
            estado = "confirmada_e_executada" if is_confirmed else "cancelada_pelo_utilizador"
        else:
            result = create_listing(
                cultura=cultura,
                quantidade_kg=quantidade_kg,
                preco_kz_kg=preco_kz_kg,
                confirmed=False,
                status_label="PROPOSED_PENDING_CONFIRMATION",
            )
            estado = "proposta_aguarda_confirmacao"

        action_record = {
            "ferramenta": "criar_anuncio",
            "argumentos": {
                "cultura": cultura,
                "quantidade_kg": quantidade_kg,
                "preco_kz_kg": preco_kz_kg,
            },
            "requer_confirmacao": True,
            "estado": estado,
            "resultado": result,
        }
        return result, action_record

    if tool_name == "agendar_rega":
        parcela = str(arguments.get("parcela", ""))
        hora = str(arguments.get("hora", ""))

        if interactive:
            prompt_msg = strings["confirm_irrigation"].format(parcela=parcela, hora=hora)
            is_confirmed = confirmation_fn(prompt_msg)
            status_label = "EXECUTED" if is_confirmed else "CANCELLED_BY_USER"
            result = schedule_irrigation(
                parcela=parcela,
                hora=hora,
                confirmed=is_confirmed,
                status_label=status_label,
            )
            estado = "confirmada_e_executada" if is_confirmed else "cancelada_pelo_utilizador"
        else:
            result = schedule_irrigation(
                parcela=parcela,
                hora=hora,
                confirmed=False,
                status_label="PROPOSED_PENDING_CONFIRMATION",
            )
            estado = "proposta_aguarda_confirmacao"

        action_record = {
            "ferramenta": "agendar_rega",
            "argumentos": {"parcela": parcela, "hora": hora},
            "requer_confirmacao": True,
            "estado": estado,
            "resultado": result,
        }
        return result, action_record

    unknown_result = {"status": "error", "message": f"Unknown tool: {tool_name}"}
    log_action(tool_name, arguments, "ERROR_UNKNOWN_TOOL", unknown_result)
    return unknown_result, {
        "ferramenta": tool_name,
        "argumentos": arguments,
        "requer_confirmacao": False,
        "estado": "erro",
        "resultado": unknown_result,
    }


def run_agent_loop(
    user_message: str,
    lang: Optional[str] = None,
    interactive: bool = True,
    confirm_callback: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    """Run the multi-turn agent loop (maximum 5 turns) using Meta's Responses API."""
    detected_lang = lang if lang in ("pt", "fr", "en") else detect_language(user_message)
    client = create_meta_client()

    history: List[Any] = [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": user_message},
    ]
    recorded_actions: List[Dict[str, Any]] = []
    final_text = ""

    for turn in range(1, MAX_TURNS + 1):
        response = client.responses.create(
            model=MODEL_NAME,
            input=history,
            tools=TOOLS,
            include=["reasoning.encrypted_content"],
        )

        # Preserve encrypted reasoning tokens across turns
        history.extend(response.output)

        function_calls = [
            item for item in response.output if getattr(item, "type", None) == "function_call"
        ]

        if not function_calls:
            final_text = response.output_text or ""
            return {
                "resposta": final_text,
                "idioma": detected_lang,
                "voltas": turn,
                "accoes": recorded_actions,
            }

        for call in function_calls:
            try:
                parsed_args = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                parsed_args = {}

            tool_output, action_record = execute_tool_call(
                tool_name=call.name,
                arguments=parsed_args,
                lang=detected_lang,
                interactive=interactive,
                confirm_callback=confirm_callback,
            )
            recorded_actions.append(action_record)

            history.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(tool_output, ensure_ascii=False),
                }
            )

        final_text = response.output_text or ""

    return {
        "resposta": final_text,
        "idioma": detected_lang,
        "voltas": MAX_TURNS,
        "accoes": recorded_actions,
    }


def main() -> None:
    """Entry point for running the NongLink field agent in the terminal."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    auto_confirm = False
    raw_args = sys.argv[1:]
    if "--auto-confirm" in raw_args:
        auto_confirm = True
        raw_args = [arg for arg in raw_args if arg != "--auto-confirm"]

    if raw_args:
        user_query = " ".join(raw_args)
    else:
        try:
            user_query = input(UI_STRINGS["pt"]["prompt_input"]).strip()
        except EOFError:
            return

    if not user_query:
        return

    def auto_confirm_callback(prompt_text: str) -> bool:
        print(f"{prompt_text}s")
        return True

    try:
        result = run_agent_loop(
            user_message=user_query,
            interactive=True,
            confirm_callback=auto_confirm_callback if auto_confirm else None,
        )
        print("\n--- NongLink Agent ---")
        print(result["resposta"])
    except AuthenticationError:
        print(
            "Erro 401 / Erreur 401 / Error 401: Invalid MODEL_API_KEY in .env.",
            file=sys.stderr,
        )
        sys.exit(1)
    except NotFoundError:
        print(
            f"Erro 404 / Erreur 404 / Error 404: Endpoint '{BASE_URL}' or model '{MODEL_NAME}' not found.",
            file=sys.stderr,
        )
        sys.exit(1)
    except APIStatusError as exc:
        print(
            f"API Error (status {exc.status_code}): {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
