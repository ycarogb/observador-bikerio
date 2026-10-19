"""Regras de comparação, cobertura e agregação.

A movimentação observada é uma proxy. Ela só existe quando duas observações
são comparáveis. Lacuna, ausência e falha de coleta não viram zero.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from observador_bikerio.tempo import FUSO_EXIBICAO, formatar_local, formatar_utc
from observador_bikerio.textos import FLAGS_SINALIZADOS

MOTIVO_MUDANCA_FONTE = "mudanca_fonte"
MOTIVO_MUDANCA_CADASTRO = "mudanca_cadastral"
MOTIVO_VALOR_AUSENTE = "valor_ausente"
MOTIVO_INCERTA = "atualizacao_incerta"
MOTIVO_TIMESTAMPS = "timestamps_incompativeis"
MOTIVO_LACUNA = "lacuna_excessiva"
MOTIVO_OPERACIONAL = "situacao_operacional_incompativel"


def avaliar_par(
    anterior: dict,
    atual: dict,
    *,
    limite_lacuna_segundos: float,
    limiar_intervencao_bicicletas: int,
) -> dict:
    flags = set(anterior.get("flags") or ()) | set(atual.get("flags") or ())
    inicio = anterior.get("last_reported") or anterior.get("coletado")
    fim = atual.get("last_reported") or atual.get("coletado")
    duracao = None
    if inicio is not None and fim is not None:
        duracao = (fim - inicio).total_seconds()

    bloqueios: list[str] = []
    if anterior.get("fonte_id") != atual.get("fonte_id"):
        bloqueios.append(MOTIVO_MUDANCA_FONTE)
        flags.add("mudanca_fonte")
    if anterior.get("estacao_id") != atual.get("estacao_id"):
        bloqueios.append(MOTIVO_MUDANCA_CADASTRO)
        flags.add("mudanca_cadastral")
    if anterior.get("bicicletas") is None or atual.get("bicicletas") is None:
        bloqueios.append(MOTIVO_VALOR_AUSENTE)
        flags.add("valor_ausente")
    if anterior.get("last_reported") is None or atual.get("last_reported") is None:
        bloqueios.append(MOTIVO_INCERTA)
        flags.add("atualizacao_incerta")
    if duracao is None or duracao <= 0:
        bloqueios.append(MOTIVO_TIMESTAMPS)
        flags.add("timestamps_incompativeis")
        if duracao is not None and duracao < 0:
            flags.add("fora_de_ordem")
    elif duracao > limite_lacuna_segundos:
        bloqueios.append(MOTIVO_LACUNA)
        flags.add("lacuna")
    if _operacao_impede(anterior, atual):
        bloqueios.append(MOTIVO_OPERACIONAL)
        flags.add("mudanca_operacional")
    elif _operacao_mudou(anterior, atual):
        flags.add("mudanca_operacional")
    if "dados_antigos" in flags:
        flags.add("dados_antigos")
    if anterior.get("versao_gbfs") and atual.get("versao_gbfs"):
        if anterior["versao_gbfs"] != atual["versao_gbfs"]:
            flags.add("mudanca_versao_gbfs")

    delta = None
    aumento = None
    reducao = None
    movimentacao = None
    comparavel = not bloqueios
    if comparavel:
        delta = int(atual["bicicletas"]) - int(anterior["bicicletas"])
        aumento = max(delta, 0)
        reducao = max(-delta, 0)
        movimentacao = aumento + reducao
        if movimentacao >= limiar_intervencao_bicicletas:
            flags.add("possivel_intervencao")

    return {
        "inicio": inicio,
        "fim": fim,
        "duracao_segundos": duracao,
        "bicicletas_anterior": anterior.get("bicicletas"),
        "bicicletas_atual": atual.get("bicicletas"),
        "delta": delta,
        "aumento_observado": aumento,
        "reducao_observada": reducao,
        "movimentacao_observada": movimentacao,
        "comparavel": comparavel,
        "motivo": bloqueios[0] if bloqueios else None,
        "flags": flags,
    }


def construir_janelas(
    inicio_local: datetime,
    fim_local: datetime,
    horas: list[tuple[int, int]] | None = None,
    dias_semana: set[int] | None = None,
) -> list[tuple[datetime, datetime]]:
    """Recorta o período local em janelas UTC. A cobertura usa a soma dessas janelas."""
    if fim_local <= inicio_local:
        return []
    todos_os_dias = dias_semana is None or dias_semana >= set(range(7))
    if todos_os_dias and not horas:
        return [
            (
                inicio_local.astimezone(timezone.utc),
                fim_local.astimezone(timezone.utc),
            )
        ]
    faixas = horas or [(0, 24)]
    janelas: list[tuple[datetime, datetime]] = []
    dia = inicio_local.date()
    ultimo = fim_local.date()
    fuso = inicio_local.tzinfo
    while dia <= ultimo:
        if dias_semana is not None and dia.weekday() not in dias_semana:
            dia += timedelta(days=1)
            continue
        for hora_inicio, hora_fim in faixas:
            ini = _combinar(dia, hora_inicio, fuso)
            fim = _combinar(dia, hora_fim, fuso)
            a = max(ini, inicio_local)
            b = min(fim, fim_local)
            if b > a:
                janelas.append((a.astimezone(timezone.utc), b.astimezone(timezone.utc)))
        dia += timedelta(days=1)
    return janelas


def faixas_horarias(hora_inicio: int, hora_fim: int) -> list[tuple[int, int]]:
    if hora_inicio == hora_fim:
        raise ValueError("O horário inicial e o final do filtro não podem ser iguais.")
    if hora_inicio < hora_fim:
        return [(hora_inicio, hora_fim)]
    return [(hora_inicio, 24), (0, hora_fim)]


def fim_em_janelas(fim: datetime, janelas: list[tuple[datetime, datetime]]) -> bool:
    return any(inicio <= fim <= termino for inicio, termino in janelas)


def segundos_cobertos(
    trechos: list[tuple[datetime, datetime]],
    janelas: list[tuple[datetime, datetime]],
) -> float:
    pedacos: list[tuple[datetime, datetime]] = []
    for ini, fim in trechos:
        if ini is None or fim is None or fim <= ini:
            continue
        for jini, jfim in janelas:
            a = max(ini, jini)
            b = min(fim, jfim)
            if b > a:
                pedacos.append((a, b))
    return _unir_segundos(pedacos)


def duracao_janelas(janelas: list[tuple[datetime, datetime]]) -> float:
    return sum((fim - inicio).total_seconds() for inicio, fim in janelas)


def montar_resumo(
    estacoes: list[dict],
    intervalos: list[dict],
    ultimos_estoques: list[dict],
    janelas: list[tuple[datetime, datetime]],
    *,
    excluir_sinalizados: bool,
    limiar_cobertura: float,
    limite_desatualizado_segundos: float,
    fim_periodo: datetime,
) -> tuple[list[dict], list[dict]]:
    """Devolve as linhas do resumo e os intervalos anotados com incluido_no_resumo."""
    anotados: list[dict] = []
    relacionados_por_estacao: dict[int, list[dict]] = {}
    for intervalo in intervalos:
        incluido = _intervalo_incluivel(intervalo, janelas, excluir_sinalizados)
        copia = dict(intervalo)
        copia["incluido_no_resumo"] = incluido
        anotados.append(copia)
        for estacao_id in {copia.get("estacao_id_inicio"), copia.get("estacao_id_fim")}:
            relacionados_por_estacao.setdefault(estacao_id, []).append(copia)
    agregados = {
        estacao["id"]: _agregar_estacao(
            estacao["id"], relacionados_por_estacao.get(estacao["id"], []), janelas
        )
        for estacao in estacoes
    }
    linhas = resumir_estacoes(
        estacoes,
        agregados,
        ultimos_estoques,
        janelas,
        limiar_cobertura=limiar_cobertura,
        limite_desatualizado_segundos=limite_desatualizado_segundos,
        fim_periodo=fim_periodo,
    )
    return linhas, anotados


AGREGADO_VAZIO = {
    "intervalos_validos": 0,
    "aumentos": None,
    "reducoes": None,
    "movimentacao": None,
    "segundos": 0.0,
    "quantidade_lacunas": 0,
    "flags": frozenset(),
    "tem_excluidos": False,
    "tem_mudanca_cadastral": False,
}


def _agregar_estacao(estacao_id: int, relacionados: list[dict], janelas: list) -> dict:
    """Totais de um cadastro. resumo_intervalos_por_estacao (banco) aplica as mesmas regras em SQL."""
    incluidos = [
        item
        for item in relacionados
        if item["incluido_no_resumo"] and item.get("estacao_id_fim") == estacao_id
    ]
    lacunas = [
        item
        for item in relacionados
        if "lacuna" in set(item.get("flags") or ())
        and item.get("fim") is not None
        and fim_em_janelas(item["fim"], janelas)
    ]
    excluidos = [
        item
        for item in relacionados
        if item.get("estacao_id_fim") == estacao_id
        and item.get("comparavel")
        and not item["incluido_no_resumo"]
        and item.get("fim") is not None
        and fim_em_janelas(item["fim"], janelas)
    ]
    flags: set[str] = set()
    for item in incluidos:
        flags.update(item.get("flags") or ())
    return {
        "intervalos_validos": len(incluidos),
        "aumentos": sum(int(item["aumento_observado"]) for item in incluidos) if incluidos else None,
        "reducoes": sum(int(item["reducao_observada"]) for item in incluidos) if incluidos else None,
        "movimentacao": sum(int(item["movimentacao_observada"]) for item in incluidos) if incluidos else None,
        "segundos": segundos_cobertos([(item["inicio"], item["fim"]) for item in incluidos], janelas),
        "quantidade_lacunas": len(lacunas),
        "flags": flags,
        "tem_excluidos": bool(excluidos),
        "tem_mudanca_cadastral": any(
            "mudanca_cadastral" in set(item.get("flags") or ()) for item in relacionados
        ),
    }


def resumir_estacoes(
    estacoes: list[dict],
    agregados: dict[int, dict],
    ultimos_estoques: list[dict],
    janelas: list[tuple[datetime, datetime]],
    *,
    limiar_cobertura: float,
    limite_desatualizado_segundos: float,
    fim_periodo: datetime,
) -> list[dict]:
    """Uma linha por cadastro a partir dos totais de cada estação. Cadastro sem totais não teve intervalo."""
    denominador = duracao_janelas(janelas)
    horas_no_filtro = denominador / 3600 if denominador else 0
    estoques = {(item["estacao_id"]): item for item in ultimos_estoques}
    linhas = []
    for estacao in estacoes:
        agregado = agregados.get(estacao["id"], AGREGADO_VAZIO)
        segundos = agregado["segundos"]
        horas_validas = segundos / 3600
        cobertura = (100 * segundos / denominador) if denominador else None
        if agregado["intervalos_validos"]:
            aumentos = agregado["aumentos"]
            reducoes = agregado["reducoes"]
            movimentacao = agregado["movimentacao"]
            taxa = (movimentacao / horas_validas) if horas_validas > 0 else None
        else:
            aumentos = reducoes = movimentacao = taxa = None
        flags = set(agregado["flags"])
        if agregado["tem_mudanca_cadastral"]:
            flags.add("mudanca_cadastral")
        if agregado["tem_excluidos"]:
            flags.add("intervalos_sinalizados_excluidos")
        if estacao.get("ausente_desde"):
            flags.add("desaparecimento")
        estoque = estoques.get(estacao["id"])
        bicicletas = None if estoque is None else estoque.get("bicicletas")
        observado_em = None if estoque is None else estoque.get("observado_em")
        desatualizado = False
        if observado_em is not None:
            desatualizado = (fim_periodo - observado_em).total_seconds() > limite_desatualizado_segundos
        linha = {
            "station_id": estacao["station_id"],
            "id_cadastro": estacao["id"],
            "nome": estacao.get("nome"),
            "latitude": estacao.get("latitude"),
            "longitude": estacao.get("longitude"),
            "capacidade": estacao.get("capacidade"),
            "aumentos_observados": aumentos,
            "reducoes_observadas": reducoes,
            "movimentacao_observada": movimentacao,
            "intervalos_validos": agregado["intervalos_validos"],
            "horas_validas": horas_validas,
            "horas_no_filtro": horas_no_filtro,
            "cobertura_percentual": cobertura,
            "taxa_por_hora_valida": taxa,
            "quantidade_lacunas": agregado["quantidade_lacunas"],
            "flags_qualidade": sorted(flags),
            "bicicletas_disponiveis": bicicletas,
            "ultima_observacao": observado_em,
            "status_desatualizado": desatualizado,
        }
        linha["categoria"] = classificar(linha, "movimentacao_observada", limiar_cobertura)
        linhas.append(linha)
    return linhas


def classificar(linha: dict, indicador: str, limiar_cobertura: float) -> str:
    if not _coordenadas_validas(linha.get("latitude"), linha.get("longitude")):
        return "sem_coordenadas"
    if indicador == "bicicletas_disponiveis":
        if linha.get("bicicletas_disponiveis") is None:
            return "sem_observacao_de_estoque"
        if linha.get("status_desatualizado"):
            return "status_desatualizado"
        return "classificada"
    if indicador == "cobertura_percentual":
        if linha.get("cobertura_percentual") is None:
            return "sem_intervalos_validos"
        return "classificada"
    if not linha.get("intervalos_validos"):
        return "sem_intervalos_validos"
    cobertura = linha.get("cobertura_percentual")
    if cobertura is None or cobertura < limiar_cobertura:
        return "cobertura_insuficiente"
    valor = linha.get(indicador)
    if valor is None:
        return "sem_intervalos_validos"
    if valor == 0:
        return "zero_movimentacao"
    return "classificada"


def agregar_temporal(
    estacoes: list[dict],
    intervalos: list[dict],
    janelas: list[tuple[datetime, datetime]],
    frequencia: str,
) -> list[dict]:
    """Agrega intervalos já marcados como incluídos. O delta fica no bucket do fim."""
    if frequencia not in {"hora", "dia"}:
        raise ValueError("A frequência temporal deve ser hora ou dia.")
    cadastros = {estacao["id"]: estacao for estacao in estacoes}
    acumulado: dict[tuple, dict] = {}

    def obter(estacao_id: int, bucket_ini: datetime, bucket_fim: datetime) -> dict:
        chave = (estacao_id, bucket_ini.astimezone(timezone.utc))
        if chave not in acumulado:
            estacao = cadastros.get(estacao_id, {})
            acumulado[chave] = {
                "station_id": estacao.get("station_id"),
                "id_cadastro": estacao_id,
                "nome": estacao.get("nome"),
                "latitude": estacao.get("latitude"),
                "longitude": estacao.get("longitude"),
                "capacidade": estacao.get("capacidade"),
                "bucket_ini": bucket_ini,
                "bucket_fim": bucket_fim,
                "segundos": 0.0,
                "aumentos_observados": 0,
                "reducoes_observadas": 0,
                "movimentacao_observada": 0,
                "intervalos_validos": 0,
                "flags": set(),
                "teve_movimento": False,
            }
        return acumulado[chave]

    for intervalo in intervalos:
        if not intervalo.get("incluido_no_resumo"):
            continue
        estacao_id = intervalo.get("estacao_id_fim")
        if estacao_id not in cadastros:
            continue
        inicio = intervalo.get("inicio")
        fim = intervalo.get("fim")
        if inicio is not None and fim is not None and fim > inicio:
            for pedaco_ini, pedaco_fim in _recortar(inicio, fim, janelas):
                for cursor, limite, bucket_ini, bucket_fim in _fatiar(pedaco_ini, pedaco_fim, frequencia):
                    item = obter(estacao_id, bucket_ini, bucket_fim)
                    item["segundos"] += (limite - cursor).total_seconds()
        if fim is not None and fim_em_janelas(fim, janelas):
            bucket_ini, bucket_fim = _bucket_de(fim, frequencia)
            item = obter(estacao_id, bucket_ini, bucket_fim)
            item["aumentos_observados"] += int(intervalo["aumento_observado"])
            item["reducoes_observadas"] += int(intervalo["reducao_observada"])
            item["movimentacao_observada"] += int(intervalo["movimentacao_observada"])
            item["intervalos_validos"] += 1
            item["flags"].update(intervalo.get("flags") or ())
            item["teve_movimento"] = True

    linhas = []
    for item in acumulado.values():
        if item["segundos"] <= 0 and not item["teve_movimento"]:
            continue
        intersecao = list(_recortar(item["bucket_ini"], item["bucket_fim"], janelas))
        if intersecao:
            inicio_periodo = min(pedaco[0] for pedaco in intersecao)
            fim_periodo = max(pedaco[1] for pedaco in intersecao)
            denominador = _unir_segundos(intersecao)
        else:
            inicio_periodo = item["bucket_ini"]
            fim_periodo = item["bucket_fim"]
            denominador = 0
        horas = item["segundos"] / 3600
        cobertura = (100 * item["segundos"] / denominador) if denominador else None
        movimentacao = item["movimentacao_observada"] if item["teve_movimento"] else 0
        aumentos = item["aumentos_observados"] if item["teve_movimento"] else 0
        reducoes = item["reducoes_observadas"] if item["teve_movimento"] else 0
        if not item["teve_movimento"]:
            movimentacao = 0
        taxa = (movimentacao / horas) if horas > 0 else None
        linhas.append(
            {
                "station_id": item["station_id"],
                "id_cadastro": item["id_cadastro"],
                "nome": item["nome"],
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "capacidade": item["capacidade"],
                "inicio_periodo": inicio_periodo.astimezone(timezone.utc),
                "fim_periodo": fim_periodo.astimezone(timezone.utc),
                "inicio_periodo_utc": formatar_utc(inicio_periodo),
                "fim_periodo_utc": formatar_utc(fim_periodo),
                "inicio_periodo_local": formatar_local(inicio_periodo),
                "fim_periodo_local": formatar_local(fim_periodo),
                "aumentos_observados": aumentos,
                "reducoes_observadas": reducoes,
                "movimentacao_observada": movimentacao,
                "intervalos_validos": item["intervalos_validos"],
                "horas_validas": horas,
                "cobertura_percentual": cobertura,
                "taxa_por_hora_valida": taxa,
                "flags_qualidade": sorted(item["flags"]),
                "frequencia": frequencia,
            }
        )
    linhas.sort(key=lambda linha: (linha["station_id"] or "", linha["inicio_periodo_utc"], linha["id_cadastro"]))
    return linhas


def _intervalo_incluivel(intervalo: dict, janelas: list, excluir_sinalizados: bool) -> bool:
    if not intervalo.get("comparavel"):
        return False
    if intervalo.get("fim") is None or intervalo.get("inicio") is None:
        return False
    if not fim_em_janelas(intervalo["fim"], janelas):
        return False
    flags = set(intervalo.get("flags") or ())
    if excluir_sinalizados and flags & FLAGS_SINALIZADOS:
        return False
    return True


def _operacao_impede(anterior: dict, atual: dict) -> bool:
    estados = (anterior.get("instalada"), atual.get("instalada"))
    if any(estado is False for estado in estados):
        return True
    return False


def _operacao_mudou(anterior: dict, atual: dict) -> bool:
    for campo in ("instalada", "alugando", "devolvendo"):
        if anterior.get(campo) is None or atual.get(campo) is None:
            continue
        if anterior.get(campo) != atual.get(campo):
            return True
    return False


def _coordenadas_validas(latitude: object, longitude: object) -> bool:
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return False
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180


def _combinar(dia, hora: int, fuso) -> datetime:
    if hora == 24:
        return datetime.combine(dia + timedelta(days=1), time.min, tzinfo=fuso)
    return datetime.combine(dia, time(hour=hora), tzinfo=fuso)


def _unir_segundos(pedacos: list[tuple[datetime, datetime]]) -> float:
    if not pedacos:
        return 0.0
    ordenados = sorted(pedacos)
    total = 0.0
    atual_ini, atual_fim = ordenados[0]
    for ini, fim in ordenados[1:]:
        if ini <= atual_fim:
            if fim > atual_fim:
                atual_fim = fim
        else:
            total += (atual_fim - atual_ini).total_seconds()
            atual_ini, atual_fim = ini, fim
    total += (atual_fim - atual_ini).total_seconds()
    return total


def _recortar(inicio: datetime, fim: datetime, janelas: list[tuple[datetime, datetime]]):
    for jini, jfim in janelas:
        a = max(inicio, jini)
        b = min(fim, jfim)
        if b > a:
            yield a, b


def _bucket_de(instante: datetime, frequencia: str) -> tuple[datetime, datetime]:
    local = instante.astimezone(FUSO_EXIBICAO)
    if frequencia == "hora":
        ini = local.replace(minute=0, second=0, microsecond=0)
        return ini, ini + timedelta(hours=1)
    ini = datetime.combine(local.date(), time.min, tzinfo=FUSO_EXIBICAO)
    return ini, ini + timedelta(days=1)


def _fatiar(inicio: datetime, fim: datetime, frequencia: str):
    cursor = inicio.astimezone(FUSO_EXIBICAO)
    final = fim.astimezone(FUSO_EXIBICAO)
    while cursor < final:
        bucket_ini, bucket_fim = _bucket_de(cursor, frequencia)
        limite = min(bucket_fim, final)
        yield cursor, limite, bucket_ini, bucket_fim
        cursor = limite
