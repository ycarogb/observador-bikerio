"""Log em arquivo com rotação. Não registra payload nem segredo."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_NOME = "observador_bikerio"


def configurar_log(pasta: Path) -> logging.Logger:
    pasta.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_NOME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    arquivo = RotatingFileHandler(
        pasta / "observador.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    arquivo.setFormatter(formato)
    console = logging.StreamHandler()
    console.setFormatter(formato)
    logger.addHandler(arquivo)
    logger.addHandler(console)
    logger.propagate = False
    return logger
