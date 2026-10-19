"""SQLite local: cadastro versionado, snapshots, intervalos, tentativas e batimento."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from observador_bikerio.tempo import agora_utc, formatar_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS fontes (
    id INTEGER PRIMARY KEY,
    url_indice_gbfs TEXT NOT NULL,
    system_id TEXT,
    nome TEXT,
    versao_gbfs TEXT,
    fuso TEXT,
    sintetica INTEGER NOT NULL DEFAULT 0,
    criada_em_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tentativas (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER,
    iniciada_em_utc TEXT NOT NULL,
    encerrada_em_utc TEXT,
    resultado TEXT NOT NULL,
    http_status INTEGER,
    mensagem TEXT,
    feed_status_atualizado_em_utc TEXT,
    ttl_status_segundos INTEGER,
    arquivo_bruto_descoberta TEXT,
    arquivo_bruto_sistema TEXT,
    arquivo_bruto_status TEXT,
    arquivo_bruto_informacao TEXT,
    estacoes_recebidas INTEGER,
    observacoes_novas INTEGER,
    observacoes_repetidas INTEGER,
    duracao_ms INTEGER,
    FOREIGN KEY (fonte_id) REFERENCES fontes(id)
);

CREATE TABLE IF NOT EXISTS estacoes (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER NOT NULL,
    station_id TEXT NOT NULL,
    nome TEXT,
    latitude REAL,
    longitude REAL,
    capacidade INTEGER,
    external_id TEXT,
    endereco TEXT,
    valido_desde_utc TEXT NOT NULL,
    valido_ate_utc TEXT,
    assinatura TEXT,
    ausente_desde_utc TEXT,
    FOREIGN KEY (fonte_id) REFERENCES fontes(id)
);

CREATE INDEX IF NOT EXISTS ix_estacoes_abertas
    ON estacoes (fonte_id, station_id, valido_ate_utc);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER NOT NULL,
    estacao_id INTEGER NOT NULL,
    station_id TEXT NOT NULL,
    coletado_em_utc TEXT NOT NULL,
    feed_atualizado_em_utc TEXT,
    last_reported_utc TEXT,
    bicicletas_disponiveis INTEGER,
    vagas_disponiveis INTEGER,
    bicicletas_desabilitadas INTEGER,
    vagas_desabilitadas INTEGER,
    instalada INTEGER,
    alugando INTEGER,
    devolvendo INTEGER,
    situacao_operacional TEXT,
    disponibilidade_por_tipo_json TEXT,
    versao_gbfs TEXT,
    arquivo_bruto TEXT,
    flags_qualidade TEXT NOT NULL,
    chave_observacao TEXT NOT NULL,
    FOREIGN KEY (fonte_id) REFERENCES fontes(id),
    FOREIGN KEY (estacao_id) REFERENCES estacoes(id),
    UNIQUE (fonte_id, chave_observacao)
);

CREATE INDEX IF NOT EXISTS ix_snapshots_estacao_tempo
    ON snapshots (fonte_id, station_id, last_reported_utc, coletado_em_utc);

CREATE TABLE IF NOT EXISTS intervalos (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER NOT NULL,
    station_id TEXT NOT NULL,
    estacao_id_inicio INTEGER,
    estacao_id_fim INTEGER,
    snapshot_anterior_id INTEGER NOT NULL,
    snapshot_atual_id INTEGER NOT NULL,
    inicio_utc TEXT,
    fim_utc TEXT,
    duracao_segundos REAL,
    bicicletas_anterior INTEGER,
    bicicletas_atual INTEGER,
    delta INTEGER,
    aumento_observado INTEGER,
    reducao_observada INTEGER,
    movimentacao_observada INTEGER,
    comparavel INTEGER NOT NULL,
    motivo TEXT,
    flags_qualidade TEXT NOT NULL,
    FOREIGN KEY (fonte_id) REFERENCES fontes(id),
    UNIQUE (snapshot_anterior_id, snapshot_atual_id)
);

CREATE INDEX IF NOT EXISTS ix_intervalos_fim
    ON intervalos (fonte_id, station_id, fim_utc);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    fonte_id INTEGER NOT NULL,
    station_id TEXT,
    detectado_em_utc TEXT NOT NULL,
    tipo TEXT NOT NULL,
    detalhe TEXT,
    FOREIGN KEY (fonte_id) REFERENCES fontes(id)
);

CREATE INDEX IF NOT EXISTS ix_eventos_tempo
    ON eventos (fonte_id, detectado_em_utc);

CREATE TABLE IF NOT EXISTS coletor_estado (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pid INTEGER,
    hostname TEXT,
    iniciado_em_utc TEXT,
    ultimo_batimento_utc TEXT,
    estado TEXT NOT NULL
);
"""


