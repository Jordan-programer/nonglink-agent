"""Database seed script (backend/scripts/seed.py) for the NongLink Field Agent.

Populates backend/data/nonglink.db with fictional demonstration crop prices for
5 crops in Kz/kg and sample records if the tables are empty.
"""

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

FICTIONAL_NOTE = (
    "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | "
    "Données fictives de démonstration | "
    "Fictional demonstration data"
)

SEED_CROP_PRICES: List[Dict[str, Any]] = [
    {"cultura": "tomate", "preco_kz_kg": 850.0, "observacao": FICTIONAL_NOTE},
    {"cultura": "mandioca", "preco_kz_kg": 450.0, "observacao": FICTIONAL_NOTE},
    {"cultura": "milho", "preco_kz_kg": 600.0, "observacao": FICTIONAL_NOTE},
    {"cultura": "feijão", "preco_kz_kg": 1200.0, "observacao": FICTIONAL_NOTE},
    {"cultura": "café", "preco_kz_kg": 2100.0, "observacao": FICTIONAL_NOTE},
]


def seed_database(db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Initialize tables and insert fictional demo prices and sample records."""
    init_db(db_path)

    for crop in SEED_CROP_PRICES:
        upsert_crop_price(
            cultura=crop["cultura"],
            preco_kz_kg=crop["preco_kz_kg"],
            observacao=crop["observacao"],
            db_path=db_path,
        )

    if len(list_listings(db_path=db_path)) == 0:
        insert_listing(
            cultura="tomate (DEMO FICTÍCIO)",
            quantidade_kg=100.0,
            preco_kz_kg=850.0,
            db_path=db_path,
        )
        insert_listing(
            cultura="mandioca (DEMO FICTÍCIO)",
            quantidade_kg=250.0,
            preco_kz_kg=450.0,
            db_path=db_path,
        )

    if len(list_irrigations(db_path=db_path)) == 0:
        insert_irrigation(
            parcela="Parcela Demo A (FICTÍCIO)",
            hora="06:00",
            db_path=db_path,
        )
        insert_irrigation(
            parcela="Parcela Demo B (FICTÍCIO)",
            hora="17:30",
            db_path=db_path,
        )

    return {
        "precos_culturas": list_crop_prices(db_path),
        "anuncios": list_listings(db_path=db_path),
        "regas": list_irrigations(db_path=db_path),
    }


def main() -> None:
    """Run the database seed and print a summary of the fictional demo data."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    summary = seed_database()
    print(f"=== Seed NongLink ({DB_PATH}) — DADOS FICTÍCIOS DE DEMONSTRAÇÃO ===")
    print("\nPreços de 5 culturas (Kz/kg):")
    for row in summary["precos_culturas"]:
        print(
            f"  - {row['cultura']}: {int(row['preco_kz_kg'])} Kz/kg ({row['observacao']})"
        )
    print(f"\nTotal de anúncios na base: {len(summary['anuncios'])}")
    print(f"Total de regas na base: {len(summary['regas'])}")


if __name__ == "__main__":
    main()
