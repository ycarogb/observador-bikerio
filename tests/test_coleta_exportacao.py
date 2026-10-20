"""Coleta sintética isolada, backup e exportação. Não grava na base real."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest

from observador_bikerio.backup import gerar_backup
from observador_bikerio.banco import conectar, consultar_sql
from observador_bikerio.consulta import FiltroConsulta, consultar, totais_do_periodo
from observador_bikerio.coletor import coletar_uma_vez, espera_ate_proximo
from observador_bikerio.exportacao import exportar
from observador_bikerio.fonte_gbfs import ClienteGbfs, ErroFonte, descobrir_feeds
from observador_bikerio.mapa import montar_geojson
from observador_bikerio.textos import COR_COBERTURA_INSUFICIENTE, COR_SEM_DADOS, PALETAS
from observador_bikerio.trava import ColetorJaEmExecucao, TravaColetor
from tests.apoio import (
    T0,
    ClienteFalso,
    cadastral,
    configuracao_sintetica,
    descoberta,
    info,
    sistema,
    situacao,
    status,
)

RAIZ = Path(__file__).resolve().parents[1]


def _cliente(config, documentos_status, documentos_info):
    return ClienteFalso(
        {
            config.url_indice_gbfs: descoberta(),
            "sintetico://system_information": sistema(),
            "sintetico://station_information": documentos_info,
            "sintetico://station_status": documentos_status,
        }
    )


def _cadastro_base():
    return [
        cadastral("A", "Estação sintética A", -22.90, -43.20),
        cadastral("B", "Estação sintética B", -22.91, -43.21),
        cadastral("C", "Estação sintética C", -22.92, -43.22),
        cadastral("D", "Estação sintética D", -22.93, -43.23),
        cadastral("E", "Estação sintética E", -22.94, -43.24),
    ]


def _status_inicial():
    return [
        situacao("A", 5, 0),
        situacao("B", 4, 0),
        situacao("C", 10, 0),
        situacao("D", 7, 0),
        situacao("E", None, 0, omitir_bicicletas=True),
    ]


def _status_seguinte():
    return [
        situacao("A", 8, 60),
        situacao("B", 4, 60),
        situacao("C", 6, 60),
        situacao("E", None, 60, omitir_bicicletas=True),
    ]


def test_coleta_sintetica_movimento_repeticao_lacuna_e_ausencia(tmp_path):
    config = configuracao_sintetica(tmp_path)
    assert config.caminho_banco.is_relative_to(tmp_path)
    cliente = _cliente(
        config,
        [
            status(_status_inicial(), 0),
            status(_status_inicial(), 0),
            status(_status_seguinte(), 60),
        ],
        info(_cadastro_base()),
    )
    primeiro = coletar_uma_vez(config, cliente=cliente, agora=T0)
    assert primeiro.sucesso
    assert primeiro.observacoes_novas == 5
    with conectar(config.caminho_banco) as conexao:
        antes = consultar_sql(conexao, "SELECT COUNT(*) AS total FROM snapshots")[0]["total"]
        estacao_e = consultar_sql(conexao, "SELECT bicicletas_disponiveis FROM snapshots WHERE station_id = 'E'")[0]
        assert estacao_e["bicicletas_disponiveis"] is None
        assert consultar_sql(conexao, "SELECT COUNT(*) AS total FROM intervalos")[0]["total"] == 0
    repetido = coletar_uma_vez(config, cliente=cliente, agora=T0)
    assert repetido.observacoes_novas == 0
    assert repetido.resultado == "resposta_repetida"
    with conectar(config.caminho_banco) as conexao:
        assert consultar_sql(conexao, "SELECT COUNT(*) AS total FROM snapshots")[0]["total"] == antes

    segundo = coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=60))
    assert segundo.observacoes_novas == 4
    with conectar(config.caminho_banco) as conexao:
        eventos = consultar_sql(conexao, "SELECT * FROM eventos WHERE tipo = 'desaparecimento'")
        assert any(item["station_id"] == "D" for item in eventos)
        estacao_d = consultar_sql(conexao, "SELECT bicicletas_disponiveis FROM snapshots WHERE station_id = 'D'")
        assert len(estacao_d) == 1
        assert estacao_d[0]["bicicletas_disponiveis"] == 7
    bruto = config.pasta_base / primeiro.arquivos_brutos[0]
    with gzip.open(bruto, "rt", encoding="utf-8") as arquivo:
        assert json.load(arquivo)

    resultado = consultar(config, _filtro(T0, T0 + timedelta(seconds=60)))
    assert resultado.fonte["sintetica"] is True
    por_estacao = resultado.resumo.set_index("station_id")
    assert int(por_estacao.loc["A", "aumentos_observados"]) == 3
    assert int(por_estacao.loc["A", "reducoes_observadas"]) == 0
    assert int(por_estacao.loc["A", "movimentacao_observada"]) == 3
    assert int(por_estacao.loc["B", "movimentacao_observada"]) == 0
    assert int(por_estacao.loc["C", "reducoes_observadas"]) == 4
    assert pd.isna(por_estacao.loc["D", "movimentacao_observada"])
    assert pd.isna(por_estacao.loc["E", "movimentacao_observada"])
    assert por_estacao.loc["B", "categoria"] == "zero_movimentacao"
    assert por_estacao.loc["D", "categoria"] == "sem_intervalos_validos"
    assert por_estacao.loc["B", "cor"] == PALETAS["movimento"][0]
    assert por_estacao.loc["D", "cor"] == COR_SEM_DADOS
    assert int(resultado.horas.loc[resultado.horas.station_id == "A", "movimentacao_observada"].sum()) == 3

    longa = consultar(config, _filtro(T0, T0 + timedelta(hours=1)))
    longa_por_estacao = longa.resumo.set_index("station_id")
    assert longa_por_estacao.loc["A", "categoria"] == "cobertura_insuficiente"
    assert longa_por_estacao.loc["A", "cor"] == COR_COBERTURA_INSUFICIENTE
    assert longa_por_estacao.loc["D", "cor"] == COR_SEM_DADOS
    assert longa_por_estacao.loc["A", "cor"] != longa_por_estacao.loc["D", "cor"]

    pasta = exportar(config, resultado, frequencia_temporal="hora", gerar_geojson=True)
    parquet = pd.read_parquet(pasta / "resumo_periodo.parquet")
    assert int(parquet.loc[parquet.station_id == "A", "movimentacao_observada"].iloc[0]) == int(por_estacao.loc["A", "movimentacao_observada"])
    assert int(parquet.loc[parquet.station_id == "B", "movimentacao_observada"].iloc[0]) == 0
    assert pd.isna(parquet.loc[parquet.station_id == "D", "movimentacao_observada"].iloc[0])
    import geopandas as gpd

    camada = gpd.read_file(pasta / "bikerio.gpkg", layer="indicadores_periodo")
    assert camada.crs.to_epsg() == 4326
    ponto = camada.loc[camada.station_id == "A"].iloc[0]
    assert ponto.geometry.x == pytest.approx(-43.20)
    assert ponto.geometry.y == pytest.approx(-22.90)
    assert int(ponto.movimentacao_observada) == 3
    assert "2026-05-10" in str(ponto.inicio_periodo_utc)
    assert "12:00:00" in str(ponto.inicio_periodo_local)
    cadastro = gpd.read_file(pasta / "bikerio.gpkg", layer="cadastro_estacoes")
    assert not cadastro.empty
    temporal = gpd.read_file(pasta / "bikerio.gpkg", layer="serie_estacao_hora")
    assert int(temporal.loc[temporal.station_id == "A", "movimentacao_observada"].sum()) == 3
    metadados = json.loads((pasta / "metadados.json").read_text(encoding="utf-8"))
    assert metadados["fonte"]["sintetica"] is True
    assert metadados["crs"] == "EPSG:4326"
    assert "não correspondem necessariamente ao número real de viagens" in " ".join(metadados["limitacoes"])
    colecao = montar_geojson(resultado.resumo)
    coordenadas = colecao["features"][0]["geometry"]["coordinates"]
    assert coordenadas[0] == pytest.approx(float(resultado.resumo.iloc[0]["longitude"]))
    assert coordenadas[1] == pytest.approx(float(resultado.resumo.iloc[0]["latitude"]))

    copia = gerar_backup(config)
    with conectar(copia) as conexao:
        assert consultar_sql(conexao, "SELECT COUNT(*) AS total FROM snapshots")[0]["total"] == 9


def _coleta_com_casos_de_qualidade(config):
    """A: movimento, lacuna e possível intervenção. B: muda de lugar. C: some do feed e volta."""
    instantes = (0, 60, 120, 600, 660, 720)
    estoques = {
        "A": (5, 8, 2, 4, 20, 18),
        "B": (4, 4, 6, 6, 7, 7),
        "C": (10, 10, 9, 9, None, 11),
    }
    documentos = [
        status(
            [
                situacao(station_id, valores[posicao], segundos)
                for station_id, valores in estoques.items()
                if valores[posicao] is not None
            ],
            segundos,
        )
        for posicao, segundos in enumerate(instantes)
    ]
    cadastro_antigo = [
        cadastral("A", "A", -22.90, -43.20),
        cadastral("B", "B", -22.91, -43.21),
        cadastral("C", "C", -22.92, -43.22),
    ]
    cadastro_novo = [cadastro_antigo[0], cadastral("B", "B", -22.95, -43.30), cadastro_antigo[2]]
    cliente = _cliente(
        config,
        documentos,
        [info(cadastro_antigo), info(cadastro_antigo), info(cadastro_novo)],
    )
    for segundos in instantes:
        coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=segundos))


@pytest.mark.parametrize("excluir", [False, True])
@pytest.mark.parametrize(
    ("inicio", "fim", "estacoes"),
    [
        (0, 720, None),
        (30, 720, None),
        (90, 660, ["A", "B"]),
        (600, 600, None),
    ],
)
def test_mapa_sem_exportacao_tem_o_mesmo_resumo(tmp_path, excluir, inicio, fim, estacoes):
    config = configuracao_sintetica(tmp_path, intervalo_cadastro_segundos=0)
    _coleta_com_casos_de_qualidade(config)
    filtro = _filtro(T0 + timedelta(seconds=inicio), T0 + timedelta(seconds=fim))
    filtro.excluir_sinalizados = excluir
    filtro.station_ids = estacoes

    completo = consultar(config, filtro)
    mapa = consultar(config, filtro, com_exportacao=False)

    pd.testing.assert_frame_equal(mapa.resumo, completo.resumo, check_exact=False, rtol=1e-12)
    assert mapa.contagens == completo.contagens
    assert not completo.snapshots.empty and not completo.intervalos.empty
    assert mapa.snapshots.empty and mapa.intervalos.empty and mapa.horas.empty and mapa.dias.empty


def test_cenario_de_qualidade_exercita_lacuna_intervencao_e_mudanca(tmp_path):
    config = configuracao_sintetica(tmp_path, intervalo_cadastro_segundos=0)
    _coleta_com_casos_de_qualidade(config)
    filtro = _filtro(T0, T0 + timedelta(seconds=720))

    resumo = consultar(config, filtro, com_exportacao=False).resumo
    a = resumo.loc[resumo.station_id == "A"].iloc[0]
    assert int(a["quantidade_lacunas"]) == 1
    assert "possivel_intervencao" in a["flags_qualidade"]
    assert int(a["movimentacao_observada"]) == 3 + 6 + 16 + 2
    assert "mudanca_cadastral" in ",".join(resumo.loc[resumo.station_id == "B", "flags_qualidade"])
    estoques = {
        (linha.station_id, linha.latitude): int(linha.bicicletas_disponiveis)
        for linha in resumo.itertuples()
    }
    assert estoques == {("A", -22.90): 18, ("B", -22.91): 4, ("B", -22.95): 7, ("C", -22.92): 11}
    assert totais_do_periodo(resumo) == {
        "estacoes": 3,
        "bicicletas": 18 + 7 + 11,
        "retiradas": 6 + 2 + 1,
        "devolucoes": 3 + 16 + 1 + 2,
    }

    filtro.excluir_sinalizados = True
    sem_sinalizados = consultar(config, filtro, com_exportacao=False).resumo
    a = sem_sinalizados.loc[sem_sinalizados.station_id == "A"].iloc[0]
    assert int(a["movimentacao_observada"]) == 3 + 6 + 2
    assert "intervalos_sinalizados_excluidos" in a["flags_qualidade"]


def test_lacuna_excessiva_nao_inventa_movimento(tmp_path):
    config = configuracao_sintetica(tmp_path)
    documentos = [
        status([situacao("A", 5, 0)], 0),
        status([situacao("A", 9, 60)], 60),
        status([situacao("A", 12, 600)], 600),
    ]
    cliente = _cliente(config, documentos, info([cadastral("A", "A", -22.9, -43.2)]))
    coletar_uma_vez(config, cliente=cliente, agora=T0)
    coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=60))
    coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=600))
    with conectar(config.caminho_banco) as conexao:
        lacunas = consultar_sql(conexao, "SELECT * FROM intervalos WHERE motivo = 'lacuna_excessiva'")
    assert len(lacunas) == 1
    assert lacunas[0]["movimentacao_observada"] is None
    assert lacunas[0]["duracao_segundos"] == 540


def test_mudanca_de_localizacao_nao_agrega_no_mesmo_ponto(tmp_path):
    config = configuracao_sintetica(tmp_path, intervalo_cadastro_segundos=0)
    informacoes = [
        info([cadastral("B", "Estação sintética B", -22.91, -43.21)]),
        info([cadastral("B", "Estação sintética B", -22.95, -43.30)]),
    ]
    documentos = [
        status([situacao("B", 4, 0)], 0),
        status([situacao("B", 4, 60)], 60),
    ]
    cliente = _cliente(config, documentos, informacoes)
    coletar_uma_vez(config, cliente=cliente, agora=T0)
    coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=60))
    with conectar(config.caminho_banco) as conexao:
        versoes = consultar_sql(conexao, "SELECT latitude, longitude, valido_ate_utc FROM estacoes WHERE station_id = 'B' ORDER BY id")
        intervalo = consultar_sql(conexao, "SELECT motivo, comparavel, movimentacao_observada FROM intervalos")[0]
    assert len(versoes) == 2
    assert versoes[0]["latitude"] != versoes[1]["latitude"]
    assert versoes[0]["valido_ate_utc"] is not None
    assert intervalo["motivo"] == "mudanca_cadastral"
    assert intervalo["comparavel"] == 0
    assert intervalo["movimentacao_observada"] is None
    resultado = consultar(config, _filtro(T0, T0 + timedelta(seconds=60)))
    assert resultado.resumo["latitude"].nunique() == 2


def test_renomear_nao_cria_outra_localizacao(tmp_path):
    config = configuracao_sintetica(tmp_path, intervalo_cadastro_segundos=0)
    informacoes = [
        info([cadastral("B", "Nome antigo", -22.91, -43.21)]),
        info([cadastral("B", "Nome novo", -22.91, -43.21)]),
    ]
    documentos = [status([situacao("B", 1, 0)], 0), status([situacao("B", 1, 60)], 60)]
    cliente = _cliente(config, documentos, informacoes)
    coletar_uma_vez(config, cliente=cliente, agora=T0)
    coletar_uma_vez(config, cliente=cliente, agora=T0 + timedelta(seconds=60))
    with conectar(config.caminho_banco) as conexao:
        versoes = consultar_sql(conexao, "SELECT nome, valido_ate_utc FROM estacoes")
    assert len(versoes) == 1
    assert versoes[0]["nome"] == "Nome novo"
    assert versoes[0]["valido_ate_utc"] is None


def test_trava_impede_duplicata_e_reassume_pid_morto(tmp_path):
    trava = tmp_path / "coletor.lock"
    with TravaColetor(trava):
        with pytest.raises(ColetorJaEmExecucao):
            with TravaColetor(trava):
                pass
    assert not trava.exists()
    processo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        trava.mkdir()
        (trava / "pid").write_text(str(processo.pid), encoding="utf-8")
        with pytest.raises(ColetorJaEmExecucao):
            with TravaColetor(trava):
                pass
    finally:
        processo.kill()
        processo.wait(timeout=10)
    with TravaColetor(trava):
        assert (trava / "pid").read_text(encoding="utf-8") == str(__import__("os").getpid())


def test_espera_respeita_ttl_e_retry_after():
    assert espera_ate_proximo(0, 60, 13) == 60
    assert espera_ate_proximo(0, 5, 13) == 13
    assert espera_ate_proximo(4, 5, 13) == 9
    chamadas = {"n": 0}

    def responder(_requisicao):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"ok": True, "data": {}})

    config = configuracao_sintetica(Path.cwd() / "nao-usar")
    cliente = ClienteGbfs(config, transporte=httpx.MockTransport(responder), dormir=lambda _segundos: None)
    try:
        assert cliente.obter_json("https://exemplo.test/gbfs")["ok"] is True
    finally:
        cliente.fechar()
    assert chamadas["n"] == 2
    with pytest.raises(ErroFonte):
        descobrir_feeds({"data": {"feeds": []}, "version": "3.0"})


def test_periodo_da_coleta_usa_so_intervalos_comparaveis(tmp_path):
    from observador_bikerio.banco import inicializar, inserir_fonte, periodo_da_coleta

    config = configuracao_sintetica(tmp_path)
    with conectar(config.caminho_banco) as conexao:
        inicializar(conexao)
        fonte_id = inserir_fonte(
            conexao,
            url_indice_gbfs="sintetico://gbfs.json",
            system_id="sintetico",
            nome="t",
            versao_gbfs="3.0",
            fuso="America/Sao_Paulo",
            sintetica=True,
            criada_em_utc="2026-10-14T12:43:00Z",
        )
        conexao.execute(
            "INSERT INTO estacoes (fonte_id, station_id, valido_desde_utc) VALUES (?, 'A', ?)",
            (fonte_id, "2026-10-14T12:43:00Z"),
        )
        estacao_id = int(conexao.execute("SELECT id FROM estacoes").fetchone()[0])
        conexao.execute(
            """
            INSERT INTO snapshots (
                fonte_id, estacao_id, station_id, coletado_em_utc, flags_qualidade, chave_observacao
            ) VALUES (?, ?, 'A', '2026-10-14T12:43:00Z', '[]', 'manha')
            """,
            (fonte_id, estacao_id),
        )
        conexao.execute(
            """
            INSERT INTO snapshots (
                fonte_id, estacao_id, station_id, coletado_em_utc, flags_qualidade, chave_observacao
            ) VALUES (?, ?, 'A', '2026-10-14T21:10:00Z', '[]', 'noite')
            """,
            (fonte_id, estacao_id),
        )
        conexao.execute(
            """
            INSERT INTO intervalos (
                fonte_id, station_id, snapshot_anterior_id, snapshot_atual_id,
                inicio_utc, fim_utc, comparavel, flags_qualidade
            ) VALUES (?, 'A', 1, 2, '2026-10-14T21:07:00Z', '2026-10-14T21:10:00Z', 1, '[]')
            """,
            (fonte_id,),
        )
        periodo = periodo_da_coleta(conexao, fonte_id)
    assert periodo["inicio"].startswith("2026-10-14T21:07")
    assert periodo["fim"].startswith("2026-10-14T21:10")


def test_banco_nao_apaga_snapshots():
    texto = (RAIZ / "observador_bikerio" / "banco.py").read_text(encoding="utf-8")
    assert "DELETE FROM" not in texto


def _filtro(inicio, fim) -> FiltroConsulta:
    return FiltroConsulta(
        inicio=inicio,
        fim=fim,
        indicador="movimentacao_observada",
        limiar_cobertura=90,
        pintar_baixa_cobertura=True,
        escopo="filtros",
    )
