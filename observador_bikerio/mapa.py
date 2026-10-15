"""Mapa de marcadores. Cada estação permanece um ponto; a cor carrega o indicador."""

from __future__ import annotations

import html

import folium
import pandas as pd

from observador_bikerio.textos import (
    COR_SEM_DADOS,
    INDICADORES,
    NOTA_INDICADORES,
    PALETAS,
)

CENTRO_RIO = (-22.9068, -43.1729)
RAIO_MARCADOR = 8


def montar_geojson(resumo: pd.DataFrame) -> dict:
    feicoes = []
    if resumo is None or resumo.empty:
        return {"type": "FeatureCollection", "features": feicoes}
    for linha in resumo.to_dict(orient="records"):
        if not _coordenada(linha.get("latitude"), linha.get("longitude")):
            continue
        feicoes.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(linha["longitude"]), float(linha["latitude"])],
                },
                "properties": _propriedades(linha),
            }
        )
    return {"type": "FeatureCollection", "features": feicoes}


def criar_mapa(resumo: pd.DataFrame, legenda: dict, sintetico: bool = False) -> folium.Map:
    coordenadas = []
    if resumo is not None and not resumo.empty:
        for linha in resumo.to_dict(orient="records"):
            if _coordenada(linha.get("latitude"), linha.get("longitude")):
                coordenadas.append((float(linha["latitude"]), float(linha["longitude"])))
    centro = (
        (sum(item[0] for item in coordenadas) / len(coordenadas), sum(item[1] for item in coordenadas) / len(coordenadas))
        if coordenadas
        else CENTRO_RIO
    )
    mapa = folium.Map(location=centro, zoom_start=12, tiles="OpenStreetMap", control_scale=True)
    colecao = montar_geojson(resumo)
    if colecao["features"]:
        folium.GeoJson(
            colecao,
            name="estacoes",
            marker=folium.CircleMarker(radius=RAIO_MARCADOR, fill=True),
            style_function=lambda feicao: {
                "radius": RAIO_MARCADOR,
                "color": feicao["properties"].get("borda") or "#333333",
                "weight": 1.5,
                "fillColor": feicao["properties"].get("cor") or COR_SEM_DADOS,
                "fillOpacity": 0.92,
            },
            popup=folium.GeoJsonPopup(
                fields=["popup"],
                labels=False,
                localize=False,
            ),
            tooltip=folium.GeoJsonTooltip(fields=["nome", "rotulo"], aliases=["Estação", "Valor"]),
        ).add_to(mapa)
    _legenda(mapa, legenda, sintetico)
    return mapa


def _propriedades(linha: dict) -> dict:
    nome = linha.get("nome") or linha.get("station_id") or "Estação"
    categoria = linha.get("categoria") or ""
    valor = linha.get("valor_indicador")
    unidade = linha.get("unidade_indicador") or ""
    if valor is None:
        rotulo = _texto_categoria(categoria)
    elif isinstance(valor, float):
        rotulo = f"{valor:.2f} {unidade}".strip()
    else:
        rotulo = f"{valor} {unidade}".strip()
    return {
        "station_id": linha.get("station_id"),
        "id_cadastro": linha.get("id_cadastro"),
        "nome": nome,
        "categoria": categoria,
        "rotulo": rotulo,
        "cor": linha.get("cor") or COR_SEM_DADOS,
        "borda": linha.get("borda") or "#333333",
        "popup": _html_popup(linha, rotulo),
    }


def _html_popup(linha: dict, rotulo: str) -> str:
    alertas = linha.get("flags_qualidade") or "nenhum"
    bicicletas = _numero(linha.get("bicicletas_disponiveis"))
    return "<br>".join(
        [
            f"<b>{html.escape(str(linha.get('nome') or 'Estação'))}</b>",
            f"Identificador: {html.escape(str(linha.get('station_id') or ''))}",
            f"Versão cadastral: {html.escape(str(linha.get('id_cadastro') or ''))}",
            f"Capacidade: {html.escape(_numero(linha.get('capacidade')))}",
            f"Período: {html.escape(str(linha.get('inicio_periodo_local') or ''))} — {html.escape(str(linha.get('fim_periodo_local') or ''))}",
            f"Devoluções de bicicletas: {html.escape(_numero(linha.get('aumentos_observados')))}",
            f"Retiradas de bicicletas: {html.escape(_numero(linha.get('reducoes_observadas')))}",
            f"Movimentação observada: {html.escape(_numero(linha.get('movimentacao_observada')))}",
            f"Taxa por hora válida: {html.escape(_numero(linha.get('taxa_por_hora_valida')))}",
            f"Horas válidas: {html.escape(_numero(linha.get('horas_validas')))}",
            f"Cobertura: {html.escape(_numero(linha.get('cobertura_percentual')))}%",
            f"Indicador no mapa: {html.escape(rotulo)}",
            f"Classificação: {html.escape(_texto_categoria(str(linha.get('categoria') or '')))}",
            f"Bicicletas na observação mais recente: {html.escape(bicicletas)}",
            f"Última observação: {html.escape(str(linha.get('ultima_observacao_local') or '—'))}",
            f"Alertas: {html.escape(str(alertas))}",
            f"<i>{html.escape(NOTA_INDICADORES)}</i>",
        ]
    )


def _legenda(mapa: folium.Map, legenda: dict, sintetico: bool) -> None:
    minimo = _numero(legenda.get("minimo"))
    maximo = _numero(legenda.get("maximo"))
    titulo = legenda.get("rotulo") or "Indicador"
    if sintetico:
        titulo = f"SINTÉTICO — {titulo}"
    indicador = legenda.get("indicador") or ""
    paleta = PALETAS.get((INDICADORES.get(indicador) or {}).get("paleta") or "", PALETAS["movimento"])
    degradado = ", ".join(paleta)
    bloco = f"""
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999; background: white;
                padding: 8px 10px; border: 1px solid #ccc; font-size: 12px; width: 220px;">
      <div style="font-weight: 700; margin-bottom: 6px;">{html.escape(str(titulo))}</div>
      <div style="height: 12px; border: 1px solid #888; background: linear-gradient(to right, {degradado});"></div>
      <div style="display: flex; justify-content: space-between; margin-top: 4px;">
        <span>{html.escape(minimo)}</span>
        <span>{html.escape(maximo)}</span>
      </div>
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(bloco))


def _coordenada(latitude, longitude) -> bool:
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return False
    return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180


def _numero(valor) -> str:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return "—"
    if isinstance(valor, float):
        return f"{valor:.2f}"
    return str(valor)


def _texto_categoria(categoria: str) -> str:
    return {
        "classificada": "incluída na escala",
        "zero_movimentacao": "zero de movimentação observada, com cobertura suficiente",
        "cobertura_insuficiente": "cobertura insuficiente",
        "sem_intervalos_validos": "sem intervalos válidos",
        "sem_observacao_de_estoque": "sem observação de estoque",
        "status_desatualizado": "status recente desatualizado",
        "sem_coordenadas": "sem coordenadas",
    }.get(categoria, categoria or "—")
