"""Fixtures sintéticas. Não representam o Bike Rio e não usam a base real."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from observador_bikerio.configuracao import Configuracao

T0 = datetime(2026, 5, 10, 15, 0, tzinfo=timezone.utc)


def instante(segundos: int = 0) -> str:
    return (T0 + timedelta(seconds=segundos)).isoformat().replace("+00:00", "Z")


def configuracao_sintetica(tmp_path, **ajustes) -> Configuracao:
    dados = {
        "caminho_arquivo": tmp_path / "config.toml",
        "diretorio_projeto": tmp_path,
        "url_descoberta": "sintetico://gbfs.json",
        "idioma_nome": "pt",
        "intervalo_coleta_segundos": 60,
        "intervalo_cadastro_segundos": 900,
        "timeout_segundos": 5,
        "tentativas_http": 3,
        "espera_inicial_segundos": 0,
        "pasta_base": tmp_path / "data",
        "pasta_logs": tmp_path / "logs",
        "limite_lacuna_segundos": 180,
        "limite_dados_antigos_segundos": 3600,
        "limiar_intervencao_bicicletas": 10,
        "limiar_cobertura_percentual": 90,
        "limite_status_desatualizado_segundos": 600,
        "atualizacao_interface_segundos": 0,
    }
    dados.update(ajustes)
    return Configuracao(**dados)


class ClienteFalso:
    """Entrega documentos em memória. Não abre rede."""

    def __init__(self, documentos: dict):
        self.documentos = documentos
        self.chamadas: list[str] = []

    def obter_json(self, url: str) -> dict:
        self.chamadas.append(url)
        item = self.documentos[url]
        if isinstance(item, list):
            if len(item) > 1:
                return item.pop(0)
            return item[0]
        return item

    def fechar(self) -> None:
        return None


def descoberta() -> dict:
    return {
        "last_updated": instante(),
        "ttl": 30,
        "version": "3.0",
        "data": {
            "feeds": [
                {"name": "system_information", "url": "sintetico://system_information"},
                {"name": "station_information", "url": "sintetico://station_information"},
                {"name": "station_status", "url": "sintetico://station_status"},
            ]
        },
    }


def sistema() -> dict:
    return {
        "last_updated": instante(),
        "ttl": 60,
        "version": "3.0",
        "data": {
            "system_id": "sintetico",
            "timezone": "America/Sao_Paulo",
            "name": [{"language": "pt", "text": "Sistema sintético"}],
        },
    }


def info(estacoes: list[dict], segundos: int = 0) -> dict:
    return {
        "last_updated": instante(segundos),
        "ttl": 30,
        "version": "3.0",
        "data": {"stations": estacoes},
        "sintetico": True,
    }


def status(estacoes: list[dict], segundos: int = 0, ttl: int = 13) -> dict:
    return {
        "last_updated": instante(segundos),
        "ttl": ttl,
        "version": "3.0",
        "data": {"stations": estacoes},
        "sintetico": True,
    }


def cadastral(station_id: str, nome: str, latitude: float, longitude: float, capacidade: int = 10) -> dict:
    return {
        "station_id": station_id,
        "name": [
            {"text": nome, "language": "pt"},
            {"text": "nome que nao deve vencer", "language": "en"},
        ],
        "lat": latitude,
        "lon": longitude,
        "capacity": capacidade,
        "address": "Endereço sintético",
    }


def situacao(
    station_id: str,
    bicicletas: int | None,
    segundos: int,
    *,
    instalada: bool = True,
    alugando: bool = True,
    devolvendo: bool = True,
    omitir_bicicletas: bool = False,
) -> dict:
    item = {
        "station_id": station_id,
        "num_docks_available": 5,
        "num_vehicles_disabled": 0,
        "num_docks_disabled": 0,
        "last_reported": instante(segundos),
        "is_installed": instalada,
        "is_renting": alugando,
        "is_returning": devolvendo,
    }
    if not omitir_bicicletas and bicicletas is not None:
        item["num_vehicles_available"] = bicicletas
    return item
