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
# 13. Testes das Novas Ferramentas (Parcelas, Solo GEE, Vendas, PATCH produtos)
# ---------------------------------------------------------------------------
def test_endpoint_config_publico(monkeypatch):
    """Verifica GET /config com modo, registo_url e aviso."""
    monkeypatch.setenv("MODO_PLATAFORMA", "api")
    monkeypatch.setenv("NONGLINK_REGISTER_URL", "https://agrilink.store/registar")

    from app.main import app
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["modo"] == "api"
    assert data["registo_url"] == "https://agrilink.store/registar"
    assert "aviso" in data


def test_listar_parcelas_mock():
    """Garante que listar_parcelas consulta GET /farms/mine com Bearer token."""
    requests_received = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[
                {"id": 1, "name": "Lavra Sul", "size_hectares": 5.0, "location": "Caxito"},
                {"id": 2, "name": "Lavra Norte", "size_hectares": 3.2, "location": "Uíge"},
            ])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    parcelas = api.listar_parcelas("token-test-123")
    assert len(parcelas) == 2
    assert parcelas[0]["name"] == "Lavra Sul"
    assert requests_received[0].headers["authorization"] == "Bearer token-test-123"


def test_estudo_campo_latest_e_cache():
    """Garante leitura de solo via GET /soil/{farm_id}/latest e validação de cache de 24h."""
    calls_made = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        calls_made.append(request.url.path)
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Lavra Principal"}])
        if request.url.path == "/api/v1/soil/10/latest":
            return httpx.Response(200, json={
                "farm_id": 10,
                "acquisition_date": "2026-10-20",
                "cloud_cover_pct": 5.2,
                "ndvi_mean": 0.58,
                "ndmi_mean": 0.18,
                "ndti_mean": 0.04,
                "salinity_index_mean": 0.07,
                "recommendations": {
                    "irrigacao": "Humidade adequada.",
                    "plantio": "Bom vigor vegetativo.",
                    "solo": "Salinidade normal.",
                },
            })
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    # 1ª chamada: vai à API
    res1 = api.obter_estudo_campo("Lavra Principal", forcar_nova_analise=False, token="tok-123")
    assert res1["status"] == "executed"
    assert res1["em_cache_24h"] is False
    assert res1["ndvi_mean"] == 0.58
    assert res1["cloud_cover_pct"] == 5.2
    assert "agrilink.store" not in res1["aviso_leitura"]

    # 2ª chamada: usa cache de 24h sem novo request a /latest
    res2 = api.obter_estudo_campo("Lavra Principal", forcar_nova_analise=False, token="tok-123")
    assert res2["status"] == "executed"
    assert res2["em_cache_24h"] is True
    assert calls_made.count("/api/v1/soil/10/latest") == 1


def test_estudo_campo_analyze_post_mock():
    """Garante que forcar_nova_analise faz POST /soil/{farm_id}/analyze sem polígono no corpo."""
    requests_received = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Lavra Principal"}])
        if request.url.path == "/api/v1/soil/10/analyze" and request.method == "POST":
            # Corpo não deve ter coordenadas nem polígonos enviados pelo chat
            body = json.loads(request.content.decode("utf-8") or "{}")
            assert "coordinates" not in body
            return httpx.Response(201, json={
                "farm_id": 10,
                "acquisition_date": "2026-11-02",
                "cloud_cover_pct": 3.0,
                "ndvi_mean": 0.62,
                "ndmi_mean": 0.20,
                "ndti_mean": 0.05,
                "salinity_index_mean": 0.06,
                "recommendations": {"irrigacao": "Irrigar conforme planeado."},
            })
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.obter_estudo_campo("Lavra Principal", forcar_nova_analise=True, token="tok-123", user={"id": 5})
    assert res["status"] == "executed"
    assert res["nova_analise"] is True
    assert res["ndvi_mean"] == 0.62


