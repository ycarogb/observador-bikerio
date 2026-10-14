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
    ler_painel,
    periodo_padrao,
)
from observador_bikerio.exportacao import exportar
from observador_bikerio.mapa import criar_mapa
from observador_bikerio.tempo import FUSO_EXIBICAO, analisar_instante, para_exibicao
from observador_bikerio.textos import (
    INDICADORES,
    NOTA_ATRIBUICAO,
    NOTA_COBERTURA,
    NOTA_COLETOR,
    NOTA_CORES,
    NOTA_INDICADORES,
    NOTA_PROXY,
    NOTA_TAXA,
)

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
COLUNAS_TABELA = {
    "nome": "Estação",
    "station_id": "Identificador",
    "id_cadastro": "Versão cadastral",
    "aumentos_observados": "Aumentos observados",
    "reducoes_observadas": "Reduções observadas",
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


def main() -> None:
    st.set_page_config(page_title="Observador Bike Rio", layout="wide")
    configuracao = carregar_configuracao()
    st.title("Observador Bike Rio")
    st.info(NOTA_INDICADORES)
    st.caption(NOTA_PROXY)
    filtro = _barra(configuracao)
    _conteudo(configuracao, filtro)


def _barra(configuracao) -> dict:
    painel = ler_painel(configuracao)
    with st.sidebar:
        st.header("Coletor")
        st.caption(NOTA_COLETOR)
        if painel["coletor_ativo"]:
            st.success("Coletor ativo")
        else:
            st.warning("Coletor inativo")
        estado = painel.get("estado") or {}
        st.write(f"Último batimento: {_hora(estado.get('ultimo_batimento_utc'))}")
        tentativa = painel.get("ultima_tentativa") or {}
        sucesso = painel.get("ultimo_sucesso") or {}
        st.write(f"Última tentativa: {_hora(tentativa.get('encerrada_em_utc'))} ({tentativa.get('resultado') or '—'})")
        st.write(f"Último sucesso: {_hora(sucesso.get('encerrada_em_utc'))} ({sucesso.get('resultado') or '—'})")
        periodo = painel.get("periodo") or {}
        st.write(f"Período armazenado: {_hora(periodo.get('inicio'))} — {_hora(periodo.get('fim'))}")
        st.caption("Esse intervalo usa os horários informados pela fonte e pode começar antes da coleta.")
        st.write(f"Estações no cadastro aberto: {painel.get('estacoes_abertas') or 0}")
        st.write(f"Snapshots: {periodo.get('snapshots') or 0}")
        fonte = painel.get("fonte") or {}
        if fonte:
            system_id = fonte.get("system_id") or "sem system_id"
            nome_feed = fonte.get("nome") or "sem nome no feed"
            st.caption(f"Fonte: {system_id} · nome no feed: {nome_feed} · {fonte.get('url_descoberta')}")
        st.header("Armazenamento")
        for nome, caminho in painel["caminhos"].items():
            st.text(f"{nome}\n{caminho}")
        st.header("Filtros")
        usar_tudo = st.checkbox("Usar o período das coletas", value=True)
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
            data_inicio = st.date_input("Data inicial", value=inicio_local.date(), disabled=usar_tudo)
            hora_inicio = st.time_input(
                "Hora inicial",
                value=inicio_local.replace(microsecond=0).time().replace(tzinfo=None),
                step=timedelta(seconds=1),
                disabled=usar_tudo,
            )
        with coluna_b:
            data_fim = st.date_input("Data final", value=fim_local.date(), disabled=usar_tudo)
            hora_fim = st.time_input(
                "Hora final",
                value=fim_local.replace(microsecond=0).time().replace(tzinfo=None),
                step=timedelta(seconds=1),
                disabled=usar_tudo,
            )
        indicador = st.selectbox(
            "Indicador do mapa",
            list(INDICADORES),
            format_func=lambda chave: INDICADORES[chave]["rotulo"],
        )
        opcoes = painel.get("opcoes_estacoes") or []
        estacoes = st.multiselect(
            "Estações",
            options=[item["station_id"] for item in opcoes],
            format_func=lambda station_id: _rotulo_estacao(opcoes, station_id),
            placeholder="Todas",
        )
        cobertura = st.slider("Cobertura mínima (%)", 0, 100, int(configuracao.limiar_cobertura_percentual))
        st.caption(NOTA_COBERTURA)
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
        restringir_hora = st.checkbox("Restringir horário do dia", value=False)
        hora_de = st.number_input("Hora inicial do dia", 0, 23, 7, disabled=not restringir_hora)
        hora_ate = st.number_input("Hora final do dia (exclusiva; 24 encerra o dia)", 0, 24, 10, disabled=not restringir_hora)
        dias = st.multiselect("Dias da semana", DIAS, default=DIAS)
        st.caption("A cobertura é recalculada só dentro dessas janelas.")
    return {
        "painel": painel,
        "usar_tudo": usar_tudo,
        "data_inicio": data_inicio,
        "hora_inicio": hora_inicio,
        "data_fim": data_fim,
        "hora_fim": hora_fim,
        "indicador": indicador,
        "estacoes": estacoes,
        "cobertura": cobertura,
        "excluir": excluir,
        "escala": escala,
        "limites": (float(vmin), float(vmax)) if limites else None,
        "restringir_hora": restringir_hora,
        "hora_de": int(hora_de),
        "hora_ate": int(hora_ate),
        "dias": dias,
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
    estado = "ativo" if painel["coletor_ativo"] else "inativo"
    st.caption(f"Coletor {estado}. Esta atualização leu apenas o banco local.")
    if painel.get("sintetica"):
        st.error("ESTES DADOS SÃO SINTÉTICOS E NÃO REPRESENTAM O BIKE RIO.")
    filtro, erro = _montar_filtro(configuracao, controles)
    if erro:
        st.warning(erro)
        return
    if filtro is None:
        st.warning("Ainda não há observações armazenadas para esta fonte.")
        return
    resultado = consultar(configuracao, filtro)
    if resultado.mensagem and resultado.resumo.empty:
        st.warning(resultado.mensagem)
    colunas = st.columns(4)
    colunas[0].metric("Estações no recorte", resultado.contagens["estacoes"])
    colunas[1].metric("Na escala de cores", resultado.contagens["na_escala"])
    colunas[2].metric("Sem classificação por qualidade", resultado.contagens["sem_classificacao"])
    soma = pd.to_numeric(resultado.resumo["movimentacao_observada"], errors="coerce").sum(min_count=1)
    colunas[3].metric("Soma da movimentação observada", "—" if pd.isna(soma) else f"{soma:.0f}")
    st.caption("Essa soma não é o total de viagens do sistema.")
    indicador = controles["indicador"]
    if (
        resultado.contagens["na_escala"] == 0
        and not pd.isna(soma)
        and INDICADORES[indicador]["aplica_cobertura"]
    ):
        st.info(
            "Há movimentação observada neste recorte, mas nenhuma estação atinge a cobertura mínima. "
            "Os valores permanecem na tabela. A escala de cores inclui a estação quando a cobertura chega ao limiar."
        )
    if resultado.mensagem:
        st.caption(resultado.mensagem)
    st.caption(NOTA_CORES)
    st.caption(NOTA_TAXA)
    st.caption(NOTA_ATRIBUICAO)
    periodo = f"{filtro.inicio.astimezone(FUSO_EXIBICAO):%d/%m/%Y %H:%M:%S} — {filtro.fim.astimezone(FUSO_EXIBICAO):%d/%m/%Y %H:%M:%S}"
    mapa = criar_mapa(resultado.resumo, resultado.legenda, periodo, bool(resultado.fonte.get("sintetica")))
    clique = st_folium_compativel(mapa)
    propriedades = ((clique or {}).get("last_object_clicked") or {}).get("properties") or {}
    if propriedades.get("station_id"):
        st.session_state["estacao_historico"] = propriedades["station_id"]
    st.subheader("Tabela do mapa")
    visivel = resultado.resumo.rename(columns=COLUNAS_TABELA)
    st.dataframe(visivel[list(COLUNAS_TABELA.values())], width="stretch", hide_index=True)
    _historico(configuracao, filtro, resultado)
    _eventos(painel)
    _exportacao(configuracao, filtro, resultado)


def _montar_filtro(configuracao, controles: dict):
    from observador_bikerio.indicadores import faixas_horarias

    if controles["usar_tudo"]:
        padrao = periodo_padrao(configuracao)
        if padrao is None:
            return None, None
        inicio, fim = padrao
    else:
        inicio = datetime.combine(
            controles["data_inicio"], controles["hora_inicio"], tzinfo=FUSO_EXIBICAO
        ).astimezone(timezone.utc)
        fim = datetime.combine(
            controles["data_fim"], controles["hora_fim"], tzinfo=FUSO_EXIBICAO
        ).astimezone(timezone.utc)
    if fim < inicio:
        return None, "A data final precisa ser igual ou posterior à inicial."
    try:
        horas = faixas_horarias(controles["hora_de"], controles["hora_ate"]) if controles["restringir_hora"] else None
    except ValueError as exc:
        return None, str(exc)
    dias = {DIAS.index(dia) for dia in controles["dias"]}
    if not dias:
        return None, "Selecione ao menos um dia da semana."
    dias_filtro = None if dias == set(range(7)) else dias
    return (
        FiltroConsulta(
            inicio=inicio,
            fim=fim,
            station_ids=controles["estacoes"] or None,
            excluir_sinalizados=controles["excluir"],
            horas=horas,
            dias_semana=dias_filtro,
            indicador=controles["indicador"],
            escala=controles["escala"],
            limites_fixos=controles["limites"],
            limiar_cobertura=float(controles["cobertura"]),
            escopo="filtros",
        ),
        None,
    )


def _historico(configuracao, filtro: FiltroConsulta, resultado) -> None:
    st.subheader("Histórico da estação")
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
        st.line_chart(grafico.set_index("observado_em_local")[["bicicletas_disponiveis"]])
    st.dataframe(snapshots, width="stretch", hide_index=True)
    st.dataframe(historico["intervalos"], width="stretch", hide_index=True)


def _eventos(painel: dict) -> None:
    eventos = painel.get("eventos") or []
    if not eventos:
        return
    st.subheader("Eventos recentes de qualidade")
    st.dataframe(pd.DataFrame(eventos), width="stretch", hide_index=True)


def _exportacao(configuracao, filtro: FiltroConsulta, resultado) -> None:
    st.subheader("Exportação para SIG-T")
    frequencia = st.radio("Camada temporal do GeoPackage", ["hora", "dia"], horizontal=True)
    geojson = st.checkbox("Gerar também o GeoJSON do resumo", value=True)
    escopo = st.radio("Recorte", ["filtros atuais", "todos os dados"], horizontal=True)
    if st.button("Exportar"):
        alvo = resultado
        if escopo == "todos os dados":
            completo = filtro_de_tudo(configuracao, filtro)
            if completo is None:
                st.error("Não há dados armazenados para exportar.")
                return
            alvo = consultar(configuracao, completo)
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
