"""Suite de testes comportamentais do agente com guardas determinísticas (Tarefa 4).

Executa 10 casos de comportamento definidos em backend/tests/comportamento/casos.json
contra o agente real com limite estrito de chamadas (máximo 15 chamadas),
base de dados temporária apagada no fim e relatório de OK/FALHOU por caso
com a taxa final de sucesso.
"""

import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "nonglink_test.db"
os.environ["NONGLINK_DB_PATH"] = str(TEST_DB_PATH.resolve())

import anyio.to_thread  # noqa: E402
import fastapi.concurrency  # noqa: E402
import fastapi.dependencies.utils  # noqa: E402
import fastapi.routing  # noqa: E402
import starlette.concurrency  # noqa: E402
import starlette.routing  # noqa: E402


async def _inline_run_in_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


async def _inline_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
    _ = kwargs
    return func(*args)


anyio.to_thread.run_sync = _inline_run_sync
starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool
fastapi.concurrency.run_in_threadpool = _inline_run_in_threadpool
fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.routing.run_in_threadpool = _inline_run_in_threadpool

from app.config import UPLOADS_DIR  # noqa: E402
from app.db import (  # noqa: E402
    _MIGRATED_DB_PATHS,
    create_conversation,
    create_session_token,
    create_user,
    init_db,
    insert_message,
    insert_photo,
    list_crop_prices,
)
from app.guardas import obter_margem_preco_percentagem  # noqa: E402
from app.main import app, reset_login_rate_limits  # noqa: E402
from scripts.seed import seed_database  # noqa: E402
from tests.test_auth import asgi_request  # noqa: E402

CASOS_FILE_PATH = BACKEND_DIR / "tests" / "comportamento" / "casos.json"
MAX_ALLOWED_MODEL_CALLS = 15


def _cleanup_test_db(temp_files: List[Path]) -> None:
    for f in temp_files:
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
    _MIGRATED_DB_PATHS.discard(str(TEST_DB_PATH.resolve()))
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(TEST_DB_PATH) + suffix)
        p.unlink(missing_ok=True)


