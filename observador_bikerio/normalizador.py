"""Normalização dos feeds GBFS já descobertos. Campo ausente permanece nulo."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from observador_bikerio.tempo import analisar_instante


@dataclass(frozen=True)
class EstacaoCadastral:
    station_id: str
    nome: str | None
    latitude: float | None
    longitude: float | None
    capacidade: int | None
    external_id: str | None
    endereco: str | None


@dataclass(frozen=True)
class DadosEstacao:
    station_id: str
    last_reported: object
    bicicletas_disponiveis: int | None
    vagas_disponiveis: int | None
    bicicletas_desabilitadas: int | None
    vagas_desabilitadas: int | None
    instalada: bool | None
    alugando: bool | None
    devolvendo: bool | None
    situacao_operacional: str | None
    disponibilidade_por_tipo_json: str | None
    flags: tuple[str, ...]


def texto_localizado(valor: object, idioma: str = "pt") -> str | None:
    if isinstance(valor, str):
        texto = valor.strip()
        return texto or None
    if not isinstance(valor, list):
        return None
    preferido = idioma.lower()
    fallback = None
    for item in valor:
        if not isinstance(item, dict):
            continue
        texto = item.get("text")
        if not isinstance(texto, str) or not texto.strip():
            continue
        limpo = texto.strip()
        lingua = str(item.get("language") or "").lower()
        if lingua == preferido or lingua.startswith(f"{preferido}-"):
            return limpo
        if fallback is None:
            fallback = limpo
    return fallback


def normalizar_informacao(estacao: object, idioma: str = "pt") -> EstacaoCadastral | None:
    if not isinstance(estacao, dict):
        return None
    station_id = _identificador(estacao.get("station_id"))
    if station_id is None:
        return None
    return EstacaoCadastral(
        station_id=station_id,
        nome=texto_localizado(estacao.get("name"), idioma),
        latitude=_coordenada(estacao.get("lat"), -90, 90),
        longitude=_coordenada(estacao.get("lon"), -180, 180),
        capacidade=_inteiro(estacao.get("capacity"))[0],
        external_id=_texto(estacao.get("external_id")),
        endereco=_texto(estacao.get("address")),
    )


def normalizar_dados_estacao(estacao: object) -> DadosEstacao | None:
    if not isinstance(estacao, dict):
        return None
    station_id = _identificador(estacao.get("station_id"))
    if station_id is None:
        return None
    flags: list[str] = []
    bicicletas, invalido = _inteiro(estacao.get("num_vehicles_available"))
    if invalido:
        flags.append("valor_invalido")
    vagas, invalido_vagas = _inteiro(estacao.get("num_docks_available"))
    desabilitadas, invalido_bikes = _inteiro(estacao.get("num_vehicles_disabled"))
    vagas_off, invalido_vagas_off = _inteiro(estacao.get("num_docks_disabled"))
    if invalido_vagas or invalido_bikes or invalido_vagas_off:
        flags.append("valor_invalido")
    instalada, invalido_instalada = _booleano(estacao.get("is_installed"))
    alugando, invalido_aluguel = _booleano(estacao.get("is_renting"))
    devolvendo, invalido_devolucao = _booleano(estacao.get("is_returning"))
    if invalido_instalada or invalido_aluguel or invalido_devolucao:
        flags.append("valor_invalido")
    tipos, tipos_invalidos = _tipos(estacao.get("vehicle_types_available"))
    if tipos_invalidos:
        flags.append("valor_invalido")
    return DadosEstacao(
        station_id=station_id,
        last_reported=analisar_instante(estacao.get("last_reported")),
        bicicletas_disponiveis=bicicletas,
        vagas_disponiveis=vagas,
        bicicletas_desabilitadas=desabilitadas,
        vagas_desabilitadas=vagas_off,
        instalada=instalada,
        alugando=alugando,
        devolvendo=devolvendo,
        situacao_operacional=situacao_operacional(instalada, alugando, devolvendo),
        disponibilidade_por_tipo_json=tipos,
        flags=tuple(sorted(set(flags))),
    )


def situacao_operacional(
    instalada: bool | None,
    alugando: bool | None,
    devolvendo: bool | None,
) -> str | None:
    if instalada is None and alugando is None and devolvendo is None:
        return None
    partes: list[str] = []
    if instalada is False:
        partes.append("nao_instalada")
    if alugando is False:
        partes.append("sem_retirada")
    if devolvendo is False:
        partes.append("sem_devolucao")
    if not partes and instalada is True and alugando is True and devolvendo is True:
        return "operando"
    return ",".join(partes) if partes else None


def listar_estacoes(documento: dict, chave: str) -> list:
    data = documento.get("data") if isinstance(documento, dict) else None
    if not isinstance(data, dict):
        return []
    estacoes = data.get(chave)
    if not isinstance(estacoes, list):
        return []
    return estacoes


def _identificador(valor: object) -> str | None:
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    if isinstance(valor, int) and not isinstance(valor, bool):
        return str(valor)
    return None


def _texto(valor: object) -> str | None:
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return None


def _inteiro(valor: object) -> tuple[int | None, bool]:
    if valor is None:
        return None, False
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None, True
    if valor < 0:
        return None, True
    return valor, False


def _booleano(valor: object) -> tuple[bool | None, bool]:
    if valor is None:
        return None, False
    if isinstance(valor, bool):
        return valor, False
    return None, True


def _coordenada(valor: object, minimo: float, maximo: float) -> float | None:
    if valor is None or isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    numero = float(valor)
    if not math.isfinite(numero) or not minimo <= numero <= maximo:
        return None
    return numero


def _tipos(valor: object) -> tuple[str | None, bool]:
    if valor is None:
        return None, False
    if not isinstance(valor, list):
        return None, True
    invalido = False
    limpos = []
    for item in valor:
        if not isinstance(item, dict):
            invalido = True
            continue
        quantidade, item_invalido = _inteiro(item.get("count"))
        if item_invalido:
            invalido = True
        tipo = item.get("vehicle_type_id")
        limpos.append(
            {
                "vehicle_type_id": tipo if isinstance(tipo, str) else None,
                "count": quantidade,
            }
        )
    return json.dumps(limpos, ensure_ascii=False), invalido
