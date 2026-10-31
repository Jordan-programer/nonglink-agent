"""End-to-end test suite (backend/tests/test_agente.py) for the NongLink Field Agent.

Tests 3 core cases against the real Meta API (muse-spark-1.3) and SQLite database:
1. Crop price lookup (obter_preco for tomato)
2. Publishing a listing with two-step confirmation (/agente -> /confirmar true)
3. Cancelling a pending action (/agente -> /confirmar false)
"""

from pathlib import Path
import sys
from typing import Callable, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import init_db, list_irrigations, list_listings  # noqa: E402
from app.main import (  # noqa: E402
    AgentMessageRequest,
    ConfirmActionRequest,
    post_agent,
    post_confirm,
)
from scripts.seed import seed_database  # noqa: E402
import pytest

MOCK_TEST_USER: dict = {"id": "test_suite_user", "nome": "Test User", "tipo": "registado"}

if not os.environ.get("MODEL_API_KEY") or os.environ.get("MODEL_API_KEY") in ("coloque_a_sua_chave_aqui", "teste", ""):
    pytest.skip("Requer chave real MODEL_API_KEY no ambiente", allow_module_level=True)


def test_case_1_tomato_price() -> Tuple[bool, str]:
    """Case 1: Query tomato price and verify obter_preco was executed with 850 Kz/kg."""
    req = AgentMessageRequest(
        sessao="test-case-1",
        mensagem="Qual é o preço do tomate por quilo?",
    )
    resp = post_agent(req, user=MOCK_TEST_USER)
    if resp.get("estado") != "concluido":
        return False, f"Estado inesperado: {resp.get('estado')}"

    actions = resp.get("accoes", [])
    price_actions = [a for a in actions if a.get("ferramenta") == "obter_preco"]
    if not price_actions:
        return False, "A ferramenta 'obter_preco' não foi chamada."

    price_val = price_actions[0].get("resultado", {}).get("preco_kz_kg")
    reply_text = resp.get("resposta", "")
    if price_val != 850 or "850" not in reply_text:
        return False, f"Preço esperado 850 Kz/kg não encontrado (obtido: {price_val})."

    return True, f"Preço de tomate consultado via obter_preco ({price_val} Kz/kg)"


def test_case_2_publish_listing_confirmed() -> Tuple[bool, str]:
    """Case 2: Propose a listing (/agente -> pendente) and confirm it (/confirmar -> SQLite)."""
    before_ids = {row["id"] for row in list_listings()}

    step1 = post_agent(
        AgentMessageRequest(
            sessao="test-case-2",
            mensagem="Quero publicar um anúncio de 120 kg de tomate a 850 Kz/kg.",
        ),
        user=MOCK_TEST_USER,
    )
    if step1.get("estado") != "pendente":
        return False, f"Esperava estado 'pendente', recebeu '{step1.get('estado')}'."

    tool_name = step1.get("accao", {}).get("ferramenta")
    if tool_name != "criar_anuncio":
        return False, f"Esperava ferramenta 'criar_anuncio', recebeu '{tool_name}'."

    after_step1_ids = {row["id"] for row in list_listings()}
    if after_step1_ids != before_ids:
        return False, "O anúncio foi gravado antes da confirmação!"

    step2 = post_confirm(ConfirmActionRequest(sessao="test-case-2", confirmar=True), user=MOCK_TEST_USER)
    if step2.get("estado") != "confirmado":
        return False, f"Esperava estado 'confirmado', recebeu '{step2.get('estado')}'."

    new_id = step2.get("resultado_accao", {}).get("id")
    after_confirm_ids = {row["id"] for row in list_listings()}
    if not new_id or new_id not in after_confirm_ids:
        return False, f"ID '{new_id}' não foi encontrado na tabela 'anuncios'."

    return True, f"Anúncio confirmado e gravado em nonglink.db com ID real {new_id}"


def test_case_3_cancel_action() -> Tuple[bool, str]:
    """Case 3: Propose an irrigation schedule (/agente -> pendente) and cancel it (/confirmar false)."""
    before_count = len(list_irrigations())

    step1 = post_agent(
        AgentMessageRequest(
            sessao="test-case-3",
            mensagem="Por favor agenda rega na Parcela Teste às 07:15.",
        ),
        user=MOCK_TEST_USER,
    )
    if step1.get("estado") != "pendente":
        return False, f"Esperava estado 'pendente', recebeu '{step1.get('estado')}'."

    tool_name = step1.get("accao", {}).get("ferramenta")
    if tool_name not in ("agendar_rega", "criar_anuncio"):
        return False, f"Ferramenta pendente inesperada: '{tool_name}'."

    step2 = post_confirm(ConfirmActionRequest(sessao="test-case-3", confirmar=False), user=MOCK_TEST_USER)
    if step2.get("estado") != "cancelado":
        return False, f"Esperava estado 'cancelado', recebeu '{step2.get('estado')}'."

    after_count = len(list_irrigations())
    if after_count != before_count:
        return False, "A tabela 'regas' foi alterada apesar de a acção ter sido cancelada!"

    return (
        True,
        f"Acção '{tool_name}' cancelada com sucesso sem gravar na base de dados",
    )


def main() -> None:
    """Run all 3 test cases and exit with 0 if all pass, or 1 if any fail."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    init_db()
    seed_database()

    tests: list[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
        ("Caso 1 (Preço de tomate)", test_case_1_tomato_price),
        ("Caso 2 (Publicar anúncio com confirmação)", test_case_2_publish_listing_confirmed),
        ("Caso 3 (Cancelar uma acção)", test_case_3_cancel_action),
    ]

    print("=== Testes End-to-End do Agente NongLink (API Real muse-spark-1.3) ===")
    passed = 0
    for label, test_fn in tests:
        try:
            ok, detail = test_fn()
        except Exception as exc:
            ok, detail = False, str(exc)

        status_str = "OK" if ok else "FALHOU"
        print(f"{status_str} - {label}: {detail}")
        if ok:
            passed += 1

    print(f"\nResumo: {passed}/{len(tests)} testes passaram.")
    if passed != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    main()