def run_tests() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not CASOS_FILE_PATH.exists():
        print(f"Ficheiro de casos não encontrado: {CASOS_FILE_PATH}")
        return 1

    with open(CASOS_FILE_PATH, "r", encoding="utf-8") as f:
        casos = json.load(f)

    temp_files: List[Path] = []
    _cleanup_test_db(temp_files)
    if "USAR_EXEMPLOS" not in os.environ:
        os.environ["USAR_EXEMPLOS"] = "1"
    init_db(TEST_DB_PATH)
    seed_database(TEST_DB_PATH, fail_if_empty=False)
    reset_login_rate_limits()

    # Validação obrigatória da tabela precos_culturas
    culturas = list_crop_prices(TEST_DB_PATH)
    if not culturas:
        print("FALHOU: A tabela precos_culturas está vazia. Não é possível calcular os intervalos de referência para os testes de comportamento.")
        return 1

    # Obtém a cultura de referência (por omissão 'tomate' ou a primeira disponível)
    ref_crop = next((c for c in culturas if c.get("cultura") == "tomate"), culturas[0])
    cultura_nome = ref_crop["cultura"]
    p_min = float(ref_crop.get("preco_min") or ref_crop.get("preco_kz_kg") or 0.0)
    p_max = float(ref_crop.get("preco_max") or ref_crop.get("preco_kz_kg") or 0.0)

    if p_min <= 0 or p_max <= 0:
        print(f"FALHOU: A cultura '{cultura_nome}' possui valores inválidos na tabela precos_culturas (min={p_min}, max={p_max}).")
        return 1

    if p_min > p_max:
        p_min, p_max = p_max, p_min

    # Margem extra configurável (por omissão 25%)
    margem_extra = obter_margem_preco_percentagem()

    # Cálculos dinâmicos a partir do intervalo da tabela:
    # 1. Preço dentro do intervalo (ponto médio)
    preco_medio = round((p_min + p_max) / 2.0)

    # 2. Preço abaixo do mínimo com a margem extra
    limite_inferior = p_min * (1.0 - margem_extra / 100.0)
    preco_abaixo = max(1, round(limite_inferior * 0.8))

    # 3. Preço acima do máximo com a margem extra
    limite_superior = p_max * (1.0 + margem_extra / 100.0)
    preco_acima = round(limite_superior * 1.15)

    user = create_user(
        nome="Agricultor Avaliador",
        email="avaliador@nonglink.ao",
        senha="SenhaSegura#2026",
        db_path=TEST_DB_PATH,
    )
    token = create_session_token(user["id"], db_path=TEST_DB_PATH)
    headers = {"Authorization": f"Bearer {token}"}

    total_casos = len(casos)
    sucessos = 0
    total_chamadas_realizadas = 0

    print("=" * 70)
    print("TESTE COMPORTAMENTAL DO AGENTE COM GUARDAS DETERMINÍSTICAS")
    print(f"Total de casos: {total_casos} | Limite máximo de chamadas: {MAX_ALLOWED_MODEL_CALLS}")
    print(f"Cultura de referência: '{cultura_nome}' ({p_min:.0f} a {p_max:.0f} Kz/kg, Margem extra: {margem_extra:.0f}%)")
    print(f"Preços calculados -> Médio: {preco_medio} Kz/kg | Abaixo: {preco_abaixo} Kz/kg | Acima: {preco_acima} Kz/kg")
    print("=" * 70)

    valores_dinamicos = {
        "cultura": cultura_nome,
        "preco_medio": f"{int(preco_medio)}",
        "preco_abaixo": f"{int(preco_abaixo)}",
        "preco_acima": f"{int(preco_acima)}",
    }

    try:
        for idx, caso in enumerate(casos, 1):
            caso_id = caso["id"]
            descricao = caso.get("descricao", "").format(**valores_dinamicos)
            entrada = caso["entrada"].format(**valores_dinamicos)
            esperado = caso.get("esperado", {})
            conv_id = f"conv_comp_{caso_id}_{int(time.time())}"

            create_conversation(
                titulo=f"Teste {caso_id}",
                conversation_id=conv_id,
                utilizador_id=user["id"],
                db_path=TEST_DB_PATH,
            )

            # Caso especial: simulação de foto com 0 detecções prévia
            if caso.get("simular_foto_zero"):
                foto_path = UPLOADS_DIR / f"foto_zero_{caso_id}.jpg"
                foto_path.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xFF\xD9")
                temp_files.append(foto_path)
                insert_photo(
                    utilizador_id=user["id"],
                    caminho=str(foto_path),
                    foto_id=f"FOTO-ZERO-{caso_id}",
                    db_path=TEST_DB_PATH,
                )
                insert_message(
                    conversa_id=conv_id,
                    papel="agente",
                    texto="Analisei a sua foto e detetei 0 frutos visíveis.",
                    anexo_json={"foto_id": f"FOTO-ZERO-{caso_id}", "contagem": 0, "cobertura": 0.0, "caixas": []},
                    utilizador_id=user["id"],
                    db_path=TEST_DB_PATH,
                )

            if total_chamadas_realizadas >= MAX_ALLOWED_MODEL_CALLS:
                print(f"[{idx}/{total_casos}] [FALHOU] {caso_id}: Limite de {MAX_ALLOWED_MODEL_CALLS} chamadas atingido")
                continue

            # Executa chamada ao endpoint /agente
            code, _, body = asgi_request(
                "POST",
                "/agente",
                headers=headers,
                json_body={"conversa_id": conv_id, "mensagem": entrada},
            )
            total_chamadas_realizadas += 1

            if code != 200:
                print(f"[{idx}/{total_casos}] [FALHOU] {caso_id}: HTTP {code} inesperado ({body[:100].decode('utf-8', errors='ignore')})")
                continue

            try:
                res = json.loads(body.decode("utf-8"))
            except Exception as e:
                print(f"[{idx}/{total_casos}] [FALHOU] {caso_id}: Erro de JSON ({e})")
                continue

            # Avaliação dos critérios esperados
            passou = True
            motivo_falha = ""

            estado_obtido = res.get("estado")
            estado_esperado = esperado.get("estado")
            if estado_esperado and estado_obtido != estado_esperado:
                passou = False
                motivo_falha = f"estado={estado_obtido} (esperado {estado_esperado})"

            # Ferramenta que devia ser chamada
            ferr_chamada_esperada = esperado.get("ferramenta_chamada")
            if ferr_chamada_esperada:
                accoes = res.get("accoes", [])
                nomes_chamados = [a.get("ferramenta") for a in accoes if isinstance(a, dict)]
                if ferr_chamada_esperada not in nomes_chamados and res.get("accao", {}).get("ferramenta") != ferr_chamada_esperada:
                    passou = False
                    motivo_falha = f"ferramenta '{ferr_chamada_esperada}' não foi chamada"

            # Ferramentas proibidas
            proibidas = esperado.get("ferramentas_proibidas", [])
            if proibidas:
                accoes = res.get("accoes", [])
                nomes_chamados = [a.get("ferramenta") for a in accoes if isinstance(a, dict)]
                accao_pendente = res.get("accao", {}).get("ferramenta")
                if accao_pendente:
                    nomes_chamados.append(accao_pendente)
                for proibid in proibidas:
                    if proibid in nomes_chamados and res.get("estado") == "pendente":
                        passou = False
                        motivo_falha = f"ferramenta proibida '{proibid}' foi gerada como pendente"

            # Se a guarda devia bloquear a criação de ação pendente
            if esperado.get("guarda_bloqueou"):
                if res.get("estado") == "pendente":
                    passou = False
                    motivo_falha = "a guarda não bloqueou a ação (gerou talão pendente indevidamente)"

            # Idioma esperado
            idioma_esperado = esperado.get("idioma")
            if idioma_esperado and res.get("idioma") != idioma_esperado:
                passou = False
                motivo_falha = f"idioma={res.get('idioma')} (esperado {idioma_esperado})"

            status_str = "OK" if passou else "FALHOU"
            if passou:
                sucessos += 1
                print(f"[{idx:02d}/{total_casos:02d}] [{status_str}] {caso_id} - {descricao}")
            else:
                print(f"[{idx:02d}/{total_casos:02d}] [{status_str}] {caso_id} - {motivo_falha}")
                print(f"   DETALHE FALHA {caso_id}: estado={res.get('estado')}, accao={res.get('accao')}, accoes={res.get('accoes')}")

    finally:
        _cleanup_test_db(temp_files)

    taxa = (sucessos / total_casos) * 100.0 if total_casos > 0 else 0.0
    print("=" * 70)
    print(f"RESULTADO FINAL: {sucessos}/{total_casos} casos com sucesso ({taxa:.1f}%)")
    print(f"Total de chamadas realizadas ao modelo: {total_chamadas_realizadas}/{MAX_ALLOWED_MODEL_CALLS}")
    print("=" * 70)

    return 0 if sucessos == total_casos else 1


if __name__ == "__main__":
    sys.exit(run_tests())
