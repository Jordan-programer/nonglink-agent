"""Suíte de testes para a camada de integração com a API REST do NongLink.

Utiliza httpx.MockTransport para simular a API do NongLink sem rede real,
cobrindo todos os requisitos:
- Envio do Bearer token nas chamadas protegidas
- Erro 401 (sessão inválida/expirada)
- Erro 404 (cultura ou recurso não encontrado)
- Erro 422 (validação de dados)
- Erros 5xx e repetições (retry apenas em erros de rede e 502/503/504)
- Timeout e reconciliação (consulta /products/mine e /irrigations/mine sem duplicar)
- Resolução de cultura (sem acentos) e de parcela (0, 1 ou várias)
- Conflito 409 (sobreposição de rega)
- Paridade de contrato entre SandboxPlataforma e ApiPlataforma
- Teste de integração real (desativado por omissão, requer TEST_REAL_NONGLINK=1).
"""

import os
import json
import time
from typing import Any, Dict, List
import pytest
import httpx
from fastapi.testclient import TestClient

from app.integracao.base import Plataforma
from app.integracao.sandbox import SandboxPlataforma
from app.integracao.api import (
    ApiPlataforma,
    limpar_caches_api,
    _remover_acentos,
)
from app.integracao.fabrica import obter_plataforma, redefinir_plataforma


@pytest.fixture(autouse=True)
def reset_state():
    """Limpa estado e caches antes de cada teste."""
    limpar_caches_api()
    redefinir_plataforma()
    yield
    limpar_caches_api()
    redefinir_plataforma()


# ---------------------------------------------------------------------------
# 1. Envio do token do utilizador nas chamadas protegidas
# ---------------------------------------------------------------------------
def test_envio_token_bearer():
    """Garante que o token Bearer do utilizador é enviado no cabeçalho Authorization."""
    requests_received: List[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        if request.url.path == "/api/v1/auth/me":
            auth = request.headers.get("authorization", "")
            if auth == "Bearer token-secreto-123":
                return httpx.Response(200, json={"id": 42, "full_name": "António Agricultor", "region_id": 2})
            return httpx.Response(401, json={"detail": "Não autorizado"})
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Parcela Norte"}])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    user = api.obter_utilizador_me("token-secreto-123")
    assert user["id"] == 42
    assert len(requests_received) >= 1
    assert requests_received[0].headers["authorization"] == "Bearer token-secreto-123"

    farms = api.listar_farms_mine("token-secreto-123")
    assert len(farms) == 1
    assert farms[0]["id"] == 10
    assert requests_received[1].headers["authorization"] == "Bearer token-secreto-123"


# ---------------------------------------------------------------------------
# 2. Erro 401 traduzido de forma segura
# ---------------------------------------------------------------------------
def test_erro_401_token_invalido_ou_expirado():
    """Garante que o erro 401 do NongLink limpa o cache e retorna utilizador vazio."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Token expirado ou inválido"})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    user = api.obter_utilizador_me("token-expirado")
    assert user == {}


# ---------------------------------------------------------------------------
# 3. Erro 404 e resolução de culturas/parcelas
# ---------------------------------------------------------------------------
def test_erro_404_cultura_nao_encontrada():
    """Se a cultura não existir no catálogo da API, o agente informa de forma clara."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[
                {"id": 1, "name": "Milho", "default_unit": "kg"},
                {"id": 2, "name": "Tomate", "default_unit": "kg"},
            ])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.obter_preco("Pitaya Rara Desconhecida", token="dummy-token")
    assert res["status"] in ("not_found", "error")
    assert "Não foram encontrados dados da cultura" in res.get("mensagem", "")


