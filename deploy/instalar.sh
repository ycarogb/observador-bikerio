#!/usr/bin/env bash
# Instala o Observador Bike Rio numa VM Ubuntu e registra coletor e interface como serviços systemd.
# Uso, na raiz do repositório clonado: bash deploy/instalar.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="$(id -un)"

APT="sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600"
$APT update
$APT install -y python3-venv python3-pip curl

if [ -z "$(swapon --show)" ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

# O projeto exige Python 3.11+. Em imagens antigas (ex.: Ubuntu 20.04), o uv baixa um Python 3.12 à parte do sistema.
if python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  python3 -m venv "$RAIZ/.venv"
else
  curl -LsSf https://astral.sh/uv/install.sh | sh
  "$HOME/.local/bin/uv" venv --python 3.12 --seed "$RAIZ/.venv"
fi
"$RAIZ/.venv/bin/pip" install --upgrade pip
"$RAIZ/.venv/bin/pip" install -e "$RAIZ"

for servico in bikerio-coletor bikerio-interface; do
  sed -e "s|__RAIZ__|$RAIZ|g" -e "s|__USUARIO__|$USUARIO|g" "$RAIZ/deploy/$servico.service" \
    | sudo tee "/etc/systemd/system/$servico.service" > /dev/null
done

sudo systemctl daemon-reload
sudo systemctl enable --now bikerio-coletor bikerio-interface
systemctl --no-pager status bikerio-coletor bikerio-interface
