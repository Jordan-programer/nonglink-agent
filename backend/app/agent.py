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
from app.guardas import (
    extrair_numeros_autorizados,
    gerar_resposta_segura_sem_alucinacoes,
    validar_anuncio,
    validar_rega,
    verificar_numeros_resposta,
)
from app.visao import resolve_photo_path, segmentar

BASE_URL = META_BASE_URL
MODEL_NAME = REASONING_MODEL
MAX_TURNS = MAX_AGENT_TURNS

FICTIONAL_CROP_PRICES_KZ: Dict[str, int] = {}

DEFAULT_CROP_PRICE_KZ = 0

SYSTEM_INSTRUCTIONS = """You are the NongLink Field Agent (Agente de Campo NongLink / Agent de Terrain NongLink), an agricultural assistant for smallholder farmers in Angola, DRC, and the Republic of the Congo.

Operational Scope:
- Market prices & reference ranges (`obter_preco`)
- Crop sale listings (`criar_anuncio`, `actualizar_anuncio`, `retirar_anuncio`)
- Irrigation management (`agendar_rega`, `cancelar_rega`)
- Farm plots & satellite soil study (`listar_parcelas`, `estudo_campo`)
- Sales tracking & financial summaries (`listar_vendas`, `resumo_vendas`, `tendencias_vendas`)
- Farm photo object segmentation (`analisar_foto`)

Strict Mandatory Rules:
1. Language: ALWAYS reply in the exact same language used by the user: Portuguese (PT), French (FR), or English (EN). Default to Portuguese if unsure.
2. No Hallucinated Numbers & Reference Price Ranges:
   - NEVER invent prices, statistics, or yields.
   - When stating crop prices obtained from `obter_preco`, ALWAYS state the full interval (`[preco_min] a [preco_max] [unidade]`), specify the type (`tipo`: produtor or retalho), and ALWAYS state: 'referência de demonstração, [local], [data]' (or localized in FR/EN).
   - NEVER provide a single number as if it were the exact 'price of the day' or market fixed price.
   - If the user profile lacks a registered region (sem region_id), state that you cannot suggest regional prices and ask for their province/region.
3. Disambiguation & Missing Information:
   - Identify farm plots and products by name. If multiple matching plots or products exist, ask the user to clarify which one they mean.
   - If any required piece of information is missing to perform an action — such as crop (`cultura`), quantity in kg (`quantidade_kg`), plot (`parcela`), product (`produto`), or time (`hora`) — DO NOT assume, guess, or invent default values. Ask the user clearly for the missing data instead of calling the tool.
4. Photo Analysis (`analisar_foto`) & Weight Estimation Rule:
   - When a photo (`foto_id`) is provided or mentioned, call `analisar_foto(foto_id, objecto)` to count and segment the crop using `sam-3.1`.
   - NEVER claim crop quality, freshness, ripeness, disease, pests, or phytosanitary diagnosis from the photo. ONLY report what the segmentation objectively measured: instance count (`contagem`), bounding boxes (`caixas`), and mask coverage percentage (`cobertura_percentagem`).
   - If the photo analysis returns 0 items (contagem = 0) or lacks detections, NEVER propose `criar_anuncio` based on that photo; you MUST ask the user for a clearer/closer photo or to provide the harvest weight directly.
   - Do NOT convert the instance count into kilograms silently on your own: either ask the user for the average weight per unit (or crate) OR explicitly state that you are using a demonstration average weight estimate (e.g., 0.15 kg per tomato as a demonstration estimate) and show the full arithmetic calculation (`contagem × peso_medio_kg = quantidade_kg`) before proposing `criar_anuncio`.
5. Satellite Soil Study (`estudo_campo`) & Recommendations:
   - Only call `estudo_campo(parcela, forcar_nova_analise=True)` when the user explicitly requests a NEW satellite analysis. Otherwise, request standard reading (`forcar_nova_analise=False`).
   - Only cite numbers that come strictly from the tool output (NDVI, NDMI, NDTI, salinidade, nebulosidade, datas).
   - Present irrigation, planting, and soil treatment recommendations strictly as "recomendações do NongLink" and DO NOT invent or alter recommendations.
   - ALWAYS remind the farmer that the satellite reading depends on the image acquisition date and cloud cover (`cloud_cover_pct`).
   - NEVER make phytosanitary disease diagnoses or promise specific crop yields based on satellite readings.
   - If the plot lacks a boundary polygon (HTTP 400), explain clearly that the plot boundary must be drawn on the map at agrilink.store; NEVER ask or receive polygons/coordinates via chat.
6. Sales Tracking & Order Status:
   - `listar_vendas`, `resumo_vendas`, and `tendencias_vendas` are strictly read-only.
   - If the user asks to alter the status of a sales order (e.g. approve or mark completed), explain that changing order status is not available to the farmer.
7. Listings Management & Retirar Anúncio:
   - `actualizar_anuncio` allows updating unit price or available quantity.
   - `retirar_anuncio` marks the listing as out of stock (quantity_available = 0) and NEVER permanently deletes the ad. Always specify in confirmation that "ficará esgotado, mas não será apagado".
8. Mandatory User Confirmation via Tool Call:
   - `criar_anuncio`, `actualizar_anuncio`, `retirar_anuncio`, `agendar_rega`, and `cancelar_rega` never execute without user confirmation because the NongLink runtime automatically intercepts your tool call and asks the user to confirm via confirmation ticket. Always call the tool to propose the action and never claim it was executed until the tool output confirms `"status": "executed"`.
9. Farmer Desired Price & Advisory Price Suggestions:
   - When the farmer explicitly indicates the price they wish to sell at (e.g. 'quero vender a 800 Kz/kg', 'tenho tomate a 800', etc.), ALWAYS RESPECT the farmer's stated price and pass that exact price to `criar_anuncio`.
   - Reference prices from `obter_preco` are purely advisory market suggestions (sugestões indicativas) for the farmer's orientation. NEVER override or ignore the farmer's stated price, and NEVER refuse or cancel the farmer's request because they chose their own price.
   - If the farmer has NOT specified a price, consult `obter_preco` and present the suggested reference interval to the farmer as a helpful recommendation, asking if they would like to proceed with that price.
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
            "PT: Obtém o intervalo de preços de referência de uma cultura agrícola (preco_min, preco_max, tipo [produtor/retalho], unidade, local, data, fonte). | "
            "FR: Obtient la fourchette de prix de référence d'une culture agricole (preco_min, preco_max, type [produtor/retalho], unité, lieu, date, source). | "
            "EN: Gets the reference price range for an agricultural crop (preco_min, preco_max, type [produtor/retalho], unit, location, date, source)."
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
                "duracao_minutos": {
                    "type": "integer",
                    "description": "Duration in minutes (1 to 600). Defaults to standard duration if omitted.",
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
    {
        "type": "function",
        "name": "listar_parcelas",
        "description": (
            "PT: Lista as parcelas e lavras registadas do agricultor autenticado. | "
            "FR: Liste les parcelles agricoles de l'agriculteur connecté. | "
            "EN: Lists the registered farm plots of the authenticated farmer."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "estudo_campo",
        "description": (
            "PT: Consulta ou solicita estudo de satélite do solo (índices NDVI, NDMI, NDTI, salinidade e recomendações técnicas do NongLink) para uma parcela. | "
            "FR: Consulte ou demande l'étude satellite du sol (NDVI, NDMI, NDTI, salinité, recommandations NongLink) d'une parcelle. | "
            "EN: Retrieves or requests satellite soil study (NDVI, NDMI, NDTI, salinity, NongLink recommendations) for a plot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parcela": {
                    "type": "string",
                    "description": "Nome ou identificador da parcela (ex: 'Parcela Norte', 'Lavra 1').",
                },
                "forcar_nova_analise": {
                    "type": "boolean",
                    "description": "True se o utilizador pediu explicitamente uma nova análise de satélite via Earth Engine (limite diário). False para ler a análise mais recente.",
                },
            },
            "required": ["parcela"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "listar_vendas",
        "description": (
            "PT: Lista o histórico de vendas realizadas pelo agricultor (modo só de leitura). | "
            "FR: Liste l'historique des ventes réalisées par l'agriculteur (lecture seule). | "
            "EN: Lists sales order history of the farmer (read-only)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "resumo_vendas",
        "description": (
            "PT: Obtém o resumo financeiro das vendas (vendas brutas, comissão da plataforma, rendimento líquido). | "
            "FR: Obtient le résumé financier des ventes (ventes brutes, commission, gains nets). | "
            "EN: Retrieves sales earnings summary (gross sales, platform fee, net earnings)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "tendencias_vendas",
        "description": (
            "PT: Obtém a série temporal das vendas diárias do agricultor. | "
            "FR: Obtient la série chronologique des ventes quotidiennes de l'agriculteur. | "
            "EN: Retrieves daily sales trends series for the farmer."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "actualizar_anuncio",
        "description": (
            "PT: Atualiza o preço unitário e/ou a quantidade disponível de um anúncio publicado. Requer confirmação. | "
            "FR: Met à jour le prix unitaire et/ou la quantité d'une annonce publiée. Nécessite confirmation. | "
            "EN: Updates unit price and/or available quantity of a published listing. Requires confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto ou anúncio a atualizar (ex: 'Tomate', 'Mandioca').",
                },
                "preco_kz_kg": {
                    "type": "number",
                    "description": "Novo preço unitário em Kz/kg (opcional).",
                },
                "quantidade_kg": {
                    "type": "number",
                    "description": "Nova quantidade disponível em kg (opcional).",
                },
            },
            "required": ["produto"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "retirar_anuncio",
        "description": (
            "PT: Retira um anúncio de venda marcando-o como esgotado (quantity_available=0). Nunca apaga o registo. Requer confirmação. | "
            "FR: Retire une annonce de la vente en la marquant épuisée. Ne supprime jamais l'enregistrement. Requiert confirmation. | "
            "EN: Withdraws a listing from sale by marking it out of stock. Never deletes the record. Requires confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto ou anúncio a retirar de venda (ex: 'Tomate').",
                },
            },
            "required": ["produto"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "cancelar_rega",
        "description": (
            "PT: Cancela uma sessão de rega agendada. Requer confirmação. | "
            "FR: Annule une session d'irrigation planifiée. Requiert confirmation. | "
            "EN: Cancels a scheduled irrigation session. Requires confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rega_id": {
                    "type": "string",
                    "description": "Identificador da rega a cancelar.",
                },
            },
            "required": ["rega_id"],
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


def _sanitize_log_data(data: Any) -> Any:
    """Recursively scrub personal data, tokens, passwords, and emails from log payloads."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if any(term in key_lower for term in ("senha", "password", "token", "email", "secret", "auth", "key")):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = _sanitize_log_data(v)
        return sanitized
    if isinstance(data, list):
        return [_sanitize_log_data(item) for item in data]
    return data