def test_estudo_campo_erro_400_sem_poligono():
    """Garante que o erro 400 (sem polígono) orienta a desenhar em agrilink.store."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Lavra Sem Limite"}])
        if request.url.path == "/api/v1/soil/10/analyze":
            return httpx.Response(400, json={"detail": "Esta lavra ainda não tem um polígono desenhado."})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.obter_estudo_campo("Lavra Sem Limite", forcar_nova_analise=True, token="tok-123", user={"id": 5})
    assert res["status"] == "sem_poligono"
    assert "agrilink.store" in res["mensagem"]


def test_estudo_campo_limite_diario_quota(monkeypatch):
    """Garante que SOLO_MAX_POR_UTILIZADOR_DIA é respeitado."""
    monkeypatch.setenv("SOLO_MAX_POR_UTILIZADOR_DIA", "2")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 10, "name": "Lavra Quota"}])
        if request.url.path == "/api/v1/soil/10/analyze":
            return httpx.Response(201, json={"farm_id": 10, "acquisition_date": "2026-11-03", "ndvi_mean": 0.5})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    # 1ª e 2ª análises são aceites
    res1 = api.obter_estudo_campo("Lavra Quota", forcar_nova_analise=True, token="tok", user={"id": "usr-1"})
    assert res1["status"] == "executed"
    res2 = api.obter_estudo_campo("Lavra Quota", forcar_nova_analise=True, token="tok", user={"id": "usr-1"})
    assert res2["status"] == "executed"

    # 3ª análise é barrada pela quota diária
    res3 = api.obter_estudo_campo("Lavra Quota", forcar_nova_analise=True, token="tok", user={"id": "usr-1"})
    assert res3["status"] == "quota_excedida"
    assert "limite diário" in res3["mensagem"]


def test_vendas_endpoints_somente_leitura():
    """Garante leitura de vendas, resumo e tendências via GET."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/orders/sales":
            return httpx.Response(200, json=[
                {"order_id": 100, "product_name": "Tomate", "quantity": 10.0, "unit_price": 2000.0}
            ])
        if request.url.path == "/api/v1/orders/sales/summary":
            return httpx.Response(200, json={
                "gross_sales": 20000.0,
                "net_earnings": 19000.0,
                "platform_fee": 1000.0,
            })
        if request.url.path == "/api/v1/orders/sales/trends":
            return httpx.Response(200, json=[{"date": "2026-11-01", "value": 20000.0}])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    vendas = api.listar_vendas("tok-vendas")
    assert len(vendas) == 1
    assert vendas[0]["product_name"] == "Tomate"

    resumo = api.obter_resumo_vendas("tok-vendas")
    assert resumo["gross_sales"] == 20000.0
    assert resumo["net_earnings"] == 19000.0

    trends = api.obter_tendencias_vendas("tok-vendas")
    assert len(trends) == 1


def test_actualizar_e_retirar_anuncio_nunca_chama_delete():
    """Garante que actualizar_anuncio e retirar_anuncio usam PATCH e NUNCA chamam DELETE."""
    all_methods_used = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        all_methods_used.append(request.method)
        if request.url.path == "/api/v1/products/mine":
            return httpx.Response(200, json=[{"id": 44, "name": "Tomate Rama", "price_per_unit": 2000.0, "quantity_available": 150.0}])
        if request.url.path == "/api/v1/products/44" and request.method == "PATCH":
            body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": 44, "name": "Tomate Rama", **body})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    # 1. Actualizar anúncio confirmado
    res_up = api.actualizar_anuncio("Tomate Rama", preco_kz_kg=2200.0, quantidade_kg=120.0, confirmed=True, token="tok")
    assert res_up["status"] == "executed"
    assert res_up["preco_kz_kg"] == 2200.0

    # 2. Retirar anúncio não confirmado (talão)
    res_ret_pend = api.retirar_anuncio("Tomate Rama", confirmed=False, token="tok")
    assert res_ret_pend["status"] == "cancelled_by_user"
    assert "não será apagado" in str(res_ret_pend["mensagem"])

    # 3. Retirar anúncio confirmado
    res_ret = api.retirar_anuncio("Tomate Rama", confirmed=True, token="tok")
    assert res_ret["status"] == "executed"
    assert res_ret["quantidade_disponivel"] == 0.0

    # Certificação de segurança: NENHUM método DELETE foi chamado
    assert "DELETE" not in all_methods_used
    assert "PATCH" in all_methods_used


