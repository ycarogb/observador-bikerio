"""Leitura da configuração local e caminhos absolutos de armazenamento."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfiguracaoInvalida(Exception):
    pass


@dataclass(frozen=True)
class Configuracao:
    caminho_arquivo: Path
    diretorio_projeto: Path
    url_indice_gbfs: str
    idioma_nome: str
    intervalo_coleta_segundos: float
    intervalo_cadastro_segundos: float
    timeout_segundos: float
    tentativas_http: int
    espera_inicial_segundos: float
    pasta_base: Path
    pasta_logs: Path
    limite_lacuna_segundos: float
    limite_dados_antigos_segundos: float
    limiar_intervencao_bicicletas: int
    limiar_cobertura_percentual: float
    limite_status_desatualizado_segundos: float
    atualizacao_interface_segundos: float

    @property
    def caminho_banco(self) -> Path:
        return self.pasta_base / "bikerio.sqlite"

    @property
    def pasta_brutos(self) -> Path:
        return self.pasta_base / "raw"

    @property
    def pasta_exportacoes(self) -> Path:
        return self.pasta_base / "exports"

    @property
    def pasta_backups(self) -> Path:
        return self.pasta_base / "backups"

    @property
    def caminho_trava(self) -> Path:
        return self.pasta_base / "coletor.lock"

    def caminhos_absolutos(self) -> dict[str, str]:
        return {
            "configuracao": str(self.caminho_arquivo.resolve()),
            "banco": str(self.caminho_banco.resolve()),
            "brutos": str(self.pasta_brutos.resolve()),
            "exportacoes": str(self.pasta_exportacoes.resolve()),
            "backups": str(self.pasta_backups.resolve()),
            "logs": str(self.pasta_logs.resolve()),
            "trava": str(self.caminho_trava.resolve()),
        }


def carregar_configuracao(caminho: Path | None = None) -> Configuracao:
    arquivo = _resolver_arquivo(caminho)
    if not arquivo.is_file():
        raise ConfiguracaoInvalida(
            f"Arquivo de configuração não encontrado: {arquivo.resolve()}"
        )
    with arquivo.open("rb") as conteudo:
        bruto = tomllib.load(conteudo)
    try:
        fonte = bruto["fonte"]
        armazenamento = bruto["armazenamento"]
        qualidade = bruto["qualidade"]
        interface = bruto["interface"]
    except KeyError as exc:
        raise ConfiguracaoInvalida(f"Seção ausente na configuração: {exc}") from exc

    diretorio = arquivo.parent.resolve()
    configuracao = Configuracao(
        caminho_arquivo=arquivo.resolve(),
        diretorio_projeto=diretorio,
        url_indice_gbfs=_texto_url_indice(fonte),
        idioma_nome=_texto(fonte, "idioma_nome") or "pt",
        intervalo_coleta_segundos=_numero(fonte, "intervalo_coleta_segundos"),
        intervalo_cadastro_segundos=_numero(fonte, "intervalo_cadastro_segundos"),
        timeout_segundos=_numero(fonte, "timeout_segundos"),
        tentativas_http=int(_numero(fonte, "tentativas_http")),
        espera_inicial_segundos=_numero(fonte, "espera_inicial_segundos"),
        pasta_base=_pasta(diretorio, armazenamento, "pasta_base"),
        pasta_logs=_pasta(diretorio, armazenamento, "pasta_logs"),
        limite_lacuna_segundos=_numero(qualidade, "limite_lacuna_segundos"),
        limite_dados_antigos_segundos=_numero(qualidade, "limite_dados_antigos_segundos"),
        limiar_intervencao_bicicletas=int(_numero(qualidade, "limiar_intervencao_bicicletas")),
        limiar_cobertura_percentual=_numero(qualidade, "limiar_cobertura_percentual"),
        limite_status_desatualizado_segundos=_numero(
            qualidade, "limite_status_desatualizado_segundos"
        ),
        atualizacao_interface_segundos=_numero(interface, "atualizacao_segundos", minimo=0),
    )
    _validar(configuracao)
    return configuracao


def _resolver_arquivo(caminho: Path | None) -> Path:
    if caminho is not None:
        return caminho
    ambiente = os.environ.get("OBSERVADOR_CONFIG")
    if ambiente:
        return Path(ambiente)
    atual = Path.cwd()
    local = atual / "config.toml"
    if local.is_file():
        return local
    return atual / "config.exemplo.toml"


def _texto_url_indice(fonte: dict) -> str:
    if "url_indice_gbfs" in fonte:
        return _texto(fonte, "url_indice_gbfs")
    if "url_descoberta" in fonte:
        return _texto(fonte, "url_descoberta")
    raise ConfiguracaoInvalida("Campo de texto inválido: url_indice_gbfs")


def _texto(secao: dict, campo: str) -> str:
    valor = secao.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ConfiguracaoInvalida(f"Campo de texto inválido: {campo}")
    return valor.strip()


def _numero(secao: dict, campo: str, minimo: float = 0) -> float:
    valor = secao.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ConfiguracaoInvalida(f"Campo numérico inválido: {campo}")
    if valor < minimo:
        raise ConfiguracaoInvalida(f"Campo {campo} deve ser >= {minimo}")
    return float(valor)


def _pasta(diretorio: Path, secao: dict, campo: str) -> Path:
    valor = secao.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ConfiguracaoInvalida(f"Pasta inválida: {campo}")
    caminho = Path(valor.strip())
    if not caminho.is_absolute():
        caminho = diretorio / caminho
    return caminho.resolve()


def _validar(configuracao: Configuracao) -> None:
    if configuracao.intervalo_coleta_segundos <= 0:
        raise ConfiguracaoInvalida("O intervalo de coleta deve ser positivo.")
    if configuracao.timeout_segundos <= 0:
        raise ConfiguracaoInvalida("O timeout deve ser positivo.")
    if configuracao.tentativas_http < 1:
        raise ConfiguracaoInvalida("É necessária ao menos uma tentativa HTTP.")
    if configuracao.limite_lacuna_segundos <= 0:
        raise ConfiguracaoInvalida("O limite de lacuna deve ser positivo.")
    if configuracao.limiar_intervencao_bicicletas < 1:
        raise ConfiguracaoInvalida("O limiar de intervenção deve ser pelo menos 1.")
    if not 0 <= configuracao.limiar_cobertura_percentual <= 100:
        raise ConfiguracaoInvalida("A cobertura mínima deve ficar entre 0 e 100.")
    if not configuracao.url_indice_gbfs:
        raise ConfiguracaoInvalida("A URL do índice GBFS é obrigatória.")
