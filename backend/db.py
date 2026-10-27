"""SQLite database module for the NongLink Field Agent (nonglink.db).

Manages tables with non-destructive migrations:
- anuncios (id, cultura, quantidade_kg, preco_kz_kg, criado_em)
- regas (id, parcela, hora, criado_em)
- precos_culturas (cultura, preco_kz_kg, observacao)
- conversas (id [UUID text], titulo, criada_em, atualizada_em)
- mensagens (
    id, conversa_id, papel ['utilizador'|'agente'], texto, criado_em,
    accao_json [nullable], estado_accao [nullable: 'pendente'|'confirmada'|'cancelada'],
    resultado_id [nullable], anexo_json [nullable: {foto_id, contagem, cobertura, caixas}]
  )
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid

DB_FILE_PATH = "nonglink.db"

VALID_MESSAGE_ROLES = ("utilizador", "agente")
VALID_ACTION_STATES = ("pendente", "confirmada", "cancelada")

# Multilingual crop alias mapping to the 5 canonical seeded crops
CROP_CANONICAL_MAP: Dict[str, str] = {
    "tomate": "tomate",
    "tomates": "tomate",
    "tomato": "tomate",
    "tomatoes": "tomate",
    "mandioca": "mandioca",
    "manioc": "mandioca",
    "cassava": "mandioca",
    "milho": "milho",
    "mais": "milho",
    "maïs": "milho",
    "maize": "milho",
    "corn": "milho",
    "feijao": "feijão",
    "feijão": "feijão",
    "haricot": "feijão",
    "haricots": "feijão",
    "bean": "feijão",
    "beans": "feijão",
    "cafe": "café",
    "café": "café",
    "coffee": "café",
    "batata": "batata",
    "pomme de terre": "batata",
    "potato": "batata",
    "cebola": "cebola",
    "oignon": "cebola",
    "onion": "cebola",
    "banana": "banana",
    "banane": "banana",
}


def _utc_now_str() -> str:
    """Return current UTC timestamp formatted as string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_connection(db_path: str = DB_FILE_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with row factory configured as dict-like Row."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: List[Tuple[str, str]],
) -> None:
    """Add any missing columns to an existing table without deleting data."""
    existing_rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_names = {str(row["name"]) for row in existing_rows}
    for col_name, col_definition in required_columns:
        if col_name not in existing_names:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
            )


def migrate_db(db_path: str = DB_FILE_PATH) -> None:
    """Run non-destructive schema creation and column migrations on nonglink.db."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anuncios (
                id TEXT PRIMARY KEY,
                cultura TEXT NOT NULL,
                quantidade_kg REAL NOT NULL,
                preco_kz_kg REAL NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS regas (
                id TEXT PRIMARY KEY,
                parcela TEXT NOT NULL,
                hora TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS precos_culturas (
                cultura TEXT PRIMARY KEY,
                preco_kz_kg REAL NOT NULL,
                observacao TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversas (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                criada_em TEXT NOT NULL,
                atualizada_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversa_id TEXT NOT NULL,
                papel TEXT NOT NULL CHECK(papel IN ('utilizador', 'agente')),
                texto TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                accao_json TEXT NULL,
                estado_accao TEXT NULL CHECK(
                    estado_accao IS NULL OR estado_accao IN ('pendente', 'confirmada', 'cancelada')
                ),
                resultado_id TEXT NULL,
                anexo_json TEXT NULL,
                FOREIGN KEY (conversa_id) REFERENCES conversas(id)
            )
            """
        )

        _ensure_columns(
            conn,
            "conversas",
            [
                ("id", "TEXT"),
                ("titulo", "TEXT NOT NULL DEFAULT 'Conversa'"),
                ("criada_em", "TEXT NOT NULL DEFAULT ''"),
                ("atualizada_em", "TEXT NOT NULL DEFAULT ''"),
            ],
        )
        _ensure_columns(
            conn,
            "mensagens",
            [
                ("conversa_id", "TEXT NOT NULL DEFAULT ''"),
                ("papel", "TEXT NOT NULL DEFAULT 'utilizador'"),
                ("texto", "TEXT NOT NULL DEFAULT ''"),
                ("criado_em", "TEXT NOT NULL DEFAULT ''"),
                ("accao_json", "TEXT NULL"),
                ("estado_accao", "TEXT NULL"),
                ("resultado_id", "TEXT NULL"),
                ("anexo_json", "TEXT NULL"),
            ],
        )
        conn.commit()


