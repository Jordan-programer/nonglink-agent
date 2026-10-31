"""Testes de protecção contra abuso, quotas, uploads, manutenção e retenção (Tarefa 9).

Cobre:
- Quota diária por utilizador (convidados e registados) com 429
- Quota diária global com 429
- Limite de pedidos por IP no /auth/demo (máximo 5 por IP por hora) com 429
- Upload demasiado grande (>5MB imagem, >2MB áudio) com 413
- Tipo de ficheiro inválido (validação de magic bytes em JPEG, PNG, WebP) com 415
- Modo de manutenção de emergência (MODO_MANUTENCAO=1) com 503
- Limpeza de contas de convidados (>24h) e conversas antigas de utilizadores registados (>30d)
- Cabeçalhos de segurança na resposta de fotos (Cache-Control, X-Content-Type-Options)

Usa uma base de dados temporária `nonglink_test.db` apagada no fim e imprime OK/FALHOU
por cada caso, sem nunca expor palavras-passe nem tokens.
"""

from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import wave

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
    create_guest_user,
    create_session_token,
    create_user,
    executar_limpeza_dados_expirados,
    get_connection,
    get_user_by_id,
    init_db,
    insert_message,
    insert_photo,
    registar_chamada_modelo,
)
from app.main import (  # noqa: E402
    app,
    reset_login_rate_limits,
)
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


