"""Guardas determinísticas do NongLink Field Agent (backend/app/guardas.py).

Implementa verificações rígidas executadas pelo código antes de criar ações ou
devolver respostas ao utilizador. As recusas devolvem mensagens explicativas
ao modelo para que este possa corrigir o pedido ou perguntar ao agricultor.
"""

from decimal import Decimal
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.db import CROP_CANONICAL_MAP, get_crop_price_from_db

DEFAULT_MAX_QUANTIDADE_KG = 10000.0
DEFAULT_MARGEM_PRECO_PERCENTAGEM = 25.0


def obter_max_quantidade_kg() -> float:
    """Retorna a quantidade máxima permitida para um anúncio (kg)."""
    try:
        return float(os.environ.get("ANUNCIO_MAX_QUANTIDADE_KG", str(DEFAULT_MAX_QUANTIDADE_KG)))
    except (ValueError, TypeError):
        return DEFAULT_MAX_QUANTIDADE_KG


def obter_margem_preco_percentagem() -> float:
    """Retorna a margem percentual permitida em relação ao intervalo de referência (MARGEM_PRECO)."""
    raw = os.environ.get("MARGEM_PRECO") or os.environ.get("ANUNCIO_MARGEM_PRECO_PERCENTAGEM")
    if raw:
        try:
            return float(raw)
        except (ValueError, TypeError):
            pass
    return DEFAULT_MARGEM_PRECO_PERCENTAGEM


def normalizar_cultura(cultura: str) -> Optional[str]:
    """Retorna o nome canónico da cultura se conhecida, ou None se desconhecida."""
    c = (cultura or "").strip().lower()
    if not c:
        return None
    if c in CROP_CANONICAL_MAP:
        return CROP_CANONICAL_MAP[c]
    db_price = get_crop_price_from_db(c)
    if db_price is not None:
        return str(db_price["cultura"]).strip().lower()
    return None


def validar_cultura(cultura: str) -> Tuple[bool, str]:
    """Verifica se a cultura pertence ao catálogo de culturas reconhecidas e possui cotação cadastrada."""
    canon = normalizar_cultura(cultura)
    if not canon:
        return (
            False,
            f"Cultura '{cultura}' desconhecida.",
        )
    db_price = get_crop_price_from_db(canon)
    if db_price is None:
        return (
            False,
            f"Cultura '{cultura}' não possui preço de referência cadastrado na tabela oficial. Ação recusada.",
        )
    return True, canon


def validar_quantidade(quantidade_kg: float) -> Tuple[bool, str]:
    """Verifica se a quantidade em kg é estritamente positiva e não excede o limite máximo."""
    try:
        qty = float(quantidade_kg)
    except (ValueError, TypeError):
        return False, "Quantidade inválida. Deve ser um número positivo em kg."

    if qty <= 0:
        return False, f"Quantidade inválida ({qty} kg). A quantidade deve ser estritamente maior que zero."

    max_qty = obter_max_quantidade_kg()
    if qty > max_qty:
        return (
            False,
            f"Quantidade excessiva ({qty} kg). O limite máximo permitido por anúncio é de {max_qty:.0f} kg.",
        )
    return True, ""


def validar_preco(cultura: str, preco_kz_kg: float) -> Tuple[bool, str]:
    """Verifica se o preço em Kz/kg é positivo e está dentro da margem permitida do intervalo de referência."""
    try:
        preco = float(preco_kz_kg)
    except (ValueError, TypeError):
        return False, "Preço inválido. Deve ser um número positivo em Kz/kg."

    if preco <= 0:
        return False, f"Preço inválido ({preco} Kz/kg). O preço deve ser estritamente maior que zero."

    canon = normalizar_cultura(cultura)
    if not canon:
        return False, f"Cultura '{cultura}' desconhecida para validação de preço."

    db_row = get_crop_price_from_db(canon)
    if db_row is None:
        return (
            False,
            f"Cultura '{cultura}' não possui preço de referência cadastrado na tabela oficial. Ação recusada.",
        )

    p_min = float(db_row.get("preco_min") or db_row.get("preco_kz_kg") or 0.0)
    p_max = float(db_row.get("preco_max") or db_row.get("preco_kz_kg") or 0.0)
    if p_min <= 0 or p_max <= 0:
        return False, f"Preço de referência inválido na base de dados para a cultura '{cultura}'."

    if p_min > p_max:
        p_min, p_max = p_max, p_min

    margem = obter_margem_preco_percentagem()
    limite_inferior = p_min * (1.0 - margem / 100.0)
    limite_superior = p_max * (1.0 + margem / 100.0)

    if preco < limite_inferior or preco > limite_superior:
        return (
            False,
            f"Preço proposto ({preco:.0f} Kz/kg) fora do intervalo permitido ({limite_inferior:.0f} a {limite_superior:.0f} Kz/kg) "
            f"em relação ao intervalo de referência de {canon} ({p_min:.0f} a {p_max:.0f} Kz/kg com margem extra de {margem:.0f}%).",
        )
    return True, ""


