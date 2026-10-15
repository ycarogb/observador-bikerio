"""Regras puras de indicador, cobertura, fuso e cor. Dados sintéticos."""

from datetime import datetime, timedelta, timezone

import pytest

from observador_bikerio.cores import aplicar_visual, posicao
from observador_bikerio.indicadores import (
    MOTIVO_LACUNA,
    MOTIVO_MUDANCA_CADASTRO,
    MOTIVO_MUDANCA_FONTE,
    MOTIVO_OPERACIONAL,
    MOTIVO_TIMESTAMPS,
    MOTIVO_VALOR_AUSENTE,
    agregar_temporal,
    avaliar_par,
    construir_janelas,
    duracao_janelas,
    montar_resumo,
    segundos_cobertos,
)
from observador_bikerio.normalizador import normalizar_informacao, normalizar_dados_estacao
from observador_bikerio.consulta import janela_fixa
from observador_bikerio.tempo import FUSO_EXIBICAO, para_grafico
from observador_bikerio.textos import (
    COR_COBERTURA_INSUFICIENTE,
    COR_SEM_DADOS,
    COR_STATUS_DESATUALIZADO,
    PALETAS,
)

LIMITE = 180
LIMIAR = 10


def par(estacao=1, fonte=1, bikes=5, segundos=0, instalada=True, alugando=True, devolvendo=True, versao="3.0"):
    base = datetime(2026, 5, 10, 15, 0, tzinfo=timezone.utc)
    return {
        "fonte_id": fonte,
        "estacao_id": estacao,
        "bicicletas": bikes,
        "last_reported": base + timedelta(seconds=segundos),
        "coletado": base + timedelta(seconds=segundos),
        "instalada": instalada,
        "alugando": alugando,
        "devolvendo": devolvendo,
        "flags": set(),
        "versao_gbfs": versao,
    }


