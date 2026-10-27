"""Testes de autenticação, sessões, palavras-passe, limite de tentativas e logs (Tarefa 7).

Usa uma base de dados temporária `nonglink_test.db` apagada no fim e imprime
OK/FALHOU por cada caso de teste, sem nunca escrever ou imprimir palavras-passe
ou tokens.
"""

from pathlib import Path
import hashlib
import io
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

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
    PBKDF2_ITERATIONS,
    _MIGRATED_DB_PATHS,
    authenticate_user,
    create_session_token,
    create_user,
    get_connection,
    get_user_by_token,
    init_db,
)
from app.main import app, reset_login_rate_limits  # noqa: E402


def asgi_request(
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Any] = None,
    raw_body: bytes = b"",
    content_type: Optional[str] = None,
    client_ip: str = "127.0.0.1",
) -> Tuple[int, Dict[str, str], bytes]:
    """Executa um pedido HTTP contra a aplicação ASGI FastAPI sem usar sockets do SO."""
    if json_body is not None:
        body_bytes = json.dumps(json_body).encode("utf-8")
        ctype = content_type or "application/json"
    else:
        body_bytes = raw_body
        ctype = content_type or ""

    raw_headers: List[Tuple[bytes, bytes]] = [
        (b"host", b"localhost:8000"),
    ]
    if ctype:
        raw_headers.append((b"content-type", ctype.encode("latin-1")))
    if body_bytes:
        raw_headers.append((b"content-length", str(len(body_bytes)).encode("latin-1")))
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    path_only, _, query_str = path.partition("?")
    scope: Dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path_only,
        "raw_path": path_only.encode("latin-1"),
        "query_string": query_str.encode("latin-1"),
        "headers": raw_headers,
        "client": (client_ip, 50000),
        "server": ("localhost", 8000),
    }

    sent_body = False
    status_code = 500
    resp_headers: Dict[str, str] = {}
    resp_chunks: List[bytes] = []

    async def receive() -> Dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Dict[str, Any]) -> None:
        nonlocal status_code, resp_headers
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            resp_headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            resp_chunks.append(message.get("body", b""))

    coro = app(scope, receive, send)
    try:
        while True:
            coro.send(None)
    except StopIteration:
        pass

    return status_code, resp_headers, b"".join(resp_chunks)


def _multipart_file_body(field_name: str, filename: str, content: bytes, mime: str) -> Tuple[bytes, str]:
    boundary = "----NongLinkTestBoundary7MA4YWxkTrZu0gW"
    lines = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
        content,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def _cleanup_test_db() -> None:
    _MIGRATED_DB_PATHS.discard(str(TEST_DB_PATH.resolve()))
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(TEST_DB_PATH) + suffix)
        p.unlink(missing_ok=True)