def init_db(db_path: str = DB_FILE_PATH) -> None:
    """Initialize and migrate required SQLite tables without deleting existing data."""
    migrate_db(db_path)


def _next_formatted_id(
    conn: sqlite3.Connection, table_name: str, prefix: str
) -> str:
    """Generate the next sequential formatted ID (e.g., NL-0001 or REGA-0001)."""
    rows = conn.execute(f"SELECT id FROM {table_name}").fetchall()
    max_num = 0
    for row in rows:
        raw_id = str(row["id"])
        if raw_id.startswith(f"{prefix}-"):
            suffix = raw_id[len(prefix) + 1 :]
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
    return f"{prefix}-{max_num + 1:04d}"


def insert_listing(
    cultura: str,
    quantidade_kg: float,
    preco_kz_kg: float,
    db_path: str = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a confirmed listing into the 'anuncios' table and return its record."""
    init_db(db_path)
    created_at = _utc_now_str()
    with get_connection(db_path) as conn:
        listing_id = _next_formatted_id(conn, "anuncios", "NL")
        conn.execute(
            """
            INSERT INTO anuncios (id, cultura, quantidade_kg, preco_kz_kg, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (listing_id, cultura, float(quantidade_kg), float(preco_kz_kg), created_at),
        )
        conn.commit()
    return {
        "id": listing_id,
        "cultura": cultura,
        "quantidade_kg": float(quantidade_kg),
        "preco_kz_kg": float(preco_kz_kg),
        "criado_em": created_at,
    }


def insert_irrigation(
    parcela: str,
    hora: str,
    db_path: str = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a confirmed irrigation schedule into the 'regas' table and return its record."""
    init_db(db_path)
    created_at = _utc_now_str()
    with get_connection(db_path) as conn:
        irrigation_id = _next_formatted_id(conn, "regas", "REGA")
        conn.execute(
            """
            INSERT INTO regas (id, parcela, hora, criado_em)
            VALUES (?, ?, ?, ?)
            """,
            (irrigation_id, parcela, hora, created_at),
        )
        conn.commit()
    return {
        "id": irrigation_id,
        "parcela": parcela,
        "hora": hora,
        "criado_em": created_at,
    }


def list_listings(db_path: str = DB_FILE_PATH) -> List[Dict[str, Any]]:
    """Return all rows from the 'anuncios' table ordered from newest to oldest."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, cultura, quantidade_kg, preco_kz_kg, criado_em FROM anuncios ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def list_irrigations(db_path: str = DB_FILE_PATH) -> List[Dict[str, Any]]:
    """Return all rows from the 'regas' table ordered from newest to oldest."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, parcela, hora, criado_em FROM regas ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_crop_price(
    cultura: str,
    preco_kz_kg: float,
    observacao: str,
    db_path: str = DB_FILE_PATH,
) -> None:
    """Insert or update a fictional crop reference price in 'precos_culturas'."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO precos_culturas (cultura, preco_kz_kg, observacao)
            VALUES (?, ?, ?)
            ON CONFLICT(cultura) DO UPDATE SET
                preco_kz_kg = excluded.preco_kz_kg,
                observacao = excluded.observacao
            """,
            (cultura.strip().lower(), float(preco_kz_kg), observacao),
        )
        conn.commit()


def get_crop_price_from_db(
    cultura: str, db_path: str = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Fetch a fictional crop price from 'precos_culturas' if present."""
    init_db(db_path)
    normalized = cultura.strip().lower()
    canonical = CROP_CANONICAL_MAP.get(normalized, normalized)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT cultura, preco_kz_kg, observacao FROM precos_culturas WHERE cultura = ?",
            (canonical,),
        ).fetchone()
    return dict(row) if row else None


def list_crop_prices(db_path: str = DB_FILE_PATH) -> List[Dict[str, Any]]:
    """Return all seeded fictional crop prices from 'precos_culturas'."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT cultura, preco_kz_kg, observacao FROM precos_culturas ORDER BY cultura ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_conversation(
    titulo: str = "Nova conversa",
    conversation_id: Optional[str] = None,
    db_path: str = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Create a new conversation in 'conversas' with a UUID text ID."""
    init_db(db_path)
    conv_id = (conversation_id or str(uuid.uuid4())).strip()
    now = _utc_now_str()
    clean_title = (titulo or "Nova conversa").strip()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversas (id, titulo, criada_em, atualizada_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                atualizada_em = excluded.atualizada_em
            """,
            (conv_id, clean_title, now, now),
        )
        row = conn.execute(
            "SELECT id, titulo, criada_em, atualizada_em FROM conversas WHERE id = ?",
            (conv_id,),
        ).fetchone()
        conn.commit()
    return dict(row) if row else {
        "id": conv_id,
        "titulo": clean_title,
        "criada_em": now,
        "atualizada_em": now,
    }


def get_conversation(
    conversation_id: str, db_path: str = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Fetch a single conversation by ID from 'conversas'."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, titulo, criada_em, atualizada_em FROM conversas WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return dict(row) if row else None


def ensure_conversation(
    conversation_id: Optional[str] = None,
    titulo: str = "Nova conversa",
    db_path: str = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Return existing conversation or create it if it does not exist."""
    if conversation_id:
        existing = get_conversation(conversation_id, db_path=db_path)
        if existing is not None:
            return existing
    return create_conversation(
        titulo=titulo, conversation_id=conversation_id, db_path=db_path
    )


def update_conversation_title(
    conversation_id: str, titulo: str, db_path: str = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Update the title and atualizada_em timestamp of a conversation."""
    init_db(db_path)
    now = _utc_now_str()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE conversas SET titulo = ?, atualizada_em = ? WHERE id = ?",
            (titulo.strip(), now, conversation_id),
        )
        conn.commit()
    return get_conversation(conversation_id, db_path=db_path)


def list_conversations(db_path: str = DB_FILE_PATH) -> List[Dict[str, Any]]:
    """Return all conversations ordered by atualizada_em DESC."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, titulo, criada_em, atualizada_em FROM conversas ORDER BY atualizada_em DESC, criada_em DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def format_photo_attachment(photo_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a photo attachment payload to {foto_id, contagem, cobertura, caixas}."""
    cobertura_val = photo_data.get(
        "cobertura", photo_data.get("cobertura_percentagem", 0.0)
    )
    return {
        "foto_id": str(photo_data.get("foto_id", "")),
        "contagem": int(photo_data.get("contagem", 0)),
        "cobertura": float(cobertura_val or 0.0),
        "caixas": list(photo_data.get("caixas", [])),
    }


def _deserialize_message_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a SQLite Row from 'mensagens' into a dictionary with parsed JSON fields."""
    item = dict(row)
    item["accao"] = (
        json.loads(item["accao_json"]) if item.get("accao_json") else None
    )
    item["anexo"] = (
        json.loads(item["anexo_json"]) if item.get("anexo_json") else None
    )
    return item


def insert_message(
    conversa_id: str,
    papel: str,
    texto: str,
    accao_json: Optional[Any] = None,
    estado_accao: Optional[str] = None,
    resultado_id: Optional[str] = None,
    anexo_json: Optional[Any] = None,
    db_path: str = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a message into 'mensagens' and update the parent conversation timestamp."""
    if papel not in VALID_MESSAGE_ROLES:
        raise ValueError(
            f"Invalid papel '{papel}'. Must be one of {VALID_MESSAGE_ROLES}."
        )
    if estado_accao is not None and estado_accao not in VALID_ACTION_STATES:
        raise ValueError(
            f"Invalid estado_accao '{estado_accao}'. Must be one of {VALID_ACTION_STATES} or None."
        )

    ensure_conversation(conversa_id, db_path=db_path)

    serialized_accao: Optional[str] = None
    if accao_json is not None:
        serialized_accao = (
            accao_json
            if isinstance(accao_json, str)
            else json.dumps(accao_json, ensure_ascii=False)
        )

    serialized_anexo: Optional[str] = None
    if anexo_json is not None:
        if isinstance(anexo_json, str):
            serialized_anexo = anexo_json
        elif isinstance(anexo_json, dict):
            normalized_anexo = (
                format_photo_attachment(anexo_json)
                if "foto_id" in anexo_json
                else anexo_json
            )
            serialized_anexo = json.dumps(normalized_anexo, ensure_ascii=False)
        else:
            serialized_anexo = json.dumps(anexo_json, ensure_ascii=False)

    now = _utc_now_str()
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO mensagens (
                conversa_id, papel, texto, criado_em,
                accao_json, estado_accao, resultado_id, anexo_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversa_id,
                papel,
                texto,
                now,
                serialized_accao,
                estado_accao,
                resultado_id,
                serialized_anexo,
            ),
        )
        msg_id = cursor.lastrowid
        conn.execute(
            "UPDATE conversas SET atualizada_em = ? WHERE id = ?",
            (now, conversa_id),
        )
        row = conn.execute(
            """
            SELECT id, conversa_id, papel, texto, criado_em,
                   accao_json, estado_accao, resultado_id, anexo_json
            FROM mensagens WHERE id = ?
            """,
            (msg_id,),
        ).fetchone()
        conn.commit()
    return _deserialize_message_row(row)


def update_message_action(
    message_id: int,
    estado_accao: str,
    resultado_id: Optional[str] = None,
    db_path: str = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Update estado_accao ('pendente'|'confirmada'|'cancelada') and resultado_id of a message."""
    if estado_accao not in VALID_ACTION_STATES:
        raise ValueError(
            f"Invalid estado_accao '{estado_accao}'. Must be one of {VALID_ACTION_STATES}."
        )
    init_db(db_path)
    now = _utc_now_str()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE mensagens
            SET estado_accao = ?, resultado_id = COALESCE(?, resultado_id)
            WHERE id = ?
            """,
            (estado_accao, resultado_id, int(message_id)),
        )
        row = conn.execute(
            """
            SELECT id, conversa_id, papel, texto, criado_em,
                   accao_json, estado_accao, resultado_id, anexo_json
            FROM mensagens WHERE id = ?
            """,
            (int(message_id),),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE conversas SET atualizada_em = ? WHERE id = ?",
                (now, row["conversa_id"]),
            )
        conn.commit()
    return _deserialize_message_row(row) if row else None


def list_messages(
    conversa_id: str, db_path: str = DB_FILE_PATH
) -> List[Dict[str, Any]]:
    """Return all messages for a conversation in chronological order."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, conversa_id, papel, texto, criado_em,
                   accao_json, estado_accao, resultado_id, anexo_json
            FROM mensagens
            WHERE conversa_id = ?
            ORDER BY id ASC
            """,
            (conversa_id,),
        ).fetchall()
    return [_deserialize_message_row(row) for row in rows]


listar_anuncios = list_listings
listar_regas = list_irrigations
criar_conversa = create_conversation
obter_conversa = get_conversation
garantir_conversa = ensure_conversation
atualizar_titulo_conversa = update_conversation_title
listar_conversas = list_conversations
inserir_mensagem = insert_message
atualizar_estado_accao_mensagem = update_message_action
listar_mensagens = list_messages
