"""Testes das rotas de conta e perfil (Tarefa A2).

Cobre:
- GET /auth/eu (criado_em, convidado, expira_em para convidados)
- PATCH /auth/eu (validação de nome 1-60 chars, sem chars de controlo, email inalterável)
- POST /auth/senha (rejeição de convidados, senha actual errada, nova curta, invalidação de outras sessões)
- POST /auth/sair-todas (invalidação de todas as sessões, 204)
- DELETE /conversas (apaga todas as conversas e fotos anexas do utilizador, mantém anúncios e regas)
- DELETE /auth/eu (apaga utilizador e tudo associado, ficheiros removidos, utilizador B intacto)
- 401 sem token em todos os endpoints novos
- Verificação de logs sem palavras-passe ou tokens
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

from app.config import LOG_FILE_PATH, UPLOADS_DIR  # noqa: E402
from app.db import (  # noqa: E402
    _MIGRATED_DB_PATHS,
    create_session_token,
    create_user,
    get_connection,
    init_db,
    insert_irrigation,
    insert_listing,
)
from app.main import app, reset_login_rate_limits  # noqa: E402
from tests.test_auth import _multipart_file_body, asgi_request  # noqa: E402


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

    temp_files: List[Path] = []
    created_secrets: List[str] = []
    _cleanup_test_db(temp_files)
    init_db(TEST_DB_PATH)
    reset_login_rate_limits()

    failures = 0

    def report(case_name: str, passed: bool, detail: str = "") -> None:
        nonlocal failures
        status = "OK" if passed else "FALHOU"
        suffix = f" ({detail})" if detail else ""
        print(f"[{status}] {case_name}{suffix}")
        if not passed:
            failures += 1

    try:
        # 1. 401 sem token em todos os novos endpoints
        new_endpoints = [
            ("GET", "/auth/eu", None),
            ("PATCH", "/auth/eu", {"nome": "Teste"}),
            ("POST", "/auth/senha", {"senha_actual": "12345678", "senha_nova": "87654321"}),
            ("POST", "/auth/sair-todas", None),
            ("DELETE", "/conversas", None),
            ("DELETE", "/auth/eu", {"senha": "12345678"}),
        ]
        all_401 = True
        for m, path, payload in new_endpoints:
            code, _, _ = asgi_request(m, path, json_body=payload)
            if code != 401:
                all_401 = False
        report("Endpoints de conta sem token devolvem 401", all_401)

        # Registar Utilizadores A e B
        pwd_a = "Palavra#A2026"
        pwd_b = "Palavra#B2026"
        created_secrets.extend([pwd_a, pwd_b])

        _, _, body_a = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Manuel Costa", "email": "manuel@nonglink.ao", "senha": pwd_a},
        )
        _, _, body_b = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Teresa Bento", "email": "teresa@nonglink.ao", "senha": pwd_b},
        )
        tok_a = json.loads(body_a.decode("utf-8"))["token"]
        tok_b = json.loads(body_b.decode("utf-8"))["token"]
        user_a_id = json.loads(body_a.decode("utf-8"))["utilizador"]["id"]
        user_b_id = json.loads(body_b.decode("utf-8"))["utilizador"]["id"]
        created_secrets.extend([tok_a, tok_b])

        hdr_a = {"Authorization": f"Bearer {tok_a}"}
        hdr_b = {"Authorization": f"Bearer {tok_b}"}

        # 2. GET /auth/eu para utilizador normal vs convidado
        code_eu_a, _, body_eu_a = asgi_request("GET", "/auth/eu", headers=hdr_a)
        res_eu_a = json.loads(body_eu_a.decode("utf-8"))
        u_eu_a = res_eu_a.get("utilizador", {})
        get_eu_a_ok = (
            code_eu_a == 200
            and u_eu_a.get("email") == "manuel@nonglink.ao"
            and u_eu_a.get("convidado") is False
            and "criado_em" in u_eu_a
            and "expira_em" not in u_eu_a
        )

        _, _, body_guest = asgi_request("POST", "/auth/demo")
        tok_guest = json.loads(body_guest.decode("utf-8"))["token"]
        created_secrets.append(tok_guest)
        hdr_guest = {"Authorization": f"Bearer {tok_guest}"}

        code_eu_g, _, body_eu_g = asgi_request("GET", "/auth/eu", headers=hdr_guest)
        res_eu_g = json.loads(body_eu_g.decode("utf-8"))
        u_eu_g = res_eu_g.get("utilizador", {})
        get_eu_g_ok = (
            code_eu_g == 200
            and u_eu_g.get("convidado") is True
            and "expira_em" in u_eu_g
        )
        report("GET /auth/eu devolve criado_em, convidado e expira_em para convidados", get_eu_a_ok and get_eu_g_ok)

        # 3. PATCH /auth/eu (mudar nome, validações 1-60 chars, sem controlo)
        code_patch_empty, _, _ = asgi_request("PATCH", "/auth/eu", headers=hdr_a, json_body={"nome": "   "})
        code_patch_long, _, _ = asgi_request("PATCH", "/auth/eu", headers=hdr_a, json_body={"nome": "A" * 61})
        code_patch_ctrl, _, _ = asgi_request("PATCH", "/auth/eu", headers=hdr_a, json_body={"nome": "Manuel\x07Costa"})
        code_patch_ok, _, body_patch_ok = asgi_request(
            "PATCH", "/auth/eu", headers=hdr_a, json_body={"nome": "  Manuel Silva Costa  "}
        )
        res_patch = json.loads(body_patch_ok.decode("utf-8")).get("utilizador", {})
        patch_validations_ok = (
            code_patch_empty == 400
            and code_patch_long == 400
            and code_patch_ctrl == 400
            and code_patch_ok == 200
            and res_patch.get("nome") == "Manuel Silva Costa"
            and res_patch.get("email") == "manuel@nonglink.ao"
        )
        report("PATCH /auth/eu valida nome (1-60 caracteres, sem chars de controlo) e mantém email", patch_validations_ok)

        # 4. POST /auth/senha (convidado dá 400; senha errada; nova curta; sessões antigas invalidadas e actual mantida)
        code_pw_guest, _, _ = asgi_request(
            "POST",
            "/auth/senha",
            headers=hdr_guest,
            json_body={"senha_actual": "qualquer", "senha_nova": "Nova123456"},
        )
        report("Convidado sem acesso a POST /auth/senha (devolve 400)", code_pw_guest == 400)

        # Criar segunda sessão para o Utilizador A (para testar que é invalidada após mudar senha)
        tok_a2 = create_session_token(user_a_id, db_path=TEST_DB_PATH)
        created_secrets.append(tok_a2)
        hdr_a2 = {"Authorization": f"Bearer {tok_a2}"}
        code_a2_check, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_a2)
        assert code_a2_check == 200

        # Tentativa com senha actual errada -> 401 genérico
        code_pw_wrong, _, body_pw_wrong = asgi_request(
            "POST",
            "/auth/senha",
            headers=hdr_a,
            json_body={"senha_actual": "Errada1234", "senha_nova": "NovaSenha#2026"},
        )
        # Tentativa com senha nova curta (< 8 chars) -> 400
        code_pw_short, _, _ = asgi_request(
            "POST",
            "/auth/senha",
            headers=hdr_a,
            json_body={"senha_actual": pwd_a, "senha_nova": "1234567"},
        )
        # Tentativa com senha igual -> 400
        code_pw_same, _, _ = asgi_request(
            "POST",
            "/auth/senha",
            headers=hdr_a,
            json_body={"senha_actual": pwd_a, "senha_nova": pwd_a},
        )

        new_pwd_a = "NovaSenha#A2026"
        created_secrets.append(new_pwd_a)
        code_pw_ok, _, _ = asgi_request(
            "POST",
            "/auth/senha",
            headers=hdr_a,
            json_body={"senha_actual": pwd_a, "senha_nova": new_pwd_a},
        )

        # tok_a continua válido; tok_a2 foi invalidado!
        code_a_still_ok, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_a)
        code_a2_revoked, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_a2)

        change_pw_ok = (
            code_pw_wrong == 401
            and code_pw_short == 400
            and code_pw_same == 400
            and code_pw_ok == 200
            and code_a_still_ok == 200
            and code_a2_revoked == 401
        )
        report(
            "POST /auth/senha valida senha actual e nova, mantém sessão actual e invalida as restantes",
            change_pw_ok,
        )

        # 5. POST /auth/sair-todas (invalida todas as sessões, incluindo a actual, 204)
        code_logout_all, _, _ = asgi_request("POST", "/auth/sair-todas", headers=hdr_a)
        code_a_after_all, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_a)
        report("POST /auth/sair-todas devolve 204 e invalida todas as sessões do utilizador", code_logout_all == 204 and code_a_after_all == 401)

        # Login de novo com o Utilizador A com a nova senha
        _, _, login_a_new = asgi_request(
            "POST",
            "/auth/login",
            json_body={"email": "manuel@nonglink.ao", "senha": new_pwd_a},
        )
        tok_a_new = json.loads(login_a_new.decode("utf-8"))["token"]
        created_secrets.append(tok_a_new)
        hdr_a_new = {"Authorization": f"Bearer {tok_a_new}"}

        # 6. DELETE /conversas (apaga todas as conversas do utilizador e fotos anexas, mantém anúncios e regas)
        # Utilizador A cria 2 conversas com 1 foto anexa, 1 anúncio e 1 rega
        _, _, c1_raw = asgi_request("POST", "/conversas", headers=hdr_a_new, json_body={"titulo": "Conversa A1"})
        _, _, c2_raw = asgi_request("POST", "/conversas", headers=hdr_a_new, json_body={"titulo": "Conversa A2"})
        c1_id = json.loads(c1_raw.decode("utf-8"))["id"]

        mp_img, mp_img_ct = _multipart_file_body("imagem", "foto_a.jpg", b"\xff\xd8\xff\xe0JFIF_CONV_A", "image/jpeg")
        _, _, up_a_raw = asgi_request("POST", "/foto", headers=hdr_a_new, raw_body=mp_img, content_type=mp_img_ct)
        foto_a_data = json.loads(up_a_raw.decode("utf-8"))
        foto_a_id = foto_a_data["foto_id"]
        foto_a_file = Path(foto_a_data["caminho"])
        temp_files.append(foto_a_file)
        assert foto_a_file.exists()

        # Associar mensagem com anexo à conversa c1 directamente na base de dados (sem chamar API externa da Meta)
        from app.db import insert_message
        insert_message(
            conversa_id=c1_id,
            papel="utilizador",
            texto="foto anexa",
            anexo_json={"foto_id": foto_a_id},
            utilizador_id=user_a_id,
            db_path=TEST_DB_PATH,
        )

        insert_listing("batata A", 200.0, 700.0, utilizador_id=user_a_id, db_path=TEST_DB_PATH)
        insert_irrigation("Parcela A Rega", "09:00", utilizador_id=user_a_id, db_path=TEST_DB_PATH)

        # Utilizador B também tem 1 conversa, 1 anúncio e 1 rega
        _, _, cb_raw = asgi_request("POST", "/conversas", headers=hdr_b, json_body={"titulo": "Conversa B"})
        insert_listing("cebola B", 150.0, 500.0, utilizador_id=user_b_id, db_path=TEST_DB_PATH)
        insert_irrigation("Parcela B Rega", "10:00", utilizador_id=user_b_id, db_path=TEST_DB_PATH)

        code_del_convs, _, body_del_convs = asgi_request("DELETE", "/conversas", headers=hdr_a_new)
        del_convs_res = json.loads(body_del_convs.decode("utf-8"))

        _, _, convs_a_after = asgi_request("GET", "/conversas", headers=hdr_a_new)
        _, _, anun_a_after = asgi_request("GET", "/anuncios", headers=hdr_a_new)
        _, _, regas_a_after = asgi_request("GET", "/regas", headers=hdr_a_new)

        _, _, convs_b_after = asgi_request("GET", "/conversas", headers=hdr_b)
        _, _, anun_b_after = asgi_request("GET", "/anuncios", headers=hdr_b)

        photo_deleted_from_disk = not foto_a_file.exists()

        delete_convs_ok = (
            code_del_convs == 200
            and del_convs_res.get("apagadas") == 2
            and len(json.loads(convs_a_after.decode("utf-8"))) == 0
            and len(json.loads(anun_a_after.decode("utf-8"))) == 1
            and len(json.loads(regas_a_after.decode("utf-8"))) == 1
            and len(json.loads(convs_b_after.decode("utf-8"))) == 1
            and len(json.loads(anun_b_after.decode("utf-8"))) == 1
            and photo_deleted_from_disk
        )
        report(
            "DELETE /conversas apaga conversas e ficheiros de fotos do utilizador, mantendo anúncios e regas",
            delete_convs_ok,
        )

        # 7. DELETE /auth/eu (apaga conta e tudo associado, validação de senha/confirmação, utilizador B intacto)
        # Upload de foto e criação de anúncio para B antes de apagar A
        mp_img_b, mp_img_b_ct = _multipart_file_body("imagem", "foto_b.jpg", b"\xff\xd8\xff\xe0JFIF_USER_B", "image/jpeg")
        _, _, up_b_raw = asgi_request("POST", "/foto", headers=hdr_b, raw_body=mp_img_b, content_type=mp_img_b_ct)
        foto_b_file = Path(json.loads(up_b_raw.decode("utf-8"))["caminho"])
        temp_files.append(foto_b_file)
        assert foto_b_file.exists()

        # A tenta apagar com senha errada -> 401
        code_del_acc_wrong, _, _ = asgi_request("DELETE", "/auth/eu", headers=hdr_a_new, json_body={"senha": "ErradaSenha"})
        assert code_del_acc_wrong == 401

        # A apaga com senha certa -> 204
        code_del_acc_ok, _, _ = asgi_request("DELETE", "/auth/eu", headers=hdr_a_new, json_body={"senha": new_pwd_a})
        # Token do A deixa de funcionar
        code_a_dead, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_a_new)

        # Convidado apaga com confirmacao == 'APAGAR'
        code_del_guest_wrong, _, _ = asgi_request("DELETE", "/auth/eu", headers=hdr_guest, json_body={"confirmacao": "NAO"})
        code_del_guest_ok, _, _ = asgi_request("DELETE", "/auth/eu", headers=hdr_guest, json_body={"confirmacao": "APAGAR"})
        code_guest_dead, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_guest)

        # Dados do Utilizador B continuam 100% intactos
        code_b_still_alive, _, _ = asgi_request("GET", "/auth/eu", headers=hdr_b)
        _, _, anun_b_final = asgi_request("GET", "/anuncios", headers=hdr_b)
        _, _, regas_b_final = asgi_request("GET", "/regas", headers=hdr_b)
        foto_b_file_intact = foto_b_file.exists()

        delete_account_ok = (
            code_del_acc_ok == 204
            and code_a_dead == 401
            and code_del_guest_wrong == 400
            and code_del_guest_ok == 204
            and code_guest_dead == 401
            and code_b_still_alive == 200
            and len(json.loads(anun_b_final.decode("utf-8"))) == 1
            and len(json.loads(regas_b_final.decode("utf-8"))) == 1
            and foto_b_file_intact
        )
        report(
            "DELETE /auth/eu apaga conta e todos os dados associados; Utilizador B intacto",
            delete_account_ok,
        )

        # 8. Nenhum log contém senhas ou tokens
        log_text = LOG_FILE_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_FILE_PATH.exists() else ""
        no_leaks = all(secret not in log_text for secret in created_secrets if secret)
        report("Nenhum log contém palavras-passe ou tokens", no_leaks)

    finally:
        reset_login_rate_limits()
        _cleanup_test_db(temp_files)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