def codificar_flags(flags: list[str] | set[str] | tuple[str, ...]) -> str:
    return json.dumps(sorted(set(flags)), ensure_ascii=False)


def decodificar_flags(texto: str | None) -> list[str]:
    if not texto:
        return []
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError:
        return []
    if not isinstance(valor, list):
        return []
    return [str(item) for item in valor]


@contextmanager
def conectar(caminho: Path) -> Iterator[sqlite3.Connection]:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho, timeout=10, isolation_level=None)
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("PRAGMA synchronous=NORMAL")
        conexao.execute("PRAGMA foreign_keys=ON")
        conexao.execute("PRAGMA busy_timeout=5000")
        yield conexao
    finally:
        conexao.close()


def inicializar(conexao: sqlite3.Connection) -> None:
    conexao.executescript(SCHEMA)
    colunas = {linha["name"] for linha in conexao.execute("PRAGMA table_info(fontes)").fetchall()}
    if "url_descoberta" in colunas and "url_indice_gbfs" not in colunas:
        conexao.execute("ALTER TABLE fontes RENAME COLUMN url_descoberta TO url_indice_gbfs")


@contextmanager
def transacao(conexao: sqlite3.Connection) -> Iterator[None]:
    conexao.execute("BEGIN IMMEDIATE")
    try:
        yield
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise


@contextmanager
def leitura(conexao: sqlite3.Connection) -> Iterator[None]:
    conexao.execute("BEGIN DEFERRED")
    try:
        yield
    finally:
        conexao.execute("ROLLBACK")


def consultar_sql(conexao: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(linha) for linha in conexao.execute(sql, params).fetchall()]


def registrar_batimento(conexao: sqlite3.Connection, estado: str) -> None:
    agora = formatar_utc(agora_utc())
    atual = conexao.execute("SELECT * FROM coletor_estado WHERE id = 1").fetchone()
    if atual is not None and atual["estado"] == "ativo" and estado == "ativo":
        iniciado = atual["iniciado_em_utc"]
    else:
        iniciado = agora
    conexao.execute(
        """
        INSERT INTO coletor_estado (
            id, pid, hostname, iniciado_em_utc, ultimo_batimento_utc, estado
        ) VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            pid = excluded.pid,
            hostname = excluded.hostname,
            iniciado_em_utc = excluded.iniciado_em_utc,
            ultimo_batimento_utc = excluded.ultimo_batimento_utc,
            estado = excluded.estado
        """,
        (os.getpid(), socket.gethostname(), iniciado, agora, estado),
    )


