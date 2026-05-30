#!/usr/bin/env bash
set -euo pipefail

# ======================================================
# CatFinder - Deploy script
# Uso: editar REMOTE_HOST abajo y ejecutar:
#   bash scripts/deploy.sh
# ======================================================

REMOTE_USER="user"
REMOTE_HOST="192.168.x.x"
REMOTE_DIR="/opt/catfinder"

# --- Colores ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

SSH_DEST="${REMOTE_USER}@${REMOTE_HOST}"

info "Iniciando deploy a ${SSH_DEST}:${REMOTE_DIR}"

# --- 1. Verificar conexión SSH ---
info "Verificando conexión SSH..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SSH_DEST}" "echo OK" >/dev/null 2>&1; then
    error "No se puede conectar a ${SSH_DEST}. Verificá la IP, usuario y conexión."
    exit 1
fi
info "Conexión SSH exitosa."

# --- 2. Verificar / instalar Docker en el remoto ---
info "Verificando Docker en el remoto..."
if ssh "${SSH_DEST}" "command -v docker &>/dev/null && docker compose version &>/dev/null"; then
    info "Docker ya está instalado."
else
    warn "Docker no encontrado. Instalando..."
    ssh "${SSH_DEST}" "
        sudo dnf install -y dnf-plugins-core &&
        sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo &&
        sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin &&
        sudo systemctl enable --now docker &&
        sudo usermod -aG docker \$USER
    "
    warn "Docker instalado. Reconectá la sesión SSH con: ssh ${SSH_DEST}"
    info "Después de reconectar, volvé a ejecutar este script para continuar."
    exit 0
fi

# --- 3. Crear directorio remoto ---
info "Creando directorio ${REMOTE_DIR} en remoto..."
ssh "${SSH_DEST}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown \$USER:\$USER ${REMOTE_DIR}"

# --- 4. Copiar archivos al remoto (rsync) ---
info "Copiando archivos al remoto..."
rsync -avz --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude 'example.env' \
    --exclude 'catfinder.service' \
    --exclude 'README.md' \
    --exclude 'scripts/deploy.sh' \
    --exclude 'requirements-dev.txt' \
    "$(dirname "$0")/.."/ "${SSH_DEST}:${REMOTE_DIR}/"

# --- 5. Construir y levantar con Docker ---
info "Construyendo y levantando contenedor Docker..."
ssh "${SSH_DEST}" "
    cd ${REMOTE_DIR}
    docker compose up -d --build
"

# --- 6. Verificar ---
info "Verificando estado..."
sleep 3
ssh "${SSH_DEST}" "
    cd ${REMOTE_DIR}
    echo '--- Contenedores ---'
    docker compose ps
    echo '--- Logs (últimas 10 líneas) ---'
    docker compose logs --tail=10
"

info ""
info "============================================"
info "Deploy completado!"
info "Para ver la web desde tu máquina local:"
info ""
info "   ssh -L 8080:localhost:8080 ${SSH_DEST}"
info ""
info "Y luego abrí http://localhost:8080"
info "============================================"
