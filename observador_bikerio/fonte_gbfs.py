"""Cliente do documento de descoberta GBFS e dos feeds apontados por ele."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx

from observador_bikerio.configuracao import Configuracao
from observador_bikerio.tempo import analisar_instante


class ErroFonte(Exception):
    def __init__(self, mensagem: str, http_status: int | None = None):
        super().__init__(mensagem)
        self.http_status = http_status


@dataclass(frozen=True)
class EnvelopeFeed:
    last_updated: object
    ttl: int | None
    version: str | None
    data: dict


class ClienteGbfs:
    def __init__(
        self,
        configuracao: Configuracao,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] | None = None,
        ao_aguardar: Callable[[], None] | None = None,
    ):
        self._configuracao = configuracao
        self._dormir = dormir or time.sleep
        self._ao_aguardar = ao_aguardar
        self._cliente = httpx.Client(
            timeout=configuracao.timeout_segundos,
            transport=transporte,
            follow_redirects=True,
            headers={
                "User-Agent": "observador-bikerio/0.1 (coleta local de disponibilidade GBFS)",
                "Accept": "application/json",
            },
        )

    def fechar(self) -> None:
        self._cliente.close()

    def obter_json(self, url: str) -> dict:
        espera = self._configuracao.espera_inicial_segundos
        ultimo: ErroFonte | None = None
        for tentativa in range(1, self._configuracao.tentativas_http + 1):
            try:
                resposta = self._cliente.get(url)
            except httpx.TimeoutException:
                ultimo = ErroFonte(f"Tempo esgotado ao consultar {url}.")
                if tentativa == self._configuracao.tentativas_http:
                    break
                self._aguardar(espera)
                espera *= 2
                continue
            except httpx.HTTPError as exc:
                ultimo = ErroFonte(f"Falha de rede ao consultar a fonte: {exc.__class__.__name__}.")
                if tentativa == self._configuracao.tentativas_http:
                    break
                self._aguardar(espera)
                espera *= 2
                continue
            if resposta.status_code == 429 or resposta.status_code >= 500:
                ultimo = ErroFonte(
                    f"A fonte respondeu HTTP {resposta.status_code}.",
                    http_status=resposta.status_code,
                )
                if tentativa == self._configuracao.tentativas_http:
                    break
                self._aguardar(_atraso(resposta, espera))
                espera *= 2
                continue
            if resposta.status_code >= 400:
                raise ErroFonte(
                    f"A fonte recusou a consulta com HTTP {resposta.status_code}.",
                    http_status=resposta.status_code,
                )
            try:
                documento = resposta.json()
            except ValueError as exc:
                raise ErroFonte("A fonte não retornou JSON.") from exc
            if not isinstance(documento, dict):
                raise ErroFonte("A resposta JSON da fonte não é um objeto.")
            return documento
        raise ultimo or ErroFonte(f"Não foi possível consultar {url}.")

    def _aguardar(self, segundos: float) -> None:
        if self._ao_aguardar is not None:
            self._ao_aguardar()
        if segundos > 0:
            self._dormir(segundos)


def ler_envelope(documento: dict) -> EnvelopeFeed:
    data = documento.get("data")
    ttl = documento.get("ttl")
    versao = documento.get("version")
    return EnvelopeFeed(
        last_updated=analisar_instante(documento.get("last_updated")),
        ttl=ttl if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl >= 0 else None,
        version=versao if isinstance(versao, str) else None,
        data=data if isinstance(data, dict) else {},
    )


def descobrir_feeds(documento: dict) -> dict[str, str]:
    feeds = ler_envelope(documento).data.get("feeds")
    if not isinstance(feeds, list):
        raise ErroFonte("O documento de descoberta GBFS não contém data.feeds.")
    mapa: dict[str, str] = {}
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        nome = feed.get("name")
        url = feed.get("url")
        if isinstance(nome, str) and isinstance(url, str) and nome and url:
            mapa[nome] = url
    obrigatorios = ("station_information", "station_status")
    faltando = [nome for nome in obrigatorios if nome not in mapa]
    if faltando:
        raise ErroFonte(
            "Feeds ausentes no documento de descoberta: " + ", ".join(faltando) + "."
        )
    return mapa


def sistema_do_feed(documento: dict, idioma: str) -> tuple[str | None, str | None, str | None]:
    from observador_bikerio.normalizador import texto_localizado

    data = ler_envelope(documento).data
    system_id = data.get("system_id")
    fuso = data.get("timezone")
    return (
        system_id if isinstance(system_id, str) and system_id.strip() else None,
        texto_localizado(data.get("name"), idioma),
        fuso if isinstance(fuso, str) and fuso.strip() else None,
    )


def fonte_sintetica(url: str, system_id: str | None) -> bool:
    identificador = (system_id or "").lower()
    endereco = url.lower()
    return identificador == "sintetico" or endereco.startswith("sintetico:") or "sintetico" in endereco


def _atraso(resposta: httpx.Response, espera: float) -> float:
    cabecalho = resposta.headers.get("Retry-After")
    if cabecalho and cabecalho.isdigit():
        return max(float(cabecalho), 0)
    return espera
