# Observador Bike Rio

> Aplicação em Python para coletar a disponibilidade das estações do Bike Rio, guardar um histórico local e visualizar a movimentação em um mapa interativo.

O coletor consulta o feed público [GBFS 3.0](https://gbfs.org/documentation/reference/) do [Bike Rio](https://www.bikerio.rio/), grava snapshots em SQLite e conserva as respostas originais comprimidas. A interface Streamlit lê só o banco local, desenha um marcador colorido por estação e exporta os dados para análise em SIG (QGIS, etc.).

**Tópicos:** GBFS · disponibilidade de estações · histórico local · SQLite · mapa interativo · Streamlit · Folium · GeoPackage · QGIS

---

## O que esta aplicação faz

- **Coleta** a disponibilidade de bicicletas via feed GBFS, a cada 60 segundos, gravando um snapshot por ciclo.
- **Calcula** retiradas observadas, devoluções observadas e movimentação total entre snapshots consecutivos.
- **Exibe** um mapa com uma estação por marcador, com cor proporcional ao indicador selecionado.
- **Filtra** por janela de tempo: 1 h, 6 h, 24 h, todo o período ou intervalo personalizado.
- **Exporta** o recorte atual para CSV, Parquet, GeoPackage e GeoJSON.

O coletor é um processo independente da interface. Abrir ou fechar o mapa não inicia nem encerra a coleta.

---

## Indicadores

| Indicador | O que representa |
|-----------|-----------------|
| **Retiradas de bicicletas** | Soma dos decrementos de estoque — proxy de viagens geradas |
| **Devoluções de bicicletas** | Soma dos incrementos de estoque — proxy de viagens recebidas |
| **Movimentação observada** | Retiradas + devoluções |
| **Movimentação por hora válida** | Movimentação dividida pelas horas com cobertura ≥ 90% |
| **Bicicletas disponíveis** | Estoque no snapshot mais recente |

Os indicadores representam mudanças observadas de disponibilidade e não correspondem necessariamente ao número real de viagens. Uma mesma viagem aparece como retirada numa estação e devolução em outra.

---

## Pré-requisitos

- Python 3.11+ (testado com 3.14 no Windows e Ubuntu 22.04)
- Acesso de rede ao feed GBFS na coleta real

---

## Instalação

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copie o arquivo de configuração de exemplo e ajuste se necessário:

```powershell
copy config.exemplo.toml config.toml
```

O `config.toml` não entra no Git.

---

## Comandos

| Comando | O que faz |
|---------|-----------|
| `python -m observador_bikerio coletar` | Coleta uma vez e grava o banco |
| `python -m observador_bikerio coletar-continuo` | Coleta continuamente até Ctrl+C |
| `python -m observador_bikerio interface` | Abre a interface Streamlit |
| `python -m observador_bikerio backup` | Copia o SQLite com a API de backup |
| `python -m observador_bikerio caminhos` | Mostra os caminhos absolutos |
| `python -m pytest` | Roda os testes sintéticos |

---

## Execução local (dois terminais)

**Terminal 1 — coletor:**
```powershell
python -m observador_bikerio coletar-continuo
```

**Terminal 2 — interface:**
```powershell
python -m observador_bikerio interface
```

Acesse em `http://localhost:8501`.

---

## Deploy em servidor (Oracle Cloud Always Free)

Para rodar 24/7 sem depender do computador local:

### 1. Criar a VM

No painel Oracle Cloud: **Compute → Instances → Create Instance**
- Image: **Ubuntu 22.04**
- Shape: **Ampere A1.Flex** — 2 OCPUs, 8 GB RAM (gratuito)
- Adicionar chave SSH pública

### 2. Abrir a porta 8501

- **Security List (VCN):** adicionar regra de entrada TCP porta 8501, source `0.0.0.0/0`
- **Firewall da VM** (após conectar via SSH):

```bash
sudo iptables -I INPUT -p tcp --dport 8501 -j ACCEPT
sudo netfilter-persistent save
```

### 3. Preparar o ambiente

```bash
ssh ubuntu@<ip-da-vm>
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/ycarogb/observador-bikerio.git
cd observador-bikerio
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.exemplo.toml config.toml
nano config.toml   # ajuste se necessário
```

### 4. Criar serviços systemd

**/etc/systemd/system/bikerio-coletor.service**
```ini
[Unit]
Description=Observador Bike Rio - Coletor
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/observador-bikerio
ExecStart=/home/ubuntu/observador-bikerio/.venv/bin/python -m observador_bikerio coletar-continuo
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**/etc/systemd/system/bikerio-interface.service**
```ini
[Unit]
Description=Observador Bike Rio - Interface
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/observador-bikerio
ExecStart=/home/ubuntu/observador-bikerio/.venv/bin/streamlit run observador_bikerio/interface.py --server.port 8501 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bikerio-coletor bikerio-interface
sudo systemctl start bikerio-coletor bikerio-interface
```

Acesse em `http://<ip-da-vm>:8501`.

---

## Estrutura do projeto

```
observador-bikerio/
├── config.exemplo.toml          # configuração de exemplo
├── observador_bikerio/
│   ├── configuracao.py          # leitura do config.toml
│   ├── fonte_gbfs.py            # cliente HTTP e descoberta GBFS
│   ├── normalizador.py          # parse e normalização dos feeds
│   ├── coletor.py               # ciclo de coleta e coleta contínua
│   ├── banco.py                 # SQLite (WAL), migrações, consultas
│   ├── indicadores.py           # cálculo de retiradas, devoluções, cobertura
│   ├── consulta.py              # leitura agregada para interface e exportação
│   ├── mapa.py                  # mapa Folium com marcadores por estação
│   ├── exportacao.py            # CSV, Parquet, GeoPackage, GeoJSON
│   ├── textos.py                # rótulos e notas metodológicas
│   └── interface.py             # Streamlit
└── tests/                       # testes sintéticos, isolados do banco real
```

---

## Armazenamento

| Caminho | Conteúdo |
|---------|---------|
| `data/bikerio.sqlite` | Cadastro, snapshots, tentativas, intervalos |
| `data/raw/AAAA-MM-DD/` | JSON original comprimido (gzip) |
| `data/exports/` | CSV, Parquet, GeoPackage, GeoJSON, metadados |
| `data/backups/` | Cópias consistentes do SQLite |
| `logs/` | Log com rotação diária |

`data/`, `logs/` e `config.toml` estão no `.gitignore`.

Horários gravados em UTC, exibidos em `America/Sao_Paulo`.

---

## Nota metodológica

Os indicadores são calculados por comparação de snapshots consecutivos:

- **Devolução** = max(estoque atual − estoque anterior, 0)
- **Retirada** = max(estoque anterior − estoque atual, 0)
- **Movimentação** = devolução + retirada

O delta só é calculado quando há observação anterior válida, os horários são compatíveis e a lacuna não excede o limite (padrão: 15 minutos). Campo ausente fica nulo; ausência de estação no feed não vira estoque zero.

Cobertura ≥ 90% da janela de tempo é exigida para a estação entrar na escala de cor.

Os dados consultados representam disponibilidade de bicicletas, não registros individuais de viagens.

---

## Exportação para SIG-T (QGIS)

O GeoPackage exportado (`bikerio.gpkg`) usa CRS **EPSG:4326** e contém:

- `cadastro_estacoes` — pontos com validade temporal
- `indicadores_periodo` — resumo desenhado no mapa
- `serie_estacao_hora` ou `serie_estacao_dia` — série temporal

No QGIS: **Camada → Adicionar camada vetorial**, escolha `bikerio.gpkg`. Use simbologia graduada no campo `movimentacao_observada` com rampa do amarelo ao vermelho. Filtre cobertura com `cobertura_percentual >= 90`.

---

## Testes

```powershell
python -m pytest
```

Os testes usam estações e feeds sintéticos em pasta temporária. Não alimentam `data/bikerio.sqlite`. A coleta real depende de rede e fica fora da suíte automática.

---

## Fonte dos dados

Feed público GBFS 3.0 do Bike Rio:

```
https://riodejaneiro.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json
```

Os endereços de `station_status` e `station_information` são descobertos a partir desse índice a cada ciclo — não ficam fixos no código.

Atribuição: disponibilidade consultada no feed público GBFS do Bike Rio, publicado em `riodejaneiro.publicbikesystem.net`.
