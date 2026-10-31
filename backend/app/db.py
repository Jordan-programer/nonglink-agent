"""SQLite database module for the NongLink Field Agent (backend/data/nonglink.db).

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

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from app.config import DB_PATH

DB_FILE_PATH: Path = DB_PATH


def _resolve_db_path(db_path: Union[str, Path] = DB_FILE_PATH) -> Path:
    """Resolve the active SQLite file path, honoring NONGLINK_DB_PATH when using default."""
    env_override = os.environ.get("NONGLINK_DB_PATH")
    if env_override and Path(db_path) == DB_PATH:
        return Path(env_override)
    return Path(db_path)

VALID_MESSAGE_ROLES = ("utilizador", "agente")
VALID_ACTION_STATES = ("pendente", "confirmada", "cancelada")

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


def _format_utc_dt(dt: datetime) -> str:
    """Format a datetime as UTC timestamp string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_utc_str(ts: str) -> Optional[datetime]:
    """Parse a UTC timestamp string into a timezone-aware UTC datetime."""
    cleaned = (ts or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _hash_session_token(token: str) -> str:
    """Return the hex SHA-256 digest of a session token (never store raw tokens)."""
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that commits/rolls back AND closes when exiting a with-block."""

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def get_connection(db_path: Union[str, Path] = DB_FILE_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with row factory configured as dict-like Row."""
    path_obj = _resolve_db_path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path_obj), factory=_ClosingConnection)
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


