"""Visualização local. Abrir esta tela não inicia, duplica nem encerra o coletor."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import streamlit as st

from observador_bikerio.configuracao import carregar_configuracao
from observador_bikerio.consulta import (
    FiltroConsulta,
    consultar,
    filtro_de_tudo,
    historico_estacao,
    janela_fixa,
    ler_painel,
    periodo_padrao,
)
from observador_bikerio.exportacao import exportar
from observador_bikerio.mapa import criar_mapa
from observador_bikerio.tempo import FUSO_EXIBICAO, analisar_instante, para_exibicao
from observador_bikerio.textos import INDICADORES, NOTA_INDICADORES

COLUNAS_TABELA = {
    "nome": "Estação",
    "station_id": "Identificador",
    "id_cadastro": "Versão cadastral",
    "aumentos_observados": "Devoluções de bicicletas",
    "reducoes_observadas": "Retiradas de bicicletas",
    "movimentacao_observada": "Movimentação observada",
    "taxa_por_hora_valida": "Taxa por hora válida",
    "horas_validas": "Horas válidas",
    "cobertura_percentual": "Cobertura (%)",
    "intervalos_validos": "Intervalos válidos",
    "quantidade_lacunas": "Lacunas",
    "bicicletas_disponiveis": "Bicicletas na observação mais recente",
    "categoria": "Classificação",
    "flags_qualidade": "Alertas",
}

RECORTES = ("Todo o período", "1h", "6h", "24h", "Personalizado")
HORAS_RECORTE = {"1h": 1, "6h": 6, "24h": 24}


def main() -> None:
    st.set_page_config(
        page_title="Observador Bike Rio",
        page_icon="🚲",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        /* ── reset de padding ─────────────────────────────── */
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
        section[data-testid="stSidebar"] { padding-top: 0; }

        /* ── sidebar fixa ─────────────────────────────────── */
        [data-testid="stSidebar"] {
            transform: none !important;
            visibility: visible !important;
            min-width: 18rem;
            border-right: 1px solid #E0DDD8;
        }
        [data-testid="collapsedControl"] { display: none !important; }

        /* ── cabeçalho da sidebar ─────────────────────────── */
        [data-testid="stSidebar"] h2 {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #6B6560;
            margin-top: 1.4rem;
            margin-bottom: 0.4rem;
        }

        /* ── separador horizontal ─────────────────────────── */
        hr { border-color: #E0DDD8; margin: 1rem 0; }

        /* ── cards de métrica ─────────────────────────────── */
        [data-testid="stMetric"] {
            background: #FFFFFF;
            border: 1px solid #E0DDD8;
            border-radius: 8px;
            padding: 0.75rem 1rem;
        }
        [data-testid="stMetricLabel"] { font-size: 0.72rem; color: #6B6560; }
        [data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; }

        /* ── botão radio (janela) como pills ──────────────── */
        div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label {
            border: 1px solid #C8C3BC;
            border-radius: 999px;
            padding: 0.25rem 0.85rem;
            font-size: 0.82rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.15s;
        }
        div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label[data-selected="true"],
        div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label:has(input:checked) {
            background: #9B2226;
            color: #FFFFFF;
            border-color: #9B2226;
        }

        /* ── dataframe ────────────────────────────────────── */
        [data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

        /* ── títulos de seção ─────────────────────────────── */
        h2 { font-size: 1rem; font-weight: 700; margin-bottom: 0.2rem; }
        h3 { font-size: 0.88rem; font-weight: 600; color: #3A3835; }

        /* ── selectbox: nome inteiro ──────────────────────── */
        div[data-testid="stSelectbox"] { max-width: 100%; }
        div[data-testid="stSelectbox"] div[data-baseweb="select"] span {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: unset !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    configuracao = carregar_configuracao()

    # ── cabeçalho ─────────────────────────────────────────
    st.markdown(
        """
        <div style="display:flex;align-items:baseline;gap:0.6rem;margin-bottom:0.25rem;">
          <span style="font-size:1.45rem;font-weight:800;letter-spacing:-0.01em;color:#1A1A1A;">
            Observador Bike Rio
          </span>
          <span style="font-size:0.8rem;color:#6B6560;font-weight:400;">
            disponibilidade de bicicletas em tempo real
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    col_janela, col_indicador = st.columns([3, 5])
    with col_janela:
        recorte = st.radio(
            "Janela",
            RECORTES,
            horizontal=True,
            index=RECORTES.index("1h"),
            help="O mapa acumula retiradas, devoluções e movimentação nesta janela.",
        )
    with col_indicador:
        indicador = st.selectbox(
            "Indicador do mapa",
            list(INDICADORES),
            format_func=lambda chave: INDICADORES[chave]["rotulo"],
            help=(
                "Movimentação observada: soma de retiradas e devoluções na janela. "
                "Por hora válida: essa soma dividida pelas horas com intervalo comparável. "
                "Bicicletas disponíveis: estoque do último snapshot."
            ),
        )
    filtro = _barra(configuracao, recorte, indicador)
    _conteudo(configuracao, filtro)


