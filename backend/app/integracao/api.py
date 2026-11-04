"""Implementação da plataforma de integração no modo 'api' contra o backend REST do NongLink."""

from datetime import datetime, timedelta, timezone
import logging
import mimetypes
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
from zoneinfo import ZoneInfo

from fastapi import HTTPException
import httpx

from app.db import CROP_CANONICAL_MAP
from app.guardas import obter_margem_preco_percentagem
from app.integracao.base import Plataforma
from app.visao import resolve_photo_path

logger = logging.getLogger(__name__)

# Cache de autenticação (token -> (timestamp_expiracao, user_dict))
_AUTH_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
AUTH_CACHE_TTL_SECONDS = 60.0

# Cache de culturas (timestamp_expiracao, lista_de_culturas)
_CROPS_CACHE: Optional[Tuple[float, List[Dict[str, Any]]]] = None
CROPS_CACHE_TTL_SECONDS = 300.0

# Registo de acções em curso para protecção de idempotência e reconciliação
_ACOES_EM_CURSO: Dict[str, Dict[str, Any]] = {}

# Cache de análise de solo (farm_id -> (timestamp_expiracao, dados_dict)) - 24 horas
_SOIL_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
SOIL_CACHE_TTL_SECONDS = 24 * 3600.0

# Registo de análises de satélite disparadas por utilizador hoje (user_id -> lista de timestamps)
_SOIL_ANALYSES_BY_USER: Dict[str, List[float]] = {}
SOIL_MAX_POR_UTILIZADOR_DIA_DEFAULT = 3
SOIL_ANALYZE_TIMEOUT_SECONDS = 90.0


def _remover_acentos(texto: str) -> str:
    """Normaliza texto para minúsculas sem acentos."""
    if not texto:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    ).lower().strip()


def _extrair_detalhe_seguro(resp: httpx.Response, fallback: str) -> str:
    """Extrai mensagem amigável sem expor dados confidenciais, tokens, URLs ou erros internos 5xx."""
    if resp.status_code >= 500:
        return fallback

    try:
        data = resp.json()
        if isinstance(data, dict):
            detail = data.get("detail") or data.get("message") or data.get("erro")
            if isinstance(detail, str) and len(detail) < 200:
                det_lower = detail.lower()
                if not any(k in det_lower for k in ("http://", "https://", "token", "key=", "bearer", "password", "senha", "secret")):
                    return detail
    except Exception:
        pass
    return fallback