def inserir_fonte(
    conexao: sqlite3.Connection,
    *,
    url_indice_gbfs: str,
    system_id: str | None,
    nome: str | None,
    versao_gbfs: str | None,
    fuso: str | None,
    sintetica: bool,
    criada_em_utc: str,
) -> int:
    cursor = conexao.execute(
        """
        INSERT INTO fontes (
            url_indice_gbfs, system_id, nome, versao_gbfs, fuso, sintetica, criada_em_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url_indice_gbfs,
            system_id,
            nome,
            versao_gbfs,
            fuso,
            1 if sintetica else 0,
            criada_em_utc,
        ),
    )
    return int(cursor.lastrowid)


def atualizar_fonte(
    conexao: sqlite3.Connection,
    fonte_id: int,
    *,
    system_id: str | None,
    nome: str | None,
    versao_gbfs: str | None,
    fuso: str | None,
) -> None:
    conexao.execute(
        """
        UPDATE fontes
        SET system_id = COALESCE(?, system_id),
            nome = COALESCE(?, nome),
            versao_gbfs = COALESCE(?, versao_gbfs),
            fuso = COALESCE(?, fuso)
        WHERE id = ?
        """,
        (system_id, nome, versao_gbfs, fuso, fonte_id),
    )


def fonte_por_url(conexao: sqlite3.Connection, url: str) -> dict | None:
    linha = conexao.execute(
        "SELECT * FROM fontes WHERE url_indice_gbfs = ? ORDER BY id DESC LIMIT 1",
        (url,),
    ).fetchone()
    return dict(linha) if linha else None


def fonte_por_id(conexao: sqlite3.Connection, fonte_id: int) -> dict | None:
    linha = conexao.execute("SELECT * FROM fontes WHERE id = ?", (fonte_id,)).fetchone()
    return dict(linha) if linha else None


def inserir_tentativa(conexao: sqlite3.Connection, dados: dict) -> int:
    colunas = [
        "fonte_id",
        "iniciada_em_utc",
        "encerrada_em_utc",
        "resultado",
        "http_status",
        "mensagem",
        "feed_status_atualizado_em_utc",
        "ttl_status_segundos",
        "arquivo_bruto_descoberta",
        "arquivo_bruto_sistema",
        "arquivo_bruto_status",
        "arquivo_bruto_informacao",
        "estacoes_recebidas",
        "observacoes_novas",
        "observacoes_repetidas",
        "duracao_ms",
    ]
    marcas = ", ".join("?" for _ in colunas)
    nomes = ", ".join(colunas)
    cursor = conexao.execute(
        f"INSERT INTO tentativas ({nomes}) VALUES ({marcas})",
        tuple(dados.get(coluna) for coluna in colunas),
    )
    return int(cursor.lastrowid)


def ultima_tentativa(conexao: sqlite3.Connection, fonte_id: int | None = None) -> dict | None:
    if fonte_id is None:
        linha = conexao.execute(
            "SELECT * FROM tentativas ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        linha = conexao.execute(
            """
            SELECT * FROM tentativas
            WHERE fonte_id = ? OR fonte_id IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (fonte_id,),
        ).fetchone()
    return dict(linha) if linha else None


def ultimo_sucesso(conexao: sqlite3.Connection, fonte_id: int | None = None) -> dict | None:
    filtro = "resultado IN ('sucesso', 'resposta_repetida')"
    params: tuple = ()
    if fonte_id is not None:
        filtro += " AND fonte_id = ?"
        params = (fonte_id,)
    linha = conexao.execute(
        f"SELECT * FROM tentativas WHERE {filtro} ORDER BY id DESC LIMIT 1",
        params,
    ).fetchone()
    return dict(linha) if linha else None


def ultima_coleta_de_cadastro(conexao: sqlite3.Connection, fonte_id: int) -> str | None:
    linha = conexao.execute(
        """
        SELECT encerrada_em_utc FROM tentativas
        WHERE fonte_id = ?
          AND arquivo_bruto_informacao IS NOT NULL
          AND resultado IN ('sucesso', 'resposta_repetida')
        ORDER BY id DESC LIMIT 1
        """,
        (fonte_id,),
    ).fetchone()
    return linha["encerrada_em_utc"] if linha else None


def estacoes_abertas(conexao: sqlite3.Connection, fonte_id: int) -> list[dict]:
    return consultar_sql(
        conexao,
        """
        SELECT * FROM estacoes
        WHERE fonte_id = ? AND valido_ate_utc IS NULL
        ORDER BY station_id
        """,
        (fonte_id,),
    )


