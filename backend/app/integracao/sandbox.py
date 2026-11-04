"""Implementação da plataforma em modo 'sandbox' (base SQLite local e cotações de demonstração)."""

from typing import Any, Dict, List, Optional, Tuple

from app.agent import (
    create_listing,
    get_crop_price,
    schedule_irrigation,
)
from app.db import (
    authenticate_user,
    create_session_token,
    get_crop_price_from_db,
    get_user_by_token,
    list_irrigations,
    list_listings,
)
from app.guardas import (
    normalizar_cultura,
    obter_margem_preco_percentagem,
    validar_anuncio,
    validar_preco as guardas_validar_preco,
)
from app.integracao.base import Plataforma


class SandboxPlataforma(Plataforma):
    """Plataforma simulada com base SQLite local (modo sandbox)."""

    def autenticar(self, identifier: str, password: str) -> Dict[str, Any]:
        user = authenticate_user(identifier, password)
        if not user:
            return {"sucesso": False, "erro": "Email ou palavra-passe incorrectos"}
        token = create_session_token(user["id"])
        return {
            "sucesso": True,
            "access_token": token,
            "token_type": "bearer",
            "user": user,
        }

    def obter_utilizador_me(self, token: str) -> Dict[str, Any]:
        user = get_user_by_token(token)
        if not user:
            return {}
        return user

    def obter_preco(
        self,
        cultura: str,
        region_id: Optional[int] = None,
        quality: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_crop_price(cultura)

    def validar_preco(
        self,
        cultura: str,
        preco_kz_kg: float,
        token: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ok, msg = guardas_validar_preco(cultura, preco_kz_kg)
        canon = normalizar_cultura(cultura) or cultura.lower().strip()
        ref = get_crop_price_from_db(canon) if canon else None
        return ok, msg, ref

    def criar_anuncio(
        self,
        cultura: str,
        quantidade_kg: float,
        preco_kz_kg: float,
        confirmed: bool,
        user: Dict[str, Any],
        token: Optional[str] = None,
        foto_id: Optional[str] = None,
        qualidade: Optional[str] = None,
        certificacao: Optional[str] = None,
    ) -> Dict[str, Any]:
        utilizador_id = str(user.get("id")) if user and user.get("id") else None
        return create_listing(
            cultura=cultura,
            quantidade_kg=quantidade_kg,
            preco_kz_kg=preco_kz_kg,
            confirmed=confirmed,
            utilizador_id=utilizador_id,
        )

    def agendar_rega(
        self,
        parcela: str,
        hora: str,
        confirmed: bool,
        user: Dict[str, Any],
        token: Optional[str] = None,
        duracao_minutos: Optional[int] = None,
        data_especifica: Optional[str] = None,
    ) -> Dict[str, Any]:
        utilizador_id = str(user.get("id")) if user and user.get("id") else None
        return schedule_irrigation(
            parcela=parcela,
            hora=hora,
            confirmed=confirmed,
            utilizador_id=utilizador_id,
        )

    def listar_anuncios(
        self,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        utilizador_id = str(user.get("id")) if user and user.get("id") else None
        return list_listings(utilizador_id=utilizador_id)

    def listar_regas(
        self,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        utilizador_id = str(user.get("id")) if user and user.get("id") else None
        return list_irrigations(utilizador_id=utilizador_id)

    def cancelar_rega(
        self,
        rega_id: str,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "cancelled",
            "id": rega_id,
            "mensagem": f"Rega {rega_id} cancelada no sandbox.",
        }

    def resolver_parcela(
        self,
        parcela_ref: Optional[str],
        token: str,
    ) -> Dict[str, Any]:
        return {
            "status": "ok",
            "farm_id": 1,
            "nome": parcela_ref or "Parcela 1",
        }

    def listar_parcelas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "id": 1,
                "name": "Parcela 1",
                "location": "Luanda",
                "size_hectares": 2.5,
                "region_id": 1,
            }
        ]

    def obter_estudo_campo(
        self,
        parcela_ref: Optional[str],
        forcar_nova_analise: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        nome = parcela_ref or "Parcela 1"
        return {
            "status": "executed",
            "parcela": nome,
            "farm_id": 1,
            "nova_analise": forcar_nova_analise,
            "em_cache_24h": not forcar_nova_analise,
            "data_imagem": "2026-10-25",
            "nebulosidade_pct": 8.5,
            "cloud_cover_pct": 8.5,
            "ndvi_mean": 0.65,
            "ndmi_mean": 0.22,
            "ndti_mean": 0.05,
            "salinity_index_mean": 0.08,
            "recomendacoes": {
                "irrigacao": "Humidade moderada (NDMI 0.22). Manter ciclo de rega habitual.",
                "plantio": "Vigor vegetativo favorável (NDVI 0.65). Adequado para culturas sazonais.",
                "solo": "Salinidade baixa (0.08). Não requer lavagem do solo.",
            },
            "fonte_recomendacoes": "recomendações do NongLink",
            "aviso_leitura": (
                "Esta leitura depende da data da imagem (2026-10-25) e da cobertura de nuvens (8.5%). "
                "As orientações apresentadas são recomendações técnicas automáticas do NongLink."
            ),
        }

    def obter_historico_solo(
        self,
        parcela_ref: Optional[str],
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        nome = parcela_ref or "Parcela 1"
        return {
            "status": "executed",
            "parcela": nome,
            "farm_id": 1,
            "historico": [
                {
                    "acquisition_date": "2026-10-25",
                    "cloud_cover_pct": 8.5,
                    "ndvi_mean": 0.65,
                    "ndmi_mean": 0.22,
                    "ndti_mean": 0.12,
                    "salinity_index_mean": 0.08,
                },
                {
                    "acquisition_date": "2026-10-10",
                    "cloud_cover_pct": 12.0,
                    "ndvi_mean": 0.58,
                    "ndmi_mean": 0.19,
                    "ndti_mean": 0.10,
                    "salinity_index_mean": 0.09,
                },
            ],
        }

    def listar_vendas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "order_id": 101,
                "order_item_id": 201,
                "product_name": "Tomate",
                "quantity": 50.0,
                "unit_price": 2200.0,
                "status": "confirmed",
                "created_at": "2026-10-28T14:30:00Z",
                "buyer_name": "Comprador de Demonstração",
            }
        ]

    def obter_resumo_vendas(
        self,
        token: str,
    ) -> Dict[str, Any]:
        return {
            "gross_sales": 110000.0,
            "platform_fee": 5500.0,
            "net_earnings": 104500.0,
        }

    def obter_tendencias_vendas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        return [
            {"date": "2026-10-28", "value": 110000.0}
        ]

    def resolver_produto(
        self,
        produto_ref: str,
        token: str,
    ) -> Dict[str, Any]:
        return {
            "status": "ok",
            "produto_id": 1,
            "nome": produto_ref or "Tomate",
            "produto": {
                "id": 1,
                "name": produto_ref or "Tomate",
                "price_per_unit": 2200.0,
                "quantity_available": 100.0,
            },
        }

    def actualizar_anuncio(
        self,
        produto_ref: str,
        preco_kz_kg: Optional[float],
        quantidade_kg: Optional[float],
        confirmed: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        nome = produto_ref or "Tomate"
        novo_preco = preco_kz_kg if preco_kz_kg is not None else 2200.0
        nova_qtd = quantidade_kg if quantidade_kg is not None else 100.0
        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "produto_id": 1,
                "produto": nome,
                "preco_kz_kg": novo_preco,
                "quantidade_kg": nova_qtd,
                "mensagem": {
                    "pt": f"Actualização do anúncio '{nome}' não efectuada (aguarda confirmação do agricultor).",
                    "fr": f"Mise à jour de l'annonce '{nome}' non effectuée (en attente de confirmation).",
                    "en": f"Update of listing '{nome}' not executed (awaiting farmer confirmation).",
                },
            }
        return {
            "status": "executed",
            "produto_id": 1,
            "produto": nome,
            "preco_kz_kg": novo_preco,
            "quantidade_kg": nova_qtd,
            "mensagem": {
                "pt": f"Anúncio '{nome}' actualizado: {nova_qtd} kg a {novo_preco:.0f} Kz/kg.",
                "fr": f"Annonce '{nome}' mise à jour : {nova_qtd} kg à {novo_preco:.0f} Kz/kg.",
                "en": f"Listing '{nome}' updated: {nova_qtd} kg at {novo_preco:.0f} Kz/kg.",
            },
        }

    def retirar_anuncio(
        self,
        produto_ref: str,
        confirmed: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        nome = produto_ref or "Tomate"
        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "produto_id": 1,
                "produto": nome,
                "mensagem": {
                    "pt": f"Retirada do anúncio '{nome}' pendente: o produto ficará esgotado, mas não será apagado.",
                    "fr": f"Retrait de l'annonce '{nome}' en attente : le produit sera épuisé mais non supprimé.",
                    "en": f"Withdrawal of listing '{nome}' pending: product will be marked as sold out, but not deleted.",
                },
            }
        return {
            "status": "executed",
            "produto_id": 1,
            "produto": nome,
            "quantidade_disponivel": 0.0,
            "mensagem": {
                "pt": f"Anúncio '{nome}' retirado de venda: ficará esgotado, mas não será apagado.",
                "fr": f"Annonce '{nome}' retiré de la vente : il restera épuisé, mais ne sera pas supprimé.",
                "en": f"Listing '{nome}' withdrawn from sale: it will be marked as out of stock, but not deleted.",
            },
        }
