# Observador Bike Rio

> Aplicação em Python para coletar a disponibilidade das estações do Bike Rio, guardar um histórico local e exportar camadas para análise em um Sistema de Informações Geográficas para Transportes (SIG-T), como o QGIS.

O coletor consulta o feed público [GBFS 3.0](https://gbfs.org/documentation/reference/) do [Bike Rio](https://www.bikerio.rio/), grava snapshots em SQLite e conserva as respostas originais. A interface Streamlit lê só o banco local, desenha um marcador por estação e exporta CSV, Parquet, GeoPackage e GeoJSON.

O documento de descoberta identifica o sistema como `bike_rio`. O nome publicado hoje no feed, em todos os idiomas, é `kitchen`. A interface mostra o identificador e esse nome.

**Tópicos:** GBFS · disponibilidade de estações · histórico local · SQLite · mapa · GeoPackage · QGIS · SIG-T

Os indicadores representam mudanças observadas de disponibilidade e não correspondem necessariamente ao número real de viagens.

## O que esta aplicação faz

- Descobre os feeds a partir de `gbfs.json` e lê `station_status` e `station_information`.
- Guarda cadastro versionado, snapshots, tentativas de coleta e intervalos comparáveis.
- Calcula aumentos observados, reduções observadas e movimentação observada.
- Mostra cada estação no mapa, com cor proporcional ao indicador escolhido.
- Exporta o mesmo recorte do mapa para análise externa. A análise SIG não é feita aqui.

O coletor é um processo à parte. Abrir, atualizar ou fechar a interface não inicia, duplica nem encerra a coleta. Desligar ou suspender o computador interrompe a coleta: não há serviço em segundo plano nesta versão.

## Nota metodológica

Os dados consultados representam disponibilidade de bicicletas, não registros individuais de viagens.

Uma mudança de estoque pode resultar de retirada, devolução, rebalanceamento ou manutenção. Movimentos simultâneos podem se compensar entre duas consultas.

Na interface e nas exportações:

- **Aumento observado** = max(estoque atual − estoque anterior, 0)
- **Redução observada** = max(estoque anterior − estoque atual, 0)
- **Movimentação observada** = aumento observado + redução observada

A movimentação observada é uma **proxy**. Não é o número confirmado de viagens. A soma entre estações também não é o total de viagens do sistema: a mesma viagem pode aparecer como redução numa estação e aumento em outra.

O delta só é calculado quando existe observação anterior, os horários são compatíveis, a lacuna não passa do limite, a fonte é a mesma e a alteração cadastral ou operacional não impede a comparação. Campo ausente fica nulo. Ausência de estação ou falha de coleta não viram estoque zero.

O limite inicial de lacuna é de 15 minutos. No feed do Bike Rio, `last_reported` costuma avançar em passos de cerca de três minutos. Um limite menor que esse passo classifica a observação nova como lacuna e deixa a movimentação nula. Intervalos mais longos continuam sem delta.

O delta é atribuído ao **horário final** do intervalo. O instante exato da movimentação é desconhecido.

A taxa por hora válida divide a movimentação observada pelas horas cobertas. Ela padroniza pelo tempo observado: não recupera movimentos perdidos nem corrige viés de cobertura.

A cobertura é a duração da união dos intervalos válidos, recortados ao período e às janelas de hora e dia da semana. Lacunas acima do limite não contam como tempo observado.

Variações grandes recebem a flag `possivel_intervencao`. Isso não identifica rebalanceamento com certeza e não exclui o dado, salvo se o filtro pedir.

Séries de fontes diferentes não são misturadas. Se o `system_id` mudar, a série nova fica em outro registro de fonte.

## Pré-requisitos

- [Python 3.11+](https://www.python.org/downloads/) (testado com 3.14 no Windows)
- Acesso de rede à fonte GBFS na coleta real

Verifique a instalação:

```powershell
python --version
```

## Como executar

Na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se a ativação do ambiente for bloqueada nesta sessão:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Equivalente em bash:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A configuração de exemplo aponta para o documento de descoberta do Bike Rio. Para ajustar intervalo, pastas ou limiares nesta máquina, copie `config.exemplo.toml` para `config.toml`. O arquivo local não entra no Git.

## Comandos

| Comando | O que faz |
| --- | --- |
| `python -m observador_bikerio coletar` | Consulta a fonte uma vez e grava o banco |
| `python -m observador_bikerio coletar-continuo` | Mantém a coleta até Ctrl+C |
| `python -m observador_bikerio backup` | Copia o SQLite com a API de backup |
| `python -m observador_bikerio interface` | Abre o mapa. Não inicia o coletor |
| `python -m observador_bikerio caminhos` | Mostra os caminhos absolutos |
| `python -m pytest` | Roda os testes sintéticos |

PowerShell, na raiz, com o ambiente ativo:

```powershell
python -m observador_bikerio coletar
python -m observador_bikerio coletar-continuo
python -m observador_bikerio interface
python -m pytest
```

O intervalo inicial é 60 segundos. Se o TTL do feed for maior que o intervalo configurado, a espera usa o TTL. HTTP 429 respeita `Retry-After`. Há timeout, poucas retentativas e espera progressiva. Uma segunda instância do coletor encerra em vez de duplicar a gravação.

O cadastro (`station_information`) é atualizado com menos frequência que o status. O padrão é 15 minutos, ou na hora se aparecer uma estação desconhecida.

## Interface

A tela mostra o mapa, o estado do coletor, a última tentativa, o último sucesso, o período armazenado, a quantidade de estações, a tabela do mesmo recorte, o histórico da estação clicada e a exportação. Os caminhos exibidos são absolutos.

A atualização da tela relê o SQLite. Ela não consulta o GBFS.

No mapa de movimentação, estação abaixo da cobertura mínima (padrão 90%) fica cinza, com a indicação de cobertura insuficiente. Esse limiar é um filtro de qualidade, não uma garantia de ausência de viés.

As cores de movimentação vão do amarelo-claro ao vermelho-escuro. Cor clara é valor menor; cor escura é valor maior. O tamanho do marcador não varia. A escala padrão é linear; a alternativa é log1p, sem alterar os números dos pop-ups e das exportações. As cores são relativas ao período, salvo quando há limites fixos.

Zero com cobertura suficiente, cobertura insuficiente, ausência de observação e status desatualizado não compartilham a mesma cor.

## Estrutura do projeto

```
observador-bikerio/
├── config.exemplo.toml
├── observador_bikerio/
│   ├── fonte_gbfs.py        # descoberta e download GBFS
│   ├── normalizador.py      # campos ausentes permanecem nulos
│   ├── coletor.py           # um ciclo ou coleta contínua
│   ├── banco.py             # SQLite
│   ├── indicadores.py       # comparação, cobertura e agregação
│   ├── consulta.py          # leitura usada pelo mapa e pela exportação
│   ├── mapa.py              # um marcador por estação
│   ├── exportacao.py        # CSV, Parquet, GeoPackage, GeoJSON
│   └── interface.py         # Streamlit
├── tests/                   # fixtures sintéticas, isoladas da base real
└── README.md
```

## Dados e armazenamento

Pastas padrão, relativas à raiz do projeto e exibidas em caminho absoluto na interface:

| Caminho | Conteúdo |
| --- | --- |
| `data/bikerio.sqlite` | Cadastro, snapshots, tentativas, intervalos e batimento |
| `data/raw/AAAA-MM-DD/` | JSON original comprimido com gzip |
| `data/exports/` | CSV, Parquet, GeoPackage, GeoJSON, metadados e dicionário |
| `data/backups/` | Cópias consistentes do SQLite |
| `logs/` | Log com rotação |

Nada disso é apagado automaticamente. `data/`, `logs/` e `config.toml` estão no `.gitignore`.

Horários são gravados em UTC e agregados em `America/Sao_Paulo`.

O SQLite usa WAL para a interface consultar enquanto o coletor grava. O backup usa `Connection.backup()`, também durante a coleta.

## Exportação para SIG-T

A exportação segue os filtros da tela, ou todos os dados com as flags preservadas.

- CSV e Parquet: cadastro, snapshots, intervalos, estação–hora, estação–dia e resumo do período.
- GeoPackage (`bikerio.gpkg`), CRS **EPSG:4326**:
  - `cadastro_estacoes` — pontos com validade
  - `indicadores_periodo` — o resumo desenhado no mapa
  - `serie_estacao_hora` ou `serie_estacao_dia`
- GeoJSON opcional do resumo, com longitude e latitude nessa ordem.

Se a estação muda de lugar dentro do período, a exportação separa a feição pela versão cadastral. Não junta coordenadas diferentes num ponto só.

`metadados.json` e `dicionario.md` registram fonte, período, fuso, definições, filtros, limites, versão do processamento e limitações. Para refazer o número do mapa, some só as linhas com `incluido_no_resumo = 1`.

## Como abrir no QGIS

1. Em **Camada → Adicionar camada → Adicionar camada vetorial**, escolha `bikerio.gpkg` e a camada `indicadores_periodo` ou a série temporal.
2. Nas propriedades da camada, confira o CRS **EPSG:4326**. Os nomes dos campos estão em `dicionario.md`. Horários `*_utc` estão em UTC; `*_local` está em America/Sao_Paulo, com offset.
3. Em **Simbologia**, use graduado no campo do indicador (por exemplo `movimentacao_observada`), com rampa do amarelo-claro ao vermelho-escuro.
4. Filtre a cobertura com `cobertura_percentual >= 90` ou `categoria IN ('classificada', 'zero_movimentacao')`. Cobertura insuficiente continua no arquivo, só sai do mapa se o filtro pedir.
5. No controlador temporal, use `inicio_periodo_local` e `fim_periodo_local` como início e fim do intervalo.
6. Relacione outras tabelas futuras pelo `station_id`. Use `id_cadastro` quando a mesma estação tiver mais de uma localização.

Esta aplicação não classifica uso do solo, não faz regressão e não prevê demanda.

## Testes

```powershell
python -m pytest
```

Os testes usam estações e feeds marcados como sintéticos, em pasta temporária. Eles não alimentam `data/bikerio.sqlite`.

A coleta real depende da rede e fica de fora da suíte automática.

## Limitações

- A movimentação observada não é contagem de viagens.
- Sem coleta em execução, o histórico para. Suspender o computador também para.
- Estação que some do feed não vira zero.
- A cor do mapa, sem limites fixos, só compara estações dentro do período selecionado.
- Dados de demonstração, quando existirem, usam `system_id` sintético e a interface os identifica como sintéticos.

## Fonte e atribuição

Documento de descoberta inicial:

`https://riodejaneiro.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json`

Os endereços de `station_status` e `station_information` são lidos desse documento a cada ciclo. Eles não ficam fixos no código. A especificação é a [referência GBFS](https://gbfs.org/documentation/reference/).

Atribuição: disponibilidade consultada no feed público GBFS do Bike Rio, publicado em `riodejaneiro.publicbikesystem.net`.