def test_recusa_recursos_outro_utilizador_404():
    """Garante tratamento correto e seguro quando o recurso pertence a outro utilizador (404)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/products/mine":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[])
        if "/cancel" in request.url.path:
            return httpx.Response(404, json={"detail": "Rega não encontrada"})
        return httpx.Response(404, json={"detail": "Recurso não encontrado"})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    # Parcela de outro utilizador (não está nas minhas parcelas)
    res_solo = api.obter_estudo_campo("Parcela Alheia", forcar_nova_analise=False, token="tok")
    assert res_solo["status"] == "sem_parcelas"

    # Produto de outro utilizador
    res_prod = api.retirar_anuncio("Produto Alheio", confirmed=True, token="tok")
    assert res_prod["status"] == "sem_produtos"

    # Rega de outro utilizador
    res_rega = api.cancelar_rega("999", user={"id": 1}, token="tok")
    assert res_rega["status"] == "error"
    assert "outro utilizador" in res_rega["message"]


def test_modo_api_falha_fechada_e_seguranca():
    """Valida falha fechada em modo API: rejeição de token (401), NongLink indisponível (503/401, nunca 200), demo/registar (403) e /config sem revelar NONGLINK_API_URL."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.integracao.fabrica import definir_plataforma, redefinir_plataforma

    old_modo = os.environ.get("MODO_PLATAFORMA")
    old_url = os.environ.get("NONGLINK_API_URL")
    try:
        os.environ["MODO_PLATAFORMA"] = "api"
        os.environ["NONGLINK_API_URL"] = "http://mock-nonglink/api/v1"

        client = TestClient(app)

        # 1. Sem token -> 401
        resp_no_tok = client.get("/conversas")
        assert resp_no_tok.status_code == 401

        # 2. Token rejeitado pelo NongLink -> 401
        def handler_rej(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Could not validate credentials"})

        plat_rej = ApiPlataforma(base_url="http://mock-nonglink/api/v1", transport=httpx.MockTransport(handler_rej))
        definir_plataforma(plat_rej)

        resp_bad_tok = client.get("/conversas", headers={"Authorization": "Bearer token_invalido"})
        assert resp_bad_tok.status_code == 401

        # 3. NongLink indisponível (503 / falha de rede) -> 503 ou 401 (NUNCA 200)
        def handler_down(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "Service Unavailable"})

        plat_down = ApiPlataforma(base_url="http://mock-nonglink/api/v1", transport=httpx.MockTransport(handler_down))
        definir_plataforma(plat_down)

        resp_down = client.get("/conversas", headers={"Authorization": "Bearer token_qualquer"})
        assert resp_down.status_code in (401, 503)
        assert resp_down.status_code != 200

        # 4. /auth/demo e /auth/registar devolvem 403 em modo API
        resp_demo = client.post("/auth/demo")
        assert resp_demo.status_code == 403
        resp_reg = client.post("/auth/registar", json={"nome": "X", "email": "x@x.com", "senha": "password123"})
        assert resp_reg.status_code == 403

        # 5. /config não revela NONGLINK_API_URL
        resp_cfg = client.get("/config")
        assert resp_cfg.status_code == 200
        cfg_data = resp_cfg.json()
        assert "NONGLINK_API_URL" not in str(cfg_data)
        assert "http://mock-nonglink" not in str(cfg_data)
    finally:
        if old_modo is not None:
            os.environ["MODO_PLATAFORMA"] = old_modo
        else:
            os.environ.pop("MODO_PLATAFORMA", None)
        if old_url is not None:
            os.environ["NONGLINK_API_URL"] = old_url
        else:
            os.environ.pop("NONGLINK_API_URL", None)
        redefinir_plataforma()


