"""Cópia consistente do SQLite pela API de backup, utilizável durante a coleta."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from observador_bikerio.configuracao import Configuracao
from observador_bikerio.tempo import agora_utc


def gerar_backup(configuracao: Configuracao, destino: Path | None = None) -> Path:
    origem_caminho = configuracao.caminho_banco
    if not origem_caminho.is_file():
        raise FileNotFoundError(
            f"Ainda não existe base para copiar: {origem_caminho.resolve()}"
        )
    pasta = configuracao.pasta_backups
    pasta.mkdir(parents=True, exist_ok=True)
    if destino is None:
        carimbo = agora_utc().strftime("%Y%m%dT%H%M%SZ")
        destino = pasta / f"bikerio-{carimbo}.sqlite"
    origem = sqlite3.connect(origem_caminho)
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()
    return destino.resolve()
