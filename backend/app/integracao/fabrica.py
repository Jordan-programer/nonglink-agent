"""Fábrica para obtenção da instância activa da plataforma de integração."""

import os
from typing import Optional

from app.integracao.base import Plataforma
from app.integracao.sandbox import SandboxPlataforma

_INSTANCIA_PLATAFORMA: Optional[Plataforma] = None


def obter_plataforma(recarregar: bool = False) -> Plataforma:
    """Retorna a plataforma activa conforme MODO_PLATAFORMA e NONGLINK_API_URL.

    O modo 'api' só é activado se MODO_PLATAFORMA == 'api' E NONGLINK_API_URL estiver definida.
    Em todos os outros casos, devolve a SandboxPlataforma com comportamento local simulado.
    """
    global _INSTANCIA_PLATAFORMA
    if _INSTANCIA_PLATAFORMA is not None and not recarregar:
        return _INSTANCIA_PLATAFORMA

    modo = os.environ.get("MODO_PLATAFORMA", "sandbox").strip().lower()
    api_url = os.environ.get("NONGLINK_API_URL", "").strip().rstrip("/")

    if modo == "api" and api_url:
        from app.integracao.api import ApiPlataforma
        _INSTANCIA_PLATAFORMA = ApiPlataforma(base_url=api_url)
    else:
        _INSTANCIA_PLATAFORMA = SandboxPlataforma()

    return _INSTANCIA_PLATAFORMA


def redefinir_plataforma() -> None:
    """Limpa a instância em cache para permitir alternar modos em testes."""
    global _INSTANCIA_PLATAFORMA
    _INSTANCIA_PLATAFORMA = None


def definir_plataforma(plataforma: Plataforma) -> None:
    """Define explicitamente a instância da plataforma activa (útil para testes)."""
    global _INSTANCIA_PLATAFORMA
    _INSTANCIA_PLATAFORMA = plataforma
