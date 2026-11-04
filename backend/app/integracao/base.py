"""Interface base para plataformas de integração do NongLink Field Agent.

Define o contrato que tanto o modo 'sandbox' (base SQLite local) quanto o
modo 'api' (REST backend NongLink) devem satisfazer.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class Plataforma(ABC):
    """Contrato abstrato de serviços agrícolas (cotações, anúncios, regas, autenticação)."""

    @abstractmethod
    def autenticar(self, identifier: str, password: str) -> Dict[str, Any]:
        """Autentica o utilizador e devolve token e dados do utilizador."""
        pass

    @abstractmethod
    def obter_utilizador_me(self, token: str) -> Dict[str, Any]:
        """Valida o token Bearer e devolve o perfil do utilizador autenticado."""
        pass

    @abstractmethod
    def obter_preco(
        self,
        cultura: str,
        region_id: Optional[int] = None,
        quality: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Consulta cotação e intervalo de referência para a cultura."""
        pass

    @abstractmethod
    def validar_preco(
        self,
        cultura: str,
        preco_kz_kg: float,
        token: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Valida se o preço proposto cumpre a margem de tolerância em relação ao intervalo de referência."""
        pass

    @abstractmethod
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
        """Publica anúncio de venda de colheita."""
        pass

    @abstractmethod
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
        """Agenda uma sessão de rega para uma parcela."""
        pass

    @abstractmethod
    def listar_anuncios(
        self,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Devolve os anúncios do utilizador autenticado."""
        pass

    @abstractmethod
    def listar_regas(
        self,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Devolve as regas do utilizador autenticado."""
        pass

    @abstractmethod
    def cancelar_rega(
        self,
        rega_id: str,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancela uma rega previamente agendada."""
        pass

    @abstractmethod
    def resolver_parcela(
        self,
        parcela_ref: Optional[str],
        token: str,
    ) -> Dict[str, Any]:
        """Resolve a parcela informada pelo utilizador ou seleciona parcela padrão."""
        pass

    @abstractmethod
    def listar_parcelas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        """Lista as parcelas / fazendas do agricultor autenticado."""
        pass

    @abstractmethod
    def obter_estudo_campo(
        self,
        parcela_ref: Optional[str],
        forcar_nova_analise: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Obtém estudo de solo/satélite (recomendações, índices) com cache 24h e limite diário."""
        pass

    @abstractmethod
    def obter_historico_solo(
        self,
        parcela_ref: Optional[str],
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Obtém as observações históricas de solo/satélite da parcela via GET /soil/{farm_id}/history."""
        pass

    @abstractmethod
    def listar_vendas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        """Devolve as vendas realizadas pelo agricultor (modo só de leitura)."""
        pass

    @abstractmethod
    def obter_resumo_vendas(
        self,
        token: str,
    ) -> Dict[str, Any]:
        """Devolve o resumo financeiro (vendas brutas, comissão, rendimento líquido)."""
        pass

    @abstractmethod
    def obter_tendencias_vendas(
        self,
        token: str,
    ) -> List[Dict[str, Any]]:
        """Devolve a série temporal de vendas diárias do agricultor."""
        pass

    @abstractmethod
    def resolver_produto(
        self,
        produto_ref: str,
        token: str,
    ) -> Dict[str, Any]:
        """Resolve produto publicado do utilizador pelo nome."""
        pass

    @abstractmethod
    def actualizar_anuncio(
        self,
        produto_ref: str,
        preco_kz_kg: Optional[float],
        quantidade_kg: Optional[float],
        confirmed: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Atualiza preço e/ou quantidade de um produto via PATCH /products/{id}."""
        pass

    @abstractmethod
    def retirar_anuncio(
        self,
        produto_ref: str,
        confirmed: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Retira produto de venda definindo quantity_available=0 (nunca DELETE)."""
        pass