def run_tests() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _cleanup_test_db()
    init_db(TEST_DB_PATH)
    reset_login_rate_limits()

    failures = 0
    created_secrets: List[str] = []

    def report(case_name: str, passed: bool, detail: str = "") -> None:
        nonlocal failures
        status = "OK" if passed else "FALHOU"
        suffix = f" ({detail})" if detail else ""
        print(f"[{status}] {case_name}{suffix}")
        if not passed:
            failures += 1

    try:
        # 1. Sem token, todos os endpoints protegidos devolvem 401 (com e sem X-Require-Auth)
        protected_calls: List[Tuple[str, str, Optional[Any], bytes, Optional[str]]] = [
            ("GET", "/", None, b"", None),
            ("GET", "/health", None, b"", None),
            ("GET", "/auth/me", None, b"", None),
            ("POST", "/auth/logout", {}, b"", None),
            ("GET", "/conversas", None, b"", None),
            ("POST", "/conversas", {"titulo": "Teste"}, b"", None),
            ("GET", "/conversas/conv-1", None, b"", None),
            ("PATCH", "/conversas/conv-1", {"titulo": "Novo"}, b"", None),
            ("DELETE", "/conversas/conv-1", None, b"", None),
            ("GET", "/conversas/conv-1/mensagens", None, b"", None),
            ("GET", "/anuncios", None, b"", None),
            ("GET", "/regas", None, b"", None),
            ("GET", "/foto/id_inexistente", None, b"", None),
            ("GET", "/fotos/id_inexistente", None, b"", None),
            ("POST", "/confirmar", {"sessao": "conv-1", "confirmar": True}, b"", None),
            ("POST", "/agente", {"sessao": "conv-1", "mensagem": "olá"}, b"", None),
            ("POST", "/agent", {"sessao": "conv-1", "mensagem": "olá"}, b"", None),
        ]
        mp_img, mp_img_ct = _multipart_file_body("imagem", "f.jpg", b"\xff\xd8\xff\xe0JFIF", "image/jpeg")
        mp_aud, mp_aud_ct = _multipart_file_body("audio", "v.wav", b"RIFF0000WAVEfmt ", "audio/wav")
        protected_calls.append(("POST", "/foto", None, mp_img, mp_img_ct))
        protected_calls.append(("POST", "/voz", None, mp_aud, mp_aud_ct))

        all_401_no_hdr = True
        all_401_with_x_hdr = True
        for method, path, jbody, rbody, ctype in protected_calls:
            code1, _, _ = asgi_request(method, path, headers={}, json_body=jbody, raw_body=rbody, content_type=ctype)
            code2, _, _ = asgi_request(
                method,
                path,
                headers={"X-Require-Auth": "0"},
                json_body=jbody,
                raw_body=rbody,
                content_type=ctype,
            )
            code3, _, _ = asgi_request(
                method,
                path,
                headers={"X-Require-Auth": "false"},
                json_body=jbody,
                raw_body=rbody,
                content_type=ctype,
            )
            if code1 != 401:
                all_401_no_hdr = False
            if code2 != 401 or code3 != 401:
                all_401_with_x_hdr = False

        report(
            "Endpoints protegidos sem token devolvem 401 (sem X-Require-Auth)",
            all_401_no_hdr,
            f"{len(protected_calls)} endpoints verificados",
        )
        report(
            "Endpoints protegidos sem token devolvem 401 (com X-Require-Auth=0/false)",
            all_401_with_x_hdr,
            f"{len(protected_calls)} endpoints verificados",
        )

        # 2. Palavra-passe mínima (8 caracteres), email em minúsculas e PBKDF2 >= 600000 + rehash
        code_short, _, _ = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Agri Curta", "email": "curta@nonglink.ao", "senha": "1234567"},
        )
        test_pwd = "Senh" + "aForte#2026"
        created_secrets.append(test_pwd)
        code_reg, _, body_reg = asgi_request(
            "POST",
            "/auth/registar",
            json_body={"nome": "Agri Auth", "email": "  AGRI.AUTH@NongLink.AO ", "senha": test_pwd},
        )
        reg_data = json.loads(body_reg.decode("utf-8")) if code_reg == 200 else {}
        tok_active = reg_data.get("token", "")
        if tok_active:
            created_secrets.append(tok_active)

        # Verificar rehash de hash legado (100 000 iterações)
        leg_pwd = "Lega" + "do#123456"
        created_secrets.append(leg_pwd)
        leg_dk = hashlib.pbkdf2_hmac("sha256", leg_pwd.encode("utf-8"), b"salttest", 100_000).hex()
        with get_connection(TEST_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO utilizadores (id, nome, email, senha_hash, criado_em) VALUES (?, ?, ?, ?, ?)",
                ("USR-LEG-01", "Legado", "legado@nonglink.ao", f"salttest${leg_dk}", "2026-01-01"),
            )
            conn.commit()
        leg_user = authenticate_user("LEGADO@nonglink.ao", leg_pwd, db_path=TEST_DB_PATH)
        with get_connection(TEST_DB_PATH) as conn:
            upgraded_hash = conn.execute(
                "SELECT senha_hash FROM utilizadores WHERE id = ?", ("USR-LEG-01",)
            ).fetchone()["senha_hash"]

        pwd_policy_ok = (
            code_short == 400
            and code_reg == 200
            and reg_data.get("utilizador", {}).get("email") == "agri.auth@nonglink.ao"
            and PBKDF2_ITERATIONS >= 600_000
            and leg_user is not None
            and str(upgraded_hash).startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$")
        )
        report(
            "Palavras-passe (min 8 chars, PBKDF2 >= 600000, rehash legado, email minúsculas)",
            pwd_policy_ok,
        )

        # 3. Sessão expirada devolve 401 e é apagada; apenas SHA-256 guardado na BD; logout invalida token
        user_id = reg_data["utilizador"]["id"]
        expired_tok = create_session_token(
            user_id,
            expira_em="2020-01-01 00:00:00 UTC",
            db_path=TEST_DB_PATH,
        )
        created_secrets.append(expired_tok)
        expired_hash = hashlib.sha256(expired_tok.encode("utf-8")).hexdigest()

        with get_connection(TEST_DB_PATH) as conn:
            raw_tokens_in_db = [
                r["token"] for r in conn.execute("SELECT token FROM sessoes_auth").fetchall()
            ]
        only_sha256_in_db = (
            tok_active not in raw_tokens_in_db
            and expired_tok not in raw_tokens_in_db
            and all(len(t) == 64 for t in raw_tokens_in_db)
        )

        code_exp, _, _ = asgi_request(
            "GET",
            "/auth/me",
            headers={"Authorization": f"Bearer {expired_tok}"},
        )
        with get_connection(TEST_DB_PATH) as conn:
            exp_still_exists = conn.execute(
                "SELECT count(*) AS c FROM sessoes_auth WHERE token = ?",
                (expired_hash,),
            ).fetchone()["c"]

        code_me_before, _, _ = asgi_request(
            "GET",
            "/auth/me",
            headers={"Authorization": f"Bearer {tok_active}"},
        )
        code_logout, _, _ = asgi_request(
            "POST",
            "/auth/logout",
            headers={"Authorization": f"Bearer {tok_active}"},
            json_body={},
        )
        code_me_after, _, _ = asgi_request(
            "GET",
            "/auth/me",
            headers={"Authorization": f"Bearer {tok_active}"},
        )

        report(
            "Sessão guarda apenas SHA-256, sessão expirada devolve 401 e é apagada",
            only_sha256_in_db and code_exp == 401 and exp_still_exists == 0,
        )
        report(
            "Logout (/auth/logout) invalida o token imediatamente (401 após logout)",
            code_me_before == 200 and code_logout == 200 and code_me_after == 401,
        )

        # 4. Login errado devolve mensagem genérica e 6.º intento falhado é bloqueado
        reset_login_rate_limits()
        wrong_pwd = "Senh" + "aErrada999"
        created_secrets.append(wrong_pwd)
        login_codes: List[int] = []
        login_details: List[str] = []
        for _ in range(6):
            c_status, _, c_body = asgi_request(
                "POST",
                "/auth/login",
                json_body={"email": "agri.auth@nonglink.ao", "senha": wrong_pwd},
                client_ip="10.20.30.40",
            )
            login_codes.append(c_status)
            login_details.append(json.loads(c_body.decode("utf-8")).get("detail", ""))

        rate_limit_ok = (
            login_codes[:5] == [401, 401, 401, 401, 401]
            and login_codes[5] == 429
            and all(d == "Email ou palavra-passe incorrectos" for d in login_details[:5])
        )
        report(
            "Login errado devolve 'Email ou palavra-passe incorrectos' e 6.º intento é bloqueado (429)",
            rate_limit_ok,
        )

        # 5. Nenhum log contém palavras-passe ou tokens
        log_text = LOG_FILE_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_FILE_PATH.exists() else ""
        no_leaks = all(secret not in log_text for secret in created_secrets if secret)
        report(
            "Nenhum ficheiro de log contém palavras-passe ou tokens",
            no_leaks,
        )

    finally:
        reset_login_rate_limits()
        _cleanup_test_db()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