def test_resolucao_parcela_zero_uma_ou_varias():
    """Verifica resolução de farm_id: 1 usa-a, várias pergunta, 0 explica sem criar nada."""
    def mock_farms_factory(farms_list):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/farms/mine":
                return httpx.Response(200, json=farms_list)
            return httpx.Response(404, json={})
        return handler

    # Caso 0 parcelas
    api_zero = ApiPlataforma(
        base_url="http://teste-nonglink/api/v1",
        transport=httpx.MockTransport(mock_farms_factory([])),
    )
    res_zero = api_zero.resolver_parcela(None, "token-1")
    assert res_zero["status"] == "sem_parcelas"
    assert "criar uma parcela" in res_zero["mensagem"]
    assert res_zero["farm_id"] is None

    # Caso 1 parcela
    api_uma = ApiPlataforma(
        base_url="http://teste-nonglink/api/v1",
        transport=httpx.MockTransport(mock_farms_factory([{"id": 5, "name": "Quinta das Flores"}])),
    )
    res_uma = api_uma.resolver_parcela(None, "token-1")
    assert res_uma["status"] == "ok"
    assert res_uma["farm_id"] == 5

    # Caso várias parcelas sem especificar
    api_varias = ApiPlataforma(
        base_url="http://teste-nonglink/api/v1",
        transport=httpx.MockTransport(mock_farms_factory([
            {"id": 5, "name": "Quinta das Flores"},
            {"id": 8, "name": "Horta do Rio"},
        ])),
    )
    res_varias = api_varias.resolver_parcela(None, "token-1")
    assert res_varias["status"] == "multiplas"
    assert "Qual das suas parcelas" in res_varias["mensagem"]
    assert res_varias["farm_id"] is None

    # Caso várias parcelas mas especificando o nome da parcela
    res_especifica = api_varias.resolver_parcela("Horta do Rio", "token-1")
    assert res_especifica["status"] == "ok"
    assert res_especifica["farm_id"] == 8


# ---------------------------------------------------------------------------
# 4. Resolução de culturas sem acentos (insensível a acentos e maiúsculas)
# ---------------------------------------------------------------------------
def test_resolucao_culturas_sem_acentos():
    """Garante que 'feijao', 'FEIJÃO', 'mandioca', etc., correspondem corretamente."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[
                {"id": 1, "name": "Feijão", "default_unit": "kg"},
                {"id": 2, "name": "Mandioca", "default_unit": "kg"},
                {"id": 3, "name": "Tomate", "default_unit": "kg"},
            ])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    assert api.resolver_cultura("feijao")["id"] == 1
    assert api.resolver_cultura("FEIJÃO")["id"] == 1
    assert api.resolver_cultura("feijão fradinho")["id"] == 1
    assert api.resolver_cultura("mandioca")["id"] == 2
    assert api.resolver_cultura("tomates")["id"] == 3


# ---------------------------------------------------------------------------
# 5. Erro 422 de validação
# ---------------------------------------------------------------------------
def test_erro_422_validacao_segura():
    """Erros de validação (422) são tratados com segurança sem expor segredos."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[{"id": 1, "name": "Milho", "default_unit": "kg"}])
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Parcela 1"}])
        if request.url.path == "/api/v1/products/":
            return httpx.Response(422, json={"detail": [{"loc": ["body", "price_per_unit"], "msg": "Valor inválido"}]})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.criar_anuncio(
        cultura="Milho",
        quantidade_kg=50.0,
        preco_kz_kg=-10.0,
        confirmed=True,
        user={"id": 1},
        token="token-valido",
    )
    assert res["status"] == "error"
    assert "Erro do NongLink" in res["message"]


# ---------------------------------------------------------------------------
# 6. Erros 5xx e retentativas (máximo 2 repetições em 502/503/504)
# ---------------------------------------------------------------------------
def test_repeticoes_em_502_503_504():
    """Verifica retry em 502/503/504 até 2 repetições adicionais (total 3 tentativas)."""
    tentativas = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1
        if tentativas < 3:
            return httpx.Response(503, json={"detail": "Serviço temporariamente indisponível"})
        return httpx.Response(200, json=[{"id": 1, "name": "Milho", "default_unit": "kg"}])

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    culturas = api._obter_culturas()
    assert len(culturas) == 1
    assert tentativas == 3  # Tentativa inicial + 2 repetições