def migrate_db(db_path: Union[str, Path] = DB_FILE_PATH) -> None:
    """Run non-destructive schema creation and column migrations on nonglink.db."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anuncios (
                id TEXT PRIMARY KEY,
                utilizador_id TEXT NULL,
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
                utilizador_id TEXT NULL,
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
                observacao TEXT NOT NULL,
                preco_min REAL NULL,
                preco_max REAL NULL,
                tipo TEXT NULL,
                unidade TEXT NULL,
                local TEXT NULL,
                data TEXT NULL,
                fonte TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversas (
                id TEXT PRIMARY KEY,
                utilizador_id TEXT NULL,
                titulo TEXT NOT NULL,
                criada_em TEXT NOT NULL,
                atualizada_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fotos (
                id TEXT PRIMARY KEY,
                utilizador_id TEXT NULL,
                caminho TEXT NOT NULL,
                criado_em TEXT NOT NULL
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS utilizadores (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessoes_auth (
                token TEXT PRIMARY KEY,
                token_hash TEXT NULL,
                utilizador_id TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                expira_em TEXT NOT NULL,
                FOREIGN KEY (utilizador_id) REFERENCES utilizadores(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chamadas_modelo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                utilizador_id TEXT NOT NULL,
                rota TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )

        _ensure_columns(
            conn,
            "sessoes_auth",
            [
                ("token_hash", "TEXT NULL"),
                ("expira_em", "TEXT NOT NULL DEFAULT ''"),
            ],
        )
        # Invalidate any legacy plaintext sessions or sessions without expiration
        conn.execute(
            """
            DELETE FROM sessoes_auth
            WHERE expira_em IS NULL
               OR expira_em = ''
               OR length(token) != 64
               OR token GLOB '*[^0-9a-fA-F]*'
            """
        )

        _ensure_columns(
            conn,
            "anuncios",
            [("utilizador_id", "TEXT NULL")],
        )
        _ensure_columns(
            conn,
            "regas",
            [("utilizador_id", "TEXT NULL")],
        )
        _ensure_columns(
            conn,
            "conversas",
            [
                ("id", "TEXT"),
                ("utilizador_id", "TEXT NULL"),
                ("utilizador_externo_id", "TEXT NULL"),
                ("titulo", "TEXT NOT NULL DEFAULT 'Conversa'"),
                ("criada_em", "TEXT NOT NULL DEFAULT ''"),
                ("atualizada_em", "TEXT NOT NULL DEFAULT ''"),
            ],
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversas_ext_user ON conversas(utilizador_externo_id)")
        conv_cols = conn.execute("PRAGMA table_info(conversas)").fetchall()
        for col in conv_cols:
            if col["name"] == "utilizador_id" and col["notnull"]:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute(
                    """
                    CREATE TABLE conversas_migrated (
                        id TEXT PRIMARY KEY,
                        utilizador_id TEXT NULL,
                        titulo TEXT NOT NULL,
                        criada_em TEXT NOT NULL,
                        atualizada_em TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO conversas_migrated (id, utilizador_id, titulo, criada_em, atualizada_em)
                    SELECT id,
                           CASE WHEN utilizador_id IN ('USR-DEMO-0001', '') THEN NULL ELSE utilizador_id END,
                           titulo, criada_em, atualizada_em
                    FROM conversas
                    """
                )
                conn.execute("DROP TABLE conversas")
                conn.execute("ALTER TABLE conversas_migrated RENAME TO conversas")
                conn.execute("PRAGMA foreign_keys=ON")
                break
        _ensure_columns(
            conn,
            "fotos",
            [
                ("utilizador_id", "TEXT NULL"),
                ("caminho", "TEXT NOT NULL DEFAULT ''"),
                ("criado_em", "TEXT NOT NULL DEFAULT ''"),
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
        _ensure_columns(
            conn,
            "precos_culturas",
            [
                ("preco_min", "REAL NULL"),
                ("preco_max", "REAL NULL"),
                ("tipo", "TEXT NULL"),
                ("unidade", "TEXT NULL"),
                ("local", "TEXT NULL"),
                ("data", "TEXT NULL"),
                ("fonte", "TEXT NULL"),
            ],
        )
        conn.commit()


_MIGRATED_DB_PATHS: set[str] = set()


def init_db(db_path: Union[str, Path] = DB_FILE_PATH) -> None:
    """Initialize and migrate required SQLite tables without deleting existing data."""
    target = _resolve_db_path(db_path)
    resolved = str(target.resolve())
    if resolved in _MIGRATED_DB_PATHS and target.exists():
        return
    migrate_db(target)
    _MIGRATED_DB_PATHS.add(resolved)


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
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a confirmed listing into the 'anuncios' table and return its record."""
    init_db(db_path)
    created_at = _utc_now_str()
    with get_connection(db_path) as conn:
        listing_id = _next_formatted_id(conn, "anuncios", "NL")
        conn.execute(
            """
            INSERT INTO anuncios (id, utilizador_id, cultura, quantidade_kg, preco_kz_kg, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                listing_id,
                utilizador_id,
                cultura,
                float(quantidade_kg),
                float(preco_kz_kg),
                created_at,
            ),
        )
        conn.commit()
    return {
        "id": listing_id,
        "utilizador_id": utilizador_id,
        "cultura": cultura,
        "quantidade_kg": float(quantidade_kg),
        "preco_kz_kg": float(preco_kz_kg),
        "criado_em": created_at,
    }


def insert_irrigation(
    parcela: str,
    hora: str,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a confirmed irrigation schedule into the 'regas' table and return its record."""
    init_db(db_path)
    created_at = _utc_now_str()
    with get_connection(db_path) as conn:
        irrigation_id = _next_formatted_id(conn, "regas", "REGA")
        conn.execute(
            """
            INSERT INTO regas (id, utilizador_id, parcela, hora, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (irrigation_id, utilizador_id, parcela, hora, created_at),
        )
        conn.commit()
    return {
        "id": irrigation_id,
        "utilizador_id": utilizador_id,
        "parcela": parcela,
        "hora": hora,
        "criado_em": created_at,
    }


def list_listings(
    utilizador_id: Optional[Union[str, Path]] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> List[Dict[str, Any]]:
    """Return rows from the 'anuncios' table ordered from newest to oldest, scoped to utilizador_id."""
    if isinstance(utilizador_id, Path):
        db_path = utilizador_id
        utilizador_id = None
    init_db(db_path)
    with get_connection(db_path) as conn:
        if utilizador_id is not None:
            rows = conn.execute(
                """
                SELECT id, utilizador_id, cultura, quantidade_kg, preco_kz_kg, criado_em
                FROM anuncios
                WHERE utilizador_id = ?
                ORDER BY id DESC
                """,
                (str(utilizador_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, utilizador_id, cultura, quantidade_kg, preco_kz_kg, criado_em FROM anuncios ORDER BY id DESC"
            ).fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        qty = float(item.get("quantidade_kg") or 0.0)
        unit_price = float(item.get("preco_kz_kg") or 0.0)
        item["preco_kg"] = unit_price
        item["total"] = round(qty * unit_price, 2)
        item["numero"] = item["id"]
        result.append(item)
    return result


def list_irrigations(
    utilizador_id: Optional[Union[str, Path]] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> List[Dict[str, Any]]:
    """Return rows from the 'regas' table ordered from newest to oldest, scoped to utilizador_id."""
    if isinstance(utilizador_id, Path):
        db_path = utilizador_id
        utilizador_id = None
    init_db(db_path)
    with get_connection(db_path) as conn:
        if utilizador_id is not None:
            rows = conn.execute(
                """
                SELECT id, utilizador_id, parcela, hora, criado_em
                FROM regas
                WHERE utilizador_id = ?
                ORDER BY id DESC
                """,
                (str(utilizador_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, utilizador_id, parcela, hora, criado_em FROM regas ORDER BY id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def insert_photo(
    utilizador_id: Optional[str],
    caminho: Union[str, Path],
    foto_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Insert a photo record with a random secrets.token_urlsafe(12) ID and utilizador_id."""
    init_db(db_path)
    created_at = _utc_now_str()
    clean_id = (foto_id or secrets.token_urlsafe(12)).strip()
    path_str = str(caminho)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fotos (id, utilizador_id, caminho, criado_em)
            VALUES (?, ?, ?, ?)
            """,
            (clean_id, utilizador_id, path_str, created_at),
        )
        conn.commit()
    return {
        "id": clean_id,
        "foto_id": clean_id,
        "utilizador_id": utilizador_id,
        "caminho": path_str,
        "criado_em": created_at,
    }


def get_photo(
    foto_id: str,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Fetch a photo record by ID, strictly verifying utilizador_id ownership when provided."""
    init_db(db_path)
    clean_id = (foto_id or "").strip()
    if not clean_id:
        return None
    with get_connection(db_path) as conn:
        if utilizador_id is not None:
            row = conn.execute(
                """
                SELECT id, utilizador_id, caminho, criado_em
                FROM fotos
                WHERE id = ? AND utilizador_id = ?
                """,
                (clean_id, utilizador_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, utilizador_id, caminho, criado_em FROM fotos WHERE id = ?",
                (clean_id,),
            ).fetchone()
    return dict(row) if row else None


def upsert_crop_price(
    cultura: str,
    preco_min: Optional[float] = None,
    preco_max: Optional[float] = None,
    tipo: str = "retalho",
    unidade: str = "kz/kg",
    local: str = "Luanda",
    data: str = "",
    fonte: str = "",
    observacao: str = "",
    preco_kz_kg: Optional[float] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
    **kwargs: Any,
) -> None:
    """Insert or update a crop reference price interval in 'precos_culturas'."""
    init_db(db_path)

    # Suporte para assinatura legada upsert_crop_price(cultura, preco_kz_kg, observacao)
    if preco_max is None and preco_min is not None:
        p_val = float(preco_min)
        preco_min_val = p_val
        preco_max_val = p_val
        calc_preco_kz_kg = preco_kz_kg if preco_kz_kg is not None else p_val
        obs = observacao or (tipo if isinstance(tipo, str) and tipo not in ("retalho", "produtor") else "")
        tipo_val = "retalho" if tipo not in ("retalho", "produtor") else tipo
    else:
        preco_min_val = float(preco_min or 0.0)
        preco_max_val = float(preco_max or preco_min_val)
        calc_preco_kz_kg = preco_kz_kg if preco_kz_kg is not None else round((preco_min_val + preco_max_val) / 2.0, 2)
        tipo_val = tipo
        obs = observacao or f"Referência {local}, {data} (Fonte: {fonte})"

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO precos_culturas (
                cultura, preco_kz_kg, observacao,
                preco_min, preco_max, tipo, unidade, local, data, fonte
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cultura) DO UPDATE SET
                preco_kz_kg = excluded.preco_kz_kg,
                observacao = excluded.observacao,
                preco_min = excluded.preco_min,
                preco_max = excluded.preco_max,
                tipo = excluded.tipo,
                unidade = excluded.unidade,
                local = excluded.local,
                data = excluded.data,
                fonte = excluded.fonte
            """,
            (
                cultura.strip().lower(),
                float(calc_preco_kz_kg),
                obs,
                float(preco_min_val),
                float(preco_max_val),
                tipo_val.strip().lower(),
                unidade.strip().lower(),
                local.strip(),
                data.strip(),
                fonte.strip(),
            ),
        )
        conn.commit()


def get_crop_price_from_db(
    cultura: str, db_path: Union[str, Path] = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Fetch a crop reference price interval from 'precos_culturas' if present."""
    init_db(db_path)
    normalized = cultura.strip().lower()
    canonical = CROP_CANONICAL_MAP.get(normalized, normalized)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT cultura, preco_min, preco_max, tipo, unidade, local, data, fonte, preco_kz_kg, observacao
            FROM precos_culturas
            WHERE cultura = ?
            """,
            (canonical,),
        ).fetchone()
    return dict(row) if row else None


def list_crop_prices(db_path: Union[str, Path] = DB_FILE_PATH) -> List[Dict[str, Any]]:
    """Return all seeded crop reference prices from 'precos_culturas'."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT cultura, preco_min, preco_max, tipo, unidade, local, data, fonte, preco_kz_kg, observacao
            FROM precos_culturas
            ORDER BY cultura ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_conversation(
    titulo: str = "Nova conversa",
    conversation_id: Optional[str] = None,
    utilizador_id: Optional[str] = None,
    utilizador_externo_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Create a new conversation in 'conversas' scoped to a specific utilizador_id / utilizador_externo_id."""
    init_db(db_path)
    conv_id = (conversation_id or str(uuid.uuid4())).strip()
    owner_id = utilizador_id.strip() if utilizador_id else None
    ext_id = utilizador_externo_id.strip() if utilizador_externo_id else (owner_id if owner_id and owner_id.isdigit() else None)
    now = _utc_now_str()
    clean_title = (titulo or "Nova conversa").strip()
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em FROM conversas WHERE id = ?",
            (conv_id,),
        ).fetchone()
        if existing is not None:
            if owner_id is not None:
                matches = (
                    existing["utilizador_id"] == owner_id
                    or existing["utilizador_externo_id"] == owner_id
                    or (ext_id and existing["utilizador_externo_id"] == ext_id)
                )
                if not matches:
                    raise PermissionError("Conversa não encontrada.")
            conn.execute(
                "UPDATE conversas SET atualizada_em = ? WHERE id = ?",
                (now, conv_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO conversas (id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conv_id, owner_id, ext_id, clean_title, now, now),
            )
        row = conn.execute(
            "SELECT id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em FROM conversas WHERE id = ?",
            (conv_id,),
        ).fetchone()
        conn.commit()
    return dict(row) if row else {
        "id": conv_id,
        "utilizador_id": owner_id,
        "utilizador_externo_id": ext_id,
        "titulo": clean_title,
        "criada_em": now,
        "atualizada_em": now,
    }


def get_conversation(
    conversation_id: str,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Fetch a single conversation by ID from 'conversas', strictly verifying ownership when utilizador_id is given."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        if utilizador_id is not None:
            row = conn.execute(
                """
                SELECT id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em
                FROM conversas
                WHERE id = ? AND (utilizador_id = ? OR utilizador_externo_id = ?)
                """,
                (conversation_id, utilizador_id, utilizador_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em FROM conversas WHERE id = ?",
                (conversation_id,),
            ).fetchone()
    return dict(row) if row else None


def ensure_conversation(
    conversation_id: Optional[str] = None,
    titulo: str = "Nova conversa",
    utilizador_id: Optional[str] = None,
    utilizador_externo_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Return existing conversation (verifying ownership) or create it if it does not exist."""
    if conversation_id:
        raw_existing = get_conversation(conversation_id, db_path=db_path)
        if raw_existing is not None:
            if utilizador_id is not None:
                matches_owner = (
                    raw_existing.get("utilizador_id") == utilizador_id
                    or raw_existing.get("utilizador_externo_id") == utilizador_id
                    or (utilizador_externo_id and raw_existing.get("utilizador_externo_id") == utilizador_externo_id)
                )
                if not matches_owner:
                    raise PermissionError("Conversa não encontrada.")
            return raw_existing
    return create_conversation(
        titulo=titulo,
        conversation_id=conversation_id,
        utilizador_id=utilizador_id,
        utilizador_externo_id=utilizador_externo_id,
        db_path=db_path,
    )


def update_conversation_title(
    conversation_id: str,
    titulo: str,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Update the title and atualizada_em timestamp of a conversation."""
    init_db(db_path)
    now = _utc_now_str()
    with get_connection(db_path) as conn:
        if utilizador_id is not None:
            cursor = conn.execute(
                "UPDATE conversas SET titulo = ?, atualizada_em = ? WHERE id = ? AND (utilizador_id = ? OR utilizador_externo_id = ?)",
                (titulo.strip(), now, conversation_id, utilizador_id, utilizador_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        else:
            conn.execute(
                "UPDATE conversas SET titulo = ?, atualizada_em = ? WHERE id = ?",
                (titulo.strip(), now, conversation_id),
            )
            conn.commit()
    return get_conversation(
        conversation_id, utilizador_id=utilizador_id, db_path=db_path
    )


def delete_conversation(
    conversation_id: str,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> bool:
    """Delete a conversation and its messages from SQLite."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        if utilizador_id:
            owner_check = conn.execute(
                "SELECT id FROM conversas WHERE id = ? AND (utilizador_id = ? OR utilizador_externo_id = ?)",
                (conversation_id, utilizador_id, utilizador_id),
            ).fetchone()
            if owner_check is None:
                return False
        conn.execute("DELETE FROM mensagens WHERE conversa_id = ?", (conversation_id,))
        cursor = conn.execute("DELETE FROM conversas WHERE id = ?", (conversation_id,))
        conn.commit()
    return cursor.rowcount > 0


def list_conversations(
    q: Optional[str] = None,
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> List[Dict[str, Any]]:
    """Return conversations ordered by atualizada_em DESC, scoped to utilizador_id when provided."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        if utilizador_id:
            if q and q.strip():
                like_pattern = f"%{q.strip()}%"
                rows = conn.execute(
                    """
                    SELECT DISTINCT c.id, c.utilizador_id, c.utilizador_externo_id, c.titulo, c.criada_em, c.atualizada_em
                    FROM conversas c
                    LEFT JOIN mensagens m ON m.conversa_id = c.id
                    WHERE (c.utilizador_id = ? OR c.utilizador_externo_id = ?) AND (c.titulo LIKE ? OR m.texto LIKE ?)
                    ORDER BY c.atualizada_em DESC, c.criada_em DESC
                    """,
                    (utilizador_id, utilizador_id, like_pattern, like_pattern),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, utilizador_id, utilizador_externo_id, titulo, criada_em, atualizada_em
                    FROM conversas
                    WHERE utilizador_id = ? OR utilizador_externo_id = ?
                    ORDER BY atualizada_em DESC, criada_em DESC
                    """,
                    (utilizador_id, utilizador_id),
                ).fetchall()
        elif q and q.strip():
            like_pattern = f"%{q.strip()}%"
            rows = conn.execute(
                """
                SELECT DISTINCT c.id, c.utilizador_id, c.titulo, c.criada_em, c.atualizada_em
                FROM conversas c
                LEFT JOIN mensagens m ON m.conversa_id = c.id
                WHERE c.titulo LIKE ? OR m.texto LIKE ?
                ORDER BY c.atualizada_em DESC, c.criada_em DESC
                """,
                (like_pattern, like_pattern),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, utilizador_id, titulo, criada_em, atualizada_em FROM conversas ORDER BY atualizada_em DESC, criada_em DESC"
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
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
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

    ensure_conversation(conversa_id, utilizador_id=utilizador_id, db_path=db_path)

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
    db_path: Union[str, Path] = DB_FILE_PATH,
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
    conversa_id: str, db_path: Union[str, Path] = DB_FILE_PATH
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


PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 100_000


def _hash_password(
    password: str,
    salt: Optional[str] = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (>= 600,000 iterations) and a random hex salt."""
    salt_str = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_str.encode("utf-8"),
        int(iterations),
    )
    return f"pbkdf2_sha256${int(iterations)}${salt_str}${dk.hex()}"


def _needs_rehash(stored_hash: str) -> bool:
    """Return True if stored_hash uses legacy format or fewer than PBKDF2_ITERATIONS."""
    if not stored_hash or "$" not in stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            return int(parts[1]) < PBKDF2_ITERATIONS
        except ValueError:
            return True
    return True


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2-HMAC-SHA256 hash using hmac.compare_digest."""
    if not password or not stored_hash or "$" not in stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            iterations = int(parts[1])
        except ValueError:
            return False
        salt_str, expected_hex = parts[2], parts[3]
        dk_hex = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_str.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(dk_hex, expected_hex)
    if len(parts) == 2:
        salt_str, expected_hex = parts[0], parts[1]
        dk_hex = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_str.encode("utf-8"),
            LEGACY_PBKDF2_ITERATIONS,
        ).hex()
        return hmac.compare_digest(dk_hex, expected_hex)
    return False


def create_guest_user(
    seed_sample_data: bool = False,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Create a new temporary guest user (convidado-xxxx@convidado.nonglink) without password."""
    init_db(db_path)
    now = _utc_now_str()
    suffix = secrets.token_hex(4).lower()
    guest_id = f"USR-GUEST-{suffix.upper()}"
    guest_email = f"convidado-{suffix}@convidado.nonglink"
    guest_name = f"Convidado ({suffix[:4]})"

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO utilizadores (id, nome, email, senha_hash, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guest_id, guest_name, guest_email, "", now),
        )
        conn.commit()

    if seed_sample_data:
        insert_listing(
            cultura="tomate (DEMO FICTÍCIO)",
            quantidade_kg=50.0,
            preco_kz_kg=850.0,
            utilizador_id=guest_id,
            db_path=db_path,
        )
        insert_irrigation(
            parcela="Parcela Demo (FICTÍCIO)",
            hora="06:30",
            utilizador_id=guest_id,
            db_path=db_path,
        )

    return {
        "id": guest_id,
        "nome": guest_name,
        "email": guest_email,
        "criado_em": now,
    }


def create_user(
    nome: str,
    email: str,
    senha: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Dict[str, Any]:
    """Register a new user in 'utilizadores' and return its public profile."""
    init_db(db_path)
    clean_name = (nome or "").strip()
    clean_email = (email or "").strip().lower()
    if not clean_name:
        raise ValueError("O nome é obrigatório.")
    if not clean_email or "@" not in clean_email:
        raise ValueError("Introduza um email válido.")
    if not senha or len(senha) < 8:
        raise ValueError("A palavra-passe deve ter pelo menos 8 caracteres.")

    now = _utc_now_str()
    user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
    pwd_hash = _hash_password(senha)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM utilizadores WHERE LOWER(email) = ?",
            (clean_email,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Já existe uma conta registada com este email.")
        conn.execute(
            """
            INSERT INTO utilizadores (id, nome, email, senha_hash, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, clean_name, clean_email, pwd_hash, now),
        )
        conn.commit()

    return {
        "id": user_id,
        "nome": clean_name,
        "email": clean_email,
        "criado_em": now,
    }


def authenticate_user(
    email: str,
    senha: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Verify email and password against 'utilizadores', rehashing legacy hashes on login."""
    init_db(db_path)
    clean_email = (email or "").strip().lower()
    if not clean_email or not senha:
        return None
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, nome, email, senha_hash, criado_em FROM utilizadores WHERE LOWER(email) = ?",
            (clean_email,),
        ).fetchone()
        if row is None:
            return None
        stored_hash = str(row["senha_hash"] or "")
        if not _verify_password(senha, stored_hash):
            return None
        if _needs_rehash(stored_hash):
            upgraded_hash = _hash_password(senha, iterations=PBKDF2_ITERATIONS)
            conn.execute(
                "UPDATE utilizadores SET senha_hash = ?, email = ? WHERE id = ?",
                (upgraded_hash, clean_email, str(row["id"])),
            )
            conn.commit()
    return {
        "id": str(row["id"]),
        "nome": str(row["nome"]),
        "email": clean_email,
        "criado_em": str(row["criado_em"]),
    }


def get_user_by_id(
    user_id: str, db_path: Union[str, Path] = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Return user public profile by ID."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, nome, email, criado_em FROM utilizadores WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_session_token(
    utilizador_id: str,
    is_guest: bool = False,
    expira_em: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> str:
    """Create a session token, store only its SHA-256 digest and expiration in 'sessoes_auth', and return raw token."""
    init_db(db_path)
    raw_token = secrets.token_urlsafe(32)
    token_sha256 = _hash_session_token(raw_token)
    now_dt = datetime.now(timezone.utc)
    now_str = _format_utc_dt(now_dt)
    if expira_em is not None:
        expires_str = expira_em
    else:
        ttl = timedelta(hours=24) if is_guest else timedelta(days=7)
        expires_str = _format_utc_dt(now_dt + ttl)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessoes_auth (token, token_hash, utilizador_id, criado_em, expira_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_sha256, token_sha256, utilizador_id, now_str, expires_str),
        )
        conn.commit()
    return raw_token


def get_user_by_token(
    token: str, db_path: Union[str, Path] = DB_FILE_PATH
) -> Optional[Dict[str, Any]]:
    """Resolve a Bearer token via its SHA-256 digest; reject and delete expired sessions."""
    if not token or not token.strip():
        return None
    init_db(db_path)
    token_sha256 = _hash_session_token(token)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT s.token AS session_key, s.expira_em, u.id, u.nome, u.email, u.criado_em
            FROM sessoes_auth s
            JOIN utilizadores u ON u.id = s.utilizador_id
            WHERE s.token = ? OR s.token_hash = ?
            """,
            (token_sha256, token_sha256),
        ).fetchone()
        if row is None:
            return None

        exp_dt = _parse_utc_str(str(row["expira_em"] or ""))
        if exp_dt is None or datetime.now(timezone.utc) >= exp_dt:
            conn.execute(
                "DELETE FROM sessoes_auth WHERE token = ? OR token_hash = ?",
                (token_sha256, token_sha256),
            )
            conn.commit()
            return None

    return {
        "id": str(row["id"]),
        "nome": str(row["nome"]),
        "email": str(row["email"]),
        "criado_em": str(row["criado_em"]),
    }


def update_user_name(
    user_id: str,
    nome: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[Dict[str, Any]]:
    """Update user's name without modifying email or password."""
    init_db(db_path)
    clean_name = (nome or "").strip()
    if not clean_name or len(clean_name) > 60:
        raise ValueError("O nome deve ter entre 1 e 60 caracteres.")
    if any(ord(c) < 32 for c in clean_name):
        raise ValueError("O nome contém caracteres de controlo inválidos.")

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE utilizadores SET nome = ? WHERE id = ?",
            (clean_name, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT id, nome, email, criado_em FROM utilizadores WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def update_user_password(
    user_id: str,
    senha_actual: str,
    senha_nova: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> None:
    """Verify current password, update to new password with PBKDF2 (600k iters), and invalidate other sessions."""
    init_db(db_path)
    if not senha_nova or len(senha_nova) < 8:
        raise ValueError("A nova palavra-passe deve ter pelo menos 8 caracteres.")
    if senha_actual == senha_nova:
        raise ValueError("A nova palavra-passe deve ser diferente da actual.")

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, senha_hash FROM utilizadores WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Utilizador não encontrado.")

        stored_hash = str(row["senha_hash"] or "")
        # Guests have empty senha_hash
        if not stored_hash:
            raise ValueError("Esta conta de demonstração/convidado não tem palavra-passe.")

        if not _verify_password(senha_actual, stored_hash):
            raise ValueError("Palavra-passe actual incorrecta.")

        new_hash = _hash_password(senha_nova, iterations=PBKDF2_ITERATIONS)
        conn.execute(
            "UPDATE utilizadores SET senha_hash = ? WHERE id = ?",
            (new_hash, user_id),
        )
        conn.commit()


def invalidate_other_sessions(
    user_id: str,
    current_token: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> None:
    """Delete all sessions of a user except the currently active one."""
    init_db(db_path)
    current_hash = _hash_session_token(current_token)
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sessoes_auth WHERE utilizador_id = ? AND token != ? AND token_hash != ?",
            (user_id, current_hash, current_hash),
        )
        conn.commit()


def invalidate_all_user_sessions(
    user_id: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> None:
    """Delete all sessions belonging to the user."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sessoes_auth WHERE utilizador_id = ?",
            (user_id,),
        )
        conn.commit()


def delete_all_user_conversations(
    user_id: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Tuple[int, List[str]]:
    """Delete all conversations and messages of a user, returning deleted count and attached photo paths to delete."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conv_rows = conn.execute(
            "SELECT id FROM conversas WHERE utilizador_id = ?",
            (user_id,),
        ).fetchall()
        conv_ids = [str(r["id"]) for r in conv_rows]
        deleted_count = len(conv_ids)
        if not conv_ids:
            return 0, []

        placeholders = ",".join(["?"] * len(conv_ids))
        # Find messages in these conversations that reference photos
        msg_rows = conn.execute(
            f"SELECT anexo_json FROM mensagens WHERE conversa_id IN ({placeholders}) AND anexo_json IS NOT NULL",
            conv_ids,
        ).fetchall()

        foto_ids = set()
        for m in msg_rows:
            try:
                data = json.loads(m["anexo_json"])
                if isinstance(data, dict):
                    fid = data.get("foto_id") or data.get("id")
                    if fid:
                        foto_ids.add(str(fid).strip())
            except Exception:
                pass

        file_paths_to_delete = []
        if foto_ids:
            f_placeholders = ",".join(["?"] * len(foto_ids))
            photo_rows = conn.execute(
                f"SELECT id, caminho FROM fotos WHERE id IN ({f_placeholders}) AND utilizador_id = ?",
                (*foto_ids, user_id),
            ).fetchall()
            for pr in photo_rows:
                if pr["caminho"]:
                    file_paths_to_delete.append(str(pr["caminho"]))
            conn.execute(
                f"DELETE FROM fotos WHERE id IN ({f_placeholders}) AND utilizador_id = ?",
                (*foto_ids, user_id),
            )

        conn.execute(
            f"DELETE FROM mensagens WHERE conversa_id IN ({placeholders})",
            conv_ids,
        )
        conn.execute(
            f"DELETE FROM conversas WHERE id IN ({placeholders})",
            conv_ids,
        )
        conn.commit()

    return deleted_count, file_paths_to_delete


def delete_user_account_and_all_data(
    user_id: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> List[str]:
    """Delete user and all associated data (conversas, mensagens, anuncios, regas, fotos, sessoes). Returns photo file paths."""
    init_db(db_path)
    file_paths_to_delete = []
    with get_connection(db_path) as conn:
        photo_rows = conn.execute(
            "SELECT caminho FROM fotos WHERE utilizador_id = ?",
            (user_id,),
        ).fetchall()
        for pr in photo_rows:
            if pr["caminho"]:
                file_paths_to_delete.append(str(pr["caminho"]))

        # Also check messages anexo_json for any photo paths just in case
        conv_rows = conn.execute(
            "SELECT id FROM conversas WHERE utilizador_id = ?",
            (user_id,),
        ).fetchall()
        conv_ids = [str(r["id"]) for r in conv_rows]

        if conv_ids:
            placeholders = ",".join(["?"] * len(conv_ids))
            conn.execute(
                f"DELETE FROM mensagens WHERE conversa_id IN ({placeholders})",
                conv_ids,
            )
            conn.execute(
                f"DELETE FROM conversas WHERE id IN ({placeholders})",
                conv_ids,
            )

        conn.execute("DELETE FROM fotos WHERE utilizador_id = ?", (user_id,))
        conn.execute("DELETE FROM anuncios WHERE utilizador_id = ?", (user_id,))
        conn.execute("DELETE FROM regas WHERE utilizador_id = ?", (user_id,))
        conn.execute("DELETE FROM sessoes_auth WHERE utilizador_id = ?", (user_id,))
        conn.execute("DELETE FROM utilizadores WHERE id = ?", (user_id,))
        conn.commit()

    return file_paths_to_delete


def delete_session_token(
    token: str, db_path: Union[str, Path] = DB_FILE_PATH
) -> None:
    """Delete a session from 'sessoes_auth' by its SHA-256 token digest on logout."""
    if not token or not token.strip():
        return
    init_db(db_path)
    token_sha256 = _hash_session_token(token)
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sessoes_auth WHERE token = ? OR token_hash = ?",
            (token_sha256, token_sha256),
        )
        conn.commit()


def get_user_session_expiry(
    token: str,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> Optional[str]:
    """Return expira_em string for a valid token session."""
    init_db(db_path)
    token_hash = _hash_session_token(token)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT expira_em FROM sessoes_auth WHERE token = ? OR token_hash = ?",
            (token_hash, token_hash),
        ).fetchone()
        return str(row["expira_em"]) if row and row["expira_em"] else None


def registar_chamada_modelo(
    user_id: Optional[str] = None,
    rota: str = "/agente",
    utilizador_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> None:
    """Record a call made to the Meta Model API (/agente, /voz, /foto) in SQLite."""
    uid = str(user_id or utilizador_id or "").strip()
    init_db(db_path)
    now_str = _utc_now_str()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chamadas_modelo (utilizador_id, rota, criado_em)
            VALUES (?, ?, ?)
            """,
            (uid, rota, now_str),
        )
        conn.commit()


def obter_contagem_chamadas_hoje(
    utilizador_id: Optional[str] = None,
    user_id: Optional[str] = None,
    db_path: Union[str, Path] = DB_FILE_PATH,
) -> int:
    """Return number of model calls made today (UTC). If utilizador_id is None, return global count."""
    init_db(db_path)
    uid = utilizador_id or user_id
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00 UTC")
    with get_connection(db_path) as conn:
        if uid is not None:
            row = conn.execute(
                """
                SELECT COUNT(*) as total
                FROM chamadas_modelo
                WHERE utilizador_id = ? AND criado_em >= ?
                """,
                (uid, today_start),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) as total
                FROM chamadas_modelo
                WHERE criado_em >= ?
                """,
                (today_start,),
            ).fetchone()
        return int(row["total"]) if row else 0


def executar_limpeza_dados_expirados(
    horas_convidado: int = 24,
    dias_registado: int = 30,
    db_path: Union[str, Path] = DB_FILE_PATH,
    uploads_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Purge expired guest accounts (> horas_convidado or expired sessions) and old registered user conversations (> dias_registado).
    
    Deletes all related records from DB and unlinks referenced photos from disk.
    """
    init_db(db_path)
    now_dt = datetime.now(timezone.utc)
    cutoff_convidado_dt = now_dt - timedelta(hours=horas_convidado)
    cutoff_convidado_str = _format_utc_dt(cutoff_convidado_dt)
    cutoff_registado_dt = now_dt - timedelta(days=dias_registado)
    cutoff_registado_str = _format_utc_dt(cutoff_registado_dt)

    deleted_guests_count = 0
    deleted_conversas_count = 0
    total_files_deleted = 0

    with get_connection(db_path) as conn:
        # 1. Identify guest users to purge
        guest_rows = conn.execute(
            """
            SELECT id, email, criado_em
            FROM utilizadores
            WHERE email LIKE '%@convidado.nonglink'
            """
        ).fetchall()

        guests_to_delete = set()
        for gr in guest_rows:
            uid = str(gr["id"])
            created_dt = _parse_utc_str(gr["criado_em"])
            if created_dt and created_dt <= cutoff_convidado_dt:
                guests_to_delete.add(uid)
            elif not created_dt and str(gr["criado_em"]) <= cutoff_convidado_str:
                guests_to_delete.add(uid)

        # Check expired guest sessions
        expired_sessions = conn.execute(
            """
            SELECT utilizador_id, expira_em
            FROM sessoes_auth
            WHERE expira_em IS NOT NULL AND expira_em != ''
            """
        ).fetchall()
        for es in expired_sessions:
            uid = str(es["utilizador_id"])
            exp_dt = _parse_utc_str(es["expira_em"])
            if exp_dt and exp_dt <= now_dt:
                u_row = conn.execute("SELECT email FROM utilizadores WHERE id = ?", (uid,)).fetchone()
                if u_row and str(u_row["email"]).endswith("@convidado.nonglink"):
                    guests_to_delete.add(uid)

    for guest_id in guests_to_delete:
        photo_paths = delete_user_account_and_all_data(guest_id, db_path=db_path)
        deleted_guests_count += 1
        for p in photo_paths:
            try:
                Path(p).unlink(missing_ok=True)
                total_files_deleted += 1
            except Exception:
                pass

    with get_connection(db_path) as conn:
        old_convs = conn.execute(
            """
            SELECT c.id, c.utilizador_id
            FROM conversas c
            JOIN utilizadores u ON c.utilizador_id = u.id
            WHERE u.email NOT LIKE '%@convidado.nonglink'
              AND (c.atualizada_em <= ? OR (c.atualizada_em = '' AND c.criada_em <= ?))
            """,
            (cutoff_registado_str, cutoff_registado_str),
        ).fetchall()

        old_conv_ids = [str(r["id"]) for r in old_convs]

        if old_conv_ids:
            deleted_conversas_count = len(old_conv_ids)
            placeholders = ",".join(["?"] * len(old_conv_ids))

            msg_rows = conn.execute(
                f"SELECT anexo_json FROM mensagens WHERE conversa_id IN ({placeholders}) AND anexo_json IS NOT NULL",
                old_conv_ids,
            ).fetchall()

            foto_ids = set()
            for m in msg_rows:
                try:
                    data = json.loads(m["anexo_json"])
                    if isinstance(data, dict):
                        fid = data.get("foto_id") or data.get("id")
                        if fid:
                            foto_ids.add(str(fid).strip())
                except Exception:
                    pass

            if foto_ids:
                f_placeholders = ",".join(["?"] * len(foto_ids))
                photo_rows = conn.execute(
                    f"SELECT caminho FROM fotos WHERE id IN ({f_placeholders})",
                    list(foto_ids),
                ).fetchall()
                for pr in photo_rows:
                    if pr["caminho"]:
                        try:
                            Path(str(pr["caminho"])).unlink(missing_ok=True)
                            total_files_deleted += 1
                        except Exception:
                            pass
                conn.execute(
                    f"DELETE FROM fotos WHERE id IN ({f_placeholders})",
                    list(foto_ids),
                )

            conn.execute(
                f"DELETE FROM mensagens WHERE conversa_id IN ({placeholders})",
                old_conv_ids,
            )
            conn.execute(
                f"DELETE FROM conversas WHERE id IN ({placeholders})",
                old_conv_ids,
            )

        cutoff_chamadas = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S UTC")
        conn.execute("DELETE FROM chamadas_modelo WHERE criado_em < ?", (cutoff_chamadas,))
        conn.commit()

    return {
        "contas_convidado_removidas": deleted_guests_count,
        "conversas_antigas_removidas": deleted_conversas_count,
        "ficheiros_fotos_apagados": total_files_deleted,
    }


listar_anuncios = list_listings
listar_regas = list_irrigations
criar_conversa = create_conversation
obter_conversa = get_conversation
garantir_conversa = ensure_conversation
atualizar_titulo_conversa = update_conversation_title
apagar_conversa = delete_conversation
listar_conversas = list_conversations
inserir_mensagem = insert_message
atualizar_estado_accao_mensagem = update_message_action
listar_mensagens = list_messages
criar_utilizador = create_user
autenticar_utilizador = authenticate_user
obter_utilizador = get_user_by_id
