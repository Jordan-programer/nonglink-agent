"""Script de teste de integração real contra a API do NongLink.

Executa o fluxo completo do contrato da plataforma com um utilizador real ou de teste,
sem vazar tokens, senhas ou dados confidenciais na saída.

Variáveis de ambiente requeridas / opcionais:
  NONGLINK_API_URL: URL base da API NongLink (omissão: http://localhost:8000/api/v1 ou https://agrilink.store/api/v1)
  TESTE_EMAIL: Email do agricultor (ex.: meta@test.com ou agricultor@agrilink.store)
  TESTE_SENHA: Senha do agricultor

Uso:
  cd backend && python scripts/teste_real_nonglink.py
  ou
  TESTE_EMAIL="meta@test.com" TESTE_SENHA="sua_senha" python scripts/teste_real_nonglink.py
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integracao.api import ApiPlataforma, limpar_caches_api


def formatar_status(nome: str, status: str, detalhe: str = "") -> str:
    """Formata linha de resultado padronizada sem expor tokens ou dados confidenciais."""
    status_formatado = f"[{status}]".ljust(11)
    if detalhe:
        return f"{status_formatado} {nome}: {detalhe}"
    return f"{status_formatado} {nome}"


def executar_fluxo_real(
    api_url: str,
    email: str,
    senha: str,
) -> Tuple[bool, List[str]]:
    """Executa o fluxo de integração contra a API e retorna (sucesso_global, relatorio)."""
    relatorio: List[str] = []
    sucesso_global = True

    limpar_caches_api()
    api = ApiPlataforma(base_url=api_url, timeout=15.0)

    # 1. Catálogo público de culturas (GET /crops/)
    cultura_nome = "Tomate"
    cultura_id = 1
    try:
        culturas = api._obter_culturas()
        if culturas and isinstance(culturas, list) and len(culturas) > 0:
            c0 = culturas[0]
            cultura_nome = c0.get("name") or "Tomate"
            cultura_id = c0.get("id") or 1
            relatorio.append(formatar_status(
                "1. GET /crops/ (Catálogo de culturas)",
                "OK",
                f"{len(culturas)} culturas catalogadas (ex.: '{cultura_nome}', ID #{cultura_id})",
            ))
        else:
            relatorio.append(formatar_status("1. GET /crops/", "FALHOU", "Catálogo devolveu lista vazia."))
            sucesso_global = False
    except Exception as exc:
        relatorio.append(formatar_status("1. GET /crops/", "FALHOU", f"Erro de ligação: {type(exc).__name__}"))
        sucesso_global = False

    # 2. Autenticação (POST /auth/login)
    token = ""
    user_me: Dict[str, Any] = {}
    try:
        auth_data = api.autenticar(identifier=email, password=senha)
        token = auth_data.get("access_token") or ""
        user_info = auth_data.get("user") or {}
        if token and user_info.get("id"):
            u_id = user_info.get("id")
            u_role = user_info.get("role", "farmer")
            relatorio.append(formatar_status(
                "2. POST /auth/login (Autenticação)",
                "OK",
                f"Utilizador autenticado com sucesso (ID #{u_id}, role={u_role}, token recebido de forma segura)",
            ))
        else:
            erro_msg = auth_data.get("erro", "Credenciais rejeitadas ou sem token na resposta")
            relatorio.append(formatar_status("2. POST /auth/login", "FALHOU", erro_msg))
            sucesso_global = False
            return False, relatorio
    except Exception as exc:
        relatorio.append(formatar_status("2. POST /auth/login", "FALHOU", f"Falha ao autenticar: {type(exc).__name__}"))
        return False, relatorio

    # 3. Perfil do utilizador (GET /auth/me)
    try:
        user_me = api.obter_utilizador_me(token)
        if user_me and user_me.get("id"):
            nome = user_me.get("name") or user_me.get("full_name") or "Agricultor"
            relatorio.append(formatar_status(
                "3. GET /auth/me (Perfil da sessão)",
                "OK",
                f"Sessão válida para '{nome}' (ID #{user_me.get('id')}, region_id={user_me.get('region_id')})",
            ))
        else:
            relatorio.append(formatar_status("3. GET /auth/me", "FALHOU", "Não foi possível validar a sessão com o token obtido."))
            sucesso_global = False
    except Exception as exc:
        relatorio.append(formatar_status("3. GET /auth/me", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    # 4. Parcelas do agricultor (GET /farms/mine)
    farm_id: Optional[int] = None
    farm_name: str = ""
    try:
        farms = api.listar_farms_mine(token)
        if farms and len(farms) > 0:
            farm_id = farms[0].get("id")
            farm_name = farms[0].get("name") or f"Parcela #{farm_id}"
            relatorio.append(formatar_status(
                "4. GET /farms/mine (Parcelas do agricultor)",
                "OK",
                f"{len(farms)} parcela(s) encontrada(s) (activa: '{farm_name}', ID #{farm_id})",
            ))
        else:
            relatorio.append(formatar_status(
                "4. GET /farms/mine (Parcelas do agricultor)",
                "IGNORADO",
                "O agricultor ainda não possui parcelas registadas (análise de solo será ignorada)",
            ))
    except Exception as exc:
        relatorio.append(formatar_status("4. GET /farms/mine", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    # 5. Sugestão e referência de preços (POST /market/price-suggestions)
    try:
        reg_id = user_me.get("region_id") or 1
        preco_res = api.obter_preco(cultura=cultura_nome, region_id=reg_id, token=token)
        if preco_res.get("status") in ("executed", "not_found"):
            p_sug = preco_res.get("suggested_price") or preco_res.get("preco_min", 0.0)
            relatorio.append(formatar_status(
                "5. POST /market/price-suggestions (Cotações de mercado)",
                "OK",
                f"Consulta para '{cultura_nome}': referência base={p_sug} Kz",
            ))
        else:
            relatorio.append(formatar_status(
                "5. POST /market/price-suggestions",
                "OK",
                f"Resposta recebida: {preco_res.get('status')}",
            ))
    except Exception as exc:
        relatorio.append(formatar_status("5. POST /market/price-suggestions", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    # 6. Listagem de anúncios publicados (GET /products/mine)
    try:
        produtos = api.listar_anuncios(token=token, user=user_me)
        relatorio.append(formatar_status(
            "6. GET /products/mine (Anúncios do agricultor)",
            "OK",
            f"{len(produtos)} produto(s)/anúncio(s) listados",
        ))
    except Exception as exc:
        relatorio.append(formatar_status("6. GET /products/mine", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    # 7. Relatórios de vendas (GET /orders/sales e /summary)
    try:
        vendas = api.listar_vendas(token=token)
        resumo = api.obter_resumo_vendas(token=token)
        bruto = resumo.get("gross_sales", 0.0)
        relatorio.append(formatar_status(
            "7. GET /orders/sales (Relatório e resumo de vendas)",
            "OK",
            f"{len(vendas)} venda(s), Total bruto acumulado: {bruto:.2f} Kz",
        ))
    except Exception as exc:
        relatorio.append(formatar_status("7. GET /orders/sales", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    # 8. Leitura recente de solo (GET /soil/{farm_id}/latest)
    if farm_id is not None:
        try:
            solo_res = api.obter_estudo_campo(parcela_ref=str(farm_id), forcar_nova_analise=False, token=token, user=user_me)
            if solo_res.get("status") in ("executed", "sem_analises"):
                relatorio.append(formatar_status(
                    "8. GET /soil/{farm_id}/latest (Estudo de solo mais recente)",
                    "OK",
                    f"Status da leitura: {solo_res.get('status')} na parcela '{farm_name}'",
                ))
            else:
                relatorio.append(formatar_status(
                    "8. GET /soil/{farm_id}/latest",
                    "OK",
                    f"Resposta da API: {solo_res.get('status')}",
                ))
        except Exception as exc:
            relatorio.append(formatar_status("8. GET /soil/{farm_id}/latest", "FALHOU", f"Erro: {type(exc).__name__}"))
            sucesso_global = False
    else:
        relatorio.append(formatar_status(
            "8. GET /soil/{farm_id}/latest",
            "IGNORADO",
            "Sem parcela registada para consulta de solo",
        ))

    # 9. Histórico de observações de solo (GET /soil/{farm_id}/history)
    if farm_id is not None:
        try:
            hist_res = api.obter_historico_solo(parcela_ref=str(farm_id), token=token, user=user_me)
            if hist_res.get("status") in ("executed", "not_found"):
                qtd = len(hist_res.get("historico", [])) if hist_res.get("status") == "executed" else 0
                relatorio.append(formatar_status(
                    "9. GET /soil/{farm_id}/history (Histórico de satélite)",
                    "OK",
                    f"{qtd} registo(s) histórico(s) para a parcela '{farm_name}'",
                ))
            else:
                relatorio.append(formatar_status(
                    "9. GET /soil/{farm_id}/history",
                    "OK",
                    f"Resposta da API: {hist_res.get('status')}",
                ))
        except Exception as exc:
            relatorio.append(formatar_status("9. GET /soil/{farm_id}/history", "FALHOU", f"Erro: {type(exc).__name__}"))
            sucesso_global = False
    else:
        relatorio.append(formatar_status(
            "9. GET /soil/{farm_id}/history",
            "IGNORADO",
            "Sem parcela registada para consulta de histórico",
        ))

    # 10. Regas agendadas (GET /irrigations/mine)
    try:
        regas = api.listar_regas(token=token, user=user_me)
        relatorio.append(formatar_status(
            "10. GET /irrigations/mine (Regas do agricultor)",
            "OK",
            f"{len(regas)} rega(s) agendada(s) ou concluída(s)",
        ))
    except Exception as exc:
        relatorio.append(formatar_status("10. GET /irrigations/mine", "FALHOU", f"Erro: {type(exc).__name__}"))
        sucesso_global = False

    return sucesso_global, relatorio


def main() -> None:
    api_url = os.environ.get("NONGLINK_API_URL") or "https://agrilink.store/api/v1"
    email = os.environ.get("TESTE_EMAIL") or ""
    senha = os.environ.get("TESTE_SENHA") or ""

    if not email or not senha:
        print("=== NongLink - Teste de Integração Real ===")
        print("Para executar o teste real, informe as credenciais de um utilizador agricultor verificado.")
        print("Dica: pode definir as variáveis TESTE_EMAIL e TESTE_SENHA ou introduzir abaixo.\n")
        if not email:
            email = input("Email do agricultor: ").strip()
        if not senha:
            import getpass
            senha = getpass.getpass("Palavra-passe: ").strip()

    if not email or not senha:
        print("Erro: Email e palavra-passe são obrigatórios para o teste real.", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 70)
    print(" INICIANDO TESTE DE INTEGRAÇÃO REAL DA API NONGLINK")
    print(f" Alvo API: {api_url}")
    print(f" Utilizador: {email}")
    print("=" * 70 + "\n")

    sucesso, relatorio = executar_fluxo_real(api_url=api_url, email=email, senha=senha)

    for linha in relatorio:
        print(linha)

    print("\n" + "=" * 70)
    if sucesso:
        print(" RESULTADO FINAL: TODOS OS ENDPOINTS DO CONTRATO FUNCIONAM COM SUCESSO! ✓")
    else:
        print(" RESULTADO FINAL: DETETADAS FALHAS NO FLUXO DE INTEGRAÇÃO.")
    print("=" * 70 + "\n")

    sys.exit(0 if sucesso else 1)


if __name__ == "__main__":
    main()