def _obter_tz_luanda():
    """Retorna o fuso horário de Angola (Africa/Luanda, UTC+1)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Africa/Luanda")
    except Exception:
        return timezone(timedelta(hours=1))


def limpar_caches_api() -> None:
    """Limpa caches em memória de autenticação, culturas, solo e ações."""
    global _AUTH_CACHE, _CROPS_CACHE, _ACOES_EM_CURSO, _SOIL_CACHE, _SOIL_ANALYSES_BY_USER
    _AUTH_CACHE.clear()
    _CROPS_CACHE = None
    _ACOES_EM_CURSO.clear()
    _SOIL_CACHE.clear()
    _SOIL_ANALYSES_BY_USER.clear()


class ApiPlataforma(Plataforma):
    """Cliente para a API REST do NongLink (prefixo /api/v1) com retry seguro e reconciliação."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 10.0,
    ) -> None:
        raw_url = base_url or os.environ.get("NONGLINK_API_URL", "http://localhost:8000")
        raw_url = raw_url.rstrip("/")
        if not raw_url.endswith("/api/v1"):
            self.base_url = f"{raw_url}/api/v1"
        else:
            self.base_url = raw_url

        self.timeout = httpx.Timeout(timeout, connect=timeout, read=timeout, write=timeout)
        self.transport = transport

    def _get_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )

    def _request_with_retry(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
        max_retries: int = 2,
    ) -> httpx.Response:
        """Executa pedido HTTP com até 2 repetições estritamente em falhas de rede e status 502/503/504."""
        tentativas = 0
        ultima_excecao: Optional[Exception] = None

        with self._get_client() as client:
            while tentativas <= max_retries:
                tentativas += 1
                try:
                    resp = client.request(
                        method=method,
                        url=path,
                        headers=headers,
                        json=json_data,
                        params=params,
                        files=files,
                    )
                    # Repete apenas se 502, 503 ou 504 e ainda restarem tentativas
                    if resp.status_code in (502, 503, 504) and tentativas <= max_retries:
                        time.sleep(0.3 * tentativas)
                        continue
                    return resp
                except (httpx.NetworkError, httpx.TimeoutException) as exc:
                    ultima_excecao = exc
                    if tentativas <= max_retries:
                        time.sleep(0.3 * tentativas)
                        continue
                    raise exc

        if ultima_excecao:
            raise ultima_excecao
        raise RuntimeError("Falha inesperada no ciclo de requisição.")

    def autenticar(self, identifier: str, password: str) -> Dict[str, Any]:
        """POST /auth/login - Autentica utilizador no NongLink e devolve token e dados."""
        payload = {"identifier": identifier.strip(), "password": password}
        try:
            resp = self._request_with_retry("POST", "/auth/login", json_data=payload)
        except (httpx.NetworkError, httpx.TimeoutException):
            return {
                "sucesso": False,
                "erro": "Não foi possível contactar o servidor do NongLink. Verifique a ligação.",
                "status_code": 503,
            }

        if resp.status_code == 200:
            data = resp.json()
            user_info = data.get("user", {})
            token = data.get("access_token", "")
            if token and user_info:
                _AUTH_CACHE[token] = (time.time() + AUTH_CACHE_TTL_SECONDS, user_info)
            return {
                "sucesso": True,
                "access_token": token,
                "token_type": "bearer",
                "user": user_info,
            }

        if resp.status_code in (400, 401, 404):
            return {
                "sucesso": False,
                "erro": "Email ou palavra-passe incorrectos",
                "status_code": 401,
            }

        return {
            "sucesso": False,
            "erro": "Erro ao autenticar no servidor NongLink.",
            "status_code": resp.status_code,
        }

    def obter_utilizador_me(self, token: str) -> Dict[str, Any]:
        """GET /auth/me com Bearer token e cache de 60 s."""
        cleaned_token = token.strip()
        if not cleaned_token:
            return {}

        now = time.time()
        cached = _AUTH_CACHE.get(cleaned_token)
        if cached:
            exp, user = cached
            if now < exp:
                return user

        headers = {"Authorization": f"Bearer {cleaned_token}"}
        try:
            resp = self._request_with_retry("GET", "/auth/me", headers=headers)
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=503,
                detail="Serviço de autenticação do NongLink temporariamente indisponível.",
            ) from exc

        if resp.status_code == 200:
            user = resp.json()
            _AUTH_CACHE[cleaned_token] = (now + AUTH_CACHE_TTL_SECONDS, user)
            return user
        elif resp.status_code in (500, 502, 503, 504):
            _AUTH_CACHE.pop(cleaned_token, None)
            raise HTTPException(
                status_code=503,
                detail="Serviço de autenticação do NongLink temporariamente indisponível.",
            )
        elif resp.status_code in (401, 403, 404):
            _AUTH_CACHE.pop(cleaned_token, None)
            return {}

        _AUTH_CACHE.pop(cleaned_token, None)
        return {}

    def _obter_culturas(self) -> List[Dict[str, Any]]:
        """GET /crops/ (público) com cache em memória."""
        global _CROPS_CACHE
        now = time.time()
        if _CROPS_CACHE is not None:
            exp, items = _CROPS_CACHE
            if now < exp:
                return items

        try:
            resp = self._request_with_retry("GET", "/crops/")
            if resp.status_code == 200:
                items = resp.json()
                _CROPS_CACHE = (now + CROPS_CACHE_TTL_SECONDS, items)
                return items
        except Exception as exc:
            logger.warning("Falha ao obter culturas do NongLink: %s", exc)

        if _CROPS_CACHE is not None:
            return _CROPS_CACHE[1]
        return []

    def resolver_cultura(self, nome_cultura: str) -> Optional[Dict[str, Any]]:
        """Resolve nome da cultura para o objeto da cultura (com crop_id) sem acentos."""
        culturas = self._obter_culturas()
        norm = _remover_acentos(nome_cultura)
        canon = CROP_CANONICAL_MAP.get(norm, norm)
        canon_norm = _remover_acentos(canon)

        # 1. Correspondência exata
        for c in culturas:
            c_norm = _remover_acentos(c.get("name", ""))
            if c_norm in (norm, canon_norm):
                return c

        # 2. Correspondência parcial
        for c in culturas:
            c_norm = _remover_acentos(c.get("name", ""))
            if norm in c_norm or c_norm in norm:
                return c

        return None

    def listar_farms_mine(self, token: str) -> List[Dict[str, Any]]:
        """GET /farms/mine com Bearer token."""
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/farms/mine", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao listar parcelas /farms/mine: %s", exc)
        return []

    def resolver_parcela(
        self,
        parcela_ref: Optional[str],
        token: str,
    ) -> Dict[str, Any]:
        """Resolve farm_id a partir de GET /farms/mine: 1 usa-a, várias pergunta, 0 avisa."""
        farms = self.listar_farms_mine(token)
        if not farms:
            return {
                "status": "sem_parcelas",
                "farm_id": None,
                "mensagem": "Não tem nenhuma parcela registada no NongLink. É necessário criar uma parcela na plataforma antes de agendar regas ou publicar anúncios.",
            }

        if len(farms) == 1:
            return {
                "status": "ok",
                "farm_id": farms[0]["id"],
                "nome": farms[0].get("name", f"Parcela {farms[0]['id']}"),
                "farm": farms[0],
            }

        # Várias parcelas: tenta identificar por nome se o agricultor tiver indicado
        if parcela_ref and parcela_ref.strip():
            ref_norm = _remover_acentos(parcela_ref)
            for f in farms:
                f_norm = _remover_acentos(f.get("name", ""))
                if f_norm == ref_norm or ref_norm in f_norm:
                    return {
                        "status": "ok",
                        "farm_id": f["id"],
                        "nome": f.get("name"),
                        "farm": f,
                    }

        nomes = [f.get("name", f"Parcela #{f['id']}") for f in farms]
        return {
            "status": "multiplas",
            "farm_id": None,
            "mensagem": f"Qual das suas parcelas ({', '.join(nomes)}) pretende utilizar?",
            "parcelas": farms,
        }

    def obter_preco(
        self,
        cultura: str,
        region_id: Optional[int] = None,
        quality: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /market/price-suggestions: obtém sugestão indicativa com intervalo, confiança e justificação."""
        crop = self.resolver_cultura(cultura)
        if not crop:
            return {
                "status": "not_found",
                "cultura": cultura,
                "mensagem": f"Não foram encontrados dados da cultura '{cultura}' na API do NongLink.",
            }

        # Resolver region_id se não fornecido
        reg_id = region_id
        if reg_id is None and token:
            user = self.obter_utilizador_me(token)
            reg_id = user.get("region_id")
        if reg_id is None:
            reg_id = 1  # Região padrão (Luanda)

        payload = {
            "crop_id": crop["id"],
            "region_id": reg_id,
        }
        if quality:
            payload["quality"] = quality

        headers = {"Authorization": f"Bearer {token.strip()}"} if token else {}
        try:
            resp = self._request_with_retry(
                "POST", "/market/price-suggestions", headers=headers, json_data=payload
            )
        except (httpx.NetworkError, httpx.TimeoutException):
            return {
                "status": "error",
                "cultura": cultura,
                "mensagem": "Não foi possível obter sugestões de preço devido a um problema de ligação à API do NongLink.",
            }

        if resp.status_code == 200:
            data = resp.json()
            is_insufficient = data.get("status") == "insufficient_data"
            sug_price = float(data.get("suggested_price") or data.get("base_price") or 0.0)
            min_price = float(data.get("min_price") or data.get("range_low") or 0.0)
            max_price = float(data.get("max_price") or data.get("range_high") or 0.0)
            raw_conf = data.get("confidence")
            if isinstance(raw_conf, (int, float)):
                conf = float(raw_conf)
            else:
                conf_str = str(raw_conf or "").lower().strip()
                conf_map = {
                    "alta": 0.85,
                    "high": 0.85,
                    "media": 0.60,
                    "média": 0.60,
                    "medium": 0.60,
                    "baixa": 0.35,
                    "low": 0.35,
                }
                conf = conf_map.get(conf_str, 0.50 if raw_conf else 0.0)
            conf_pct = round(conf * 100, 1)
            reasoning = str(
                data.get("reasoning")
                or data.get("note")
                or ("Sem histórico suficiente de mercado para calcular intervalo preditivo." if is_insufficient else "Estimativa baseada nos dados de mercado recentes.")
            )
            unidade = crop.get("default_unit", "kg")

            nota = (
                f"referência indicativa NongLink ({reasoning})"
                if is_insufficient or sug_price <= 0
                else (
                    f"referência indicativa NongLink (sugerido: {sug_price:.0f} Kz/{unidade}, "
                    f"intervalo: {min_price:.0f} a {max_price:.0f} Kz/{unidade}, confiança: {conf_pct}%)"
                )
            )

            return {
                "status": "executed",
                "cultura": cultura,
                "crop_id": crop["id"],
                "region_id": reg_id,
                "preco_sugerido": sug_price,
                "preco_min": min_price,
                "preco_max": max_price,
                "confianca": conf,
                "confianca_percentagem": conf_pct,
                "justificacao": reasoning,
                "unidade": f"Kz/{unidade}",
                "tipo": "indicativo",
                "nota": nota,
                "sem_historico": is_insufficient or (min_price <= 0 and max_price <= 0),
                "mensagem": (
                    f"Cultura '{cultura}': {reasoning}"
                    if is_insufficient or sug_price <= 0
                    else (
                        f"Preço indicativo sugerido: {sug_price:.0f} Kz/{unidade} "
                        f"(intervalo de {min_price:.0f} a {max_price:.0f} Kz/{unidade}, confiança {conf_pct}%). "
                        f"Justificação: {reasoning}"
                    )
                ),
            }

        return {
            "status": "error",
            "cultura": cultura,
            "mensagem": f"A API do NongLink devolveu erro ao consultar preços (status {resp.status_code}).",
        }

    def validar_preco(
        self,
        cultura: str,
        preco_kz_kg: float,
        token: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Compara o preço com min_price e max_price com a margem MARGEM_PRECO. Se a API falhar, recusa."""
        cotacao = self.obter_preco(cultura, token=token)
        if cotacao.get("status") != "executed":
            return (
                False,
                "Não foi possível validar o preço através da API oficial do NongLink. O anúncio não será proposto.",
                None,
            )

        p_min = float(cotacao.get("preco_min") or 0.0)
        p_max = float(cotacao.get("preco_max") or 0.0)
        if p_min <= 0 or p_max <= 0:
            if preco_kz_kg > 0:
                # Sem histórico preditivo suficiente no mercado; aceita o preço definido pelo agricultor
                return (
                    True,
                    "Preço aceite: sem cotação preditiva estatística disponível na plataforma para esta região.",
                    cotacao,
                )
            return (
                False,
                "O preço por quilograma deve ser superior a zero.",
                None,
            )

        if p_min > p_max:
            p_min, p_max = p_max, p_min

        margem = obter_margem_preco_percentagem()
        lim_inf = p_min * (1.0 - margem / 100.0)
        lim_sup = p_max * (1.0 + margem / 100.0)

        if preco_kz_kg < lim_inf or preco_kz_kg > lim_sup:
            return (
                False,
                (
                    f"Preço proposto ({preco_kz_kg:.0f} Kz/kg) fora do intervalo permitido "
                    f"({lim_inf:.0f} a {lim_sup:.0f} Kz/kg) em relação à sugestão do NongLink "
                    f"({p_min:.0f} a {p_max:.0f} Kz/kg com margem de {margem:.0f}%)."
                ),
                cotacao,
            )

        return True, "", cotacao

    def _upload_foto_anuncio(self, foto_id: str, token: str, user_id: Optional[str] = None) -> Optional[str]:
        """Faz POST /products/upload-image se ANEXAR_FOTO=1 e devolve image_url."""
        if os.environ.get("ANEXAR_FOTO", "").strip() != "1":
            return None

        photo_path = resolve_photo_path(foto_id, utilizador_id=user_id)
        if not photo_path or not photo_path.is_file():
            return None

        mime, _ = mimetypes.guess_type(str(photo_path))
        mime = mime or "image/jpeg"
        headers = {"Authorization": f"Bearer {token.strip()}"}

        try:
            with open(photo_path, "rb") as f:
                file_content = f.read()
            files = {"file": (photo_path.name, file_content, mime)}
            resp = self._request_with_retry(
                "POST",
                "/products/upload-image",
                headers=headers,
                files=files,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("image_url")
        except Exception as exc:
            logger.warning("Erro ao enviar foto para /products/upload-image: %s", exc)
        return None

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
        """POST /products/ com validação, prevenção de duplicados e reconciliação pós-timeout."""
        if not token:
            return {
                "status": "error",
                "message": "Token de autenticação não fornecido para integração com o NongLink.",
            }

        total_kz = round(float(quantidade_kg) * float(preco_kz_kg), 2)
        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "cultura": cultura,
                "quantidade_kg": quantidade_kg,
                "preco_kz_kg": preco_kz_kg,
                "valor_total_kz": total_kz,
                "mensagem": {
                    "pt": "Anúncio não publicado (aguarda confirmação ou cancelado pelo utilizador).",
                    "fr": "Annonce non publiée (en attente de confirmation ou annulée par l'utilisateur).",
                    "en": "Listing not published (awaiting confirmation or cancelled by user).",
                },
            }

        # 1. Resolver cultura -> crop_id
        crop = self.resolver_cultura(cultura)
        if not crop:
            return {
                "status": "error",
                "message": f"Cultura '{cultura}' não encontrada no catálogo oficial do NongLink.",
            }

        # 2. Resolver parcela -> farm_id
        res_parcela = self.resolver_parcela(None, token)
        if res_parcela["status"] != "ok":
            return {
                "status": "error",
                "message": res_parcela["mensagem"],
            }
        farm_id = res_parcela["farm_id"]

        # 3. Upload opcional de imagem se ANEXAR_FOTO=1
        image_url = None
        if foto_id:
            user_id = str(user.get("id")) if user else None
            image_url = self._upload_foto_anuncio(foto_id, token, user_id=user_id)

        product_payload = {
            "farm_id": farm_id,
            "crop_id": crop["id"],
            "name": f"{crop.get('name', cultura).capitalize()}",
            "price_per_unit": float(preco_kz_kg),
            "quantity_available": float(quantidade_kg),
            "unit": crop.get("default_unit", "kg"),
        }
        if image_url:
            product_payload["image_url"] = image_url
        if qualidade:
            product_payload["quality"] = qualidade
        if certificacao:
            product_payload["certification"] = certificacao

        # 4. Registar ação "em curso" antes de criar
        action_key = f"prod_{farm_id}_{crop['id']}_{float(quantidade_kg):.2f}_{float(preco_kz_kg):.2f}"
        _ACOES_EM_CURSO[action_key] = {
            "status": "em_curso",
            "tipo": "produto",
            "iniciado_em": time.time(),
            "payload": product_payload,
        }

        headers = {"Authorization": f"Bearer {token.strip()}"}
        criado_com_sucesso = False
        reconciliado_flag = False
        resp_data: Dict[str, Any] = {}

        try:
            resp = self._request_with_retry(
                "POST",
                "/products/",
                headers=headers,
                json_data=product_payload,
                max_retries=0,
            )
            if resp.status_code in (200, 201):
                criado_com_sucesso = True
                resp_data = resp.json()
            else:
                _ACOES_EM_CURSO.pop(action_key, None)
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": f"Erro do NongLink ao criar produto (HTTP {resp.status_code}): {detail}",
                }
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            # Reconciliação: consulta GET /products/mine para verificar se o produto foi criado
            logger.warning("Timeout/erro de rede ao criar produto. A consultar /products/mine para reconciliar...")
            reconciliado = self._reconciliar_produto_apos_timeout(farm_id, crop["id"], quantidade_kg, preco_kz_kg, token)
            if reconciliado:
                criado_com_sucesso = True
                resp_data = reconciliado
                reconciliado_flag = True
            else:
                _ACOES_EM_CURSO.pop(action_key, None)
                return {
                    "status": "error",
                    "message": "Ocorreu uma falha de comunicação com o NongLink. A verificação indicou que o anúncio não foi criado. Pode tentar novamente em segurança.",
                }

        _ACOES_EM_CURSO.pop(action_key, None)
        real_id = resp_data.get("id")
        return {
            "status": "executed",
            "id": real_id,
            "anuncio_id": real_id,
            "reconciliado_pos_timeout": reconciliado_flag,
            "cultura": cultura,
            "quantidade_kg": float(quantidade_kg),
            "preco_kz_kg": float(preco_kz_kg),
            "valor_total_kz": total_kz,
            "image_url": resp_data.get("image_url"),
            "criado_em": resp_data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "mensagem": {
                "pt": f"Anúncio #{real_id} publicado no NongLink: {quantidade_kg} kg de {cultura} a {preco_kz_kg} Kz/kg (Total: {total_kz} Kz).",
                "fr": f"Annonce #{real_id} publiée sur NongLink : {quantidade_kg} kg de {cultura} à {preco_kz_kg} Kz/kg (Total : {total_kz} Kz).",
                "en": f"Listing #{real_id} published on NongLink: {quantidade_kg} kg of {cultura} at {preco_kz_kg} Kz/kg (Total: {total_kz} Kz).",
            },
        }

    def _reconciliar_produto_apos_timeout(
        self,
        farm_id: int,
        crop_id: int,
        quantidade_kg: float,
        preco_kz_kg: float,
        token: str,
    ) -> Optional[Dict[str, Any]]:
        """Consulta /products/mine para verificar se o produto foi inserido apesar do timeout."""
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/products/mine", headers=headers)
            if resp.status_code == 200:
                products = resp.json()
                for p in reversed(products):
                    if (
                        p.get("farm_id") == farm_id
                        and p.get("crop_id") == crop_id
                        and abs(float(p.get("price_per_unit", 0)) - float(preco_kz_kg)) < 0.01
                        and abs(float(p.get("quantity_available", 0)) - float(quantidade_kg)) < 0.01
                    ):
                        return p
        except Exception as exc:
            logger.warning("Falha na reconciliação de produto: %s", exc)
        return None

    def _converter_hora_luanda_para_utc(self, hora_str: str, data_especifica: Optional[str] = None) -> str:
        """Converte hora fornecida pelo utilizador (Africa/Luanda, UTC+1) para timestamp ISO UTC."""
        tz_luanda = _obter_tz_luanda()
        agora_luanda = datetime.now(tz_luanda)

        match = re.search(r"(\d{1,2}):(\d{2})", hora_str)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            if data_especifica:
                partes = [int(p) for p in data_especifica.split("-")]
                dt_local = datetime(partes[0], partes[1], partes[2], h, m, tzinfo=tz_luanda)
            else:
                dt_local = agora_luanda.replace(hour=h, minute=m, second=0, microsecond=0)
                # Se a hora informada já passou hoje com mais de 1 minuto de margem, agenda para o dia seguinte
                if dt_local < agora_luanda - timedelta(minutes=1):
                    dt_local += timedelta(days=1)
            dt_utc = dt_local.astimezone(timezone.utc)
            return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Se já for formato ISO:
        try:
            cleaned = hora_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz_luanda)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            raise ValueError(f"Formato de hora inválido: {hora_str}")

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
        """POST /farms/{farm_id}/irrigations com conversão Africa/Luanda -> UTC e duração 1..600."""
        if not token:
            return {
                "status": "error",
                "message": "Token de autenticação não fornecido para agendar rega no NongLink.",
            }

        # Obter duração padrão (DURACAO_REGA_PADRAO, omissão 30)
        duracao_final = duracao_minutos
        if duracao_final is None:
            try:
                duracao_final = int(os.environ.get("DURACAO_REGA_PADRAO", "30"))
            except (ValueError, TypeError):
                duracao_final = 30
        duracao_final = max(1, min(600, duracao_final))

        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "parcela": parcela,
                "hora": hora,
                "duracao_minutos": duracao_final,
                "mensagem": {
                    "pt": f"Rega não agendada na parcela '{parcela}' (Duração: {duracao_final} min).",
                    "fr": f"Irrigation non planifiée sur la parcelle '{parcela}' (Durée : {duracao_final} min).",
                    "en": f"Irrigation not scheduled on plot '{parcela}' (Duration: {duracao_final} min).",
                },
            }

        # 1. Resolver parcela
        res_parcela = self.resolver_parcela(parcela, token)
        if res_parcela["status"] != "ok":
            return {
                "status": "error",
                "message": res_parcela["mensagem"],
            }
        farm_id = res_parcela["farm_id"]
        nome_parcela = res_parcela.get("nome", parcela)

        # 2. Converter hora Africa/Luanda -> UTC
        try:
            utc_scheduled_time = self._converter_hora_luanda_para_utc(hora, data_especifica=data_especifica)
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Erro no formato de hora: {exc}",
            }

        irrigation_payload = {
            "scheduled_time": utc_scheduled_time,
            "duration_minutes": duracao_final,
            "notes": f"Rega agendada pelo assistente inteligente para {nome_parcela}",
            "criada_via": "agente",
        }

        # 3. Registar acção "em curso"
        action_key = f"rega_{farm_id}_{utc_scheduled_time}_{duracao_final}"
        _ACOES_EM_CURSO[action_key] = {
            "status": "em_curso",
            "tipo": "rega",
            "iniciado_em": time.time(),
            "payload": irrigation_payload,
        }

        headers = {"Authorization": f"Bearer {token.strip()}"}
        reconciliado_flag = False
        resp_data: Dict[str, Any] = {}

        try:
            resp = self._request_with_retry(
                "POST",
                f"/farms/{farm_id}/irrigations",
                headers=headers,
                json_data=irrigation_payload,
                max_retries=0,
            )

            # Caso 409 (sobreposição): explica conflito e pede outro horário sem repetir
            if resp.status_code == 409:
                _ACOES_EM_CURSO.pop(action_key, None)
                return {
                    "status": "error",
                    "conflito_sobreposicao": True,
                    "parcela": nome_parcela,
                    "hora": hora,
                    "duracao_minutos": duracao_final,
                    "mensagem": (
                        f"Já existe uma rega agendada na parcela '{nome_parcela}' nesse horário. "
                        "Por favor escolha outro horário para a rega."
                    ),
                }

            if resp.status_code in (200, 201):
                resp_data = resp.json()
            else:
                _ACOES_EM_CURSO.pop(action_key, None)
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": f"Erro ao agendar rega no NongLink (HTTP {resp.status_code}): {detail}",
                }

        except (httpx.NetworkError, httpx.TimeoutException):
            logger.warning("Timeout/erro de rede ao agendar rega. A consultar /irrigations/mine para reconciliar...")
            reconciliado = self._reconciliar_rega_apos_timeout(farm_id, utc_scheduled_time, token)
            if reconciliado:
                resp_data = reconciliado
                reconciliado_flag = True
            else:
                _ACOES_EM_CURSO.pop(action_key, None)
                return {
                    "status": "error",
                    "message": "Ocorreu um erro de comunicação com o NongLink. A verificação indicou que a rega não foi criada. Pode tentar agendar novamente.",
                }

        _ACOES_EM_CURSO.pop(action_key, None)
        real_id = resp_data.get("id")
        return {
            "status": "executed",
            "id": real_id,
            "agendamento_id": real_id,
            "reconciliado_pos_timeout": reconciliado_flag,
            "parcela": nome_parcela,
            "hora": hora,
            "duracao_minutos": duracao_final,
            "scheduled_time_utc": utc_scheduled_time,
            "criada_via": resp_data.get("criada_via", "agente"),
            "criado_em": resp_data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "mensagem": {
                "pt": f"Rega #{real_id} agendada com sucesso no NongLink para a parcela '{nome_parcela}' às {hora} (Duração: {duracao_final} min).",
                "fr": f"Irrigation #{real_id} planifiée avec succès sur NongLink pour '{nome_parcela}' à {hora} (Durée : {duracao_final} min).",
                "en": f"Irrigation #{real_id} scheduled successfully on NongLink for plot '{nome_parcela}' at {hora} (Duration: {duracao_final} min).",
            },
        }

    def _reconciliar_rega_apos_timeout(
        self,
        farm_id: int,
        utc_scheduled_time: str,
        token: str,
    ) -> Optional[Dict[str, Any]]:
        """Consulta /irrigations/mine para verificar se a rega foi inserida após timeout."""
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/irrigations/mine", headers=headers)
            if resp.status_code == 200:
                irrigations = resp.json()
                for irr in reversed(irrigations):
                    if irr.get("farm_id") == farm_id:
                        # Compara início do timestamp UTC
                        t_iso = str(irr.get("scheduled_time", "")).replace(" ", "T")
                        if utc_scheduled_time[:16] in t_iso:
                            return irr
        except Exception as exc:
            logger.warning("Falha na reconciliação de rega: %s", exc)
        return None

    def listar_anuncios(
        self,
        user: Any,
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """GET /products/mine com Bearer token."""
        auth_token = token or (user if isinstance(user, str) else (user.get("token") if isinstance(user, dict) else None))
        if not auth_token:
            return []
        headers = {"Authorization": f"Bearer {auth_token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/products/mine", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao listar /products/mine: %s", exc)
        return []

    def listar_regas(
        self,
        user: Any,
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """GET /irrigations/mine com Bearer token."""
        auth_token = token or (user if isinstance(user, str) else (user.get("token") if isinstance(user, dict) else None))
        if not auth_token:
            return []
        headers = {"Authorization": f"Bearer {auth_token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/irrigations/mine", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao listar /irrigations/mine: %s", exc)
        return []

    def cancelar_rega(
        self,
        rega_id: str,
        user: Dict[str, Any],
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PATCH /irrigations/{id}/cancel com Bearer token."""
        if not token:
            return {"status": "error", "message": "Token de autenticação obrigatório."}

        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("PATCH", f"/irrigations/{rega_id}/cancel", headers=headers)
            if resp.status_code == 200:
                return {
                    "status": "cancelled",
                    "id": rega_id,
                    "resultado": resp.json(),
                    "mensagem": f"Rega #{rega_id} cancelada com sucesso no NongLink.",
                }
            if resp.status_code == 404:
                return {"status": "error", "message": "Rega não encontrada ou pertence a outro utilizador."}
            if resp.status_code == 400:
                return {"status": "error", "message": "Apenas regas no estado agendada podem ser canceladas."}
            detail = _extrair_detalhe_seguro(resp, "Não foi possível cancelar a rega.")
            return {"status": "error", "message": f"Erro do NongLink ao cancelar rega: {detail}"}
        except Exception as exc:
            return {"status": "error", "message": f"Falha de comunicação com o NongLink: {exc}"}

    def listar_parcelas(self, token: str) -> List[Dict[str, Any]]:
        """GET /farms/mine com Bearer token."""
        return self.listar_farms_mine(token)

    def obter_estudo_campo(
        self,
        parcela_ref: Optional[str],
        forcar_nova_analise: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Consulta ou solicita observação de solo/satélite via Google Earth Engine."""
        if not token:
            return {"status": "error", "message": "Token de autenticação obrigatório para estudo de campo."}

        # 1. Resolver parcela
        res_parcela = self.resolver_parcela(parcela_ref, token)
        if res_parcela.get("status") != "ok":
            return res_parcela

        farm_id = res_parcela["farm_id"]
        nome_parcela = res_parcela.get("nome", f"Parcela #{farm_id}")
        now = time.time()
        headers = {"Authorization": f"Bearer {token.strip()}"}

        # 2. Se forçada nova análise via POST /soil/{farm_id}/analyze (timeout de 90s, sem repetições automáticas)
        if forcar_nova_analise:
            user_key = (
                str(user.get("id"))
                if user and user.get("id")
                else (str(user.get("utilizador_externo_id")) if user and user.get("utilizador_externo_id") else "user_default")
            )
            limite_diario = int(os.environ.get("SOLO_MAX_POR_UTILIZADOR_DIA", str(SOIL_MAX_POR_UTILIZADOR_DIA_DEFAULT)))

            # Verificar quota de análises de satélite
            historico = _SOIL_ANALYSES_BY_USER.get(user_key, [])
            cutoff = now - 24 * 3600.0
            historico = [t for t in historico if t > cutoff]
            _SOIL_ANALYSES_BY_USER[user_key] = historico

            if len(historico) >= limite_diario:
                return {
                    "status": "quota_excedida",
                    "parcela": nome_parcela,
                    "farm_id": farm_id,
                    "limite_diario": limite_diario,
                    "mensagem": (
                        f"Atingiu o limite diário de {limite_diario} análises de satélite. "
                        "Para poupar recursos, consulte os dados mais recentes da lavra ou tente novamente amanhã."
                    ),
                }

            with httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(SOIL_ANALYZE_TIMEOUT_SECONDS, connect=15.0, read=SOIL_ANALYZE_TIMEOUT_SECONDS, write=15.0),
                transport=self.transport,
            ) as client:
                try:
                    resp = client.post(f"/soil/{farm_id}/analyze", headers=headers, json={})
                except (httpx.NetworkError, httpx.TimeoutException) as exc:
                    return {
                        "status": "error",
                        "parcela": nome_parcela,
                        "farm_id": farm_id,
                        "mensagem": f"O processamento de imagens de satélite excedeu o tempo limite ({SOIL_ANALYZE_TIMEOUT_SECONDS:.0f}s). Tente novamente mais tarde.",
                    }

            if resp.status_code in (200, 201):
                data = resp.json()
                _SOIL_ANALYSES_BY_USER[user_key].append(now)
                _SOIL_CACHE[farm_id] = (now + SOIL_CACHE_TTL_SECONDS, data)
                return self._formatar_resposta_solo(data, nome_parcela, farm_id, nova_analise=True, em_cache=False)

            if resp.status_code == 400:
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {
                    "status": "sem_poligono",
                    "codigo": 400,
                    "parcela": nome_parcela,
                    "farm_id": farm_id,
                    "mensagem": (
                        f"Esta parcela ('{nome_parcela}') ainda não tem um polígono desenhado. "
                        "O limite da parcela deve ser desenhado na plataforma agrilink.store antes de solicitar a análise."
                    ),
                }

            if resp.status_code == 404:
                return {
                    "status": "error",
                    "codigo": 404,
                    "parcela": nome_parcela,
                    "farm_id": farm_id,
                    "mensagem": f"Parcela '{nome_parcela}' não encontrada ou não pertence ao agricultor autenticado.",
                }

            detail = _extrair_detalhe_seguro(resp, "Erro ao analisar solo.")
            return {
                "status": "error",
                "codigo": resp.status_code,
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "mensagem": f"A API do NongLink devolveu erro ao analisar solo (HTTP {resp.status_code}): {detail}",
            }

        # 3. Leitura padrão (GET /soil/{farm_id}/latest com cache de 24h)
        cached = _SOIL_CACHE.get(farm_id)
        if cached and now < cached[0]:
            return self._formatar_resposta_solo(cached[1], nome_parcela, farm_id, nova_analise=False, em_cache=True)

        try:
            resp = self._request_with_retry("GET", f"/soil/{farm_id}/latest", headers=headers)
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            return {
                "status": "error",
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "mensagem": "Falha de ligação ao consultar análise de solo mais recente.",
            }

        if resp.status_code == 200:
            data = resp.json()
            _SOIL_CACHE[farm_id] = (now + SOIL_CACHE_TTL_SECONDS, data)
            return self._formatar_resposta_solo(data, nome_parcela, farm_id, nova_analise=False, em_cache=False)

        if resp.status_code == 404:
            return {
                "status": "sem_analises",
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "mensagem": (
                    f"Ainda não existem análises de solo/satélite para a parcela '{nome_parcela}'. "
                    "Se o polígono já estiver desenhado em agrilink.store, peça ao assistente para realizar uma nova análise."
                ),
            }

        return {
            "status": "error",
            "codigo": resp.status_code,
            "parcela": nome_parcela,
            "farm_id": farm_id,
            "mensagem": f"Erro ao obter dados de solo (HTTP {resp.status_code}).",
        }

    def _formatar_resposta_solo(
        self,
        data: Dict[str, Any],
        nome_parcela: str,
        farm_id: int,
        nova_analise: bool,
        em_cache: bool,
    ) -> Dict[str, Any]:
        acq_date = str(data.get("acquisition_date") or data.get("created_at") or "")
        cloud_cover = float(data.get("cloud_cover_pct") or 0.0)
        ndvi = float(data.get("ndvi_mean") or 0.0)
        ndmi = float(data.get("ndmi_mean") or 0.0)
        ndti = float(data.get("ndti_mean") or 0.0)
        salinidade = float(data.get("salinity_index_mean") or 0.0)
        recs = data.get("recommendations") or {}

        return {
            "status": "executed",
            "parcela": nome_parcela,
            "farm_id": farm_id,
            "nova_analise": nova_analise,
            "em_cache_24h": em_cache,
            "data_imagem": acq_date,
            "nebulosidade_pct": round(cloud_cover, 1),
            "cloud_cover_pct": round(cloud_cover, 1),
            "ndvi_mean": round(ndvi, 3),
            "ndmi_mean": round(ndmi, 3),
            "ndti_mean": round(ndti, 3),
            "salinity_index_mean": round(salinidade, 3),
            "recomendacoes": recs,
            "fonte_recomendacoes": "recomendações do NongLink",
            "aviso_leitura": (
                f"Esta leitura depende da data da imagem ({acq_date}) e da cobertura de nuvens ({cloud_cover:.1f}%). "
                "As orientações apresentadas são recomendações técnicas automáticas do NongLink."
            ),
        }

    def obter_historico_solo(
        self,
        parcela_ref: Optional[str],
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Consulta as observações históricas de solo via GET /soil/{farm_id}/history."""
        if not token:
            return {"status": "error", "message": "Token de autenticação obrigatório para consultar histórico de solo."}

        res_parcela = self.resolver_parcela(parcela_ref, token)
        if res_parcela.get("status") != "ok":
            return res_parcela

        farm_id = res_parcela["farm_id"]
        nome_parcela = res_parcela.get("nome", f"Parcela #{farm_id}")
        headers = {"Authorization": f"Bearer {token.strip()}"}

        try:
            resp = self._request_with_retry("GET", f"/soil/{farm_id}/history", headers=headers)
        except (httpx.NetworkError, httpx.TimeoutException):
            return {
                "status": "error",
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "mensagem": "Falha de ligação ao consultar histórico de solo.",
            }

        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "executed",
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "historico": data if isinstance(data, list) else data.get("history", []),
            }

        if resp.status_code == 404:
            return {
                "status": "not_found",
                "parcela": nome_parcela,
                "farm_id": farm_id,
                "mensagem": f"Nenhum histórico de solo encontrado para a parcela '{nome_parcela}'.",
            }

        detail = _extrair_detalhe_seguro(resp, "Erro ao obter histórico.")
        return {
            "status": "error",
            "codigo": resp.status_code,
            "parcela": nome_parcela,
            "farm_id": farm_id,
            "mensagem": f"Erro do NongLink ao consultar histórico de solo (HTTP {resp.status_code}): {detail}",
        }

    def listar_vendas(self, token: str) -> List[Dict[str, Any]]:
        """GET /orders/sales (modo só de leitura)."""
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/orders/sales", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao listar vendas /orders/sales: %s", exc)
        return []

    def obter_resumo_vendas(self, token: str) -> Dict[str, Any]:
        """GET /orders/sales/summary (vendas brutas, comissão da plataforma e rendimento líquido)."""
        if not token:
            return {"gross_sales": 0.0, "net_earnings": 0.0, "platform_fee": 0.0}
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/orders/sales/summary", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao obter resumo de vendas: %s", exc)
        return {"gross_sales": 0.0, "net_earnings": 0.0, "platform_fee": 0.0}

    def obter_tendencias_vendas(self, token: str) -> List[Dict[str, Any]]:
        """GET /orders/sales/trends (série temporal diária de vendas)."""
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("GET", "/orders/sales/trends", headers=headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("Erro ao obter tendências de vendas: %s", exc)
        return []

    def resolver_produto(
        self,
        produto_ref: str,
        token: str,
    ) -> Dict[str, Any]:
        """Resolve o anúncio do agricultor pelo nome a partir de GET /products/mine."""
        produtos = self.listar_anuncios(token=token, user=None)
        if not produtos:
            return {
                "status": "sem_produtos",
                "produto_id": None,
                "mensagem": "Não tem nenhum produto publicado no NongLink.",
            }

        ref_norm = _remover_acentos(produto_ref)
        exact_matches = []
        partial_matches = []

        for p in produtos:
            nome_norm = _remover_acentos(p.get("name", ""))
            if nome_norm == ref_norm:
                exact_matches.append(p)
            elif ref_norm in nome_norm or nome_norm in ref_norm:
                partial_matches.append(p)

        matches = exact_matches or partial_matches
        if not matches:
            nomes = [p.get("name", f"Produto #{p['id']}") for p in produtos]
            return {
                "status": "not_found",
                "produto_id": None,
                "mensagem": f"Não encontrei o produto '{produto_ref}' nos seus anúncios ({', '.join(nomes)}).",
            }

        if len(matches) == 1:
            p = matches[0]
            return {
                "status": "ok",
                "produto_id": p["id"],
                "nome": p.get("name"),
                "produto": p,
            }

        nomes = [f"{p.get('name')} (ID #{p['id']})" for p in matches]
        return {
            "status": "multiplos",
            "produto_id": None,
            "mensagem": f"Encontrei mais de um anúncio correspondente ({', '.join(nomes)}). Qual deles pretende actualizar?",
            "produtos": matches,
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
        """PATCH /products/{id} com novo preço e/ou quantidade disponível."""
        if not token:
            return {"status": "error", "message": "Token de autenticação obrigatório."}

        res_prod = self.resolver_produto(produto_ref, token)
        if res_prod.get("status") != "ok":
            return res_prod

        prod = res_prod["produto"]
        prod_id = res_prod["produto_id"]
        prod_nome = res_prod["nome"]

        novo_preco = float(preco_kz_kg) if preco_kz_kg is not None else float(prod.get("price_per_unit", 0))
        nova_qtd = float(quantidade_kg) if quantidade_kg is not None else float(prod.get("quantity_available", 0))

        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "produto_id": prod_id,
                "produto": prod_nome,
                "preco_kz_kg": novo_preco,
                "quantidade_kg": nova_qtd,
                "mensagem": {
                    "pt": f"Actualização do anúncio '{prod_nome}' não efectuada (aguarda confirmação do agricultor).",
                    "fr": f"Mise à jour de l'annonce '{prod_nome}' non effectuée (en attente de confirmation).",
                    "en": f"Update of listing '{prod_nome}' not executed (awaiting farmer confirmation).",
                },
            }

        payload: Dict[str, Any] = {}
        if preco_kz_kg is not None:
            payload["price_per_unit"] = novo_preco
        if quantidade_kg is not None:
            payload["quantity_available"] = nova_qtd

        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            resp = self._request_with_retry("PATCH", f"/products/{prod_id}", headers=headers, json_data=payload)
            if resp.status_code in (200, 204):
                data = resp.json() if resp.status_code == 200 else {}
                return {
                    "status": "executed",
                    "produto_id": prod_id,
                    "produto": prod_nome,
                    "preco_kz_kg": novo_preco,
                    "quantidade_kg": nova_qtd,
                    "resultado": data,
                    "mensagem": {
                        "pt": f"Anúncio '{prod_nome}' (ID #{prod_id}) actualizado: {nova_qtd} kg a {novo_preco:.0f} Kz/kg.",
                        "fr": f"Annonce '{prod_nome}' (ID #{prod_id}) mise à jour : {nova_qtd} kg à {novo_preco:.0f} Kz/kg.",
                        "en": f"Listing '{prod_nome}' (ID #{prod_id}) updated: {nova_qtd} kg at {novo_preco:.0f} Kz/kg.",
                    },
                }
            if resp.status_code == 404:
                return {"status": "error", "message": f"Produto #{prod_id} não encontrado ou pertence a outro utilizador."}
            return {"status": "error", "message": f"Erro ao actualizar anúncio no NongLink (HTTP {resp.status_code}): {resp.text}"}
        except Exception as exc:
            return {"status": "error", "message": f"Falha de comunicação ao actualizar anúncio: {exc}"}

    def retirar_anuncio(
        self,
        produto_ref: str,
        confirmed: bool,
        token: str,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """PATCH /products/{id} com quantity_available = 0. Nunca chama DELETE."""
        if not token:
            return {"status": "error", "message": "Token de autenticação obrigatório."}

        res_prod = self.resolver_produto(produto_ref, token)
        if res_prod.get("status") != "ok":
            return res_prod

        prod_id = res_prod["produto_id"]
        prod_nome = res_prod["nome"]

        if not confirmed:
            return {
                "status": "cancelled_by_user",
                "produto_id": prod_id,
                "produto": prod_nome,
                "mensagem": {
                    "pt": f"Retirada do anúncio '{prod_nome}' pendente: o produto ficará esgotado, mas não será apagado.",
                    "fr": f"Retrait de l'annonce '{prod_nome}' en attente : le produit sera épuisé mais non supprimé.",
                    "en": f"Withdrawal of listing '{prod_nome}' pending: product will be marked as sold out, but not deleted.",
                },
            }

        headers = {"Authorization": f"Bearer {token.strip()}"}
        try:
            # Nunca chama DELETE: faz PATCH com quantity_available=0
            resp = self._request_with_retry("PATCH", f"/products/{prod_id}", headers=headers, json_data={"quantity_available": 0.0})
            if resp.status_code in (200, 204):
                return {
                    "status": "executed",
                    "produto_id": prod_id,
                    "produto": prod_nome,
                    "quantidade_disponivel": 0.0,
                    "mensagem": {
                        "pt": f"Anúncio '{prod_nome}' (ID #{prod_id}) retirado de venda: ficará esgotado, mas não será apagado.",
                        "fr": f"Annonce '{prod_nome}' (ID #{prod_id}) retiré de la vente : il restera épuisé, mais ne sera pas supprimé.",
                        "en": f"Listing '{prod_nome}' (ID #{prod_id}) withdrawn from sale: it will be marked as out of stock, but not deleted.",
                    },
                }
            if resp.status_code == 404:
                return {"status": "error", "message": f"Produto #{prod_id} não encontrado ou pertence a outro utilizador."}
            return {"status": "error", "message": f"Erro ao retirar anúncio no NongLink (HTTP {resp.status_code}): {resp.text}"}
        except Exception as exc:
            return {"status": "error", "message": f"Falha de comunicação ao retirar anúncio: {exc}"}