def log_action(tool_name: str, args: Dict[str, Any], status: str, details: Dict[str, Any]) -> None:
    """Append a sanitized action record to LOG_FILE_PATH in JSON Lines format."""
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "timestamp": timestamp,
        "tool": tool_name,
        "arguments": _sanitize_log_data(args),
        "status": status,
        "details": _sanitize_log_data(details),
    }
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def get_crop_price(cultura: str) -> Dict[str, Any]:
    """Return real crop reference price interval from SQLite and log the lookup."""
    init_db()
    db_row = get_crop_price_from_db(cultura)
    if db_row is None:
        result = {
            "status": "not_found",
            "cultura": cultura,
            "mensagem": f"Não foram encontrados preços de referência para a cultura '{cultura}' na base de dados oficial.",
        }
        log_action("obter_preco", {"cultura": cultura}, "NOT_FOUND", result)
        return result

    p_min = float(db_row.get("preco_min") or db_row.get("preco_kz_kg") or 0.0)
    p_max = float(db_row.get("preco_max") or db_row.get("preco_kz_kg") or 0.0)
    tipo = str(db_row.get("tipo") or "retalho")
    unidade = str(db_row.get("unidade") or "kz/kg")
    local = str(db_row.get("local") or "")
    data = str(db_row.get("data") or "")
    fonte = str(db_row.get("fonte") or "")
    nota = f"referência de demonstração, {local}, {data}"

    result = {
        "status": "executed",
        "cultura": cultura,
        "preco_min": p_min,
        "preco_max": p_max,
        "tipo": tipo,
        "unidade": unidade,
        "local": local,
        "data": data,
        "fonte": fonte,
        "nota": nota,
    }
    log_action("obter_preco", {"cultura": cultura}, "EXECUTED", result)
    return result


