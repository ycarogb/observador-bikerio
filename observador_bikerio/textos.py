"""Textos metodológicos compartilhados pela interface, pelo README e pelas exportações."""

from __future__ import annotations

NOTA_INDICADORES = (
    "Os indicadores representam mudanças observadas de disponibilidade "
    "e não correspondem necessariamente ao número real de viagens."
)

NOTA_PROXY = (
    "A movimentação observada é a soma das devoluções e das retiradas válidas "
    "de disponibilidade. É uma proxy de movimentação: não representa o número "
    "confirmado de viagens. Uma mudança de estoque pode resultar de retirada, "
    "devolução, rebalanceamento ou manutenção, e movimentos simultâneos podem "
    "se compensar entre duas consultas."
)

NOTA_TAXA = (
    "A taxa por hora válida apenas padroniza a movimentação observada pelo "
    "tempo coberto. Ela não recupera movimentos perdidos nas lacunas nem "
    "corrige automaticamente vieses de cobertura."
)

NOTA_COBERTURA = (
    "O limiar de cobertura é um filtro de qualidade da visualização. "
    "Ele não garante ausência de viés."
)

NOTA_CORES = (
    "As cores são relativas aos valores do período selecionado, "
    "exceto quando há limites fixos."
)

NOTA_COLETOR = (
    "Desligar ou suspender o computador interrompe a coleta. "
    "Abrir, atualizar ou fechar a interface não inicia, duplica nem encerra o coletor."
)

NOTA_ATRIBUICAO = (
    "Os deltas são atribuídos ao horário final de cada intervalo. "
    "O instante exato de cada retirada ou devolução é desconhecido."
)

NOTA_TIPOS = (
    "A disponibilidade por tipo de bicicleta é guardada apenas como detalhe. "
    "Ela não é somada ao estoque total nem à movimentação observada."
)

ATRIBUICAO_FONTE = (
    "Disponibilidade consultada no feed público GBFS do Bike Rio, "
    "publicado em riodejaneiro.publicbikesystem.net. "
    "Documentação do formato: https://gbfs.org/documentation/reference/"
)

INDICADORES = {
    "movimentacao_observada": {
        "rotulo": "Movimentação observada",
        "unidade": "bicicletas (proxy)",
        "paleta": "movimento",
        "aplica_cobertura": True,
    },
    "reducoes_observadas": {
        "rotulo": "Retiradas de bicicletas",
        "unidade": "bicicletas",
        "paleta": "movimento",
        "aplica_cobertura": True,
    },
    "aumentos_observados": {
        "rotulo": "Devoluções de bicicletas",
        "unidade": "bicicletas",
        "paleta": "movimento",
        "aplica_cobertura": True,
    },
    "taxa_por_hora_valida": {
        "rotulo": "Movimentação observada por hora válida",
        "unidade": "bicicletas por hora válida",
        "paleta": "movimento",
        "aplica_cobertura": True,
    },
    "bicicletas_disponiveis": {
        "rotulo": "Bicicletas disponíveis na observação mais recente",
        "unidade": "bicicletas",
        "paleta": "bicicletas",
        "aplica_cobertura": False,
    },
}

PALETAS = {
    "movimento": ("#FFF3C4", "#F7B267", "#E85D04", "#9B2226"),
    "bicicletas": ("#DEEBF7", "#6BAED6", "#2171B5", "#08306B"),
    "cobertura": ("#F7FCB9", "#ADDD8E", "#31A354", "#006837"),
}

COR_COBERTURA_INSUFICIENTE = "#BDBDBD"
COR_SEM_DADOS = "#FFFFFF"
COR_STATUS_DESATUALIZADO = "#6D597A"
BORDA_PADRAO = "#333333"
BORDA_SEM_DADOS = "#111111"
BORDA_INSUFICIENTE = "#616161"
BORDA_DESATUALIZADO = "#311B46"

FLAGS_SINALIZADOS = frozenset(
    {
        "possivel_intervencao",
        "mudanca_operacional",
        "dados_antigos",
        "mudanca_versao_gbfs",
    }
)

DESCRICAO_FLAGS = {
    "dados_antigos": "last_reported muito anterior à atualização do feed.",
    "fora_de_ordem": "observação com horário anterior ao da última observação válida.",
    "lacuna": "intervalo maior que o limite configurado; a movimentação não foi calculada.",
    "valor_invalido": "contagem ausente no formato esperado ou negativa; o valor foi anulado.",
    "atualizacao_incerta": "faltou timestamp para distinguir uma observação nova de uma resposta repetida.",
    "possivel_intervencao": "variação igual ou acima do limiar; pode ser rebalanceamento ou manutenção, sem certeza.",
    "mudanca_cadastral": "localização ou capacidade mudou; as séries não foram agregadas no mesmo ponto.",
    "mudanca_operacional": "a situação operacional mudou ou a estação não estava instalada em um dos extremos do intervalo.",
    "mudanca_fonte": "a comparação cruzaria séries de fontes diferentes.",
    "mudanca_versao_gbfs": "a versão do feed mudou entre as observações.",
    "timestamps_incompativeis": "a ordem ou a duração dos horários impede a comparação.",
    "desaparecimento": "a estação deixou de aparecer no feed; isso não é estoque zero.",
    "intervalos_sinalizados_excluidos": "havia intervalos sinalizados e o filtro pediu para excluí-los do resumo.",
}
