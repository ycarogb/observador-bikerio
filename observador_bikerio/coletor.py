"""Coleta GBFS em processo próprio. A interface não chama este módulo."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from observador_bikerio.banco import (
    atualizar_estacao,
    atualizar_fonte,
    codificar_flags,
    conectar,
    decodificar_flags,
    encerrar_estacao,
    estacoes_abertas,
    existe_snapshot,
    fonte_por_id,
    fonte_por_url,
    inicializar,
    inserir_estacao,
    inserir_evento,
    inserir_fonte,
    inserir_intervalo,
    inserir_snapshot,
    inserir_tentativa,
    limpar_ausencia,
    marcar_ausencia,
    registrar_batimento,
    transacao,
    ultima_coleta_de_cadastro,
    ultimos_snapshots,
)
from observador_bikerio.bruto import salvar_bruto
from observador_bikerio.configuracao import Configuracao
from observador_bikerio.fonte_gbfs import (
    ClienteGbfs,
    ErroFonte,
    descobrir_feeds,
    fonte_sintetica,
    ler_envelope,
    sistema_do_feed,
)
from observador_bikerio.indicadores import avaliar_par
from observador_bikerio.normalizador import (
    listar_estacoes,
    normalizar_informacao,
    normalizar_status,
)
from observador_bikerio.registro import configurar_log
from observador_bikerio.tempo import agora_utc, analisar_instante, formatar_utc
from observador_bikerio.trava import TravaColetor


@dataclass
class ResultadoColeta:
    sucesso: bool
    resultado: str
    mensagem: str
    estacoes_recebidas: int = 0
    observacoes_novas: int = 0
    observacoes_repetidas: int = 0
    intervalos_gravados: int = 0
    ttl_status_segundos: int | None = None
    arquivo_banco: str = ""
    arquivos_brutos: list[str] = field(default_factory=list)
    http_status: int | None = None


def coletar_uma_vez(
    configuracao: Configuracao,
    cliente: ClienteGbfs | None = None,
    agora: datetime | None = None,
) -> ResultadoColeta:
    proprio = cliente is None
    cliente = cliente or ClienteGbfs(configuracao, ao_aguardar=lambda: _batimento(configuracao, "ativo"))
    try:
        with TravaColetor(configuracao.caminho_trava):
            _batimento(configuracao, "ativo")
            try:
                return _executar_ciclo(configuracao, cliente, agora or agora_utc())
            finally:
                _batimento(configuracao, "encerrado")
    finally:
        if proprio:
            cliente.fechar()


def coletar_continuo(configuracao: Configuracao) -> None:
    import signal

    logger = configurar_log(configuracao.pasta_logs)
    logger.info(
        "Coleta contínua iniciada. Desligar ou suspender o computador interrompe a coleta. "
        "A interface não controla este processo."
    )
    parar = False

    def solicitar_encerramento(*_args) -> None:
        nonlocal parar
        parar = True
        logger.info("Encerramento solicitado. O ciclo atual termina e o coletor para.")

    signal.signal(signal.SIGINT, solicitar_encerramento)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, solicitar_encerramento)
    cliente = ClienteGbfs(configuracao, ao_aguardar=lambda: _batimento(configuracao, "ativo"))
    try:
        with TravaColetor(configuracao.caminho_trava):
            _batimento(configuracao, "ativo")
            try:
                while not parar:
                    inicio = time.monotonic()
                    try:
                        resultado = _executar_ciclo(configuracao, cliente, agora_utc())
                    except KeyboardInterrupt:
                        break
                    logger.info("%s %s", resultado.resultado, resultado.mensagem)
                    espera = espera_ate_proximo(
                        time.monotonic() - inicio,
                        configuracao.intervalo_coleta_segundos,
                        resultado.ttl_status_segundos,
                    )
                    _dormir(espera, lambda: parar)
            finally:
                _batimento(configuracao, "encerrado")
    finally:
        cliente.fechar()
    logger.info("Coletor encerrado.")


def espera_ate_proximo(decorrido: float, intervalo: float, ttl: int | None) -> float:
    alvo = max(intervalo, float(ttl or 0))
    return max(0.0, alvo - decorrido)


def assinatura_cadastral(latitude: float | None, longitude: float | None, capacidade: int | None) -> str | None:
    if latitude is None or longitude is None:
        return None
    capacidade_txt = "n" if capacidade is None else str(capacidade)
    return f"{latitude:.6f}|{longitude:.6f}|{capacidade_txt}"


def _executar_ciclo(configuracao: Configuracao, cliente: ClienteGbfs, agora: datetime) -> ResultadoColeta:
    logger = configurar_log(configuracao.pasta_logs)
    inicio_mono = time.monotonic()
    try:
        descoberta = cliente.obter_json(configuracao.url_descoberta)
        feeds = descobrir_feeds(descoberta)
        sistema = None
        aviso_sistema = None
        if "system_information" in feeds:
            try:
                sistema = cliente.obter_json(feeds["system_information"])
            except ErroFonte as exc:
                aviso_sistema = str(exc)
                logger.warning("system_information indisponível: %s", exc)
        status_doc = cliente.obter_json(feeds["station_status"])
        status = [
            item
            for item in (
                normalizar_status(bruto) for bruto in listar_estacoes(status_doc, "stations")
            )
            if item is not None
        ]
        if not status:
            raise ErroFonte(
                "Feed station_status sem estações utilizáveis. "
                "Nada foi gravado como estoque zero."
            )
        with conectar(configuracao.caminho_banco) as conexao:
            inicializar(conexao)
            fonte = fonte_por_url(conexao, configuracao.url_descoberta)
            abertas = estacoes_abertas(conexao, fonte["id"]) if fonte else []
            conhecidas = {item["station_id"] for item in abertas}
            ultima_info = ultima_coleta_de_cadastro(conexao, fonte["id"]) if fonte else None
        ids_status = {item.station_id for item in status}
        precisa_cadastro = _precisa_cadastro(
            fonte is not None,
            ultima_info,
            agora,
            configuracao.intervalo_cadastro_segundos,
            ids_status - conhecidas,
        )
        info_doc = None
        if precisa_cadastro:
            info_doc = cliente.obter_json(feeds["station_information"])
        arquivos = {
            "descoberta": salvar_bruto(configuracao.pasta_base, "gbfs", agora, descoberta),
            "status": salvar_bruto(configuracao.pasta_base, "station_status", agora, status_doc),
        }
        if sistema is not None:
            arquivos["sistema"] = salvar_bruto(
                configuracao.pasta_base, "system_information", agora, sistema
            )
        if info_doc is not None:
            arquivos["informacao"] = salvar_bruto(
                configuracao.pasta_base, "station_information", agora, info_doc
            )
        envelope = ler_envelope(status_doc)
        system_id, nome_sistema, fuso = (None, None, None)
        if sistema is not None:
            system_id, nome_sistema, fuso = sistema_do_feed(sistema, configuracao.idioma_nome)
        informacoes = []
        if info_doc is not None:
            informacoes = [
                item
                for item in (
                    normalizar_informacao(bruto, configuracao.idioma_nome)
                    for bruto in listar_estacoes(info_doc, "stations")
                )
                if item is not None
            ]
            if not informacoes:
                logger.warning("station_information sem estações; o cadastro anterior foi preservado.")
        resultado = _gravar_ciclo(
            configuracao,
            agora,
            fonte_sistema=(system_id, nome_sistema, fuso, envelope.version),
            informacoes=informacoes,
            status=status,
            feed_atualizado=envelope.last_updated,
            ttl=envelope.ttl,
            arquivos=arquivos,
            aviso_sistema=aviso_sistema,
            duracao_ms=int((time.monotonic() - inicio_mono) * 1000),
        )
        logger.info("%s %s", resultado.resultado, resultado.mensagem)
        return resultado
    except ErroFonte as exc:
        mensagem = str(exc)
        logger.error("Falha de coleta: %s", mensagem)
        _registrar_falha(configuracao, agora, mensagem, exc.http_status, inicio_mono)
        return ResultadoColeta(
            sucesso=False,
            resultado="falha",
            mensagem=mensagem,
            arquivo_banco=str(configuracao.caminho_banco.resolve()),
            http_status=exc.http_status,
            ttl_status_segundos=None,
        )


def _gravar_ciclo(
    configuracao: Configuracao,
    agora: datetime,
    *,
    fonte_sistema: tuple,
    informacoes: list,
    status: list,
    feed_atualizado: datetime | None,
    ttl: int | None,
    arquivos: dict,
    aviso_sistema: str | None,
    duracao_ms: int,
) -> ResultadoColeta:
    system_id, nome_sistema, fuso, versao = fonte_sistema
    coletado = formatar_utc(agora)
    feed_txt = formatar_utc(feed_atualizado) if feed_atualizado else None
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        with transacao(conexao):
            fonte, mudou_fonte = _sincronizar_fonte(
                conexao,
                configuracao,
                system_id,
                nome_sistema,
                versao,
                fuso,
                coletado,
            )
            if mudou_fonte:
                inserir_evento(
                    conexao,
                    fonte_id=fonte["id"],
                    station_id=None,
                    detectado_em_utc=coletado,
                    tipo="mudanca_fonte",
                    detalhe="A série anterior foi preservada em outro registro de fonte.",
                )
            if informacoes:
                _atualizar_cadastro(conexao, fonte["id"], informacoes, coletado)
            abertas = {item["station_id"]: item for item in estacoes_abertas(conexao, fonte["id"])}
            baselines = {
                station_id: _par_de_linha(linha)
                for station_id, linha in ultimos_snapshots(conexao, fonte["id"]).items()
            }
            novas = 0
            repetidas = 0
            intervalos = 0
            for item in status:
                cadastro = abertas.get(item.station_id)
                if cadastro is None:
                    estacao_id = _inserir_placeholder(conexao, fonte["id"], item.station_id, coletado)
                    inserir_evento(
                        conexao,
                        fonte_id=fonte["id"],
                        station_id=item.station_id,
                        detectado_em_utc=coletado,
                        tipo="cadastro_ausente",
                        detalhe="Status sem cadastro de localização. Nenhuma coordenada foi inventada.",
                    )
                    cadastro = {
                        "id": estacao_id,
                        "station_id": item.station_id,
                        "assinatura": None,
                        "ausente_desde_utc": None,
                    }
                    abertas[item.station_id] = cadastro
                flags = set(item.flags)
                if item.last_reported is None:
                    flags.add("atualizacao_incerta")
                if feed_atualizado is not None and item.last_reported is not None:
                    atraso = (feed_atualizado - item.last_reported).total_seconds()
                    if atraso > configuracao.limite_dados_antigos_segundos:
                        flags.add("dados_antigos")
                anterior = baselines.get(item.station_id)
                if anterior and anterior.get("last_reported") and item.last_reported:
                    if item.last_reported < anterior["last_reported"]:
                        flags.add("fora_de_ordem")
                chave = _chave(item.station_id, item.last_reported, feed_atualizado)
                if _repetida(anterior, item, feed_atualizado) or existe_snapshot(conexao, fonte["id"], chave):
                    repetidas += 1
                    continue
                atual = {
                    "fonte_id": fonte["id"],
                    "estacao_id": cadastro["id"],
                    "station_id": item.station_id,
                    "last_reported": item.last_reported,
                    "coletado": agora,
                    "bicicletas": item.bicicletas_disponiveis,
                    "instalada": item.instalada,
                    "alugando": item.alugando,
                    "devolvendo": item.devolvendo,
                    "flags": flags,
                    "versao_gbfs": versao,
                }
                snapshot_id = inserir_snapshot(
                    conexao,
                    {
                        "fonte_id": fonte["id"],
                        "estacao_id": cadastro["id"],
                        "station_id": item.station_id,
                        "coletado_em_utc": coletado,
                        "feed_atualizado_em_utc": feed_txt,
                        "last_reported_utc": formatar_utc(item.last_reported) if item.last_reported else None,
                        "bicicletas_disponiveis": item.bicicletas_disponiveis,
                        "vagas_disponiveis": item.vagas_disponiveis,
                        "bicicletas_desabilitadas": item.bicicletas_desabilitadas,
                        "vagas_desabilitadas": item.vagas_desabilitadas,
                        "instalada": _bit(item.instalada),
                        "alugando": _bit(item.alugando),
                        "devolvendo": _bit(item.devolvendo),
                        "situacao_operacional": item.situacao_operacional,
                        "disponibilidade_por_tipo_json": item.disponibilidade_por_tipo_json,
                        "versao_gbfs": versao,
                        "arquivo_bruto": arquivos.get("status"),
                        "flags_qualidade": codificar_flags(flags),
                        "chave_observacao": chave,
                    },
                )
                novas += 1
                if anterior is not None:
                    par = avaliar_par(
                        anterior,
                        atual,
                        limite_lacuna_segundos=configuracao.limite_lacuna_segundos,
                        limiar_intervencao_bicicletas=configuracao.limiar_intervencao_bicicletas,
                    )
                    inserir_intervalo(
                        conexao,
                        {
                            "fonte_id": fonte["id"],
                            "station_id": item.station_id,
                            "estacao_id_inicio": anterior["estacao_id"],
                            "estacao_id_fim": atual["estacao_id"],
                            "snapshot_anterior_id": anterior["snapshot_id"],
                            "snapshot_atual_id": snapshot_id,
                            "inicio_utc": formatar_utc(par["inicio"]) if par["inicio"] else None,
                            "fim_utc": formatar_utc(par["fim"]) if par["fim"] else None,
                            "duracao_segundos": par["duracao_segundos"],
                            "bicicletas_anterior": par["bicicletas_anterior"],
                            "bicicletas_atual": par["bicicletas_atual"],
                            "delta": par["delta"],
                            "aumento_observado": par["aumento_observado"],
                            "reducao_observada": par["reducao_observada"],
                            "movimentacao_observada": par["movimentacao_observada"],
                            "comparavel": 1 if par["comparavel"] else 0,
                            "motivo": par["motivo"],
                            "flags_qualidade": codificar_flags(par["flags"]),
                        },
                    )
                    intervalos += 1
                atual["snapshot_id"] = snapshot_id
                if _preferir_baseline(atual, anterior):
                    baselines[item.station_id] = atual
            _detectar_ausencias(conexao, fonte["id"], abertas, {item.station_id for item in status}, coletado)
            if novas == 0 and repetidas > 0:
                resultado = "resposta_repetida"
            else:
                resultado = "sucesso"
            mensagem = (
                f"{novas} observações novas, {repetidas} respostas repetidas, "
                f"{intervalos} intervalos avaliados."
            )
            if aviso_sistema:
                mensagem = f"{mensagem} system_information não foi lido: {aviso_sistema}"
            inserir_tentativa(
                conexao,
                {
                    "fonte_id": fonte["id"],
                    "iniciada_em_utc": coletado,
                    "encerrada_em_utc": formatar_utc(agora),
                    "resultado": resultado,
                    "http_status": 200,
                    "mensagem": mensagem,
                    "feed_status_atualizado_em_utc": feed_txt,
                    "ttl_status_segundos": ttl,
                    "arquivo_bruto_descoberta": arquivos.get("descoberta"),
                    "arquivo_bruto_sistema": arquivos.get("sistema"),
                    "arquivo_bruto_status": arquivos.get("status"),
                    "arquivo_bruto_informacao": arquivos.get("informacao"),
                    "estacoes_recebidas": len(status),
                    "observacoes_novas": novas,
                    "observacoes_repetidas": repetidas,
                    "duracao_ms": duracao_ms,
                },
            )
    return ResultadoColeta(
        sucesso=True,
        resultado=resultado,
        mensagem=mensagem,
        estacoes_recebidas=len(status),
        observacoes_novas=novas,
        observacoes_repetidas=repetidas,
        intervalos_gravados=intervalos,
        ttl_status_segundos=ttl,
        arquivo_banco=str(configuracao.caminho_banco.resolve()),
        arquivos_brutos=list(arquivos.values()),
    )


def _sincronizar_fonte(conexao, configuracao, system_id, nome, versao, fuso, agora):
    atual = fonte_por_url(conexao, configuracao.url_descoberta)
    sintetica = fonte_sintetica(configuracao.url_descoberta, system_id)
    if atual is None:
        fonte_id = inserir_fonte(
            conexao,
            url_descoberta=configuracao.url_descoberta,
            system_id=system_id,
            nome=nome,
            versao_gbfs=versao,
            fuso=fuso,
            sintetica=sintetica,
            criada_em_utc=agora,
        )
        return fonte_por_id(conexao, fonte_id), False
    if atual["system_id"] and system_id and atual["system_id"] != system_id:
        fonte_id = inserir_fonte(
            conexao,
            url_descoberta=configuracao.url_descoberta,
            system_id=system_id,
            nome=nome,
            versao_gbfs=versao,
            fuso=fuso,
            sintetica=sintetica,
            criada_em_utc=agora,
        )
        return fonte_por_id(conexao, fonte_id), True
    atualizar_fonte(
        conexao,
        atual["id"],
        system_id=system_id,
        nome=nome,
        versao_gbfs=versao,
        fuso=fuso,
    )
    return fonte_por_id(conexao, atual["id"]), False


def _atualizar_cadastro(conexao, fonte_id: int, informacoes: list, agora: str) -> None:
    abertas = {item["station_id"]: item for item in estacoes_abertas(conexao, fonte_id)}
    for estacao in informacoes:
        nova = assinatura_cadastral(estacao.latitude, estacao.longitude, estacao.capacidade)
        atual = abertas.get(estacao.station_id)
        if atual is None:
            inserir_estacao(conexao, _dados_estacao(fonte_id, estacao, agora, nova))
            continue
        if atual["assinatura"] is None and nova is not None:
            atualizar_estacao(
                conexao,
                atual["id"],
                {
                    "nome": estacao.nome,
                    "latitude": estacao.latitude,
                    "longitude": estacao.longitude,
                    "capacidade": estacao.capacidade,
                    "external_id": estacao.external_id,
                    "endereco": estacao.endereco,
                    "assinatura": nova,
                },
            )
            continue
        if atual["assinatura"] and nova and atual["assinatura"] != nova:
            encerrar_estacao(conexao, atual["id"], agora)
            inserir_estacao(conexao, _dados_estacao(fonte_id, estacao, agora, nova))
            inserir_evento(
                conexao,
                fonte_id=fonte_id,
                station_id=estacao.station_id,
                detectado_em_utc=agora,
                tipo="mudanca_cadastral",
                detalhe="Localização ou capacidade mudou. A versão anterior permanece no histórico.",
            )
            continue
        if atual["nome"] != estacao.nome or atual["endereco"] != estacao.endereco:
            atualizar_estacao(
                conexao,
                atual["id"],
                {
                    "nome": estacao.nome,
                    "endereco": estacao.endereco,
                    "external_id": estacao.external_id,
                },
            )


def _dados_estacao(fonte_id: int, estacao, agora: str, assinatura: str | None) -> dict:
    return {
        "fonte_id": fonte_id,
        "station_id": estacao.station_id,
        "nome": estacao.nome,
        "latitude": estacao.latitude,
        "longitude": estacao.longitude,
        "capacidade": estacao.capacidade,
        "external_id": estacao.external_id,
        "endereco": estacao.endereco,
        "valido_desde_utc": agora,
        "valido_ate_utc": None,
        "assinatura": assinatura,
        "ausente_desde_utc": None,
    }


def _inserir_placeholder(conexao, fonte_id: int, station_id: str, agora: str) -> int:
    return inserir_estacao(
        conexao,
        {
            "fonte_id": fonte_id,
            "station_id": station_id,
            "nome": None,
            "latitude": None,
            "longitude": None,
            "capacidade": None,
            "external_id": None,
            "endereco": None,
            "valido_desde_utc": agora,
            "valido_ate_utc": None,
            "assinatura": None,
            "ausente_desde_utc": None,
        },
    )


def _detectar_ausencias(conexao, fonte_id: int, abertas: dict, presentes: set[str], agora: str) -> None:
    for station_id, cadastro in abertas.items():
        if station_id not in presentes:
            if cadastro.get("ausente_desde_utc") is None:
                marcar_ausencia(conexao, cadastro["id"], agora)
                inserir_evento(
                    conexao,
                    fonte_id=fonte_id,
                    station_id=station_id,
                    detectado_em_utc=agora,
                    tipo="desaparecimento",
                    detalhe="A estação saiu do feed de status. Isso não foi registrado como estoque zero.",
                )
            continue
        if cadastro.get("ausente_desde_utc") is not None:
            limpar_ausencia(conexao, cadastro["id"])
            inserir_evento(
                conexao,
                fonte_id=fonte_id,
                station_id=station_id,
                detectado_em_utc=agora,
                tipo="retorno",
                detalhe="A estação voltou ao feed de status.",
            )


def _par_de_linha(linha: dict) -> dict:
    return {
        "fonte_id": linha["fonte_id"],
        "estacao_id": linha["estacao_id"],
        "station_id": linha["station_id"],
        "last_reported": analisar_instante(linha.get("last_reported_utc")),
        "coletado": analisar_instante(linha["coletado_em_utc"]),
        "bicicletas": linha.get("bicicletas_disponiveis"),
        "instalada": None if linha.get("instalada") is None else bool(linha["instalada"]),
        "alugando": None if linha.get("alugando") is None else bool(linha["alugando"]),
        "devolvendo": None if linha.get("devolvendo") is None else bool(linha["devolvendo"]),
        "flags": set(decodificar_flags(linha.get("flags_qualidade"))),
        "versao_gbfs": linha.get("versao_gbfs"),
        "snapshot_id": linha["id"],
    }


def _repetida(anterior: dict | None, status, feed_atualizado: datetime | None) -> bool:
    if anterior is None:
        return False
    if status.last_reported is not None and anterior.get("last_reported") == status.last_reported:
        return True
    if (
        status.last_reported is None
        and anterior.get("last_reported") is None
        and feed_atualizado is not None
        and anterior.get("feed_atualizado") == feed_atualizado
    ):
        return True
    return False


def _preferir_baseline(atual: dict, anterior: dict | None) -> bool:
    if anterior is None:
        return True
    momento_atual = atual.get("last_reported") or atual.get("coletado")
    momento_anterior = anterior.get("last_reported") or anterior.get("coletado")
    if momento_atual is None:
        return False
    if momento_anterior is None:
        return True
    return momento_atual >= momento_anterior


def _chave(station_id: str, last_reported: datetime | None, feed_atualizado: datetime | None) -> str:
    if last_reported is not None:
        return f"{station_id}|{formatar_utc(last_reported)}"
    feed = formatar_utc(feed_atualizado) if feed_atualizado else "sem_feed"
    return f"{station_id}|sem_reporte|{feed}"


def _precisa_cadastro(tem_fonte: bool, ultima_info: str | None, agora: datetime, intervalo: float, desconhecidas: set[str]) -> bool:
    if not tem_fonte or ultima_info is None or desconhecidas:
        return True
    ultima = analisar_instante(ultima_info)
    if ultima is None:
        return True
    return (agora - ultima).total_seconds() >= intervalo


def recalcular_intervalos(configuracao: Configuracao) -> int:
    """Reaplica o limite de lacuna vigente aos intervalos já gravados."""
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        linhas = conexao.execute(
            """
            SELECT
                i.id AS intervalo_id,
                sa.fonte_id, sa.estacao_id, sa.station_id, sa.last_reported_utc,
                sa.coletado_em_utc, sa.bicicletas_disponiveis, sa.instalada,
                sa.alugando, sa.devolvendo, sa.flags_qualidade, sa.versao_gbfs,
                sa.id,
                sb.fonte_id AS fonte_id_atual, sb.estacao_id AS estacao_id_atual,
                sb.station_id AS station_id_atual, sb.last_reported_utc AS last_reported_utc_atual,
                sb.coletado_em_utc AS coletado_em_utc_atual,
                sb.bicicletas_disponiveis AS bicicletas_disponiveis_atual,
                sb.instalada AS instalada_atual, sb.alugando AS alugando_atual,
                sb.devolvendo AS devolvendo_atual, sb.flags_qualidade AS flags_qualidade_atual,
                sb.versao_gbfs AS versao_gbfs_atual, sb.id AS id_atual
            FROM intervalos AS i
            JOIN snapshots AS sa ON sa.id = i.snapshot_anterior_id
            JOIN snapshots AS sb ON sb.id = i.snapshot_atual_id
            """
        ).fetchall()
        with transacao(conexao):
            for linha in linhas:
                anterior = _par_de_linha(dict(linha))
                atual = _par_de_linha(
                    {
                        "fonte_id": linha["fonte_id_atual"],
                        "estacao_id": linha["estacao_id_atual"],
                        "station_id": linha["station_id_atual"],
                        "last_reported_utc": linha["last_reported_utc_atual"],
                        "coletado_em_utc": linha["coletado_em_utc_atual"],
                        "bicicletas_disponiveis": linha["bicicletas_disponiveis_atual"],
                        "instalada": linha["instalada_atual"],
                        "alugando": linha["alugando_atual"],
                        "devolvendo": linha["devolvendo_atual"],
                        "flags_qualidade": linha["flags_qualidade_atual"],
                        "versao_gbfs": linha["versao_gbfs_atual"],
                        "id": linha["id_atual"],
                    }
                )
                par = avaliar_par(
                    anterior,
                    atual,
                    limite_lacuna_segundos=configuracao.limite_lacuna_segundos,
                    limiar_intervencao_bicicletas=configuracao.limiar_intervencao_bicicletas,
                )
                conexao.execute(
                    """
                    UPDATE intervalos
                    SET estacao_id_inicio = ?,
                        estacao_id_fim = ?,
                        inicio_utc = ?,
                        fim_utc = ?,
                        duracao_segundos = ?,
                        bicicletas_anterior = ?,
                        bicicletas_atual = ?,
                        delta = ?,
                        aumento_observado = ?,
                        reducao_observada = ?,
                        movimentacao_observada = ?,
                        comparavel = ?,
                        motivo = ?,
                        flags_qualidade = ?
                    WHERE id = ?
                    """,
                    (
                        anterior["estacao_id"],
                        atual["estacao_id"],
                        formatar_utc(par["inicio"]) if par["inicio"] else None,
                        formatar_utc(par["fim"]) if par["fim"] else None,
                        par["duracao_segundos"],
                        par["bicicletas_anterior"],
                        par["bicicletas_atual"],
                        par["delta"],
                        par["aumento_observado"],
                        par["reducao_observada"],
                        par["movimentacao_observada"],
                        1 if par["comparavel"] else 0,
                        par["motivo"],
                        codificar_flags(par["flags"]),
                        linha["intervalo_id"],
                    ),
                )
    return len(linhas)


def _bit(valor: bool | None) -> int | None:
    if valor is None:
        return None
    return 1 if valor else 0


def _batimento(configuracao: Configuracao, estado: str) -> None:
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        registrar_batimento(conexao, estado)


def _registrar_falha(configuracao, agora, mensagem, http_status, inicio_mono) -> None:
    with conectar(configuracao.caminho_banco) as conexao:
        inicializar(conexao)
        fonte = fonte_por_url(conexao, configuracao.url_descoberta)
        inserir_tentativa(
            conexao,
            {
                "fonte_id": None if fonte is None else fonte["id"],
                "iniciada_em_utc": formatar_utc(agora),
                "encerrada_em_utc": formatar_utc(agora),
                "resultado": "falha",
                "http_status": http_status,
                "mensagem": mensagem,
                "duracao_ms": int((time.monotonic() - inicio_mono) * 1000),
                "estacoes_recebidas": 0,
                "observacoes_novas": 0,
                "observacoes_repetidas": 0,
            },
        )


def _dormir(segundos: float, cancelado) -> None:
    restante = segundos
    while restante > 0 and not cancelado():
        fatia = min(1.0, restante)
        time.sleep(fatia)
        restante -= fatia