def inserir_estacao(conexao: sqlite3.Connection, dados: dict) -> int:
    colunas = [
        "fonte_id",
        "station_id",
        "nome",
        "latitude",
        "longitude",
        "capacidade",
        "external_id",
        "endereco",
        "valido_desde_utc",
        "valido_ate_utc",
        "assinatura",
        "ausente_desde_utc",
    ]
    marcas = ", ".join("?" for _ in colunas)
    cursor = conexao.execute(
        f"INSERT INTO estacoes ({', '.join(colunas)}) VALUES ({marcas})",
        tuple(dados.get(coluna) for coluna in colunas),
    )
    return int(cursor.lastrowid)


def encerrar_estacao(conexao: sqlite3.Connection, estacao_id: int, valido_ate_utc: str) -> None:
    conexao.execute(
        "UPDATE estacoes SET valido_ate_utc = ? WHERE id = ? AND valido_ate_utc IS NULL",
        (valido_ate_utc, estacao_id),
    )


def atualizar_estacao(conexao: sqlite3.Connection, estacao_id: int, dados: dict) -> None:
    campos = []
    valores = []
    for campo in ("nome", "latitude", "longitude", "capacidade", "external_id", "endereco", "assinatura"):
        if campo in dados:
            campos.append(f"{campo} = ?")
            valores.append(dados[campo])
    if not campos:
        return
    valores.append(estacao_id)
    conexao.execute(f"UPDATE estacoes SET {', '.join(campos)} WHERE id = ?", valores)


def marcar_ausencia(conexao: sqlite3.Connection, estacao_id: int, instante: str) -> None:
    conexao.execute(
        "UPDATE estacoes SET ausente_desde_utc = ? WHERE id = ? AND ausente_desde_utc IS NULL",
        (instante, estacao_id),
    )


def limpar_ausencia(conexao: sqlite3.Connection, estacao_id: int) -> None:
    conexao.execute(
        "UPDATE estacoes SET ausente_desde_utc = NULL WHERE id = ?",
        (estacao_id,),
    )


def inserir_evento(
    conexao: sqlite3.Connection,
    *,
    fonte_id: int,
    station_id: str | None,
    detectado_em_utc: str,
    tipo: str,
    detalhe: str | None,
) -> None:
    conexao.execute(
        """
        INSERT INTO eventos (fonte_id, station_id, detectado_em_utc, tipo, detalhe)
        VALUES (?, ?, ?, ?, ?)
        """,
        (fonte_id, station_id, detectado_em_utc, tipo, detalhe),
    )


def ultimos_snapshots(conexao: sqlite3.Connection, fonte_id: int) -> dict[str, dict]:
    linhas = consultar_sql(
        conexao,
        """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY station_id
                ORDER BY COALESCE(last_reported_utc, coletado_em_utc) DESC, id DESC
            ) AS rn
            FROM snapshots
            WHERE fonte_id = ?
        ) WHERE rn = 1
        """,
        (fonte_id,),
    )
    return {linha["station_id"]: linha for linha in linhas}


def existe_snapshot(conexao: sqlite3.Connection, fonte_id: int, chave: str) -> bool:
    linha = conexao.execute(
        "SELECT 1 FROM snapshots WHERE fonte_id = ? AND chave_observacao = ?",
        (fonte_id, chave),
    ).fetchone()
    return linha is not None


def inserir_snapshot(conexao: sqlite3.Connection, dados: dict) -> int:
    colunas = [
        "fonte_id",
        "estacao_id",
        "station_id",
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
        "chave_observacao",
    ]
    marcas = ", ".join("?" for _ in colunas)
    cursor = conexao.execute(
        f"INSERT INTO snapshots ({', '.join(colunas)}) VALUES ({marcas})",
        tuple(dados.get(coluna) for coluna in colunas),
    )
    return int(cursor.lastrowid)


def inserir_intervalo(conexao: sqlite3.Connection, dados: dict) -> int:
    colunas = [
        "fonte_id",
        "station_id",
        "estacao_id_inicio",
        "estacao_id_fim",
        "snapshot_anterior_id",
        "snapshot_atual_id",
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
    ]
    marcas = ", ".join("?" for _ in colunas)
    cursor = conexao.execute(
        f"INSERT INTO intervalos ({', '.join(colunas)}) VALUES ({marcas})",
        tuple(dados.get(coluna) for coluna in colunas),
    )
    return int(cursor.lastrowid)


