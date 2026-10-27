"""Testes de isolamento entre utilizadores e convidados (Tarefa 7).

Usa uma base de dados temporária `nonglink_test.db` apagada no fim e imprime
OK/FALHOU por cada caso de teste, sem nunca escrever ou imprimir palavras-passe
ou tokens.
"""

from pathlib import Path
import json
import os
import sys
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
    """Executa funções síncronas directamente sem criar sockets/threads."""
    return func(*args, **kwargs)


async def _inline_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Substitui anyio.to_thread.run_sync para execução síncrona imediata."""
    _ = kwargs
    return func(*args)


anyio.to_thread.run_sync = _inline_run_sync
starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool
fastapi.concurrency.run_in_threadpool = _inline_run_in_threadpool
fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.routing.run_in_threadpool = _inline_run_in_threadpool

from app.config import LOG_FILE_PATH  # noqa: E402
from app.db import (  # noqa: E402
    _MIGRATED_DB_PATHS,
    create_conversation,
    init_db,
    insert_irrigation,
    insert_listing,
)
from app.main import PENDING_SESSIONS, app  # noqa: E402
from tests.test_auth import _multipart_file_body, asgi_request  # noqa: E402


def _cleanup_test_db(temp_files: List[Path]) -> None:
    for f in temp_files:
        f.unlink(missing_ok=True)
    _MIGRATED_DB_PATHS.discard(str(TEST_DB_PATH.resolve()))
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(TEST_DB_PATH) + suffix)
        p.unlink(missing_ok=True)


def run_tests() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    temp_files: List[Path] = []
    created_secrets: List[str] = []
    _cleanup_test_db(temp_files)
    init_db(TEST_DB_PATH)

    failures = 0

    def report(case_name: str, passed: bool, detail: str = "") -> None:
        nonlocal failures
        status = "OK" if passed else "FALHOU"
        suffix = f" ({detail})" if detail else ""
        print(f"[{status}] {case_name}{suffix}")
        if not passed:
            failures += 1

    try:
        # Criar linhas antigas sem dono (utilizador_id = None)
        insert_listing("milho antigo", 300.0, 600.0, utilizador_id=None, db_path=TEST_DB_PATH)
        insert_irrigation("Parcela Antiga Sem Dono", "05:00", utilizador_id=None, db_path=TEST_DB_PATH)
        orphan_conv = create_conversation("Conversa Sem Dono", utilizador_id=None, db_path=TEST_DB_PATH)

        # Registar Utilizador A e Utilizador B
        pwd_a = "Senh" + "aUtilizadorA1"
        pwd_b = "Senh" + "aUtilizadorB2"
        created_secrets.extend([pwd_a, pwd_b])

        _, _, body_a = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Utilizador A", "email": "usera@nonglink.ao", "senha": pwd_a},
        )
        _, _, body_b = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Utilizador B", "email": "userb@nonglink.ao", "senha": pwd_b},
        )
        data_a = json.loads(body_a.decode("utf-8"))
        data_b = json.loads(body_b.decode("utf-8"))
        tok_a = data_a["token"]
        tok_b = data_b["token"]
        user_b_id = data_b["utilizador"]["id"]
        created_secrets.extend([tok_a, tok_b])

        hdr_a = {"Authorization": f"Bearer {tok_a}"}
        hdr_b = {"Authorization": f"Bearer {tok_b}"}

        # 1. Linhas sem dono não são visíveis
        code_orphan, _, _ = asgi_request("GET", f"/conversas/{orphan_conv['id']}", headers=hdr_a)
        _, _, list_convs_a = asgi_request("GET", "/conversas", headers=hdr_a)
        _, _, list_anun_a = asgi_request("GET", "/anuncios", headers=hdr_a)
        _, _, list_regas_a = asgi_request("GET", "/regas", headers=hdr_a)
        orphans_hidden = (
            code_orphan == 404
            and len(json.loads(list_convs_a.decode("utf-8"))) == 0
            and len(json.loads(list_anun_a.decode("utf-8"))) == 0
            and len(json.loads(list_regas_a.decode("utf-8"))) == 0
        )
        report("Linhas antigas sem dono (utilizador_id=NULL) ficam ocultas", orphans_hidden)

        # 2. Utilizador B cria conversa, anúncio, rega, foto e acção pendente; A tenta aceder
        _, _, conv_b_raw = asgi_request(
            "POST",
            "/conversas",
            headers=hdr_b,
            json_body={"titulo": "Conversa Privada B"},
        )
        conv_b_id = json.loads(conv_b_raw.decode("utf-8"))["id"]

        insert_listing("tomate B", 120.0, 850.0, utilizador_id=user_b_id, db_path=TEST_DB_PATH)
        insert_irrigation("Parcela Secreta B", "07:30", utilizador_id=user_b_id, db_path=TEST_DB_PATH)

        PENDING_SESSIONS[conv_b_id] = {
            "utilizador_id": user_b_id,
            "history": [],
            "pending_message_id": None,
            "pending_call": {
                "call_id": "call_b_1",
                "ferramenta": "agendar_rega",
                "argumentos": {"parcela": "Parcela Secreta B", "hora": "08:00"},
            },
            "remaining_calls": [],
            "turn": 1,
            "lang": "pt",
            "executed_actions": [],
            "descricao": "Agendar rega na Parcela Secreta B",
        }

        code_read_b, _, _ = asgi_request("GET", f"/conversas/{conv_b_id}", headers=hdr_a)
        code_msgs_b, _, _ = asgi_request("GET", f"/conversas/{conv_b_id}/mensagens", headers=hdr_a)
        code_ren_b, _, _ = asgi_request(
            "PATCH",
            f"/conversas/{conv_b_id}",
            headers=hdr_a,
            json_body={"titulo": "Invadida por A"},
        )
        code_del_b, _, _ = asgi_request("DELETE", f"/conversas/{conv_b_id}", headers=hdr_a)
        code_conf_b, _, _ = asgi_request(
            "POST",
            "/confirmar",
            headers=hdr_a,
            json_body={"sessao": conv_b_id, "confirmar": True},
        )

        conv_isolation_ok = (
            [code_read_b, code_msgs_b, code_ren_b, code_del_b, code_conf_b] == [404, 404, 404, 404, 404]
            and conv_b_id in PENDING_SESSIONS
        )
        report(
            "A não consegue ler, renomear, apagar nem confirmar acções da conversa do B (404)",
            conv_isolation_ok,
        )

        # 3. A não vê anúncios nem regas do B
        _, _, anun_a_raw = asgi_request("GET", "/anuncios", headers=hdr_a)
        _, _, regas_a_raw = asgi_request("GET", "/regas", headers=hdr_a)
        _, _, anun_b_raw = asgi_request("GET", "/anuncios", headers=hdr_b)
        _, _, regas_b_raw = asgi_request("GET", "/regas", headers=hdr_b)

        listings_regas_ok = (
            len(json.loads(anun_a_raw.decode("utf-8"))) == 0
            and len(json.loads(regas_a_raw.decode("utf-8"))) == 0
            and len(json.loads(anun_b_raw.decode("utf-8"))) == 1
            and len(json.loads(regas_b_raw.decode("utf-8"))) == 1
        )
        report(
            "A não vê os anúncios nem as regas do B",
            listings_regas_ok,
        )

        # 4. Fotos: B carrega foto; A recebe 404 em /foto/{id} e /fotos/{id}
        mp_body, mp_ct = _multipart_file_body(
            "imagem",
            "lote_b.jpg",
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01",
            "image/jpeg",
        )
        code_up_b, _, up_b_raw = asgi_request(
            "POST",
            "/foto",
            headers=hdr_b,
            raw_body=mp_body,
            content_type=mp_ct,
        )
        up_b_data = json.loads(up_b_raw.decode("utf-8"))
        foto_b_id = up_b_data["foto_id"]
        temp_files.append(Path(up_b_data["caminho"]))

        code_foto_b_by_b, _, _ = asgi_request("GET", f"/foto/{foto_b_id}", headers=hdr_b)
        code_foto_b_by_a1, _, _ = asgi_request("GET", f"/foto/{foto_b_id}", headers=hdr_a)
        code_foto_b_by_a2, _, _ = asgi_request("GET", f"/fotos/{foto_b_id}", headers=hdr_a)
        code_agente_foto_b, _, _ = asgi_request(
            "POST",
            "/agente",
            headers=hdr_a,
            json_body={"sessao": "conv-a", "mensagem": "analisa", "foto_id": foto_b_id},
        )

        photo_isolation_ok = (
            code_up_b == 200
            and len(foto_b_id) >= 16
            and code_foto_b_by_b == 200
            and code_foto_b_by_a1 == 404
            and code_foto_b_by_a2 == 404
            and code_agente_foto_b == 404
        )
        report(
            "A não consegue obter nem usar a foto do B em /foto/{id}, /fotos/{id} e /agente (404)",
            photo_isolation_ok,
        )

        # 5. Dois convidados (/auth/demo) não vêem dados um do outro
        _, _, g1_raw = asgi_request("POST", "/auth/demo")
        _, _, g2_raw = asgi_request("POST", "/auth/demo")
        g1 = json.loads(g1_raw.decode("utf-8"))
        g2 = json.loads(g2_raw.decode("utf-8"))
        created_secrets.extend([g1["token"], g2["token"]])
        hdr_g1 = {"Authorization": f"Bearer {g1['token']}"}
        hdr_g2 = {"Authorization": f"Bearer {g2['token']}"}

        _, _, conv_g1_raw = asgi_request(
            "POST",
            "/conversas",
            headers=hdr_g1,
            json_body={"titulo": "Conversa Convidado 1"},
        )
        conv_g1_id = json.loads(conv_g1_raw.decode("utf-8"))["id"]
        insert_listing("mandioca convidado 1", 80.0, 450.0, utilizador_id=g1["utilizador"]["id"], db_path=TEST_DB_PATH)
        insert_irrigation("Parcela Convidado 1", "06:15", utilizador_id=g1["utilizador"]["id"], db_path=TEST_DB_PATH)

        code_g2_read_g1, _, _ = asgi_request("GET", f"/conversas/{conv_g1_id}", headers=hdr_g2)
        _, _, g2_convs = asgi_request("GET", "/conversas", headers=hdr_g2)
        _, _, g2_anun = asgi_request("GET", "/anuncios", headers=hdr_g2)
        _, _, g2_regas = asgi_request("GET", "/regas", headers=hdr_g2)

        guests_isolated = (
            g1["utilizador"]["id"] != g2["utilizador"]["id"]
            and g1["utilizador"]["email"].endswith("@convidado.nonglink")
            and g2["utilizador"]["email"].endswith("@convidado.nonglink")
            and code_g2_read_g1 == 404
            and len(json.loads(g2_convs.decode("utf-8"))) == 0
            and len(json.loads(g2_anun.decode("utf-8"))) == 0
            and len(json.loads(g2_regas.decode("utf-8"))) == 0
        )
        report(
            "Dois convidados (/auth/demo) têm contas distintas e não vêem dados um do outro",
            guests_isolated,
        )

        # 6. Nenhum log contém palavras-passe ou tokens
        log_text = LOG_FILE_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_FILE_PATH.exists() else ""
        no_leaks = all(secret not in log_text for secret in created_secrets if secret)
        report(
            "Nenhum ficheiro de log contém palavras-passe ou tokens",
            no_leaks,
        )

    finally:
        PENDING_SESSIONS.clear()
        _cleanup_test_db(temp_files)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