def _barra(configuracao, recorte: str, indicador: str) -> dict:
    painel = ler_painel(configuracao)
    with st.sidebar:
        st.markdown(
            "<div style='padding:1rem 1rem 0;font-size:0.95rem;font-weight:700;color:#1A1A1A;'>"
            "🚲 Observador Bike Rio</div>",
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.header("Filtros")
        livre = recorte == "Personalizado"
        padrao = periodo_padrao(configuracao)
        if padrao:
            inicio_local = para_exibicao(padrao[0])
            fim_local = para_exibicao(padrao[1])
        else:
            from observador_bikerio.tempo import agora_utc

            fim_local = para_exibicao(agora_utc())
            inicio_local = fim_local.replace(hour=0, minute=0, second=0, microsecond=0)
        coluna_a, coluna_b = st.columns(2)
        with coluna_a:
            data_inicio = st.date_input("Data inicial", value=inicio_local.date(), disabled=not livre)
            hora_inicio = st.time_input(
                "Hora inicial",
                value=inicio_local.replace(microsecond=0).time().replace(tzinfo=None),
                step=timedelta(seconds=1),
                disabled=not livre,
            )
        with coluna_b:
            data_fim = st.date_input("Data final", value=fim_local.date(), disabled=not livre)
            hora_fim = st.time_input(
                "Hora final",
                value=fim_local.replace(microsecond=0).time().replace(tzinfo=None),
                step=timedelta(seconds=1),
                disabled=not livre,
            )
        opcoes = painel.get("opcoes_estacoes") or []
        estacoes = st.multiselect(
            "Estações",
            options=[item["station_id"] for item in opcoes],
            format_func=lambda station_id: _rotulo_estacao(opcoes, station_id),
            placeholder="Todas",
        )
        pintar_cobertura = st.checkbox(
            "Pintar cobertura insuficiente em cinza",
            value=False,
            help="Desligado, a cor segue o indicador escolhido. A cobertura continua na tabela e no pop-up.",
        )
        excluir = st.checkbox(
            "Excluir intervalos sinalizados",
            value=False,
            help="Possível intervenção, mudança operacional, dados antigos ou mudança de versão do feed.",
        )
        escala = st.radio("Escala", ["linear", "log1p"], format_func=lambda item: "Linear" if item == "linear" else "Logarítmica (log1p)")
        limites = st.checkbox("Usar limites fixos de cor", value=False)
        vmin = vmax = None
        if limites:
            vmin = st.number_input("Mínimo fixo", value=0.0)
            vmax = st.number_input("Máximo fixo", value=10.0)
    return {
        "painel": painel,
        "recorte": recorte,
        "data_inicio": data_inicio,
        "hora_inicio": hora_inicio,
        "data_fim": data_fim,
        "hora_fim": hora_fim,
        "indicador": indicador,
        "estacoes": estacoes,
        "pintar_cobertura": pintar_cobertura,
        "excluir": excluir,
        "escala": escala,
        "limites": (float(vmin), float(vmax)) if limites else None,
    }


def _conteudo(configuracao, controles: dict) -> None:
    segundos = int(configuracao.atualizacao_interface_segundos)

    def renderizar() -> None:
        _renderizar(configuracao, controles)

    if segundos > 0:
        fragmento = st.fragment(run_every=timedelta(seconds=segundos))(renderizar)
    else:
        fragmento = st.fragment(renderizar)
    fragmento()


def _renderizar(configuracao, controles: dict) -> None:
    painel = ler_painel(configuracao)
    if painel.get("sintetica"):
        st.error("⚠️ ESTES DADOS SÃO SINTÉTICOS E NÃO REPRESENTAM O BIKE RIO.")
    filtro, erro = _montar_filtro(configuracao, controles)
    if erro:
        st.warning(erro)
        return
    if filtro is None:
        st.warning("Ainda não há observações armazenadas para esta fonte.")
        return
    resultado = consultar(configuracao, filtro, com_exportacao=False)
    if resultado.mensagem and resultado.resumo.empty:
        st.warning(resultado.mensagem)
        return
    _status_principal(painel, filtro)
    st.divider()
    colunas = st.columns(4)
    colunas[0].metric("Estações no mapa", resultado.contagens["estacoes"])
    colunas[1].metric("Na escala de cor", resultado.contagens["na_escala"])
    colunas[2].metric("Sem classificação", resultado.contagens["sem_classificacao"])
    soma = pd.to_numeric(resultado.resumo["movimentacao_observada"], errors="coerce").sum(min_count=1)
    colunas[3].metric(
        "Movimentação total",
        "—" if pd.isna(soma) else f"{soma:.0f}",
        help="Soma das movimentações observadas. Não é o total de viagens do sistema.",
    )
    indicador = controles["indicador"]
    if (
        resultado.contagens["na_escala"] == 0
        and not pd.isna(soma)
        and INDICADORES[indicador]["aplica_cobertura"]
    ):
        st.caption("Nenhuma estação atingiu cobertura ≥ 90% na janela. Os valores continuam na tabela.")
    st.divider()
    mapa = criar_mapa(resultado.resumo, resultado.legenda, bool(resultado.fonte.get("sintetica")))
    clique = st_folium_compativel(mapa)
    propriedades = ((clique or {}).get("last_object_clicked") or {}).get("properties") or {}
    if propriedades.get("station_id"):
        st.session_state["estacao_historico"] = propriedades["station_id"]
    st.divider()
    st.subheader("Tabela das estações")
    visivel = resultado.resumo.rename(columns=COLUNAS_TABELA)
    st.dataframe(visivel[list(COLUNAS_TABELA.values())], width="stretch", hide_index=True)
    with st.expander("Histórico da estação", expanded=False):
        _historico(configuracao, filtro, resultado)
    _eventos(painel)
    with st.expander("Exportação para SIG-T", expanded=False):
        _exportacao(configuracao, filtro)


def _status_principal(painel: dict, filtro: FiltroConsulta) -> None:
    ativo = painel.get("coletor_ativo")
    estado = painel.get("estado") or {}
    sucesso = painel.get("ultimo_sucesso") or {}
    tentativa = painel.get("ultima_tentativa") or {}
    periodo = (
        f"{filtro.inicio.astimezone(FUSO_EXIBICAO):%d/%m %H:%M} — "
        f"{filtro.fim.astimezone(FUSO_EXIBICAO):%d/%m %H:%M}"
    )
    cor_status = "#15803D" if ativo else "#B45309"
    label_status = "● Coletor ativo" if ativo else "● Coletor inativo"
    ultima = _hora(sucesso.get("encerrada_em_utc") or tentativa.get("encerrada_em_utc"))
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:2rem;flex-wrap:wrap;
                    background:#FFFFFF;border:1px solid #E0DDD8;border-radius:10px;
                    padding:0.75rem 1.25rem;margin-bottom:0.5rem;">
          <span style="color:{cor_status};font-weight:700;font-size:0.85rem;">{label_status}</span>
          <span style="color:#6B6560;font-size:0.8rem;">
            Última coleta: <strong style="color:#1A1A1A;">{ultima}</strong>
          </span>
          <span style="color:#6B6560;font-size:0.8rem;">
            Janela: <strong style="color:#1A1A1A;">{periodo}</strong>
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    fonte = painel.get("fonte") or {}
    if fonte:
        st.caption(f"{fonte.get('system_id') or 'sem system_id'} · {fonte.get('url_indice_gbfs')}")


def _montar_filtro(configuracao, controles: dict):
    recorte = controles["recorte"]
    padrao = periodo_padrao(configuracao)
    if recorte == "Personalizado":
        inicio = datetime.combine(
            controles["data_inicio"], controles["hora_inicio"], tzinfo=FUSO_EXIBICAO
        ).astimezone(timezone.utc)
        fim = datetime.combine(
            controles["data_fim"], controles["hora_fim"], tzinfo=FUSO_EXIBICAO
        ).astimezone(timezone.utc)
    elif padrao is None:
        return None, None
    elif recorte in HORAS_RECORTE:
        inicio, fim = janela_fixa(padrao[0], padrao[1], HORAS_RECORTE[recorte])
    else:
        inicio, fim = padrao
    if fim < inicio:
        return None, "A data final precisa ser igual ou posterior à inicial."
    return (
        FiltroConsulta(
            inicio=inicio,
            fim=fim,
            station_ids=controles["estacoes"] or None,
            excluir_sinalizados=controles["excluir"],
            horas=None,
            dias_semana=None,
            indicador=controles["indicador"],
            escala=controles["escala"],
            limites_fixos=controles["limites"],
            limiar_cobertura=90.0,
            pintar_baixa_cobertura=controles["pintar_cobertura"],
            escopo="filtros",
        ),
        None,
    )


def _historico(configuracao, filtro: FiltroConsulta, resultado) -> None:
    rotulos = {}
    if not resultado.resumo.empty:
        for item in resultado.resumo[["station_id", "nome"]].drop_duplicates().itertuples(index=False):
            if item.station_id is None or (isinstance(item.station_id, float) and pd.isna(item.station_id)):
                continue
            nome = item.nome if isinstance(item.nome, str) and item.nome else item.station_id
            rotulos[item.station_id] = f"{nome} ({item.station_id})"
    opcoes = list(rotulos)
    if not opcoes:
        st.caption("Nenhuma estação no recorte.")
        return
    atual = st.session_state.get("estacao_historico")
    indice = opcoes.index(atual) if atual in opcoes else 0
    station_id = st.selectbox(
        "Abrir histórico",
        opcoes,
        index=indice,
        format_func=lambda chave: rotulos.get(chave, chave),
        key="estacao_historico",
    )
    historico = historico_estacao(configuracao, station_id, filtro.inicio, filtro.fim)
    if historico["mudou_localizacao"]:
        st.warning(
            "Esta estação mudou de localização no período. "
            "As observações de pontos diferentes não foram agregadas num único marcador."
        )
        st.dataframe(historico["versoes"], width="stretch", hide_index=True)
    snapshots = historico["snapshots"]
    if snapshots.empty:
        st.caption("Sem observações desta estação no período.")
        return
    grafico = snapshots.copy()
    grafico["bicicletas_disponiveis"] = pd.to_numeric(grafico["bicicletas_disponiveis"], errors="coerce")
    grafico = grafico.dropna(subset=["observado_em_local"])
    if not grafico.empty:
        st.caption("Eixo do gráfico em America/Sao_Paulo.")
        st.line_chart(grafico.set_index("observado_em_local")[["bicicletas_disponiveis"]])
    st.dataframe(snapshots, width="stretch", hide_index=True)
    st.dataframe(historico["intervalos"], width="stretch", hide_index=True)


def _eventos(painel: dict) -> None:
    eventos = painel.get("eventos") or []
    if not eventos:
        return
    with st.expander("Eventos recentes de qualidade", expanded=False):
        st.dataframe(pd.DataFrame(eventos), width="stretch", hide_index=True)


def _exportacao(configuracao, filtro: FiltroConsulta) -> None:
    st.caption(
        "A exportação cobre o recorte do mapa e da tabela. "
        "Filtros atuais: período e estações da barra lateral."
    )
    frequencia = st.radio("Camada temporal do GeoPackage", ["hora", "dia"], horizontal=True)
    geojson = st.checkbox("Gerar também o GeoJSON do resumo", value=True)
    escopo = st.radio("Recorte", ["filtros atuais", "todos os dados"], horizontal=True)
    if st.button("Exportar"):
        alvo_filtro = filtro
        if escopo == "todos os dados":
            alvo_filtro = filtro_de_tudo(configuracao, filtro)
            if alvo_filtro is None:
                st.error("Não há dados armazenados para exportar.")
                return
        alvo = consultar(configuracao, alvo_filtro)
        pasta = exportar(configuracao, alvo, frequencia_temporal=frequencia, gerar_geojson=geojson)
        st.success(f"Arquivos gravados em {pasta}")


def st_folium_compativel(mapa):
    from streamlit_folium import st_folium

    tentativas = [
        {"height": 680, "width": "stretch", "returned_objects": ["last_object_clicked"]},
        {"height": 680, "width": None, "returned_objects": ["last_object_clicked"]},
        {"height": 680, "width": None},
    ]
    ultimo_erro = None
    for argumentos in tentativas:
        try:
            return st_folium(mapa, **argumentos)
        except TypeError as exc:
            ultimo_erro = exc
    raise ultimo_erro


def _hora(valor) -> str:
    instante = analisar_instante(valor) if valor else None
    if instante is None:
        return "—"
    return para_exibicao(instante).strftime("%d/%m/%Y %H:%M:%S")


def _rotulo_estacao(opcoes: list[dict], station_id: str) -> str:
    for item in opcoes:
        if item["station_id"] == station_id:
            return f"{item['nome']} ({station_id})"
    return station_id


if __name__ == "__main__":
    main()