def estado_coletor(conexao: sqlite3.Connection) -> dict | None:
    linha = conexao.execute("SELECT * FROM coletor_estado WHERE id = 1").fetchone()
    return dict(linha) if linha else None


def periodo_da_coleta(conexao: sqlite3.Connection, fonte_id: int) -> dict | None:
    """Janela dos intervalos comparáveis. Snapshots isolados não esticam o período.

    Assim a cobertura não usa o vão de uma coleta antiga, só o trecho em que
    houve movimentação observada.
    """
    # Por estação, para usar ix_intervalos_fim: o MIN/MAX direto lê a tabela inteira.
    # Intervalos comparáveis de uma estação não se sobrepõem, então o primeiro pelo fim também tem o menor início.
    comparavel = conexao.execute(
        """
        SELECT
            MIN((
                SELECT i.inicio_utc FROM intervalos AS i
                WHERE i.fonte_id = ? AND i.station_id = e.station_id
                  AND i.comparavel = 1
                  AND i.inicio_utc IS NOT NULL
                  AND i.fim_utc IS NOT NULL
                ORDER BY i.fim_utc
                LIMIT 1
            )) AS inicio,
            MAX((
                SELECT i.fim_utc FROM intervalos AS i
                WHERE i.fonte_id = ? AND i.station_id = e.station_id
                  AND i.comparavel = 1
                  AND i.inicio_utc IS NOT NULL
                  AND i.fim_utc IS NOT NULL
                ORDER BY i.fim_utc DESC
                LIMIT 1
            )) AS fim
        FROM (SELECT DISTINCT station_id FROM estacoes WHERE fonte_id = ?) AS e
        """,
        (fonte_id, fonte_id, fonte_id),
    ).fetchone()
    if comparavel is not None and comparavel["inicio"] and comparavel["fim"]:
        return {"inicio": comparavel["inicio"], "fim": comparavel["fim"]}
    linha = conexao.execute(
        """
        SELECT MIN(coletado_em_utc) AS inicio, MAX(coletado_em_utc) AS fim
        FROM snapshots
        WHERE fonte_id = ?
        """,
        (fonte_id,),
    ).fetchone()
    if linha is None or not linha["inicio"] or not linha["fim"]:
        return None
    return {"inicio": linha["inicio"], "fim": linha["fim"]}


def periodo_armazenado(conexao: sqlite3.Connection, fonte_id: int) -> dict:
    linha = conexao.execute(
        """
        SELECT
            MIN(COALESCE(last_reported_utc, coletado_em_utc)) AS inicio,
            MAX(COALESCE(last_reported_utc, coletado_em_utc)) AS fim,
            COUNT(*) AS snapshots
        FROM snapshots
        WHERE fonte_id = ?
        """,
        (fonte_id,),
    ).fetchone()
    return {
        "inicio": linha["inicio"] if linha else None,
        "fim": linha["fim"] if linha else None,
        "snapshots": int(linha["snapshots"]) if linha else 0,
    }


def contar_estacoes_abertas(conexao: sqlite3.Connection, fonte_id: int) -> int:
    linha = conexao.execute(
        "SELECT COUNT(*) AS total FROM estacoes WHERE fonte_id = ? AND valido_ate_utc IS NULL",
        (fonte_id,),
    ).fetchone()
    return int(linha["total"]) if linha else 0


