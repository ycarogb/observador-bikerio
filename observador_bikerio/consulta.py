"""Leitura da base local. A interface e a exportação usam estes mesmos números."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from observador_bikerio.banco import (
    conectar,
    contar_estacoes_abertas,
    decodificar_flags,
    estacoes_abertas,
    estacoes_no_periodo,
    estado_coletor,
    eventos_recentes,
    fonte_por_url,
    inicializar,
    intervalos_sobrepostos,
    leitura,
    periodo_armazenado,
    periodo_da_coleta,
    snapshots_no_periodo,
    todo_cadastro,
    todos_intervalos,
    todos_snapshots,
    ultima_tentativa,
    ultimo_sucesso,
    ultimos_estoques_no_periodo,
)
from observador_bikerio.configuracao import Configuracao
from observador_bikerio.cores import aplicar_visual
from observador_bikerio.indicadores import agregar_temporal, construir_janelas, montar_resumo
from observador_bikerio.tempo import (
    FUSO_EXIBICAO,
    agora_utc,
    analisar_instante,
    formatar_local,
    formatar_utc,
    para_grafico,
)

COLUNAS_RESUMO = [
    "station_id",
    "id_cadastro",
    "nome",
    "latitude",
    "longitude",
    "capacidade",
    "inicio_periodo_utc",
    "fim_periodo_utc",
    "inicio_periodo_local",
    "fim_periodo_local",
    "aumentos_observados",
    "reducoes_observadas",
    "movimentacao_observada",
    "intervalos_validos",
    "horas_validas",
    "horas_no_filtro",
    "cobertura_percentual",
    "taxa_por_hora_valida",
    "quantidade_lacunas",
    "flags_qualidade",
    "categoria",
    "bicicletas_disponiveis",
    "ultima_observacao_utc",
    "ultima_observacao_local",
    "valor_indicador",
    "rotulo_indicador",
    "unidade_indicador",
    "cor",
    "borda",
]

COLUNAS_TEMPORAL = [
    "station_id",
    "id_cadastro",
    "nome",
    "latitude",
    "longitude",
    "capacidade",
    "inicio_periodo_utc",
    "fim_periodo_utc",
    "inicio_periodo_local",
    "fim_periodo_local",
    "aumentos_observados",
    "reducoes_observadas",
    "movimentacao_observada",
    "intervalos_validos",
    "horas_validas",
    "cobertura_percentual",
    "taxa_por_hora_valida",
    "flags_qualidade",
    "frequencia",
]

COLUNAS_INTERVALOS = [
    "station_id",
    "estacao_id_inicio",
    "estacao_id_fim",
    "inicio_utc",
    "fim_utc",
    "duracao_segundos",
    "bicicletas_anterior",
    "bicicletas_atual",
    "delta",
    "aumento_observado",
    "reducao_observada",
    "movimentacao_observada",
    "comparavel",
    "motivo",
    "flags_qualidade",
    "incluido_no_resumo",
]

COLUNAS_CADASTRO = [
    "id_cadastro",
    "station_id",
    "nome",
    "latitude",
    "longitude",
    "capacidade",
    "external_id",
    "endereco",
    "valido_desde_utc",
    "valido_ate_utc",
    "ausente_desde_utc",
]

COLUNAS_SNAPSHOTS = [
    "id",
    "station_id",
    "id_cadastro",
    "coletado_em_utc",
    "feed_atualizado_em_utc",
    "last_reported_utc",
    "bicicletas_disponiveis",
    "vagas_disponiveis",
    "bicicletas_desabilitadas",
    "vagas_desabilitadas",
    "instalada",
    "alugando",
    "devolvendo",
    "situacao_operacional",
    "disponibilidade_por_tipo_json",
    "versao_gbfs",
    "arquivo_bruto",
    "flags_qualidade",
]


@dataclass
class FiltroConsulta:
    inicio: datetime
    fim: datetime
    station_ids: list[str] | None = None
    excluir_sinalizados: bool = False
    horas: list[tuple[int, int]] | None = None
    dias_semana: set[int] | None = None
    indicador: str = "movimentacao_observada"
    escala: str = "linear"
    limites_fixos: tuple[float, float] | None = None
    limiar_cobertura: float | None = None
    pintar_baixa_cobertura: bool = False
    escopo: str = "filtros"


@dataclass
class ResultadoConsulta:
    resumo: pd.DataFrame
    intervalos: pd.DataFrame
    horas: pd.DataFrame
    dias: pd.DataFrame
    snapshots: pd.DataFrame
    cadastro: pd.DataFrame
    legenda: dict
    contagens: dict
    filtros: dict
    fonte: dict
    mensagem: str | None = None
    linhas: list[dict] = field(default_factory=list)


def consultar(
    configuracao: Configuracao, filtro: FiltroConsulta, *, com_exportacao: bool = True
) -> ResultadoConsulta:
    """Sem exportação, só o resumo do mapa é calculado: snapshots, séries e tabelas de intervalos ficam vazios."""
    limiar = (
        configuracao.limiar_cobertura_percentual
        if filtro.limiar_cobertura is None
        else filtro.limiar_cobertura
    )
    vazio = _vazio(filtro, {})
    if not configuracao.caminho_banco.is_file():
        vazio.mensagem = "Ainda não há base local. A interface só lê o banco; ela não inicia o coletor."
        return vazio
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        with leitura(conexao):
            fonte = fonte_por_url(conexao, configuracao.url_indice_gbfs)
            if fonte is None:
                vazio.mensagem = "A base existe, mas ainda não há coleta desta fonte."
                return vazio
            inicio_txt = formatar_utc(filtro.inicio)
            fim_txt = formatar_utc(filtro.fim)
            brutos_estacoes = estacoes_no_periodo(
                conexao, fonte["id"], inicio_txt, fim_txt, filtro.station_ids
            )
            brutos_intervalos = intervalos_sobrepostos(
                conexao, fonte["id"], inicio_txt, fim_txt, filtro.station_ids
            )
            brutos_estoques = ultimos_estoques_no_periodo(
                conexao, fonte["id"], inicio_txt, fim_txt, filtro.station_ids
            )
            brutos_snapshots = (
                snapshots_no_periodo(conexao, fonte["id"], inicio_txt, fim_txt, filtro.station_ids)
                if com_exportacao
                else []
            )
            if filtro.escopo == "tudo":
                brutos_cadastro = todo_cadastro(conexao, fonte["id"])
            else:
                brutos_cadastro = brutos_estacoes
    if filtro.fim < filtro.inicio:
        vazio = _vazio(filtro, fonte)
        vazio.mensagem = "O fim do período é anterior ao início."
        return vazio
    janelas = construir_janelas(
        filtro.inicio.astimezone(FUSO_EXIBICAO),
        filtro.fim.astimezone(FUSO_EXIBICAO),
        filtro.horas,
        filtro.dias_semana,
    )
    estacoes = [_estacao(item) for item in brutos_estacoes]
    intervalos = [_intervalo(item) for item in brutos_intervalos]
    estoques = [_estoque(item) for item in brutos_estoques]
    linhas, anotados = montar_resumo(
        estacoes,
        intervalos,
        estoques,
        janelas,
        excluir_sinalizados=filtro.excluir_sinalizados,
        limiar_cobertura=limiar,
        limite_desatualizado_segundos=configuracao.limite_status_desatualizado_segundos,
        fim_periodo=filtro.fim,
    )
    for linha in linhas:
        linha["inicio_periodo_utc"] = formatar_utc(filtro.inicio)
        linha["fim_periodo_utc"] = formatar_utc(filtro.fim)
        linha["inicio_periodo_local"] = formatar_local(filtro.inicio)
        linha["fim_periodo_local"] = formatar_local(filtro.fim)
        linha["ultima_observacao_utc"] = (
            formatar_utc(linha["ultima_observacao"]) if linha.get("ultima_observacao") else None
        )
        linha["ultima_observacao_local"] = (
            formatar_local(linha["ultima_observacao"]) if linha.get("ultima_observacao") else None
        )
        linha["flags_qualidade"] = ",".join(linha["flags_qualidade"])
    legenda = aplicar_visual(
        linhas,
        filtro.indicador,
        escala=filtro.escala,
        limiar_cobertura=limiar,
        limites_fixos=filtro.limites_fixos,
        pintar_baixa_cobertura=filtro.pintar_baixa_cobertura,
    )
    if com_exportacao:
        horas = _temporal(estacoes, anotados, janelas, "hora")
        dias = _temporal(estacoes, anotados, janelas, "dia")
        exportaveis = [_intervalo_exportavel(item) for item in anotados]
    else:
        horas = dias = exportaveis = []
    mensagem = None
    if not janelas:
        mensagem = "O período filtrado não tem duração. Não há janela para calcular cobertura."
    return ResultadoConsulta(
        resumo=_quadro(linhas, COLUNAS_RESUMO),
        intervalos=_quadro(exportaveis, COLUNAS_INTERVALOS),
        horas=_quadro(horas, COLUNAS_TEMPORAL),
        dias=_quadro(dias, COLUNAS_TEMPORAL),
        snapshots=_quadro([_snapshot_exportavel(item) for item in brutos_snapshots], COLUNAS_SNAPSHOTS),
        cadastro=_quadro([_cadastro_exportavel(item) for item in brutos_cadastro], COLUNAS_CADASTRO),
        legenda=legenda,
        contagens={
            "estacoes": len(linhas),
            "na_escala": legenda.get("na_escala", 0),
            "sem_classificacao": legenda.get("sem_classificacao", 0),
        },
        filtros=_filtros_serializaveis(filtro, limiar, janelas),
        fonte={
            "id": fonte["id"],
            "url_indice_gbfs": fonte["url_indice_gbfs"],
            "system_id": fonte.get("system_id"),
            "nome": fonte.get("nome"),
            "versao_gbfs": fonte.get("versao_gbfs"),
            "fuso_fonte": fonte.get("fuso"),
            "sintetica": bool(fonte.get("sintetica")),
        },
        mensagem=mensagem,
        linhas=linhas,
    )


def filtro_de_tudo(configuracao: Configuracao, base: FiltroConsulta) -> FiltroConsulta | None:
    if not configuracao.caminho_banco.is_file():
        return None
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        fonte = fonte_por_url(conexao, configuracao.url_indice_gbfs)
        if fonte is None:
            return None
        periodo = periodo_da_coleta(conexao, fonte["id"])
    if not periodo or not periodo.get("inicio") or not periodo.get("fim"):
        return None
    inicio = analisar_instante(periodo["inicio"])
    fim = analisar_instante(periodo["fim"])
    if inicio is None or fim is None:
        return None
    if fim < inicio:
        return None
    return FiltroConsulta(
        inicio=inicio,
        fim=fim,
        station_ids=None,
        excluir_sinalizados=False,
        horas=None,
        dias_semana=None,
        indicador=base.indicador,
        escala=base.escala,
        limites_fixos=None,
        limiar_cobertura=base.limiar_cobertura,
        pintar_baixa_cobertura=base.pintar_baixa_cobertura,
        escopo="tudo",
    )


def ler_painel(configuracao: Configuracao) -> dict:
    caminhos = configuracao.caminhos_absolutos()
    painel = {
        "caminhos": caminhos,
        "banco_existe": configuracao.caminho_banco.is_file(),
        "coletor_ativo": False,
        "estado": None,
        "ultima_tentativa": None,
        "ultimo_sucesso": None,
        "periodo": None,
        "estacoes_abertas": 0,
        "fonte": None,
        "eventos": [],
        "opcoes_estacoes": [],
        "sintetica": False,
    }
    if not painel["banco_existe"]:
        return painel
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        with leitura(conexao):
            fonte = fonte_por_url(conexao, configuracao.url_indice_gbfs)
            estado = estado_coletor(conexao)
            painel["estado"] = estado
            painel["coletor_ativo"] = _coletor_ativo(
                estado, agora_utc(), configuracao.intervalo_coleta_segundos
            )
            painel["ultima_tentativa"] = ultima_tentativa(conexao)
            if fonte is not None:
                painel["fonte"] = dict(fonte)
                painel["sintetica"] = bool(fonte.get("sintetica"))
                painel["ultimo_sucesso"] = ultimo_sucesso(conexao, fonte["id"])
                painel["periodo"] = periodo_armazenado(conexao, fonte["id"])
                painel["estacoes_abertas"] = contar_estacoes_abertas(conexao, fonte["id"])
                painel["eventos"] = eventos_recentes(conexao, fonte["id"])
                painel["opcoes_estacoes"] = [
                    {
                        "station_id": item["station_id"],
                        "nome": item.get("nome") or item["station_id"],
                    }
                    for item in estacoes_abertas(conexao, fonte["id"])
                ]
    return painel


def historico_estacao(
    configuracao: Configuracao,
    station_id: str,
    inicio: datetime,
    fim: datetime,
) -> dict:
    if not configuracao.caminho_banco.is_file():
        return {"snapshots": pd.DataFrame(), "intervalos": pd.DataFrame(), "versoes": pd.DataFrame(), "mudou_localizacao": False}
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        with leitura(conexao):
            fonte = fonte_por_url(conexao, configuracao.url_indice_gbfs)
            if fonte is None:
                return {
                    "snapshots": pd.DataFrame(),
                    "intervalos": pd.DataFrame(),
                    "versoes": pd.DataFrame(),
                    "mudou_localizacao": False,
                }
            snapshots = snapshots_no_periodo(
                conexao, fonte["id"], formatar_utc(inicio), formatar_utc(fim), [station_id]
            )
            intervalos = intervalos_sobrepostos(
                conexao, fonte["id"], formatar_utc(inicio), formatar_utc(fim), [station_id]
            )
            versoes = [
                item
                for item in estacoes_no_periodo(
                    conexao, fonte["id"], formatar_utc(inicio), formatar_utc(fim), [station_id]
                )
            ]
    quadro_snapshots = _quadro([_snapshot_exportavel(item) for item in snapshots], COLUNAS_SNAPSHOTS)
    if not quadro_snapshots.empty:
        origem = quadro_snapshots["last_reported_utc"].fillna(quadro_snapshots["coletado_em_utc"])
        quadro_snapshots["observado_em_local"] = origem.map(para_grafico)
    locais = {
        (item.get("latitude"), item.get("longitude"))
        for item in versoes
        if item.get("latitude") is not None and item.get("longitude") is not None
    }
    return {
        "snapshots": quadro_snapshots,
        "intervalos": _quadro([_intervalo_exportavel(_intervalo(item)) for item in intervalos], COLUNAS_INTERVALOS),
        "versoes": _quadro([_cadastro_exportavel(item) for item in versoes], COLUNAS_CADASTRO),
        "mudou_localizacao": len(locais) > 1,
    }


def janela_fixa(
    inicio_serie: datetime, fim_serie: datetime, horas: float
) -> tuple[datetime, datetime]:
    """Últimas `horas` até o fim da série, sem começar antes da primeira observação comparável."""
    if horas <= 0:
        raise ValueError("A janela fixa precisa ter duração positiva.")
    inicio = fim_serie - timedelta(hours=horas)
    if inicio < inicio_serie:
        inicio = inicio_serie
    if inicio > fim_serie:
        inicio = fim_serie
    return inicio, fim_serie


def periodo_padrao(configuracao: Configuracao) -> tuple[datetime, datetime] | None:
    if not configuracao.caminho_banco.is_file():
        return None
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        fonte = fonte_por_url(conexao, configuracao.url_indice_gbfs)
        if fonte is None:
            return None
        periodo = periodo_da_coleta(conexao, fonte["id"])
    inicio = analisar_instante(periodo["inicio"]) if periodo else None
    fim = analisar_instante(periodo["fim"]) if periodo else None
    if inicio is None or fim is None:
        return None
    return inicio, fim


def _coletor_ativo(estado: dict | None, agora: datetime, intervalo: float) -> bool:
    if not estado or estado.get("estado") != "ativo":
        return False
    batimento = analisar_instante(estado.get("ultimo_batimento_utc"))
    if batimento is None:
        return False
    limite = max(intervalo * 3, 90)
    return (agora - batimento).total_seconds() <= limite


def _estacao(item: dict) -> dict:
    return {
        "id": item["id"],
        "station_id": item["station_id"],
        "nome": item.get("nome"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "capacidade": item.get("capacidade"),
        "ausente_desde": item.get("ausente_desde_utc"),
    }


def _intervalo(item: dict) -> dict:
    return {
        "station_id": item["station_id"],
        "estacao_id_inicio": item.get("estacao_id_inicio"),
        "estacao_id_fim": item.get("estacao_id_fim"),
        "inicio": analisar_instante(item.get("inicio_utc")),
        "fim": analisar_instante(item.get("fim_utc")),
        "inicio_utc": item.get("inicio_utc"),
        "fim_utc": item.get("fim_utc"),
        "duracao_segundos": item.get("duracao_segundos"),
        "bicicletas_anterior": item.get("bicicletas_anterior"),
        "bicicletas_atual": item.get("bicicletas_atual"),
        "delta": item.get("delta"),
        "aumento_observado": item.get("aumento_observado"),
        "reducao_observada": item.get("reducao_observada"),
        "movimentacao_observada": item.get("movimentacao_observada"),
        "comparavel": bool(item.get("comparavel")),
        "motivo": item.get("motivo"),
        "flags": set(decodificar_flags(item.get("flags_qualidade"))),
        "flags_qualidade": item.get("flags_qualidade"),
    }


def _estoque(item: dict) -> dict:
    observado = analisar_instante(item.get("last_reported_utc")) or analisar_instante(
        item.get("coletado_em_utc")
    )
    return {
        "estacao_id": item["estacao_id"],
        "station_id": item["station_id"],
        "bicicletas": item.get("bicicletas_disponiveis"),
        "observado_em": observado,
    }


def _intervalo_exportavel(item: dict) -> dict:
    flags = item.get("flags")
    if isinstance(flags, set):
        texto = ",".join(sorted(flags))
    else:
        texto = ",".join(decodificar_flags(item.get("flags_qualidade")))
    return {
        "station_id": item.get("station_id"),
        "estacao_id_inicio": item.get("estacao_id_inicio"),
        "estacao_id_fim": item.get("estacao_id_fim"),
        "inicio_utc": item.get("inicio_utc"),
        "fim_utc": item.get("fim_utc"),
        "duracao_segundos": item.get("duracao_segundos"),
        "bicicletas_anterior": item.get("bicicletas_anterior"),
        "bicicletas_atual": item.get("bicicletas_atual"),
        "delta": item.get("delta"),
        "aumento_observado": item.get("aumento_observado"),
        "reducao_observada": item.get("reducao_observada"),
        "movimentacao_observada": item.get("movimentacao_observada"),
        "comparavel": 1 if item.get("comparavel") else 0,
        "motivo": item.get("motivo"),
        "flags_qualidade": texto,
        "incluido_no_resumo": 1 if item.get("incluido_no_resumo") else 0,
    }


def _snapshot_exportavel(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "station_id": item.get("station_id"),
        "id_cadastro": item.get("estacao_id"),
        "coletado_em_utc": item.get("coletado_em_utc"),
        "feed_atualizado_em_utc": item.get("feed_atualizado_em_utc"),
        "last_reported_utc": item.get("last_reported_utc"),
        "bicicletas_disponiveis": item.get("bicicletas_disponiveis"),
        "vagas_disponiveis": item.get("vagas_disponiveis"),
        "bicicletas_desabilitadas": item.get("bicicletas_desabilitadas"),
        "vagas_desabilitadas": item.get("vagas_desabilitadas"),
        "instalada": item.get("instalada"),
        "alugando": item.get("alugando"),
        "devolvendo": item.get("devolvendo"),
        "situacao_operacional": item.get("situacao_operacional"),
        "disponibilidade_por_tipo_json": item.get("disponibilidade_por_tipo_json"),
        "versao_gbfs": item.get("versao_gbfs"),
        "arquivo_bruto": item.get("arquivo_bruto"),
        "flags_qualidade": ",".join(decodificar_flags(item.get("flags_qualidade"))),
    }


def _cadastro_exportavel(item: dict) -> dict:
    return {
        "id_cadastro": item.get("id"),
        "station_id": item.get("station_id"),
        "nome": item.get("nome"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "capacidade": item.get("capacidade"),
        "external_id": item.get("external_id"),
        "endereco": item.get("endereco"),
        "valido_desde_utc": item.get("valido_desde_utc"),
        "valido_ate_utc": item.get("valido_ate_utc"),
        "ausente_desde_utc": item.get("ausente_desde_utc"),
    }


def _temporal(estacoes, anotados, janelas, frequencia: str) -> list[dict]:
    linhas = agregar_temporal(estacoes, anotados, janelas, frequencia)
    for linha in linhas:
        linha["flags_qualidade"] = ",".join(linha["flags_qualidade"])
        linha.pop("inicio_periodo", None)
        linha.pop("fim_periodo", None)
    return linhas


def _quadro(linhas: list[dict], colunas: list[str]) -> pd.DataFrame:
    quadro = pd.DataFrame(linhas)
    for coluna in colunas:
        if coluna not in quadro.columns:
            quadro[coluna] = pd.Series(dtype="object")
    return quadro[colunas]


def _filtros_serializaveis(filtro: FiltroConsulta, limiar: float, janelas) -> dict:
    return {
        "escopo": filtro.escopo,
        "inicio_utc": formatar_utc(filtro.inicio),
        "fim_utc": formatar_utc(filtro.fim),
        "inicio_local": formatar_local(filtro.inicio),
        "fim_local": formatar_local(filtro.fim),
        "fuso": "America/Sao_Paulo",
        "station_ids": filtro.station_ids,
        "excluir_sinalizados": filtro.excluir_sinalizados,
        "horas": filtro.horas,
        "dias_semana": sorted(filtro.dias_semana) if filtro.dias_semana is not None else None,
        "indicador": filtro.indicador,
        "escala": filtro.escala,
        "limites_fixos": filtro.limites_fixos,
        "limiar_cobertura_percentual": limiar,
        "pintar_baixa_cobertura": filtro.pintar_baixa_cobertura,
        "janelas_utc": [
            [formatar_utc(inicio), formatar_utc(fim)] for inicio, fim in janelas
        ],
    }


def _vazio(filtro: FiltroConsulta, fonte: dict) -> ResultadoConsulta:
    return ResultadoConsulta(
        resumo=_quadro([], COLUNAS_RESUMO),
        intervalos=_quadro([], COLUNAS_INTERVALOS),
        horas=_quadro([], COLUNAS_TEMPORAL),
        dias=_quadro([], COLUNAS_TEMPORAL),
        snapshots=_quadro([], COLUNAS_SNAPSHOTS),
        cadastro=_quadro([], COLUNAS_CADASTRO),
        legenda={"na_escala": 0, "sem_classificacao": 0, "sem_valores": True},
        contagens={"estacoes": 0, "na_escala": 0, "sem_classificacao": 0},
        filtros={},
        fonte=fonte,
    )
