"""Comandos de coleta, backup, caminhos e interface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from observador_bikerio.configuracao import ConfiguracaoInvalida, carregar_configuracao
from observador_bikerio.tempo import FUSO_EXIBICAO
from observador_bikerio.trava import ColetorJaEmExecucao


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="observador-bikerio",
        description="Coleta a disponibilidade das estações do Bike Rio e exporta o histórico para SIG-T.",
    )
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("--config", type=Path, default=None, help="Caminho do TOML. Padrão: config.toml ou config.exemplo.toml.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("coletar", parents=[comum], help="Consulta a fonte uma vez e grava o banco local.")
    sub.add_parser("coletar-continuo", parents=[comum], help="Mantém a coleta em processo separado da interface.")
    sub.add_parser("backup", parents=[comum], help="Gera uma cópia consistente do SQLite.")
    sub.add_parser("interface", parents=[comum], help="Abre a visualização. Não inicia o coletor.")
    sub.add_parser("caminhos", parents=[comum], help="Mostra os caminhos absolutos de armazenamento.")
    args = parser.parse_args(argv)
    try:
        configuracao = carregar_configuracao(args.config)
    except ConfiguracaoInvalida as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.comando == "caminhos":
        _imprimir_caminhos(configuracao)
        return 0
    if args.comando == "coletar":
        return _coletar(configuracao)
    if args.comando == "coletar-continuo":
        return _continuo(configuracao)
    if args.comando == "backup":
        return _backup(configuracao)
    if args.comando == "interface":
        return _interface(configuracao)
    return 1


def _coletar(configuracao) -> int:
    from observador_bikerio.coletor import coletar_uma_vez

    try:
        resultado = coletar_uma_vez(configuracao)
    except ColetorJaEmExecucao as exc:
        print(exc, file=sys.stderr)
        return 2
    print(resultado.mensagem)
    print(f"Resultado: {resultado.resultado}")
    _imprimir_caminhos(configuracao)
    return 0 if resultado.sucesso else 1


def _continuo(configuracao) -> int:
    from observador_bikerio.coletor import coletar_continuo

    print(
        "A coleta contínua depende deste processo. "
        "Desligar ou suspender o computador interrompe a coleta."
    )
    print("Fuso de exibição: America/Sao_Paulo. Armazenamento em UTC.")
    _imprimir_caminhos(configuracao)
    try:
        coletar_continuo(configuracao)
    except ColetorJaEmExecucao as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _backup(configuracao) -> int:
    from observador_bikerio.backup import gerar_backup

    try:
        destino = gerar_backup(configuracao)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Backup: {destino}")
    return 0


def _interface(configuracao) -> int:
    script = configuracao.diretorio_projeto / "observador_bikerio" / "interface.py"
    if not script.is_file():
        print(f"Interface não encontrada: {script}", file=sys.stderr)
        return 1
    completo = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(script)],
        cwd=configuracao.diretorio_projeto,
        check=False,
    )
    return int(completo.returncode)


def _imprimir_caminhos(configuracao) -> None:
    print(f"Fuso de agregação: {FUSO_EXIBICAO.key}")
    for nome, caminho in configuracao.caminhos_absolutos().items():
        print(f"{nome}: {caminho}")


if __name__ == "__main__":
    raise SystemExit(main())
