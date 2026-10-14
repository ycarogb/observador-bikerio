"""Respostas originais comprimidas, separadas por dia UTC, sem apagar histórico."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path


def salvar_bruto(pasta_base: Path, nome_feed: str, coletado_em: datetime, payload: dict) -> str:
    instante = coletado_em.astimezone(timezone.utc)
    dia = instante.strftime("%Y-%m-%d")
    pasta = pasta_base / "raw" / dia
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = instante.strftime("%Y%m%dT%H%M%S%fZ")
    relativo = Path("raw") / dia / f"{nome_feed}_{carimbo}.json.gz"
    destino = pasta_base / relativo
    with gzip.open(destino, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return relativo.as_posix()
