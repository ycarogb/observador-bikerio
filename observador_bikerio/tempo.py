"""Horários em UTC na base e em America/Sao_Paulo na exibição."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FUSO_EXIBICAO = ZoneInfo("America/Sao_Paulo")


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def analisar_instante(valor: object) -> datetime | None:
    """Converte um instante ISO-8601 com fuso. Ausência permanece nula."""
    if valor is None or valor == "":
        return None
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not texto:
        return None
    if texto.endswith("Z"):
        texto = f"{texto[:-1]}+00:00"
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if instante.tzinfo is None:
        return None
    instante = instante.astimezone(timezone.utc)
    microssegundos = (instante.microsecond // 1000) * 1000
    return instante.replace(microsecond=microssegundos)


def formatar_utc(instante: datetime) -> str:
    return instante.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def formatar_local(instante: datetime) -> str:
    return instante.astimezone(FUSO_EXIBICAO).isoformat(timespec="seconds")


def para_exibicao(instante: datetime) -> datetime:
    return instante.astimezone(FUSO_EXIBICAO)


def para_grafico(valor: object) -> datetime | None:
    """Relógio de São Paulo, sem fuso, para o gráfico não adiantar 3 horas."""
    instante = analisar_instante(valor)
    if instante is None:
        return None
    return para_exibicao(instante).replace(tzinfo=None)


def analisar_armazenado(valor: object) -> datetime | None:
    return analisar_instante(valor)