def test_nao_repete_em_500():
    """Erros 500 normais não sofrem retry cego."""
    tentativas = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1
        return httpx.Response(500, json={"detail": "Erro interno do servidor"})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    resp = api._request_with_retry("GET", "/crops/")
    assert resp.status_code == 500
    assert tentativas == 1  # Sem repetições


# ---------------------------------------------------------------------------
# 7. Timeout e Reconciliação sem duplicação de anúncios
# ---------------------------------------------------------------------------
def test_timeout_reconciliacao_produto_com_sucesso():
    """Após timeout na criação do produto, consulta /products/mine para reconciliar."""
    produtos_db = []
    post_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[{"id": 1, "name": "Tomate", "default_unit": "kg"}])
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 2, "name": "Parcela Tomates"}])
        if request.url.path == "/api/v1/products/":
            post_count += 1
            # O servidor processou mas deu timeout na resposta
            produtos_db.append({
                "id": 999,
                "farm_id": 2,
                "crop_id": 1,
                "name": "Tomate",
                "price_per_unit": 400.0,
                "quantity_available": 100.0,
                "unit": "kg",
            })
            raise httpx.TimeoutException("Ligação expirou após 10 segundos")
        if request.url.path == "/api/v1/products/mine":
            return httpx.Response(200, json=produtos_db)
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    resultado = api.criar_anuncio(
        cultura="Tomate",
        quantidade_kg=100.0,
        preco_kz_kg=400.0,
        confirmed=True,
        user={"id": 1},
        token="token-teste",
    )

    assert resultado["status"] in ("executed", "success")
    assert resultado["id"] == 999
    assert resultado["reconciliado_pos_timeout"] is True
    # Garante que não repetiu a chamada de criação às cegas
    assert post_count == 1


# ---------------------------------------------------------------------------
# 8. Timeout e Reconciliação de Rega
# ---------------------------------------------------------------------------
def test_timeout_reconciliacao_rega_com_sucesso():
    """Após timeout ao agendar rega, consulta /irrigations/mine para reconciliar."""
    regas_db = []
    post_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 4, "name": "Parcela Leste"}])
        if request.url.path == "/api/v1/farms/4/irrigations":
            post_count += 1
            payload = json.loads(request.content.decode("utf-8"))
            regas_db.append({
                "id": 888,
                "farm_id": 4,
                "scheduled_time": payload["scheduled_time"],
                "duration_minutes": payload["duration_minutes"],
                "status": "agendada",
                "criada_via": "agente",
            })
            raise httpx.TimeoutException("Timeout de rede")
        if request.url.path == "/api/v1/irrigations/mine":
            return httpx.Response(200, json=regas_db)
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.agendar_rega(
        parcela="Parcela Leste",
        hora="08:00",
        confirmed=True,
        user={"id": 1},
        token="token-teste",
        duracao_minutos=45,
    )

    assert res["status"] in ("executed", "success")
    assert res["id"] == 888
    assert res["duracao_minutos"] == 45
    assert res["reconciliado_pos_timeout"] is True
    assert post_count == 1


