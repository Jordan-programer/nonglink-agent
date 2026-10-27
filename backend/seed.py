"""Database seeder for NongLink (backend/seed.py)."""

import sys
from typing import List, Tuple

from backend.db import (
    DB_FILE_PATH,
    init_db,
    insert_irrigation,
    insert_listing,
    list_crop_prices,
    list_irrigations,
    list_listings,
    upsert_crop_price,
)

FICTIONAL_SEED_PRICES: List[Tuple[str, float, str]] = [
    (
        "tomate",
        850.0,
        "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data",
    ),
    (
        "mandioca",
        450.0,
        "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data",
    ),
    (
        "milho",
        600.0,
        "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data",
    ),
    (
        "feijão",
        1200.0,
        "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data",
    ),
    (
        "café",
        2100.0,
        "DADOS FICTÍCIOS DE DEMONSTRAÇÃO (Hackathon) | Données fictives | Fictional demo data",
    ),
]


def seed_database(db_path: str = DB_FILE_PATH) -> None:
    """Seed nonglink.db with 5 fictional crop prices and sample records."""
    init_db(db_path)

    for crop_name, price_kz, note in FICTIONAL_SEED_PRICES:
        upsert_crop_price(crop_name, price_kz, note, db_path=db_path)

    if not list_listings(db_path):
        insert_listing(
            cultura="mandioca (fictício / demo)",
            quantidade_kg=150.0,
            preco_kz_kg=450.0,
            db_path=db_path,
        )

    if not list_irrigations(db_path):
        insert_irrigation(
            parcela="Parcela Demo Norte (fictícia)",
            hora="06:00",
            db_path=db_path,
        )


def main() -> None:
    """Run the database seed and print a summary of fictional data."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    seed_database()

    print("=== NongLink SQLite Seed (DADOS FICTÍCIOS DE DEMONSTRAÇÃO) ===")
    print("\n[Preços Fictícios de 5 Culturas / 5 Fictional Crop Prices (Kz/kg)]:")
    for item in list_crop_prices():
        print(
            f"  - {item['cultura']}: {item['preco_kz_kg']:.0f} Kz/kg ({item['observacao']})"
        )

    print("\n[Tabela 'anuncios' (nonglink.db)]:")
    for row in list_listings():
        print(
            f"  - {row['id']} | {row['cultura']} | {row['quantidade_kg']} kg | "
            f"{row['preco_kz_kg']} Kz/kg | {row['criado_em']}"
        )

    print("\n[Tabela 'regas' (nonglink.db)]:")
    for row in list_irrigations():
        print(
            f"  - {row['id']} | {row['parcela']} | {row['hora']} | {row['criado_em']}"
        )


if __name__ == "__main__":
    main()
