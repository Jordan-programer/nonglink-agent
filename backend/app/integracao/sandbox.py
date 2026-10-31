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