def validar_anuncio(
    cultura: str,
    quantidade_kg: float,
    preco_kz_kg: float,
    historico_texto: str = "",
) -> Tuple[bool, str]:
    """Valida conjuntamente cultura, quantidade e preço para a criação de anúncio."""
    ok_cult, msg_cult = validar_cultura(cultura)
    if not ok_cult:
        return False, msg_cult

    ok_qtd, msg_qtd = validar_quantidade(quantidade_kg)
    if not ok_qtd:
        return False, msg_qtd

    ok_prc, msg_prc = validar_preco(cultura, preco_kz_kg)
    if not ok_prc:
        return False, msg_prc

    # Guarda determinística adicional: se o agricultor propôs um preço no texto da volta
    # (ex: 'a 10 Kz/kg'), garante que esse preço proposto também cumpre a margem de referência,
    # impedindo que o modelo ignore o preço do agricultor e substitua pela cotação de mercado.
    if historico_texto:
        match_preco = re.search(
            r"\b(?:a|ao preço de|au prix de|at)\s*(\d+(?:[.,]\d+)?)\s*(?:kz|kwanzas?)(?:/kg|\s+por\s+kg)?\b",
            historico_texto,
            re.IGNORECASE,
        )
        if not match_preco:
            match_preco = re.search(
                r"\b(\d+(?:[.,]\d+)?)\s*(?:kz|kwanzas?)/kg\b",
                historico_texto,
                re.IGNORECASE,
            )
        if match_preco:
            try:
                user_price = float(match_preco.group(1).replace(",", "."))
                if user_price > 0:
                    ok_uprc, msg_uprc = validar_preco(cultura, user_price)
                    if not ok_uprc:
                        return False, msg_uprc
            except (ValueError, TypeError):
                pass

    return True, ""


def validar_rega(parcela: str, hora: str) -> Tuple[bool, str]:
    """Verifica se o nome da parcela não está vazio e se a hora é válida (formato HH:MM 00:00-23:59)."""
    p = (parcela or "").strip()
    if not p:
        return False, "Nome da parcela não pode estar vazio."
    if len(p) > 100:
        return False, "Nome da parcela demasiado longo (máximo 100 caracteres)."

    h = (hora or "").strip()
    if not h:
        return False, "Hora da rega não pode estar vazia (utilize o formato HH:MM, ex: '06:30')."

    match = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", h)
    if not match:
        return (
            False,
            f"Formato de hora inválido ('{hora}'). Utilize o formato 24 horas HH:MM (ex: '06:00', '18:30').",
        )
    return True, ""


def validar_prerequisitos_foto(
    analise_foto: Optional[Dict[str, Any]],
    historico_texto: str,
) -> Tuple[bool, str]:
    """Garante que a estimativa a partir de foto só ocorre com contagem > 0 e peso médio confirmado."""
    texto_lower = (historico_texto or "").lower()

    contagem: Optional[int] = None
    if analise_foto:
        contagem = int(analise_foto.get("contagem", 0))
    elif any(term in texto_lower for term in ("0 tomate", "0 fruto", "0 unidade", "contagem 0", "0 detec")):
        contagem = 0

    if contagem is not None and contagem <= 0:
        return (
            False,
            "A análise da foto não detetou nenhuma unidade visível (contagem = 0). Peça ao agricultor uma nova foto mais nítida e aproximada do lote, ou pergunte a quantidade diretamente.",
        )

    if contagem is not None and contagem > 0:
        # Verifica se no histórico o agricultor mencionou o peso médio por fruto/unidade (ex: '150g', '0.15kg', 'peso médio')
        indicadores_peso = (
            "peso médio",
            "peso medio",
            "pèse",
            "pese",
            "cada um",
            "cada uma",
            "chacun",
            "chacune",
            "per unit",
            "each",
            "gramas",
            "grammes",
            "0.",
            "g cada",
        )
        tem_peso_medio = any(term in texto_lower for term in indicadores_peso)

        if not tem_peso_medio:
            return (
                False,
                f"A foto detetou {contagem} unidades, mas falta o peso médio estimado por unidade para calcular a quantidade total em kg com rigor. Peça ao agricultor o peso médio aproximado por unidade (ex: 120 g por fruto) antes de propor o anúncio.",
            )

    return True, ""

    return True, ""