def create_listing(
    cultura: str,
    quantidade_kg: float,
    preco_kz_kg: float,
    confirmed: bool = True,
    status_label: str = "EXECUTED",
    utilizador_id: Optional[str] = None,
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
        utilizador_id=utilizador_id,
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
    utilizador_id: Optional[str] = None,
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

    db_record = insert_irrigation(
        parcela=parcela,
        hora=hora,
        utilizador_id=utilizador_id,
    )
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


def analyze_photo(
    foto_id: str, objecto: str, utilizador_id: Optional[str] = None
) -> Dict[str, Any]:
    """Segment an image using visao.segmentar (sam-3.1) and return count, coverage, and boxes."""
    resolved_path = resolve_photo_path(foto_id, utilizador_id=utilizador_id)
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
        duracao = arguments.get("duracao_minutos")
        if not duracao:
            try:
                duracao = int(os.environ.get("DURACAO_REGA_PADRAO", "30"))
            except (ValueError, TypeError):
                duracao = 30
        descriptions = {
            "pt": f"Agendar rega na parcela '{parcela}' às {hora} (Duração: {duracao} min).",
            "fr": f"Planifier l'irrigation sur la parcelle '{parcela}' à {hora} (Durée : {duracao} min).",
            "en": f"Schedule irrigation on plot '{parcela}' at {hora} (Duration: {duracao} min).",
        }
        return descriptions.get(lang, descriptions["pt"])

    if tool_name == "actualizar_anuncio":
        produto = arguments.get("produto", "")
        preco = arguments.get("preco_kz_kg")
        qtd = arguments.get("quantidade_kg")
        detalhes = []
        if preco is not None:
            detalhes.append(f"Preço: {float(preco):g} Kz/kg")
        if qtd is not None:
            detalhes.append(f"Qtd: {float(qtd):g} kg")
        detalhes_str = ", ".join(detalhes) or "novos valores"
        descriptions = {
            "pt": f"Actualizar anúncio de '{produto}' ({detalhes_str}).",
            "fr": f"Mettre à jour l'annonce de '{produto}' ({detalhes_str}).",
            "en": f"Update listing for '{produto}' ({detalhes_str}).",
        }
        return descriptions.get(lang, descriptions["pt"])

    if tool_name == "retirar_anuncio":
        produto = arguments.get("produto", "")
        descriptions = {
            "pt": f"Retirar anúncio de '{produto}' de venda (ficará esgotado, mas não será apagado).",
            "fr": f"Retirer l'annonce de '{produto}' de la vente (sera marqué épuisé, mais non supprimé).",
            "en": f"Withdraw listing for '{produto}' from sale (will be marked as sold out, but not deleted).",
        }
        return descriptions.get(lang, descriptions["pt"])

    if tool_name == "cancelar_rega":
        rega_id = arguments.get("rega_id", "")
        descriptions = {
            "pt": f"Cancelar a rega agendada #{rega_id}.",
            "fr": f"Annuler l'irrigation planifiée #{rega_id}.",
            "en": f"Cancel scheduled irrigation #{rega_id}.",
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
        try:
            quantidade_kg = float(arguments.get("quantidade_kg", 0))
        except (ValueError, TypeError):
            quantidade_kg = 0.0
        try:
            preco_kz_kg = float(arguments.get("preco_kz_kg", 0))
        except (ValueError, TypeError):
            preco_kz_kg = 0.0

        ok_anuncio, msg_anuncio = validar_anuncio(cultura, quantidade_kg, preco_kz_kg)
        if not ok_anuncio:
            refusal_result = {
                "status": "recusado_pelas_guardas",
                "ferramenta": "criar_anuncio",
                "motivo": msg_anuncio,
            }
            action_record = {
                "ferramenta": "criar_anuncio",
                "argumentos": arguments,
                "requer_confirmacao": False,
                "estado": "recusada_pelas_guardas",
                "resultado": refusal_result,
            }
            log_action("criar_anuncio", arguments, "REJECTED_BY_GUARDS", refusal_result)
            return refusal_result, action_record

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

        ok_rega, msg_rega = validar_rega(parcela, hora)
        if not ok_rega:
            refusal_result = {
                "status": "recusado_pelas_guardas",
                "ferramenta": "agendar_rega",
                "motivo": msg_rega,
            }
            action_record = {
                "ferramenta": "agendar_rega",
                "argumentos": arguments,
                "requer_confirmacao": False,
                "estado": "recusada_pelas_guardas",
                "resultado": refusal_result,
            }
            log_action("agendar_rega", arguments, "REJECTED_BY_GUARDS", refusal_result)
            return refusal_result, action_record

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
            numeros_autorizados = extrair_numeros_autorizados(recorded_actions, [user_message])
            ok_num, _ = verificar_numeros_resposta(final_text, numeros_autorizados)
            if not ok_num:
                final_text = gerar_resposta_segura_sem_alucinacoes(final_text, lang=detected_lang)
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

    numeros_autorizados = extrair_numeros_autorizados(recorded_actions, [user_message])
    ok_num, _ = verificar_numeros_resposta(final_text, numeros_autorizados)
    if not ok_num:
        final_text = gerar_resposta_segura_sem_alucinacoes(final_text, lang=detected_lang)

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
