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

- Python 3.11+ (testado com 3.14 no Windows)
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

O coletor e a interface rodam como serviços `systemd`: iniciam com a VM e reiniciam sozinhos se caírem. A interface escuta só em `127.0.0.1`; o acesso é por túnel SSH, sem abrir porta na internet.

### 1. Criar a VM

No painel Oracle Cloud: **Compute → Instances → Create Instance**

- Image: **Canonical Ubuntu 24.04** (o projeto exige Python 3.11+; o 22.04 traz 3.10)
- Shape: **VM.Standard.A1.Flex** (Ampere) com 1 OCPU e 6 GB de memória, ou **VM.Standard.E2.1.Micro** se a Ampere estiver sem capacidade na região
- Networking: manter a subnet pública com IP público
- SSH keys: gerar o par e baixar a chave privada, ou enviar a sua chave pública

### 2. Instalar

```bash
ssh -i <chave-privada> ubuntu@<ip-da-vm>
git clone https://github.com/ycarogb/observador-bikerio.git
cd observador-bikerio
bash deploy/instalar.sh
```

O script instala o Python, cria o `.venv`, adiciona 2 GB de swap quando a VM não tem, e ativa os serviços `bikerio-coletor` e `bikerio-interface` (arquivos em `deploy/`). Sem `config.toml`, vale o `config.exemplo.toml`.

### 3. Acompanhar a coleta

```bash
systemctl status bikerio-coletor
journalctl -u bikerio-coletor -f
.venv/bin/python -m observador_bikerio caminhos
```

### 4. Abrir o mapa pelo túnel SSH

No seu computador:

```bash
ssh -i <chave-privada> -N -L 8501:127.0.0.1:8501 ubuntu@<ip-da-vm>
```

Com o túnel aberto, acesse `http://localhost:8501`.

### 5. Atualizar o código

```bash
cd ~/observador-bikerio
git pull
.venv/bin/pip install -e .
sudo systemctl restart bikerio-coletor bikerio-interface
```

### 6. Trazer os dados para análise

```bash
ssh -i <chave-privada> ubuntu@<ip-da-vm> "cd observador-bikerio && .venv/bin/python -m observador_bikerio backup"
scp -i <chave-privada> -r ubuntu@<ip-da-vm>:observador-bikerio/data/backups ./backups-vm
```

O backup usa a API de cópia do SQLite e pode rodar com o coletor ativo.

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