def test_aumento_reducao_e_estabilidade():
    aumento = avaliar_par(par(bikes=5), par(bikes=8, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert aumento["comparavel"] is True
    assert aumento["delta"] == 3
    assert aumento["aumento_observado"] == 3
    assert aumento["reducao_observada"] == 0
    assert aumento["movimentacao_observada"] == 3

    reducao = avaliar_par(par(bikes=10), par(bikes=6, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert reducao["aumento_observado"] == 0
    assert reducao["reducao_observada"] == 4
    assert reducao["movimentacao_observada"] == 4

    estavel = avaliar_par(par(bikes=4), par(bikes=4, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert estavel["comparavel"] is True
    assert estavel["movimentacao_observada"] == 0
    assert estavel["motivo"] is None


def test_passo_de_tres_minutos_respeita_o_limite_de_lacuna():
    dentro = avaliar_par(
        par(bikes=5),
        par(bikes=7, segundos=182),
        limite_lacuna_segundos=900,
        limiar_intervencao_bicicletas=LIMIAR,
    )
    assert dentro["comparavel"] is True
    assert dentro["movimentacao_observada"] == 2
    assert dentro["motivo"] is None

    fora = avaliar_par(
        par(bikes=5),
        par(bikes=7, segundos=182),
        limite_lacuna_segundos=180,
        limiar_intervencao_bicicletas=LIMIAR,
    )
    assert fora["comparavel"] is False
    assert fora["motivo"] == MOTIVO_LACUNA
    assert fora["movimentacao_observada"] is None


def test_lacuna_timestamps_valor_ausente_e_mudancas():
    lacuna = avaliar_par(par(), par(segundos=600), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert lacuna["comparavel"] is False
    assert lacuna["motivo"] == MOTIVO_LACUNA
    assert lacuna["movimentacao_observada"] is None
    assert lacuna["duracao_segundos"] == 600

    invertido = avaliar_par(par(segundos=60), par(segundos=0), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert invertido["motivo"] == MOTIVO_TIMESTAMPS
    assert invertido["movimentacao_observada"] is None

    ausente = avaliar_par(par(bikes=None), par(bikes=None, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert ausente["motivo"] == MOTIVO_VALOR_AUSENTE
    assert ausente["delta"] is None

    fonte = avaliar_par(par(fonte=1), par(fonte=2, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert fonte["motivo"] == MOTIVO_MUDANCA_FONTE

    cadastro = avaliar_par(par(estacao=1), par(estacao=2, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert cadastro["motivo"] == MOTIVO_MUDANCA_CADASTRO
    assert cadastro["movimentacao_observada"] is None

    fora = avaliar_par(par(instalada=False), par(instalada=False, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert fora["motivo"] == MOTIVO_OPERACIONAL

    operacional = avaliar_par(par(alugando=True), par(alugando=False, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert operacional["comparavel"] is True
    assert "mudanca_operacional" in operacional["flags"]

    grande = avaliar_par(par(bikes=0), par(bikes=10, segundos=60), limite_lacuna_segundos=LIMITE, limiar_intervencao_bicicletas=LIMIAR)
    assert grande["comparavel"] is True
    assert grande["movimentacao_observada"] == 10
    assert "possivel_intervencao" in grande["flags"]


def test_campo_ausente_nao_vira_zero_e_nome_em_portugues():
    status = normalizar_dados_estacao({"station_id": "7", "is_installed": True, "last_reported": "2026-05-10T15:00:00Z"})
    assert status is not None
    assert status.bicicletas_disponiveis is None
    assert status.vagas_disponiveis is None
    negativo = normalizar_dados_estacao({"station_id": "7", "num_vehicles_available": -1, "last_reported": "2026-05-10T15:00:00Z"})
    assert negativo.bicicletas_disponiveis is None
    assert "valor_invalido" in negativo.flags
    cadastro = normalizar_informacao(
        {
            "station_id": "7",
            "name": [{"language": "en", "text": "English"}, {"language": "pt", "text": "Estação sintética"}],
            "lat": -22.9,
            "lon": -43.2,
        }
    )
    assert cadastro.nome == "Estação sintética"
    assert cadastro.capacidade is None


def test_cobertura_de_horario_e_dia_da_semana():
    dia = datetime(2026, 5, 11, tzinfo=FUSO_EXIBICAO)
    while dia.weekday() != 0:
        dia += timedelta(days=1)
    inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=2)
    janelas = construir_janelas(inicio, fim, [(7, 9)], {0})
    assert duracao_janelas(janelas) == pytest.approx(2 * 3600)

    segunda = datetime.combine(inicio.date(), datetime.min.time(), tzinfo=FUSO_EXIBICAO).replace(hour=7, minute=30)
    terca = segunda + timedelta(days=1)
    intervalos = [
        _intervalo(1, segunda, segunda + timedelta(hours=1), 4),
        _intervalo(1, terca, terca + timedelta(hours=1), 9),
    ]
    estacoes = [_estacao(1)]
    linhas, anotados = montar_resumo(
        estacoes,
        intervalos,
        [],
        janelas,
        excluir_sinalizados=False,
        limiar_cobertura=90,
        limite_desatualizado_segundos=600,
        fim_periodo=fim.astimezone(timezone.utc),
    )
    assert linhas[0]["movimentacao_observada"] == 4
    assert linhas[0]["cobertura_percentual"] == pytest.approx(50)
    assert linhas[0]["horas_validas"] == pytest.approx(1)
    assert sum(item["incluido_no_resumo"] for item in anotados) == 1


def test_janela_fixa_recorta_as_ultimas_horas_sem_passar_do_inicio():
    inicio = datetime(2026, 10, 14, 21, 7, tzinfo=timezone.utc)
    fim = datetime(2026, 10, 14, 23, 7, tzinfo=timezone.utc)
    uma = janela_fixa(inicio, fim, 1)
    assert uma == (fim - timedelta(hours=1), fim)
    dia = janela_fixa(inicio, fim, 24)
    assert dia == (inicio, fim)


def test_grafico_usa_relogio_de_sao_paulo_nao_utc():
    ponto = para_grafico("2026-10-14T21:00:00.000+00:00")
    assert ponto is not None
    assert ponto.tzinfo is None
    assert ponto.hour == 18
    assert ponto.day == 14


def test_fuso_de_sao_paulo_no_agregado():
    inicio = datetime(2026, 1, 15, 1, 30, tzinfo=timezone.utc)
    fim = datetime(2026, 1, 15, 2, 30, tzinfo=timezone.utc)
    janelas = [(inicio, fim)]
    intervalo = _intervalo(1, inicio, fim, 2)
    intervalo["incluido_no_resumo"] = True
    linhas = agregar_temporal([_estacao(1)], [intervalo], janelas, "hora")
    assert linhas
    assert any("T23:00:00-03:00" in linha["inicio_periodo_local"] for linha in linhas)
    dias = agregar_temporal([_estacao(1)], [intervalo], janelas, "dia")
    assert dias[0]["inicio_periodo_local"].startswith("2026-01-14")
    assert dias[0]["movimentacao_observada"] == 2


def test_intervalo_que_cruza_a_hora_soma_o_mesmo_total():
    inicio = datetime(2026, 5, 10, 13, 50, tzinfo=timezone.utc)
    fim = datetime(2026, 5, 10, 14, 10, tzinfo=timezone.utc)
    janelas = [(inicio, fim)]
    intervalo = _intervalo(1, inicio, fim, 2)
    intervalo["aumento_observado"] = 2
    intervalo["reducao_observada"] = 0
    linhas, anotados = montar_resumo(
        [_estacao(1)],
        [intervalo],
        [],
        janelas,
        excluir_sinalizados=False,
        limiar_cobertura=90,
        limite_desatualizado_segundos=600,
        fim_periodo=fim,
    )
    temporal = agregar_temporal([_estacao(1)], anotados, janelas, "hora")
    assert sum(item["movimentacao_observada"] for item in temporal) == linhas[0]["movimentacao_observada"]
    assert sum(item["horas_validas"] for item in temporal) == pytest.approx(linhas[0]["horas_validas"])


def test_uniao_nao_conta_sobreposicao_duas_vezes():
    base = datetime(2026, 5, 10, 12, tzinfo=timezone.utc)
    janela = [(base, base + timedelta(hours=1))]
    trechos = [
        (base, base + timedelta(minutes=30)),
        (base + timedelta(minutes=20), base + timedelta(minutes=50)),
    ]
    assert segundos_cobertos(trechos, janela) == pytest.approx(50 * 60)


def test_cores_de_zero_sem_dados_baixa_cobertura_e_valores_iguais():
    zero = _linha_visual(0, 100, 1)
    sem_dados = _linha_visual(None, 0, 0)
    baixa = _linha_visual(4, 10, 1)
    info = aplicar_visual([zero, sem_dados, baixa], "movimentacao_observada", escala="linear", limiar_cobertura=90)
    assert zero["categoria"] == "zero_movimentacao"
    assert sem_dados["categoria"] == "sem_intervalos_validos"
    assert baixa["categoria"] == "cobertura_insuficiente"
    assert zero["cor"] != sem_dados["cor"]
    assert baixa["cor"] == COR_COBERTURA_INSUFICIENTE
    assert sem_dados["cor"] == COR_SEM_DADOS
    assert zero["cor"] != COR_COBERTURA_INSUFICIENTE
    assert info["na_escala"] == 1
    assert info["sem_classificacao"] == 2

    aplicar_visual(
        [baixa],
        "movimentacao_observada",
        escala="linear",
        limiar_cobertura=90,
        pintar_baixa_cobertura=False,
    )
    assert baixa["categoria"] == "cobertura_insuficiente"
    assert baixa["cor"] != COR_COBERTURA_INSUFICIENTE
    assert baixa["cor"] != COR_SEM_DADOS

    iguais = [_linha_visual(5, 100, 1), _linha_visual(5, 100, 1)]
    info_igual = aplicar_visual(iguais, "movimentacao_observada", escala="linear", limiar_cobertura=90)
    assert iguais[0]["cor"] == iguais[1]["cor"]
    assert info_igual["valores_iguais"] is True

    zeros = [_linha_visual(0, 100, 1), _linha_visual(0, 100, 1)]
    aplicar_visual(zeros, "movimentacao_observada", escala="linear", limiar_cobertura=90)
    assert zeros[0]["cor"] == PALETAS["movimento"][0]

    desatualizado = {
        "latitude": -22.9,
        "longitude": -43.2,
        "bicicletas_disponiveis": 0,
        "status_desatualizado": True,
        "intervalos_validos": 0,
        "cobertura_percentual": 0,
    }
    aplicar_visual([desatualizado], "bicicletas_disponiveis", escala="linear", limiar_cobertura=90)
    assert desatualizado["categoria"] == "status_desatualizado"
    assert desatualizado["cor"] == COR_STATUS_DESATUALIZADO


def test_log1p_preserva_a_posicao_e_nao_altera_o_valor_original():
    assert posicao(0, 0, 10, "log1p") == 0
    meio = posicao(pytest.importorskip("math").expm1(0.5), 0, pytest.importorskip("math").expm1(1), "log1p")
    assert meio == pytest.approx(0.5)
    linha = _linha_visual(3, 100, 1)
    aplicar_visual([linha], "movimentacao_observada", escala="log1p", limiar_cobertura=90)
    assert linha["valor_indicador"] == 3


def _estacao(identificador: int) -> dict:
    return {
        "id": identificador,
        "station_id": "A",
        "nome": "Estação sintética",
        "latitude": -22.9,
        "longitude": -43.2,
        "capacidade": 10,
    }


def _intervalo(identificador: int, inicio: datetime, fim: datetime, movimento: int) -> dict:
    return {
        "station_id": "A",
        "estacao_id_inicio": identificador,
        "estacao_id_fim": identificador,
        "inicio": inicio.astimezone(timezone.utc),
        "fim": fim.astimezone(timezone.utc),
        "aumento_observado": movimento,
        "reducao_observada": 0,
        "movimentacao_observada": movimento,
        "comparavel": True,
        "flags": set(),
        "motivo": None,
    }


def _linha_visual(movimento, cobertura, intervalos):
    return {
        "latitude": -22.9,
        "longitude": -43.2,
        "movimentacao_observada": movimento,
        "aumentos_observados": movimento,
        "reducoes_observadas": 0,
        "taxa_por_hora_valida": movimento,
        "cobertura_percentual": cobertura,
        "intervalos_validos": intervalos,
        "bicicletas_disponiveis": 1,
        "status_desatualizado": False,
    }