# ---------------------------------------------------------------------------
# 13. Testes de Histórico de Solo e Sanitização (T2 Correcções)
# ---------------------------------------------------------------------------
def test_obter_historico_solo_mock_transport():
    """Valida consulta de histórico de observações de satélite via GET /soil/{farm_id}/history com MockTransport."""
    requests_received: List[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 7, "name": "Parcela Sul"}])
        if request.url.path == "/api/v1/soil/7/history":
            assert request.headers.get("authorization") == "Bearer token-valido"
            return httpx.Response(200, json=[
                {"acquisition_date": "2026-10-20", "ndvi_mean": 0.62, "cloud_cover_pct": 5.0},
                {"acquisition_date": "2026-10-05", "ndvi_mean": 0.55, "cloud_cover_pct": 10.2},
            ])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.obter_historico_solo(parcela_ref="Parcela Sul", token="token-valido")
    assert res["status"] == "executed"
    assert res["farm_id"] == 7
    assert len(res["historico"]) == 2
    assert res["historico"][0]["ndvi_mean"] == 0.62

    # Verifica também paridade com SandboxPlataforma
    sandbox = SandboxPlataforma()
    sb_res = sandbox.obter_historico_solo("Parcela Sul", token="token-valido")
    assert sb_res["status"] == "executed"
    assert isinstance(sb_res["historico"], list)


def test_obter_historico_solo_404_mock_transport():
    """Valida tratamento de erro 404 em histórico de solo."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/farms/mine":
            return httpx.Response(200, json=[{"id": 9, "name": "Parcela Leste"}])
        if request.url.path == "/api/v1/soil/9/history":
            return httpx.Response(404, json={"detail": "Nenhum histórico encontrado"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res = api.obter_historico_solo(parcela_ref="Parcela Leste", token="token-valido")
    assert res["status"] == "not_found"
    assert "Nenhum histórico" in res["mensagem"]


def test_sanitizacao_erros_sem_vazar_pii():
    """Valida que mensagens de erro não vazam tokens, URLs ou stack traces."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/cancel" in request.url.path:
            return httpx.Response(500, json={"detail": "Internal error at https://secret-cluster/db?key=sec123"})
        return httpx.Response(500, text="Internal Server Error: database connection timeout")

    transport = httpx.MockTransport(mock_handler)
    api = ApiPlataforma(base_url="http://teste-nonglink/api/v1", transport=transport)

    res_canc = api.cancelar_rega("99", user={"id": 1}, token="token-valido")
    assert res_canc["status"] == "error"
    # Garante que mensagem é sanitizada
    assert "https://secret-cluster" not in res_canc["message"]
    assert "sec123" not in res_canc["message"]


# ---------------------------------------------------------------------------
# 14. Teste de Integração Real (Opcional, ativado apenas quando TEST_REAL_NONGLINK=1)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("TEST_REAL_NONGLINK") != "1",
    reason="Requer TEST_REAL_NONGLINK=1 e variáveis TESTE_EMAIL e TESTE_SENHA definidas",
)
def test_integracao_real_nonglink_local():
    """Teste de integração ponta a ponta contra a API real do NongLink."""
    from scripts.teste_real_nonglink import executar_fluxo_real

    api_url = os.environ.get("NONGLINK_API_URL", "https://agrilink.store/api/v1")
    email = os.environ.get("TESTE_EMAIL", "meta@test.com")
    senha = os.environ.get("TESTE_SENHA", "meta@123")

    sucesso, relatorio = executar_fluxo_real(api_url=api_url, email=email, senha=senha)
    for linha in relatorio:
        print(linha)
    assert sucesso, f"Falha no fluxo de integracao real com NongLink: {relatorio}"
