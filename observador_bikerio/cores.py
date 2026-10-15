"""Escala de cores do mapa. Os valores originais não são alterados."""

from __future__ import annotations

import math

from observador_bikerio.textos import (
    BORDA_DESATUALIZADO,
    BORDA_INSUFICIENTE,
    BORDA_PADRAO,
    BORDA_SEM_DADOS,
    COR_COBERTURA_INSUFICIENTE,
    COR_SEM_DADOS,
    COR_STATUS_DESATUALIZADO,
    INDICADORES,
    PALETAS,
)

CATEGORIAS_NA_ESCALA = frozenset({"classificada", "zero_movimentacao"})
CATEGORIAS_SEM_DADOS = frozenset(
    {"sem_intervalos_validos", "sem_observacao_de_estoque", "sem_coordenadas"}
)


def aplicar_visual(
    linhas: list[dict],
    indicador: str,
    *,
    escala: str,
    limiar_cobertura: float,
    limites_fixos: tuple[float, float] | None = None,
    pintar_baixa_cobertura: bool = True,
) -> dict:
    from observador_bikerio.indicadores import classificar

    if indicador not in INDICADORES:
        raise ValueError(f"Indicador desconhecido: {indicador}")
    definicao = INDICADORES[indicador]
    paleta = PALETAS[definicao["paleta"]]
    for linha in linhas:
        linha["categoria"] = classificar(linha, indicador, limiar_cobertura)
        linha["valor_indicador"] = _valor(linha, indicador)
        linha["rotulo_indicador"] = definicao["rotulo"]
        linha["unidade_indicador"] = definicao["unidade"]

    na_escala = frozenset(CATEGORIAS_NA_ESCALA)
    if not pintar_baixa_cobertura:
        na_escala = CATEGORIAS_NA_ESCALA | {"cobertura_insuficiente"}
    valores = [
        linha["valor_indicador"]
        for linha in linhas
        if linha["categoria"] in na_escala and linha["valor_indicador"] is not None
    ]
    info = _info_escala(valores, escala, limites_fixos, definicao)
    info["pintar_baixa_cobertura"] = pintar_baixa_cobertura
    for linha in linhas:
        cor, borda = _cor_linha(linha, paleta, info)
        linha["cor"] = cor
        linha["borda"] = borda
    info["na_escala"] = sum(1 for linha in linhas if linha["categoria"] in na_escala)
    info["sem_classificacao"] = sum(1 for linha in linhas if linha["categoria"] not in na_escala)
    info["indicador"] = indicador
    return info


def posicao(valor: float, vmin: float, vmax: float, escala: str) -> float:
    transformado = _transformar(valor, escala)
    inicio = _transformar(vmin, escala)
    fim = _transformar(vmax, escala)
    if transformado is None or inicio is None or fim is None or fim == inicio:
        return 0.0 if valor == 0 else 0.5
    return (transformado - inicio) / (fim - inicio)


def interpolar(paleta: tuple[str, ...], t: float) -> str:
    if not paleta:
        return COR_SEM_DADOS
    limite = min(1.0, max(0.0, t))
    if len(paleta) == 1:
        return paleta[0]
    pos = limite * (len(paleta) - 1)
    indice = int(pos)
    if indice >= len(paleta) - 1:
        return paleta[-1]
    frac = pos - indice
    return _misturar(paleta[indice], paleta[indice + 1], frac)


def texto_metodo(info: dict) -> str:
    if info.get("sem_valores"):
        return "Sem valores classificáveis neste período."
    escala = "log1p" if info.get("escala") == "log1p" else "linear"
    if info.get("limites_fixos"):
        base = "limites fixos"
    elif info.get("valores_iguais"):
        base = "valor único no período"
    else:
        base = "mínimo e máximo do período"
    if escala == "log1p":
        return f"Escala contínua log1p ({base}). Os valores originais são preservados."
    return f"Escala contínua linear ({base})."


def _cor_linha(linha: dict, paleta: tuple[str, ...], info: dict) -> tuple[str, str]:
    categoria = linha["categoria"]
    if categoria in CATEGORIAS_SEM_DADOS:
        return COR_SEM_DADOS, BORDA_SEM_DADOS
    if categoria == "cobertura_insuficiente" and info.get("pintar_baixa_cobertura", True):
        return COR_COBERTURA_INSUFICIENTE, BORDA_INSUFICIENTE
    if categoria == "status_desatualizado":
        return COR_STATUS_DESATUALIZADO, BORDA_DESATUALIZADO
    valor = linha.get("valor_indicador")
    if valor is None or info.get("sem_valores"):
        return COR_SEM_DADOS, BORDA_SEM_DADOS
    t = posicao(float(valor), info["minimo_escala"], info["maximo_escala"], info["escala"])
    if info.get("valores_iguais") and not info.get("limites_fixos"):
        t = 0.0 if valor == 0 else 0.5
    return interpolar(paleta, t), BORDA_PADRAO


def _info_escala(valores: list[float], escala: str, limites_fixos, definicao: dict) -> dict:
    info = {
        "rotulo": definicao["rotulo"],
        "unidade": definicao["unidade"],
        "escala": escala,
        "limites_fixos": limites_fixos is not None,
        "valores_iguais": False,
        "sem_valores": False,
        "minimo": None,
        "maximo": None,
        "minimo_escala": None,
        "maximo_escala": None,
    }
    if not valores:
        info["sem_valores"] = True
        return info
    info["minimo"] = min(valores)
    info["maximo"] = max(valores)
    if limites_fixos is not None:
        info["minimo_escala"], info["maximo_escala"] = limites_fixos
    else:
        info["minimo_escala"] = info["minimo"]
        info["maximo_escala"] = info["maximo"]
    if info["minimo_escala"] == info["maximo_escala"]:
        info["valores_iguais"] = True
    return info


def _valor(linha: dict, indicador: str) -> float | None:
    valor = linha.get(indicador)
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    return float(valor)


def _transformar(valor: float, escala: str) -> float | None:
    if escala == "log1p":
        if valor < 0:
            return None
        return math.log1p(valor)
    return valor


def _misturar(origem: str, destino: str, frac: float) -> str:
    r1, g1, b1 = _rgb(origem)
    r2, g2, b2 = _rgb(destino)
    r = round(r1 + (r2 - r1) * frac)
    g = round(g1 + (g2 - g1) * frac)
    b = round(b1 + (b2 - b1) * frac)
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb(cor: str) -> tuple[int, int, int]:
    texto = cor.removeprefix("#")
    return int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16)