def extrair_numeros_relevantes(texto: str) -> Set[float]:
    """Extrai números inteiros e decimais de quantidades, valores monetários ou contagens no texto."""
    if not texto:
        return set()
    padrao = r"(?<![\w\.\,\-])(\d+(?:[\.\,]\d+)?)(?![\w\.\,\-])"
    encontrados: Set[float] = set()
    for match in re.finditer(padrao, texto):
        val_str = match.group(1).replace(",", ".")
        try:
            val = float(val_str)
            # Ignora anos como 2024, 2025, 2026 e horas como 18.30
            if val in (2024.0, 2025.0, 2026.0):
                continue
            encontrados.add(val)
        except ValueError:
            pass
    return encontrados


def extrair_numeros_autorizados(
    executed_actions: List[Dict[str, Any]],
    user_inputs: List[str],
) -> Set[float]:
    """Compila o conjunto de números legítimos provenientes das ferramentas, dos inputs e dos seus produtos."""
    autorizados: Set[float] = set()

    for inp in user_inputs:
        autorizados.update(extrair_numeros_relevantes(inp))

    quantidades: List[float] = []
    precos: List[float] = []

    for action in executed_actions:
        res = action.get("resultado")
        args = action.get("argumentos", {})

        if isinstance(args, dict):
            if "quantidade_kg" in args:
                try:
                    q = float(args["quantidade_kg"])
                    quantidades.append(q)
                    autorizados.add(q)
                except (ValueError, TypeError):
                    pass
            if "preco_kz_kg" in args:
                try:
                    p = float(args["preco_kz_kg"])
                    precos.append(p)
                    autorizados.add(p)
                except (ValueError, TypeError):
                    pass

        if isinstance(res, dict):
            if "preco_min" in res:
                try:
                    p = float(res["preco_min"])
                    precos.append(p)
                    autorizados.add(p)
                except (ValueError, TypeError):
                    pass
            if "preco_max" in res:
                try:
                    p = float(res["preco_max"])
                    precos.append(p)
                    autorizados.add(p)
                except (ValueError, TypeError):
                    pass
            if "preco_kz_kg" in res:
                try:
                    p = float(res["preco_kz_kg"])
                    precos.append(p)
                    autorizados.add(p)
                except (ValueError, TypeError):
                    pass
            if "contagem" in res:
                try:
                    c = float(res["contagem"])
                    autorizados.add(c)
                except (ValueError, TypeError):
                    pass
            if "cobertura_percentagem" in res:
                try:
                    cob = float(res["cobertura_percentagem"])
                    autorizados.add(cob)
                except (ValueError, TypeError):
                    pass
            if "valor_total_kz" in res:
                try:
                    tot = float(res["valor_total_kz"])
                    autorizados.add(tot)
                except (ValueError, TypeError):
                    pass

    # Adiciona produtos cruzados legítimos (quantidade * preco)
    for q in quantidades:
        for p in precos:
            autorizados.add(round(q * p, 2))
            autorizados.add(round(q * p, 0))

    return autorizados


def verificar_numeros_resposta(
    texto: str,
    numeros_autorizados: Set[float],
) -> Tuple[bool, List[float]]:
    """Verifica se todos os números no texto final têm suporte no conjunto de números autorizados."""
    numeros_texto = extrair_numeros_relevantes(texto)
    numeros_inventados: List[float] = []

    for num in numeros_texto:
        # Tolerância de arredondamento
        suportado = any(abs(num - aut) < 0.05 or abs(num - aut) / max(aut, 1.0) < 0.01 for aut in numeros_autorizados)
        if not suportado:
            numeros_inventados.append(num)

    if numeros_inventados:
        return False, numeros_inventados
    return True, []


def gerar_resposta_segura_sem_alucinacoes(texto: str, lang: str = "pt") -> str:
    """Devolve uma resposta segura e determinística quando o modelo persiste em alucinar valores numéricos."""
    if lang == "fr":
        return (
            "Pour garantir l'exactitude de vos données agricoles, je ne peux afficher que "
            "les prix officiels et les quantités confirmées. Veuillez préciser votre demande "
            "avec la culture exacte et la quantité souhaitée."
        )
    if lang == "en":
        return (
            "To ensure the accuracy of your agricultural records, I can only display "
            "official reference prices and confirmed quantities. Please specify the crop "
            "and desired quantity so I can assist you."
        )
    return (
        "Para garantir o rigor das suas informações agrícolas, apresento apenas "
        "preços de referência e quantidades confirmadas. Por favor indique a cultura "
        "e a quantidade exacta para que possamos continuar."
    )
