"""Database seed script (backend/scripts/seed.py) for the NongLink Field Agent.

Loads real agricultural reference prices from backend/scripts/precos_referencia.csv
into backend/data/nonglink.db (precos_culturas). If the CSV has no data, fails with
a clear message instead of using invented prices. Lines marked 'EXEMPLO' are ignored
unless USAR_EXEMPLOS=1 is set in the environment.
"""

import csv
import os
from pathlib import Path
import sys
from typing import Any, Dict, List

# Allow running directly as `python scripts/seed.py` from `backend/`
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import DB_PATH  # noqa: E402
from app.db import (  # noqa: E402
    init_db,
    insert_irrigation,
    insert_listing,
    list_crop_prices,
    list_irrigations,
    list_listings,
    upsert_crop_price,
)

CSV_PRECOS_PATH = BACKEND_ROOT / "scripts" / "precos_referencia.csv"


def is_row_exemplo(row: Dict[str, Any]) -> bool:
    """Check if the CSV row is tagged as an 'EXEMPLO' row."""
    for val in row.values():
        if val and str(val).strip().upper() == "EXEMPLO":
            return True
    return False


def carregar_precos_csv(
    csv_path: Path = CSV_PRECOS_PATH,
    usar_exemplos: bool = False,
) -> List[Dict[str, Any]]:
    """Load valid crop price rows from precos_referencia.csv."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Ficheiro de preços não encontrado: {csv_path}")

    registos: List[Dict[str, Any]] = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not any(row.values()):
                continue
            if is_row_exemplo(row) and not usar_exemplos:
                continue

            cultura = (row.get("cultura") or "").strip()
            if not cultura:
                continue

            try:
                p_min = float(str(row.get("preco_min", "0")).replace(",", "."))
                p_max = float(str(row.get("preco_max", "0")).replace(",", "."))
            except (ValueError, TypeError):
                continue

            registos.append(
                {
                    "cultura": cultura,
                    "tipo": (row.get("tipo") or "retalho").strip(),
                    "preco_min": p_min,
                    "preco_max": p_max,
                    "unidade": (row.get("unidade") or "kz/kg").strip(),
                    "local": (row.get("local") or "").strip(),
                    "data": (row.get("data") or "").strip(),
                    "fonte": (row.get("fonte") or "").strip(),
                }
            )

    return registos


def seed_database(
    db_path: Path = DB_PATH,
    csv_path: Path = CSV_PRECOS_PATH,
    fail_if_empty: bool = True,
) -> Dict[str, Any]:
    """Initialize tables and load crop prices from CSV into precos_culturas."""
    init_db(db_path)

    usar_exemplos_env = os.environ.get("USAR_EXEMPLOS", "").strip().lower() in (
        "1",
        "true",
        "sim",
        "yes",
        "on",
    )
    precos = carregar_precos_csv(csv_path=csv_path, usar_exemplos=usar_exemplos_env)

    if not precos:
        if fail_if_empty:
            raise ValueError(
                f"Nenhum preço de referência válido encontrado em {csv_path.name}. "
                "Linhas marcadas como 'EXEMPLO' são ignoradas a menos que a variável "
                "de ambiente USAR_EXEMPLOS=1 esteja ativa. "
                "Por favor preencha o CSV com cotações reais antes de executar o seed."
            )
        # Se não falhar explicitamente, não insere preços inventados
    else:
        from app.db import get_connection
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM precos_culturas")
            conn.commit()

        for item in precos:
            upsert_crop_price(
                cultura=item["cultura"],
                preco_min=item["preco_min"],
                preco_max=item["preco_max"],
                tipo=item["tipo"],
                unidade=item["unidade"],
                local=item["local"],
                data=item["data"],
                fonte=item["fonte"],
                db_path=db_path,
            )
        print(f"Carregadas {len(precos)} culturas de referência a partir de {csv_path.name}.")

    if len(list_listings(db_path=db_path)) == 0:
        insert_listing(
            cultura="tomate (DEMO)",
            quantidade_kg=100.0,
            preco_kz_kg=2200.0,
            db_path=db_path,
        )

    if len(list_irrigations(db_path=db_path)) == 0:
        insert_irrigation(
            parcela="Parcela Demo A",
            hora="06:00",
            db_path=db_path,
        )

    return {
        "precos_culturas": list_crop_prices(db_path),
        "anuncios": list_listings(db_path=db_path),
        "regas": list_irrigations(db_path=db_path),
    }


def main() -> None:
    """Run the database seed and print loaded price ranges."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        summary = seed_database(fail_if_empty=True)
    except ValueError as exc:
        print(f"ERRO NO SEED: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Seed NongLink ({DB_PATH}) ===")
    print(f"\nPreços de {len(summary['precos_culturas'])} culturas:")
    for row in summary["precos_culturas"]:
        p_min = float(row.get("preco_min") or row.get("preco_kz_kg") or 0.0)
        p_max = float(row.get("preco_max") or row.get("preco_kz_kg") or 0.0)
        unidade = row.get("unidade", "kz/kg")
        tipo = row.get("tipo", "retalho")
        local = row.get("local", "")
        data = row.get("data", "")
        fonte = row.get("fonte", "")
        print(
            f"  - {row['cultura']}: {p_min:.0f} a {p_max:.0f} {unidade} ({tipo}) em {local}, {data} (Fonte: {fonte})"
        )
    print(f"\nTotal de anúncios na base: {len(summary['anuncios'])}")
    print(f"Total de regas na base: {len(summary['regas'])}")


if __name__ == "__main__":
    main()
