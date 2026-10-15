"""CSV, Parquet, GeoPackage e GeoJSON com o mesmo recorte da consulta."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from observador_bikerio import __version__
from observador_bikerio.configuracao import Configuracao
from observador_bikerio.consulta import ResultadoConsulta
from observador_bikerio.tempo import FUSO_EXIBICAO, agora_utc, formatar_local, formatar_utc
from observador_bikerio.textos import (
    ATRIBUICAO_FONTE,
    DESCRICAO_FLAGS,
    NOTA_ATRIBUICAO,
    NOTA_COBERTURA,
    NOTA_CORES,
    NOTA_INDICADORES,
    NOTA_PROXY,
    NOTA_TAXA,
    NOTA_TIPOS,
)

COLUNAS_ESPACIAIS_RESUMO = [
    "station_id",
    "id_cadastro",
    "nome",
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
    "latitude",
    "longitude",
]

COLUNAS_ESPACIAIS_TEMPORAL = [
    "station_id",
    "id_cadastro",
    "nome",
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
    "latitude",
    "longitude",
]


def exportar(
    configuracao: Configuracao,
    resultado: ResultadoConsulta,
    frequencia_temporal: str = "hora",
    gerar_geojson: bool = True,
) -> Path:
    if frequencia_temporal not in {"hora", "dia"}:
        raise ValueError("A camada temporal deve ser hora ou dia.")
    carimbo = agora_utc().astimezone(FUSO_EXIBICAO).strftime("%Y%m%dT%H%M%S%z")
    pasta = configuracao.pasta_exportacoes / carimbo
    pasta.mkdir(parents=True, exist_ok=True)
    _tabular(pasta / "cadastro", resultado.cadastro)
    _tabular(pasta / "snapshots", resultado.snapshots)
    _tabular(pasta / "intervalos", resultado.intervalos)
    _tabular(pasta / "indicadores_estacao_hora", resultado.horas)
    _tabular(pasta / "indicadores_estacao_dia", resultado.dias)
    _tabular(pasta / "resumo_periodo", resultado.resumo.drop(columns=["cor", "borda"], errors="ignore"))
    temporal = resultado.horas if frequencia_temporal == "hora" else resultado.dias
    _geopackage(
        pasta / "bikerio.gpkg",
        resultado.cadastro,
        resultado.resumo,
        temporal,
        f"serie_estacao_{frequencia_temporal}",
    )
    if gerar_geojson:
        _geojson(pasta / "resumo_periodo.geojson", resultado.resumo)
    metadados = _metadados(configuracao, resultado, frequencia_temporal, pasta)
    (pasta / "metadados.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (pasta / "dicionario.md").write_text(_dicionario(metadados), encoding="utf-8")
    return pasta.resolve()


def _tabular(caminho: Path, quadro: pd.DataFrame) -> None:
    quadro.to_csv(caminho.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    quadro.to_parquet(caminho.with_suffix(".parquet"), index=False)


def _geopackage(caminho: Path, cadastro: pd.DataFrame, resumo: pd.DataFrame, temporal: pd.DataFrame, nome_temporal: str) -> None:
    gpd = _geopandas()
    camadas = [
        ("cadastro_estacoes", _pontos(gpd, cadastro, ["id_cadastro", "station_id", "nome", "capacidade", "external_id", "endereco", "valido_desde_utc", "valido_ate_utc", "ausente_desde_utc", "latitude", "longitude"])),
        ("indicadores_periodo", _pontos(gpd, resumo, COLUNAS_ESPACIAIS_RESUMO)),
        (nome_temporal, _pontos(gpd, temporal, COLUNAS_ESPACIAIS_TEMPORAL)),
    ]
    if caminho.exists():
        caminho.unlink()
    primeira = True
    for nome, camada in camadas:
        camada.to_file(caminho, layer=nome, driver="GPKG", mode="w" if primeira else "a")
        primeira = False


def _geojson(caminho: Path, resumo: pd.DataFrame) -> None:
    gpd = _geopandas()
    camada = _pontos(gpd, resumo, COLUNAS_ESPACIAIS_RESUMO)
    camada.to_file(caminho, driver="GeoJSON")


def _pontos(gpd, quadro: pd.DataFrame, colunas: list[str]):
    from shapely.geometry import Point

    presentes = [coluna for coluna in colunas if coluna in quadro.columns]
    tabela = quadro[presentes].copy() if presentes else pd.DataFrame(columns=colunas)
    geometrias = []
    indices = []
    for indice, linha in tabela.iterrows():
        latitude = linha.get("latitude")
        longitude = linha.get("longitude")
        if not _coordenada(latitude, longitude):
            continue
        geometrias.append(Point(float(longitude), float(latitude)))
        indices.append(indice)
    espacial = tabela.loc[indices].copy() if indices else tabela.iloc[0:0].copy()
    if espacial.empty:
        espacial = pd.DataFrame(columns=presentes)
    return gpd.GeoDataFrame(espacial, geometry=geometrias, crs="EPSG:4326")


def _geopandas():
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError(
            "A exportação espacial precisa de GeoPandas e Pyogrio instalados."
        ) from exc
    return gpd


def _coordenada(latitude, longitude) -> bool:
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return False
    if latitude != latitude or longitude != longitude:
        return False
    return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180


def _metadados(configuracao: Configuracao, resultado: ResultadoConsulta, frequencia: str, pasta: Path) -> dict:
    return {
        "versao_processamento": __version__,
        "gerado_em_utc": formatar_utc(agora_utc()),
        "gerado_em_local": formatar_local(agora_utc()),
        "pasta": str(pasta),
        "fonte": {
            "nome": resultado.fonte.get("nome"),
            "system_id": resultado.fonte.get("system_id"),
            "url_indice_gbfs": resultado.fonte.get("url_indice_gbfs"),
            "versao_gbfs": resultado.fonte.get("versao_gbfs"),
            "fuso_da_fonte": resultado.fonte.get("fuso_fonte"),
            "sintetica": bool(resultado.fonte.get("sintetica")),
            "atribuicao": ATRIBUICAO_FONTE,
            "documentacao": "https://gbfs.org/documentation/reference/",
        },
        "periodo": {
            "inicio_utc": resultado.filtros.get("inicio_utc"),
            "fim_utc": resultado.filtros.get("fim_utc"),
            "inicio_local": resultado.filtros.get("inicio_local"),
            "fim_local": resultado.filtros.get("fim_local"),
            "fuso_de_exibicao_e_agregacao": "America/Sao_Paulo",
            "armazenamento": "UTC",
        },
        "crs": "EPSG:4326",
        "ordem_geojson": "longitude, latitude",
        "camada_temporal": f"serie_estacao_{frequencia}",
        "filtros": resultado.filtros,
        "limites": {
            "lacuna_segundos": configuracao.limite_lacuna_segundos,
            "dados_antigos_segundos": configuracao.limite_dados_antigos_segundos,
            "intervencao_bicicletas": configuracao.limiar_intervencao_bicicletas,
            "cobertura_minima_percentual": resultado.filtros.get("limiar_cobertura_percentual"),
            "status_desatualizado_segundos": configuracao.limite_status_desatualizado_segundos,
        },
        "definicoes": {
            "aumento_observado": "max(estoque_atual - estoque_anterior, 0), só em intervalos comparáveis.",
            "reducao_observada": "max(estoque_anterior - estoque_atual, 0), só em intervalos comparáveis.",
            "movimentacao_observada": "aumento_observado + reducao_observada. Proxy de movimentação, não contagem de viagens.",
            "taxa_por_hora_valida": "movimentacao_observada / horas_validas. Não reconstitui lacunas.",
            "cobertura_percentual": "duração da união dos intervalos válidos, recortados às janelas do filtro, dividida pela duração dessas janelas.",
            "horas_no_filtro": "denominador da cobertura, em horas. Com filtro de horário ou dia da semana, não é o vão contínuo entre início e fim.",
            "atribuicao_temporal": NOTA_ATRIBUICAO,
            "incluido_no_resumo": "1 reproduz a soma do mapa e da tabela. 0 ficou de fora por regra de qualidade ou por terminar fora da janela.",
        },
        "flags": DESCRICAO_FLAGS,
        "limitacoes": [
            NOTA_INDICADORES,
            NOTA_PROXY,
            NOTA_TAXA,
            NOTA_COBERTURA,
            NOTA_CORES,
            NOTA_ATRIBUICAO,
            NOTA_TIPOS,
            "Falha de coleta e estação ausente do feed não são gravadas como zero.",
            "Soma entre estações não é o total de viagens do sistema: a mesma viagem pode aparecer como redução numa estação e aumento em outra.",
            "Horas sem intervalo válido não são materializadas como zero na série temporal.",
            "Mudança de localização gera outra feição. Observações de pontos diferentes não são agregadas.",
        ],
        "contagens": resultado.contagens,
    }


def _dicionario(metadados: dict) -> str:
    linhas = [
        "# Dicionário dos arquivos exportados",
        "",
        metadados["fonte"]["atribuicao"],
        "",
        f"Versão do processamento: {metadados['versao_processamento']}",
        f"Gerado em UTC: {metadados['gerado_em_utc']}",
        f"CRS: {metadados['crs']}. No GeoJSON a coordenada é longitude, latitude.",
        "Horários `*_utc` estão em UTC. Horários `*_local` estão em America/Sao_Paulo, com offset.",
        "",
        "## Limitações",
        "",
    ]
    linhas.extend(f"- {item}" for item in metadados["limitacoes"])
    linhas.extend(
        [
            "",
            "## Filtros e limites",
            "",
            "```json",
            json.dumps({"filtros": metadados["filtros"], "limites": metadados["limites"]}, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Definições",
            "",
        ]
    )
    for nome, texto in metadados["definicoes"].items():
        linhas.append(f"- **{nome}**: {texto}")
    linhas.extend(["", "## Flags", ""])
    for nome, texto in metadados["flags"].items():
        linhas.append(f"- **{nome}**: {texto}")
    linhas.extend(
        [
            "",
            "## Arquivos",
            "",
            "- `cadastro`: versões de nome, capacidade e coordenada, com início e fim de validade.",
            "- `snapshots`: observações de estoque. Nulo significa ausência de informação, não zero.",
            "- `intervalos`: pares comparados. Métricas nulas têm `motivo`. `incluido_no_resumo = 1` reproduz o mapa.",
            "- `indicadores_estacao_hora` e `indicadores_estacao_dia`: agregação atribuída ao fim do intervalo.",
            "- `resumo_periodo`: a mesma linha do mapa e da tabela.",
            "- `bikerio.gpkg`: `cadastro_estacoes`, `indicadores_periodo` e a série temporal escolhida.",
            "- `resumo_periodo.geojson`: o resumo espacial, quando solicitado.",
            "",
            "Para reproduzir o mapa, use `movimentacao_observada` (ou o indicador escolhido) e exclua `categoria` de cobertura insuficiente quando a visualização principal estiver em vigor. O valor numérico continua no arquivo.",
            "",
        ]
    )
    return "\n".join(linhas)