def eventos_recentes(conexao: sqlite3.Connection, fonte_id: int, limite: int = 20) -> list[dict]:
    return consultar_sql(
        conexao,
        """
        SELECT * FROM eventos
        WHERE fonte_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (fonte_id, limite),
    )


def _filtro_estacoes(station_ids: list[str] | None) -> tuple[str, tuple]:
    if not station_ids:
        return "", ()
    marcas = ", ".join("?" for _ in station_ids)
    return f" AND station_id IN ({marcas})", tuple(station_ids)


def estacoes_no_periodo(
    conexao: sqlite3.Connection,
    fonte_id: int,
    inicio_utc: str,
    fim_utc: str,
    station_ids: list[str] | None = None,
) -> list[dict]:
    extra, params_ids = _filtro_estacoes(station_ids)
    return consultar_sql(
        conexao,
        f"""
        SELECT * FROM estacoes
        WHERE fonte_id = ?
          AND valido_desde_utc <= ?
          AND (valido_ate_utc IS NULL OR valido_ate_utc > ?)
          {extra}
        ORDER BY station_id, valido_desde_utc, id
        """,
        (fonte_id, fim_utc, inicio_utc, *params_ids),
    )


def intervalos_sobrepostos(
    conexao: sqlite3.Connection,
    fonte_id: int,
    inicio_utc: str,
    fim_utc: str,
    station_ids: list[str] | None = None,
) -> list[dict]:
    extra, params_ids = _filtro_estacoes(station_ids)
    return consultar_sql(
        conexao,
        f"""
        SELECT * FROM intervalos
        WHERE fonte_id = ?
          AND (inicio_utc IS NULL OR inicio_utc <= ?)
          AND (fim_utc IS NULL OR fim_utc >= ?)
          {extra}
        ORDER BY station_id, fim_utc, id
        """,
        (fonte_id, fim_utc, inicio_utc, *params_ids),
    )


def snapshots_no_periodo(
    conexao: sqlite3.Connection,
    fonte_id: int,
    inicio_utc: str,
    fim_utc: str,
    station_ids: list[str] | None = None,
) -> list[dict]:
    extra, params_ids = _filtro_estacoes(station_ids)
    return consultar_sql(
        conexao,
        f"""
        SELECT * FROM snapshots
        WHERE fonte_id = ?
          AND COALESCE(last_reported_utc, coletado_em_utc) >= ?
          AND COALESCE(last_reported_utc, coletado_em_utc) <= ?
          {extra}
        ORDER BY station_id, coletado_em_utc, id
        """,
        (fonte_id, inicio_utc, fim_utc, *params_ids),
    )


def ultimos_estoques_no_periodo(
    conexao: sqlite3.Connection,
    fonte_id: int,
    inicio_utc: str,
    fim_utc: str,
    station_ids: list[str] | None = None,
) -> list[dict]:
    extra, params_ids = _filtro_estacoes(station_ids)
    # Sem INDEXED BY, o SQLite lê a tabela inteira; com ele, o filtro de tempo roda no índice e só as linhas da janela são lidas.
    return consultar_sql(
        conexao,
        f"""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY estacao_id
                ORDER BY COALESCE(last_reported_utc, coletado_em_utc) DESC, id DESC
            ) AS rn
            FROM snapshots INDEXED BY ix_snapshots_estacao_tempo
            WHERE fonte_id = ?
              AND COALESCE(last_reported_utc, coletado_em_utc) >= ?
              AND COALESCE(last_reported_utc, coletado_em_utc) <= ?
              {extra}
        ) WHERE rn = 1
        """,
        (fonte_id, inicio_utc, fim_utc, *params_ids),
    )


def todo_cadastro(conexao: sqlite3.Connection, fonte_id: int) -> list[dict]:
    return consultar_sql(
        conexao,
        "SELECT * FROM estacoes WHERE fonte_id = ? ORDER BY station_id, valido_desde_utc, id",
        (fonte_id,),
    )


def todos_snapshots(conexao: sqlite3.Connection, fonte_id: int) -> list[dict]:
    return consultar_sql(
        conexao,
        "SELECT * FROM snapshots WHERE fonte_id = ? ORDER BY coletado_em_utc, id",
        (fonte_id,),
    )


def todos_intervalos(conexao: sqlite3.Connection, fonte_id: int) -> list[dict]:
    return consultar_sql(
        conexao,
        "SELECT * FROM intervalos WHERE fonte_id = ? ORDER BY fim_utc, id",
        (fonte_id,),
    )