# ---------------------------------------------------------------------------
# 9. Conflito 409 (sobreposição de rega)
# ---------------------------------------------------------------------------
def test_conflito_409_sobreposicao_rega():
    """Em 409, explica conflito de sobreposição e pede outro horário sem repetir."""
    tentativas = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 1, "name": "Parcela Principal"}])
        if "/irrigations" in request.url.path:
            tentativas += 1
            return httpx.Response(409, json={"detail": "Já existe uma rega agendada que se sobrepõe a este horário"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.agendar_rega(
        parcela="Parcela Principal",
        hora="09:00",
        confirmed=True,
        user={"id": 1},
        token="token-teste",
        duracao_minutos=30,
    )

    assert res["status"] == "error"
    assert res.get("conflito_sobreposicao") is True
    assert "Já existe uma rega agendada na parcela" in res["mensagem"]
    assert "escolha outro horário" in res["mensagem"]
    # Sem repetição cega
    assert tentativas == 1


# ---------------------------------------------------------------------------
# 10. Sugestão de preços e guardas MARGEM_PRECO
# ---------------------------------------------------------------------------
def test_precos_sugestoes_e_guardas():
    """Valida que obter_preco usa price-suggestions com intervalo e confiança, e validar_preco aplica margem."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[{"id": 1, "name": "Milho", "default_unit": "kg"}])
        if request.url.path == "/api/v1/market/price-suggestions":
            return httpx.Response(200, json={
                "crop_id": 1,
                "region_id": 1,
                "suggested_price": 500.0,
                "min_price": 400.0,
                "max_price": 600.0,
                "confidence": 0.85,
                "reasoning": "Oferta estável no mercado do Luanda.",
            })
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    cotacao = api.obter_preco("Milho", token="token-teste")
    assert cotacao["status"] == "executed"
    assert cotacao["preco_sugerido"] == 500.0
    assert cotacao["preco_min"] == 400.0
    assert cotacao["preco_max"] == 600.0
    assert cotacao["confianca_percentagem"] == 85.0
    assert "referência indicativa NongLink" in cotacao["nota"]

    # Margem padrão é 20%: min=400 -> lim_inf=320; max=600 -> lim_sup=720
    ok, msg, _ = api.validar_preco("Milho", 550.0, token="token-teste")
    assert ok is True

    # Preço demasiado alto (> 720)
    ok_alto, msg_alto, _ = api.validar_preco("Milho", 800.0, token="token-teste")
    assert ok_alto is False
    assert "fora do intervalo permitido" in msg_alto

    # Preço demasiado baixo (< 320)
    ok_baixo, msg_baixo, _ = api.validar_preco("Milho", 250.0, token="token-teste")
    assert ok_baixo is False
    assert "fora do intervalo permitido" in msg_baixo


def test_recusa_anuncio_quando_api_falha():
    """Se a API de preços falhar (ex: 500 ou rede), não propõe anúncio."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/crops/":
            return httpx.Response(200, json=[{"id": 1, "name": "Milho", "default_unit": "kg"}])
        if request.url.path == "/api/v1/market/price-suggestions":
            return httpx.Response(500, json={"detail": "Erro interno"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    ok, msg, _ = api.validar_preco("Milho", 500.0, token="token-teste")
    assert ok is False
    assert "Não foi possível validar o preço" in msg


# ---------------------------------------------------------------------------
# 11. Paridade de contrato entre SandboxPlataforma e ApiPlataforma
# ---------------------------------------------------------------------------
def test_paridade_contrato_sandbox_e_api():
    """Garante que tanto SandboxPlataforma como ApiPlataforma respeitam a interface Plataforma."""
    sandbox = SandboxPlataforma()
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1")

    assert isinstance(sandbox, Plataforma)
    assert isinstance(api, Plataforma)

    metodos_obrigatorios = [
        "autenticar",
        "obter_utilizador_me",
        "obter_preco",
        "validar_preco",
        "criar_anuncio",
        "agendar_rega",
        "listar_anuncios",
        "listar_regas",
        "resolver_parcela",
    ]

    for metodo in metodos_obrigatorios:
        assert hasattr(sandbox, metodo), f"SandboxPlataforma deve ter {metodo}"
        assert hasattr(api, metodo), f"ApiPlataforma deve ter {metodo}"
        assert callable(getattr(sandbox, metodo))
        assert callable(getattr(api, metodo))


# ---------------------------------------------------------------------------
# 12. Testes dos Endpoints FastAPI em Modo API (com TestClient)
# ---------------------------------------------------------------------------
def test_api_mode_rotas_autenticacao(monkeypatch):
    """Garante que em modo API, login reencaminha para NongLink e registo/demo ficam desativados."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            data = json.loads(request.content.decode("utf-8"))
            if data.get("identifier") == "agricultor@nonglink.ao" and data.get("password") == "senha123":
                return httpx.Response(200, json={
                    "access_token": "nl-jwt-token-999",
                    "token_type": "bearer",
                    "user": {"id": 15, "full_name": "Manuel Agricultor", "email": "agricultor@nonglink.ao", "role": "farmer"},
                })
            return httpx.Response(401, json={"detail": "Credenciais inválidas"})
        if request.url.path == "/api/v1/auth/me":
            if request.headers.get("authorization") == "Bearer nl-jwt-token-999":
                return httpx.Response(200, json={
                    "id": 15, "full_name": "Manuel Agricultor", "email": "agricultor@nonglink.ao", "role": "farmer", "region_id": 1
                })
            return httpx.Response(401, json={"detail": "Sessão inválida"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api_inst = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    # Injeta a plataforma no estado global
    import app.integracao.fabrica as fab
    fab.definir_plataforma(api_inst)
    monkeypatch.setenv("MODO_PLATAFORMA", "api")
    monkeypatch.setenv("NONGLINK_API_URL", "http://teste-nonglink/api/v1")

    from app.main import app
    client = TestClient(app)

    # 1. Registo e demo desativados (403)
    resp_reg = client.post("/auth/registar", json={"nome": "Teste", "email": "a@b.com", "senha": "123"})
    assert resp_reg.status_code == 403
    assert "desativado" in resp_reg.json()["detail"]

    resp_demo = client.post("/auth/demo")
    assert resp_demo.status_code == 403

    # 2. Login correto
    resp_login = client.post("/auth/login", json={"email": "agricultor@nonglink.ao", "senha": "senha123"})
    assert resp_login.status_code == 200
    login_data = resp_login.json()
    assert login_data["token"] == "nl-jwt-token-999"
    assert login_data["utilizador"]["id"] == "15"

    # 3. /auth/me protegido com Bearer
    resp_me = client.get("/auth/me", headers={"Authorization": "Bearer nl-jwt-token-999"})
    assert resp_me.status_code == 200
    assert resp_me.json()["utilizador"]["nome"] == "Manuel Agricultor"

    # 4. Bearer inválido faz voltar ao ecrã de entrada (401)
    resp_me_inv = client.get("/auth/me", headers={"Authorization": "Bearer token-falso"})
    assert resp_me_inv.status_code == 401


def test_api_mode_anuncios_e_regas_endpoints(monkeypatch):
    """Garante que /anuncios e /regas consultam a API do NongLink em modo API."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": 15, "full_name": "Manuel", "region_id": 1})
        if request.url.path == "/api/v1/products/mine":
            return httpx.Response(200, json=[{"id": 1, "name": "Mandioca Fresca", "price_per_unit": 250.0}])
        if request.url.path == "/api/v1/irrigations/mine":
            return httpx.Response(200, json=[{"id": 2, "scheduled_time": "2026-11-01T08:00:00Z", "duration_minutes": 40, "status": "agendada"}])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api_inst = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    import app.integracao.fabrica as fab
    fab.definir_plataforma(api_inst)

    from app.main import app
    client = TestClient(app)

    headers = {"Authorization": "Bearer token-manuel-15"}
    resp_anuncios = client.get("/anuncios", headers=headers)
    assert resp_anuncios.status_code == 200
    assert len(resp_anuncios.json()) == 1
    assert resp_anuncios.json()[0]["name"] == "Mandioca Fresca"

    resp_regas = client.get("/regas", headers=headers)
    assert resp_regas.status_code == 200
    assert len(resp_regas.json()) == 1
    assert resp_regas.json()[0]["duration_minutes"] == 40


# ---------------------------------------------------------------------------
# 13. Teste de Integração Real (Opcional, desativado por omissão)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("TEST_REAL_NONGLINK") != "1",
    reason="Requer TEST_REAL_NONGLINK=1 e instância ativa do backend NongLink em http://localhost:8000/api/v1",
)
def test_integracao_real_nonglink_local():
    """Teste de integração ponta a ponta contra o backend do NongLink real local."""
    api_url = os.environ.get("NONGLINK_API_URL", "http://localhost:8000/api/v1")
    api = ApiPlataforma(base_url=api_url)

    # 1. Consulta culturas públicas
    culturas = api._obter_culturas()
    assert isinstance(culturas, list)
    assert len(culturas) > 0