def _multipart_file_with_fields(
    field_name: str,
    filename: str,
    content: bytes,
    mime: str,
    extra_fields: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, str]:
    boundary = "----NongLinkTestBoundary7MA4YWxkTrZu0gW"
    lines: List[bytes] = []
    if extra_fields:
        for k, v in extra_fields.items():
            lines.extend([
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"),
                f"{v}\r\n".encode("utf-8"),
            ])
    lines.extend([
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
        content,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def _make_dummy_wav(duration_sec: float) -> bytes:
    """Generate minimal valid PCM WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        frames_count = int(8000 * duration_sec)
        wf.writeframes(b"\x00\x00" * frames_count)
    return buf.getvalue()


def run_tests() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    temp_files: List[Path] = []
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
        # Create registered user and guest user
        user_reg = create_user(
            nome="Agricultor Teste",
            email="agricultor@nonglink.ao",
            senha="PalavraPasse#2026",
            db_path=TEST_DB_PATH,
        )
        tok_reg = create_session_token(user_reg["id"], db_path=TEST_DB_PATH)
        hdr_reg = {"Authorization": f"Bearer {tok_reg}"}

        user_gst = create_guest_user(db_path=TEST_DB_PATH)
        tok_gst = create_session_token(user_gst["id"], is_guest=True, db_path=TEST_DB_PATH)
        hdr_gst = {"Authorization": f"Bearer {tok_gst}"}

        # Valid JPEG minimal bytes
        valid_jpeg = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xFF\xDB\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xFF\xC0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xFF\xDA\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xFF\xD9"

        # -------------------------------------------------------------
        # 1. Quota por utilizador (15 para convidado, 40 para registado)
        # -------------------------------------------------------------
        os.environ["QUOTA_DIARIA_CONVIDADO"] = "2"
        # Convidado com 0 chamadas faz upload de foto -> OK (200)
        body_p1, ct_p1 = _multipart_file_body("imagem", "foto1.jpg", valid_jpeg, "image/jpeg")
        code1, _, resp1 = asgi_request("POST", "/foto", headers=hdr_gst, raw_body=body_p1, content_type=ct_p1)
        r1_json = json.loads(resp1.decode("utf-8")) if code1 == 200 else {}
        if r1_json.get("caminho"):
            temp_files.append(Path(r1_json["caminho"]))

        # Segunda chamada de convidado -> OK (atinge 2)
        body_p2, ct_p2 = _multipart_file_body("imagem", "foto2.jpg", valid_jpeg, "image/jpeg")
        code2, _, resp2 = asgi_request("POST", "/foto", headers=hdr_gst, raw_body=body_p2, content_type=ct_p2)
        r2_json = json.loads(resp2.decode("utf-8")) if code2 == 200 else {}
        if r2_json.get("caminho"):
            temp_files.append(Path(r2_json["caminho"]))

        # Terceira chamada de convidado -> 429
        body_p3, ct_p3 = _multipart_file_body("imagem", "foto3.jpg", valid_jpeg, "image/jpeg")
        code3, _, resp3 = asgi_request("POST", "/foto", headers=hdr_gst, raw_body=body_p3, content_type=ct_p3)
        res3_json = json.loads(resp3.decode("utf-8")) if code3 == 429 else {}

        quota_user_ok = (
            code1 == 200
            and code2 == 200
            and code3 == 429
            and "Atingiu o limite diário da demonstração" in res3_json.get("detail", "")
        )
        report("Quota diária por utilizador devolve 429 ao atingir limite", quota_user_ok)

        # -------------------------------------------------------------
        # 2. Quota global (por omissão 400; testa com limite atingido)
        # -------------------------------------------------------------
        # Utilizador registado ainda tem quota individual livre, mas quota global está atingida
        os.environ["QUOTA_DIARIA_CONVIDADO"] = "15"
        os.environ["QUOTA_DIARIA_REGISTADO"] = "40"
        os.environ["QUOTA_DIARIA_GLOBAL"] = "2"  # Já foram feitas 2 chamadas acima

        code_global, _, resp_global = asgi_request(
            "POST",
            "/agente",
            headers=hdr_reg,
            json_body={"mensagem": "Olá agente"},
        )
        res_global_json = json.loads(resp_global.decode("utf-8")) if code_global == 429 else {}
        quota_global_ok = (
            code_global == 429
            and "Atingiu o limite diário da demonstração" in res_global_json.get("detail", "")
        )
        report("Quota global diária devolve 429", quota_global_ok)

        # Restaura quota global alta para os testes seguintes
        os.environ["QUOTA_DIARIA_GLOBAL"] = "400"

        # -------------------------------------------------------------
        # 3. Limite por IP no /auth/demo (máx 5 por IP por hora)
        # -------------------------------------------------------------
        reset_login_rate_limits()
        demo_ip = "192.168.1.55"
        demo_codes = []
        for _ in range(5):
            c_demo, _, _ = asgi_request("POST", "/auth/demo", client_ip=demo_ip)
            demo_codes.append(c_demo)
        # 6.ª tentativa deve falhar com 429
        c_demo_6, _, resp_demo_6 = asgi_request("POST", "/auth/demo", client_ip=demo_ip)
        res_demo_6 = json.loads(resp_demo_6.decode("utf-8")) if c_demo_6 == 429 else {}

        # Outro IP diferente ainda consegue criar conta normalmente
        c_demo_other, _, _ = asgi_request("POST", "/auth/demo", client_ip="192.168.1.56")

        demo_rate_ok = (
            all(c == 200 for c in demo_codes)
            and c_demo_6 == 429
            and "Demasiadas contas de demonstração" in res_demo_6.get("detail", "")
            and c_demo_other == 200
        )
        report("Limite de pedidos por IP no /auth/demo bloqueia à 6.ª tentativa", demo_rate_ok)

        # -------------------------------------------------------------
        # 4. Uploads: Imagem > 5MB e Áudio > 2MB rejeitados com 413
        # -------------------------------------------------------------
        big_image_bytes = b"\xFF\xD8\xFF" + b"\x00" * (5 * 1024 * 1024 + 50)
        body_big_img, ct_big_img = _multipart_file_body("imagem", "pesada.jpg", big_image_bytes, "image/jpeg")
        code_big_img, _, resp_big_img = asgi_request("POST", "/foto", headers=hdr_reg, raw_body=body_big_img, content_type=ct_big_img)

        big_audio_bytes = b"\x00" * (2 * 1024 * 1024 + 50)
        body_big_aud, ct_big_aud = _multipart_file_body("audio", "audio_pesado.wav", big_audio_bytes, "audio/wav")
        code_big_aud, _, resp_big_aud = asgi_request("POST", "/voz", headers=hdr_reg, raw_body=body_big_aud, content_type=ct_big_aud)

        upload_size_ok = (code_big_img == 413 and code_big_aud == 413)
        report("Uploads demasiado grandes rejeitados com 413 (>5MB imagem, >2MB áudio)", upload_size_ok)

        # -------------------------------------------------------------
        # 5. Validação de formato de imagem por magic bytes (415)
        # -------------------------------------------------------------
        sess_reg_ft = {"sessao": "sess_reg_fotos"}
        fake_jpeg = b"ESTE_E_UM_FICHEIRO_DE_TEXTO_COM_EXTENSAO_FALSA"
        body_fake, ct_fake = _multipart_file_with_fields("imagem", "virus.jpg", fake_jpeg, "image/jpeg", extra_fields=sess_reg_ft)
        code_fake, _, resp_fake = asgi_request("POST", "/foto", headers=hdr_reg, raw_body=body_fake, content_type=ct_fake)

        # Valid PNG magic bytes
        valid_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        body_png, ct_png = _multipart_file_with_fields("imagem", "teste.png", valid_png, "image/png", extra_fields=sess_reg_ft)
        code_png, _, resp_png = asgi_request("POST", "/foto", headers=hdr_reg, raw_body=body_png, content_type=ct_png)
        r_png_json = json.loads(resp_png.decode("utf-8")) if code_png == 200 else {}
        if r_png_json.get("caminho"):
            temp_files.append(Path(r_png_json["caminho"]))

        # Valid WebP magic bytes (RIFF .... WEBP)
        valid_webp = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x00\x07\x01\x02\x03\x04\x05\x06\x07"
        body_webp, ct_webp = _multipart_file_with_fields("imagem", "teste.webp", valid_webp, "image/webp", extra_fields=sess_reg_ft)
        code_webp, _, resp_webp = asgi_request("POST", "/foto", headers=hdr_reg, raw_body=body_webp, content_type=ct_webp)
        r_webp_json = json.loads(resp_webp.decode("utf-8")) if code_webp == 200 else {}
        if r_webp_json.get("caminho"):
            temp_files.append(Path(r_webp_json["caminho"]))

        magic_bytes_ok = (code_fake == 415 and code_png == 200 and code_webp == 200)
        report("Validação de magic bytes em imagem rejeita extensão forjada com 415", magic_bytes_ok)

        # -------------------------------------------------------------
        # 6. Modo de manutenção de emergência (MODO_MANUTENCAO=1 -> 503)
        # -------------------------------------------------------------
        os.environ["MODO_MANUTENCAO"] = "1"
        c_man_ag, _, r_man_ag = asgi_request("POST", "/agente", headers=hdr_reg, json_body={"mensagem": "olá"})
        c_man_ft, _, r_man_ft = asgi_request("POST", "/foto", headers=hdr_reg, raw_body=body_png, content_type=ct_png)

        os.environ["MODO_MANUTENCAO"] = "0"
        c_pos_ag, _, _ = asgi_request("GET", "/health", headers=hdr_reg)

        manutencao_ok = (
            c_man_ag == 503
            and c_man_ft == 503
            and "manutenção" in json.loads(r_man_ag.decode("utf-8")).get("detail", "")
            and c_pos_ag == 200
        )
        report("Modo de manutenção (MODO_MANUTENCAO=1) bloqueia rotas com 503", manutencao_ok)

        # -------------------------------------------------------------
        # 7. Cabeçalhos de segurança na resposta de fotos
        # -------------------------------------------------------------
        photo_id = r_png_json.get("foto_id")
        code_foto_h, headers_foto_h, _ = asgi_request("GET", f"/foto/{photo_id}", headers=hdr_reg)
        headers_ok = (
            code_foto_h == 200
            and headers_foto_h.get("cache-control") == "private, no-store"
            and headers_foto_h.get("x-content-type-options") == "nosniff"
            and headers_foto_h.get("content-type") == "image/png"
        )
        report("Cabeçalhos de segurança na resposta de fotos (Cache-Control, nosniff)", headers_ok)

        # -------------------------------------------------------------
        # 8. Limpeza de convidados (>24h) e conversas antigas (>30d)
        # -------------------------------------------------------------
        # Cria convidado expirado (>24h) com foto no disco
        guest_exp = create_guest_user(db_path=TEST_DB_PATH)
        guest_exp_id = guest_exp["id"]
        old_guest_photo_file = UPLOADS_DIR / f"test_guest_old_{guest_exp_id}.jpg"
        old_guest_photo_file.write_bytes(valid_jpeg)
        temp_files.append(old_guest_photo_file)

        insert_photo(utilizador_id=guest_exp_id, caminho=str(old_guest_photo_file), foto_id=f"gfoto_{guest_exp_id}", db_path=TEST_DB_PATH)
        create_conversation(titulo="Conversa Velha Convidado", conversation_id=f"conv_gst_{guest_exp_id}", utilizador_id=guest_exp_id, db_path=TEST_DB_PATH)

        # Força data antiga (30 horas atrás) na tabela utilizadores
        past_guest_date = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S UTC")
        with get_connection(TEST_DB_PATH) as conn:
            conn.execute("UPDATE utilizadores SET criado_em = ? WHERE id = ?", (past_guest_date, guest_exp_id))
            conn.commit()

        # Cria utilizador registado com 1 conversa antiga (35 dias) e 1 recente (1 dia)
        user_clean = create_user(nome="Carlos Produtor", email="carlos@nonglink.ao", senha="SenhaSegura#2026", db_path=TEST_DB_PATH)
        user_clean_id = user_clean["id"]

        old_reg_photo = UPLOADS_DIR / f"test_reg_old_{user_clean_id}.jpg"
        old_reg_photo.write_bytes(valid_jpeg)
        temp_files.append(old_reg_photo)
        insert_photo(utilizador_id=user_clean_id, caminho=str(old_reg_photo), foto_id=f"rfoto_{user_clean_id}", db_path=TEST_DB_PATH)

        conv_antiga_id = f"conv_old_{user_clean_id}"
        conv_recente_id = f"conv_rec_{user_clean_id}"
        create_conversation(titulo="Conversa Antiga 35d", conversation_id=conv_antiga_id, utilizador_id=user_clean_id, db_path=TEST_DB_PATH)
        create_conversation(titulo="Conversa Recente 1d", conversation_id=conv_recente_id, utilizador_id=user_clean_id, db_path=TEST_DB_PATH)

        # Anexa foto à conversa antiga
        insert_message(
            conversa_id=conv_antiga_id,
            papel="utilizador",
            texto="Anexo foto antiga",
            anexo_json={"foto_id": f"rfoto_{user_clean_id}"},
            utilizador_id=user_clean_id,
            db_path=TEST_DB_PATH,
        )

        past_35d_date = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S UTC")
        with get_connection(TEST_DB_PATH) as conn:
            conn.execute("UPDATE conversas SET criada_em = ?, atualizada_em = ? WHERE id = ?", (past_35d_date, past_35d_date, conv_antiga_id))
            conn.commit()

        # Executa limpeza
        res_limpeza = executar_limpeza_dados_expirados(
            horas_convidado=24,
            dias_registado=30,
            db_path=TEST_DB_PATH,
        )

        # Verificações pós-limpeza:
        # 1) Convidado expirado foi apagado e foto removida do disco
        guest_in_db = get_user_by_id(guest_exp_id, db_path=TEST_DB_PATH)
        guest_file_exists = old_guest_photo_file.exists()

        # 2) Conversa antiga do utilizador registado foi apagada e foto removida
        with get_connection(TEST_DB_PATH) as conn:
            row_old_conv = conn.execute("SELECT id FROM conversas WHERE id = ?", (conv_antiga_id,)).fetchone()
            row_rec_conv = conn.execute("SELECT id FROM conversas WHERE id = ?", (conv_recente_id,)).fetchone()

        reg_old_file_exists = old_reg_photo.exists()

        limpeza_ok = (
            res_limpeza["contas_convidado_removidas"] >= 1
            and res_limpeza["conversas_antigas_removidas"] >= 1
            and guest_in_db is None
            and not guest_file_exists
            and row_old_conv is None
            and row_rec_conv is not None
            and not reg_old_file_exists
        )
        report("Limpeza de dados remove convidados >24h e conversas >30d mantendo ficheiros limpos", limpeza_ok)

    finally:
        _cleanup_test_db(temp_files)
        # Reset any env vars modified in tests
        os.environ["MODO_MANUTENCAO"] = "0"
        os.environ["QUOTA_DIARIA_CONVIDADO"] = "15"
        os.environ["QUOTA_DIARIA_REGISTADO"] = "40"
        os.environ["QUOTA_DIARIA_GLOBAL"] = "400"

    print(f"\nResultado final: {8 - failures}/8 testes com sucesso.")
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(run_tests())
